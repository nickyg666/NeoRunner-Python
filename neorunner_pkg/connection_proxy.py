"""Smart single-port entrance: one exposed Minecraft port, routed by handshake.

Every client hits ONE public port (``cfg.mc_port``, normally 25565). This proxy
peeks at the very first packet -- the Minecraft ``Set Protocol`` (handshake)
packet, which carries the client's protocol version, the address it typed, and
a ``\\0FML*\\0`` marker appended by Forge/NeoForge clients -- and routes:

========================================  ==============================
Client                                    Routed to
========================================  ==============================
Forge/NeoForge marker + matching proto    modded server (loopback)
Vanilla-compatible, matching room proto   vanilla waiting room (loopback)
Anything else                             holding cell w/ clickable
                                          download link (both old camelCase
                                          and new snake_case click-event
                                          schemas included) + 60-sec timeout
========================================  ==============================

Both real servers bind loopback ONLY (``server-ip=127.0.0.1``), so the proxy is
the single publicly-reachable listener -- no second exposed port.

The proxy never terminates the Minecraft session: after classifying the first
frame it splices the TCP streams bidirectionally, forwarding the original bytes
untouched (including any pipelined frames that arrived in the same segment).

Protocol numbers for routing are learned live by status-pinging each backend
(never hard-coded), cached with a TTL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .config import ServerConfig
from .constants import CWD
from .log import log_event

logger = logging.getLogger(__name__)

PROXY_LOG = CWD / "proxy.log"

# Forge/NeoForge append a NUL-separated marker to the handshake address:
#   legacy FML: "\0FML\0", modern: "\0FML2\0", 1.13+: "\0FML3\0", newer forks
#   may bump the digit. Fabric sends NO marker (looks vanilla).
_FML_MARKER = "\x00FML"

_CONNECT_TIMEOUT = 5.0
_IDLE_TIMEOUT = 1800.0          # generous; MC keep-alives flow constantly
_PROTO_TTL = 60.0               # seconds a learned backend protocol is trusted
_CHUNK = 64 * 1024


# ---------------------------------------------------------------------------
# Wire helpers (pure, unit-tested)
# ---------------------------------------------------------------------------

def encode_varint(value: int) -> bytes:
    """Encode an unsigned varint (Minecraft protocol, max 5 bytes)."""
    if value < 0:
        raise ValueError("varints are unsigned")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(data: bytes | bytearray, pos: int = 0) -> tuple[int, int]:
    """Decode a varint from ``data[pos:]``; return ``(value, next_pos)``.

    Raises ``ValueError`` on truncation or >5-byte encodings.
    """
    result = 0
    for shift in range(0, 35, 7):
        if pos >= len(data):
            raise ValueError("varint truncated")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
    raise ValueError("varint too long")


def frame_packet(packet_id: int, body: bytes) -> bytes:
    """Wrap ``body`` in a length-prefixed packet with the given packet id."""
    inner = encode_varint(packet_id) + body
    return encode_varint(len(inner)) + inner


def pack_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return encode_varint(len(raw)) + raw


@dataclass
class Handshake:
    protocol: int
    address: str
    port: int
    next_state: int      # 1 = status/ping, 2 = login
    has_fml_marker: bool


def parse_handshake(body: bytes) -> Handshake | None:
    """Parse the body of a Set Protocol (handshake) packet.

    ``body`` excludes the frame length and packet id. Returns None if the
    payload doesn't decode as a handshake (wrong packet shape / junk).
    """
    try:
        protocol, pos = decode_varint(body, 0)
        addr_len, pos = decode_varint(body, pos)
        if addr_len < 0 or pos + addr_len > len(body):
            return None
        address = body[pos:pos + addr_len].decode("utf-8", errors="replace")
        pos += addr_len
        if pos + 2 > len(body):
            return None
        (port,) = struct.unpack_from(">H", body, pos)
        pos += 2
        next_state, pos = decode_varint(body, pos)
    except (ValueError, UnicodeDecodeError, struct.error):
        return None
    return Handshake(
        protocol=protocol,
        address=address,
        port=port,
        next_state=next_state,
        has_fml_marker=_FML_MARKER in address,
    )


def split_first_frame(buf: bytes | bytearray) -> tuple[bytes, bytes] | None:
    """Split ``buf`` into ``(first_frame_bytes, rest)``.

    Returns None if ``buf`` doesn't yet contain one complete frame.
    """
    try:
        length, pos = decode_varint(buf, 0)
    except ValueError:
        return None
    if length <= 0 or length > 2 * 1024 * 1024:
        raise ValueError(f"insane frame length {length}")
    end = pos + length
    if len(buf) < end:
        return None
    return bytes(buf[:end]), bytes(buf[end:])


# ---------------------------------------------------------------------------
# Routing decision (pure, unit-tested)
# ---------------------------------------------------------------------------

VERDICT_MODDED = "modded"
VERDICT_ROOM = "room"
VERDICT_KICK = "kick"


def route_login(hs: Handshake, modded_proto: int | None, room_proto: int | None,
                unmarked_target: str = VERDICT_MODDED) -> tuple[str, str]:
    """Decide where a LOGIN handshake goes: ``(verdict, human_reason)``.

    Marker-INDEPENDENT by design: modern NeoForge clients no longer reliably
    append the ``\\0FML*`` marker to the handshake address, so the protocol
    number is the trustworthy signal.

    - Client speaking the modded server's protocol -> MODDED backend. The
      backend itself accepts NeoForge clients and kicks truly-vanilla ones
      with the (jar-patched, link-carrying) "requires NeoForge" message, so
      onboarding still ends in a clickable download link.
    - ``unmarked_target == VERDICT_ROOM`` (explicit lobby opt-in): matching-
      protocol clients with no marker go to the waiting room instead.
    - Anything else -> clickable kick (wrong version / unknown / junk).
    """
    if unmarked_target == VERDICT_ROOM:
        # Explicit lobby mode: modloader clients still go to the pack server;
        # markerless clients go to the room when their protocol matches it.
        if hs.has_fml_marker and modded_proto is not None and hs.protocol == modded_proto:
            return VERDICT_MODDED, f"modloader client, protocol {hs.protocol} matches modded"
        if room_proto is not None and hs.protocol == room_proto:
            return VERDICT_ROOM, f"vanilla-compatible client, protocol {hs.protocol}"
        return VERDICT_KICK, f"unknown client, protocol {hs.protocol}"
    if modded_proto is not None and hs.protocol == modded_proto:
        return VERDICT_MODDED, f"client, protocol {hs.protocol} matches modded"
    return VERDICT_KICK, f"unknown client, protocol {hs.protocol}"


def build_kick_json(reason: str, link: str) -> str:
    """Disconnect-screen component with a REAL clickable download link.

    Minecraft JSON chat requires ``action: "open_url"`` with ``value: <url>``.
    The ``url`` field is IGNORED by the vanilla client. SecurityCraft uses
    ``value`` and it works. Also carry ``click_event`` snake_case for older clients.
    """
    return json.dumps({
        "text": reason + "\n",
        "color": "gold",
        "extra": [
            {"text": link, "color": "aqua", "underlined": True,
             # camelCase for 1.19.3+; snake_case for older Forge clients
             "clickEvent": {"action": "open_url", "value": link},
             "click_event": {"action": "open_url", "value": link},
             "hoverEvent": {"action": "show_text", "contents": {"text": f"Open {link}"}}},
            {"text": "\n", "color": "gold"},
            {"text": "[Download Mods]", "color": "yellow", "bold": True,
             "clickEvent": {"action": "open_url", "value": link},
             "click_event": {"action": "open_url", "value": link},
             "hoverEvent": {"action": "show_text", "contents": {"text": f"Download mods from {link}"}}},
        ],
    })


def kick_packet(reason: str, link: str) -> bytes:
    """Framed login-state Disconnect (packet 0x00) carrying the kick JSON."""
    return frame_packet(0x00, pack_string(build_kick_json(reason, link)))


# ---------------------------------------------------------------------------
# The proxy service
# ---------------------------------------------------------------------------

class ConnectionProxy:
    """Asyncio TCP proxy with handshake classification. Own thread + loop."""

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self.protocols: dict[str, int | None] = {"modded": None, "room": None}
        self._proto_ts = 0.0
        self.total_connections = 0
        self.recent: deque = deque(maxlen=50)

    # -- addressing ---------------------------------------------------------

    @property
    def listen_port(self) -> int:
        return int(self.cfg.mc_port or 25565)

    @property
    def modded_port(self) -> int:
        return int(getattr(self.cfg, "backend_modded_port", 0) or 25570)

    @property
    def room_port(self) -> int:
        return int(self.cfg.holding_cell_port or 25565)

    def _download_link(self) -> str:
        from .mod_hosting import public_download_link
        return public_download_link(self.cfg)

    def _loader_name(self) -> str:
        return {"neoforge": "NeoForge", "forge": "Forge",
                "fabric": "Fabric"}.get(str(self.cfg.loader or "").lower(), "modded")

    def _unmarked_target(self) -> str:
        """Where protocol-matching clients without an FML marker go.

        Default (``auto``): the modded backend, for EVERY loader. Modern
        NeoForge clients can't be trusted to append the marker, so the protocol
        match is the real signal -- the modded server accepts its own clients
        and kicks truly-vanilla ones with a patched, link-carrying message.
        Set ``unmarked_client_target=lobby`` explicitly to keep the vanilla
        waiting room as the fallback for unmarked clients instead.
        """
        pref = str(getattr(self.cfg, "unmarked_client_target", "auto") or "auto").lower()
        if pref == "lobby":
            pref = VERDICT_ROOM  # "lobby" and "room" are the same target
        if pref in (VERDICT_ROOM, VERDICT_MODDED):
            return pref
        return VERDICT_MODDED

    # -- lifecycle ----------------------------------------------------------

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server)

    def start(self) -> bool:
        if self.listen_port == self.modded_port or self.listen_port == self.room_port:
            log_event("PROXY",
                      f"refusing to start: backend port collides with public port {self.listen_port}")
            return False
        if self.is_running():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="neorunner-proxy")
        self._thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._server is not None:
                break
            time.sleep(0.05)
        ok = self._server is not None
        log_event("PROXY",
                  f"proxy {'started' if ok else 'FAILED to start'} on :{self.listen_port} "
                  f"(modded->127.0.0.1:{self.modded_port}, room->127.0.0.1:{self.room_port})")
        return ok

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        srv = self._server
        if loop and srv:

            async def _close():
                srv.close()
                await srv.wait_closed()

            fut = asyncio.run_coroutine_threadsafe(_close(), loop)
            try:
                fut.result(timeout=5)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=6)
        self._thread = None
        self._server = None
        log_event("PROXY", "proxy stopped")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _main():
            self._server = await asyncio.start_server(
                self._handle_client, "0.0.0.0", self.listen_port)
            async with self._server:
                await self._server.serve_forever()

        try:
            self._loop.run_until_complete(_main())
        except asyncio.CancelledError:
            pass
        except OSError as e:
            if not self._stop.is_set():
                log_event("PROXY", f"proxy listener died: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    # -- protocol probing ---------------------------------------------------

    async def refresh_protocols(self) -> None:
        """Status-ping both backends to learn their protocol versions."""
        results = await asyncio.gather(
            self._probe_protocol(self.modded_port),
            self._probe_protocol(self.room_port),
        )
        self.protocols["modded"], self.protocols["room"] = results
        self._proto_ts = time.monotonic()

    async def _probe_protocol(self, port: int) -> int | None:
        """Status-ping a backend; return its advertised protocol version."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), _CONNECT_TIMEOUT)
            try:
                hs = frame_packet(0x00, encode_varint(0) + pack_string("127.0.0.1")
                                  + struct.pack(">H", port) + encode_varint(1))
                req = frame_packet(0x00, b"")
                writer.write(hs + req)
                await writer.drain()
                buf = b""
                frame: bytes | None = None
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    try:
                        got = await asyncio.wait_for(reader.read(_CHUNK), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if not got:
                        break
                    buf += got
                    split = split_first_frame(buf)
                    if split:
                        frame = split[0]
                        break
                if not frame:
                    return None
                # Walk varints positionally: length prefix, then packet id,
                # then the String field (its own varint length + UTF-8 JSON).
                # NOTE: do NOT slice by "length-varint width + 1" and then read
                # another id from the payload -- payloads start with their own
                # varints (e.g. the string length), which misparse as ids.
                pos = decode_varint(frame, 0)[1]          # skip length prefix
                pid, pos = decode_varint(frame, pos)      # packet id (0x00)
                if pid != 0x00:
                    return None
                slen, pos = decode_varint(frame, pos)     # String length
                status = json.loads(frame[pos:pos + slen].decode("utf-8"))
                return int(status.get("version", {}).get("protocol", -1))
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        except Exception:
            return None

    async def _ensure_protocols(self) -> None:
        stale = time.monotonic() - self._proto_ts > _PROTO_TTL
        unknown = self.protocols.get("modded") is None or self.protocols.get("room") is None
        if stale or unknown:
            await self.refresh_protocols()

    # -- connection handling -------------------------------------------------

    def _record(self, verdict: str, detail: str) -> None:
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "verdict": verdict, "detail": detail}
        self.recent.append(entry)
        log_event("PROXY", f"{verdict.upper()}: {detail}")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = "unknown"
        try:
            peer = ": ".join(str(x) for x in writer.get_extra_info("peername")[:2])
        except Exception:
            pass
        self.total_connections += 1
        try:
            buf = b""
            deadline = time.monotonic() + 10
            split = None
            while time.monotonic() < deadline:
                try:
                    chunk = await asyncio.wait_for(reader.read(_CHUNK), timeout=5.0)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
                try:
                    split = split_first_frame(buf)
                except ValueError:
                    break
                if split:
                    break
            if not split:
                writer.close()
                return

            first_frame, rest = split
            try:
                _length, lp = decode_varint(first_frame, 0)
                hs = parse_handshake(first_frame[lp + 1:])  # strip length + packet id
            except ValueError:
                hs = None

            await self._ensure_protocols()
            link = self._download_link()

            if hs is None:
                # Not a recognizable handshake (legacy 0xFE ping or garbage):
                # give it to the waiting room so old pingers still get an answer.
                self._record("room", f"{peer}: non-handshake traffic forwarded to room")
                await self._splice(reader, writer, "127.0.0.1", self.room_port,
                                  first_frame + rest)
                return

            kind = "status" if hs.next_state == 1 else "login"
            if kind == "status":
                # Status pings keep marker-based MOTD selection: modded clients
                # see the modded MOTD, vanilla see the lobby MOTD.
                target = self.modded_port if hs.has_fml_marker else self.room_port
                self._record("status",
                             f"{peer}: proto={hs.protocol} modloader={hs.has_fml_marker} "
                             f"-> status via :{target}")
                await self._splice(reader, writer, "127.0.0.1", target,
                                  first_frame + rest)
                return

            unmarked = self._unmarked_target()
            verdict, why = route_login(hs, self.protocols.get("modded"),
                                       self.protocols.get("room"), unmarked)
            detail = (f"{peer}: addr={hs.address.split(chr(0))[0]!r} proto={hs.protocol} "
                      f"modloader={hs.has_fml_marker} ({why})")

            if verdict == VERDICT_KICK:
                self._record("kick", detail)
                loader = self._loader_name()
                reason = (f"This server needs its {loader} mods. Grab the installer, then rejoin:"
                          if hs.has_fml_marker else
                          f"This server runs {loader} mods. Download them first, then rejoin:")
                writer.write(kick_packet(reason, link))
                await writer.drain()
                await asyncio.sleep(0.2)
                writer.close()
                return

            backend = self.modded_port if verdict == VERDICT_MODDED else self.room_port
            self._record(verdict, detail + f" -> 127.0.0.1:{backend}")
            await self._splice(reader, writer, "127.0.0.1", backend,
                                  first_frame + rest)
        except Exception as e:  # noqa: BLE001 - never let one client kill the proxy
            logger.warning("proxy connection error from %s: %s", peer, e)
            try:
                writer.close()
            except Exception:
                pass

    async def _splice(self, c_reader, c_writer, host: str, port: int, initial: bytes) -> None:
        """Connect the backend, replay buffered bytes, pipe until either side dies.

        If the backend is down the client gets a friendly clickable kick instead
        of a bare connection reset.
        """
        try:
            b_reader, b_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), _CONNECT_TIMEOUT)
        except Exception:
            self._record("kick", f"backend {host}:{port} unreachable - sent 'server starting' kick")
            c_writer.write(kick_packet(
                "The server is starting up (or restarting). Give it a minute, then reconnect:",
                self._download_link()))
            await c_writer.drain()
            await asyncio.sleep(0.2)
            c_writer.close()
            return

        if initial:
            b_writer.write(initial)
            await b_writer.drain()

        async def _pump(src, dst, half_name: str):
            try:
                while True:
                    data = await asyncio.wait_for(src.read(_CHUNK), timeout=_IDLE_TIMEOUT)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (asyncio.TimeoutError, ConnectionError, OSError):
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        await asyncio.gather(
            _pump(c_reader, b_writer, "c2b"),
            _pump(b_reader, c_writer, "b2c"),
        )

    # -- introspection -------------------------------------------------------

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "listen_port": self.listen_port,
            "backends": {
                "modded": f"127.0.0.1:{self.modded_port}",
                "room": f"127.0.0.1:{self.room_port}",
            },
            "learned_protocols": dict(self.protocols),
            "total_connections": self.total_connections,
            "recent": list(self.recent)[-20:],
        }


_proxy_instance: ConnectionProxy | None = None
_proxy_lock = threading.Lock()


def get_connection_proxy(cfg: ServerConfig | None = None) -> ConnectionProxy:
    """Get or create the shared proxy instance."""
    global _proxy_instance
    with _proxy_lock:
        if _proxy_instance is None:
            _proxy_instance = ConnectionProxy(cfg or ServerConfig())
        elif cfg is not None:
            _proxy_instance.cfg = cfg
        return _proxy_instance


__all__ = [
    "ConnectionProxy",
    "Handshake",
    "VERDICT_KICK",
    "VERDICT_MODDED",
    "VERDICT_ROOM",
    "build_kick_json",
    "decode_varint",
    "encode_varint",
    "frame_packet",
    "get_connection_proxy",
    "kick_packet",
    "pack_string",
    "parse_handshake",
    "route_login",
    "split_first_frame",
]
