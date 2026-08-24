#!/usr/bin/env python3
"""Nightly self-test of the single-port entrance (whichever backend owns it).

Runs the routing matrix against the LIVE public port:
  1. status ping, plain vanilla address      -> must answer a JSON status
  2. status ping with \\0FML3\\0 marker       -> must answer a JSON status
  3. wrong-version login                     -> must get a response or clean close
  4. correct-proto FML login                 -> must reach the modded backend
                                               (python: pipes bytes; velocity:
                                               routes after Mojang auth - a fake
                                               client gets an auth disconnect,
                                               which still proves the path lives)

Exits non-zero if any case fails; every result is logged via log_event() so it
lands in live.log next to the [PROXY] decisions.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neorunner_pkg.connection_proxy import (  # noqa: E402
    decode_varint,
    encode_varint,
    frame_packet,
    pack_string,
    split_first_frame,
)
from neorunner_pkg.log import log_event  # noqa: E402


def _hs_packet(proto: int, addr: str, next_state: int) -> bytes:
    return frame_packet(0x00, encode_varint(proto) + pack_string(addr)
                        + struct.pack(">H", 25565) + encode_varint(next_state))


def _talk(host: str, port: int, payload: bytes, timeout: float = 6.0) -> bytes:
    out = b""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.sendall(payload)
        s.settimeout(timeout)
        while len(out) < 300_000:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            out += chunk
        s.close()
    except OSError:
        pass
    return out


def _first_status_json(buf: bytes):
    split = split_first_frame(buf)
    if not split:
        return None
    frame = split[0]
    pos = decode_varint(frame, 0)[1]
    pid, pos = decode_varint(frame, pos)
    slen, pos = decode_varint(frame, pos)
    try:
        return json.loads(frame[pos:pos + slen].decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=None,
                    help="public MC port (default: cfg.mc_port)")
    ap.add_argument("--backend", choices=("python", "velocity"), default="python")
    ap.add_argument("--url", default="https://w8.mom")
    args = ap.parse_args()

    port = args.port
    if port is None:
        from neorunner_pkg.config import load_cfg
        port = int(load_cfg().mc_port or 25565)

    results: list[tuple[str, bool, str]] = []

    # 1. vanilla status ping
    buf = _talk(args.host, port, _hs_packet(774, "selftest", 1) + frame_packet(0x00, b""))
    st = _first_status_json(buf)
    ok = isinstance(st, dict) and "version" in st
    results.append(("status_vanilla", ok, f"proto={st.get('version', {}).get('protocol') if st else '?'}"))

    # 2. FML-marker status ping
    buf = _talk(args.host, port, _hs_packet(774, "selftest\x00FML3\x00", 1) + frame_packet(0x00, b""))
    st = _first_status_json(buf)
    ok = isinstance(st, dict) and "version" in st
    results.append(("status_fml_marker", ok, ""))

    # 3. wrong-version login -> some authoritative response / clean close
    buf = _talk(args.host, port, _hs_packet(100, "selftest", 2))
    if args.backend == "python":
        j = _first_status_json(buf)
        blob = json.dumps(j) if j else ""
        ok = bool(j) and args.url in blob and "click_event" in blob
        detail = "clickable kick" if ok else f"buf={len(buf)}B"
    else:
        # Velocity authenticates at the edge: a fake login gets an auth
        # disconnect (or close). Any framed reply proves the pipeline is live.
        ok = len(buf) > 0
        detail = f"reply={len(buf)}B"
    results.append(("wrong_version_login", ok, detail))

    # 4. correct-proto FML login reaches the modded path
    #    Learn the modded proto from the FML status ping first.
    buf = _talk(args.host, port, _hs_packet(774, "s\x00FML3\x00", 1) + frame_packet(0x00, b""))
    st = _first_status_json(buf)
    modded_proto = int(st.get("version", {}).get("protocol", 0)) if st else 0
    if modded_proto:
        # Handshake + Login Start: the backend/proxy has something to answer.
        payload = (_hs_packet(modded_proto, "selftest\x00FML3\x00", 2)
                   + frame_packet(0x00, pack_string("selftest")))
        buf = _talk(args.host, port, payload)
        ok = len(buf) > 0  # backend/proxy replies to our synthetic login
        detail = f"reply={len(buf)}B"
    else:
        ok, detail = False, "could not learn modded protocol"
    results.append(("modded_path_live", ok, detail))

    failures = [r for r in results if not r[1]]
    for name, ok, detail in results:
        log_event("PROXY_SELFTEST",
                  f"{name}: {'PASS' if ok else 'FAIL'}{(' (' + detail + ')') if detail else ''}")
    log_event("PROXY_SELFTEST",
              f"summary: {len(results) - len(failures)}/{len(results)} passed "
              f"(backend={args.backend}, port={port})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
