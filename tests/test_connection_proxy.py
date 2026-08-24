"""Tests for the handshake-routing entrance proxy (connection_proxy.py)."""

import asyncio
import json
import socket
import struct
import threading
import time

import pytest

from neorunner_pkg.config import ServerConfig
from neorunner_pkg.connection_proxy import (
    Handshake,
    VERDICT_KICK,
    VERDICT_MODDED,
    VERDICT_ROOM,
    ConnectionProxy,
    build_kick_json,
    decode_varint,
    encode_varint,
    frame_packet,
    kick_packet,
    pack_string,
    parse_handshake,
    route_login,
    split_first_frame,
)


# ---------------------------------------------------------------------------
# varints / framing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 16383, 16384, 2097151,
                                   2097152, 2147483647, 1073741824])
def test_varint_roundtrip(value):
    enc = encode_varint(value)
    assert len(enc) <= 5
    decoded, pos = decode_varint(enc, 0)
    assert decoded == value
    assert pos == len(enc)


def test_varint_truncated_raises():
    with pytest.raises(ValueError):
        decode_varint(b"\x80", 0)  # continuation bit set but no follow-up byte


def test_varint_overlong_raises():
    with pytest.raises(ValueError):
        decode_varint(b"\x80" * 6 + b"\x00", 0)


def test_frame_split_roundtrip():
    pkt = frame_packet(0x00, b"hello")
    split = split_first_frame(pkt + b"EXTRA")
    assert split is not None
    first, rest = split
    assert first == pkt
    assert rest == b"EXTRA"


def test_frame_split_incomplete_returns_none():
    pkt = frame_packet(0x00, b"x" * 100)
    assert split_first_frame(pkt[:3]) is None


def test_handshake_roundtrip_vanilla():
    body = encode_varint(771) + pack_string("w8.mom") + struct.pack(">H", 25565) + encode_varint(2)
    hs = parse_handshake(body)
    assert hs == Handshake(protocol=771, address="w8.mom", port=25565,
                           next_state=2, has_fml_marker=False)


@pytest.mark.parametrize("addr", ["w8.mom\x00FML3\x00", "w8.mom\x00FML4\x00",
                                  "w8.mom\x00FML\x00", "w8.mom\x00FML2\x00"])
def test_handshake_detects_modloader_markers(addr):
    body = encode_varint(999) + pack_string(addr) + struct.pack(">H", 25565) + encode_varint(2)
    hs = parse_handshake(body)
    assert hs.has_fml_marker is True


def test_handshake_junk_returns_none():
    assert parse_handshake(b"\xff\xff\xff") is None


def test_handshake_bad_addr_len_returns_none():
    # addr length says 5000 bytes but only a few present
    body = encode_varint(771) + encode_varint(5000) + b"short"
    assert parse_handshake(body) is None


# ---------------------------------------------------------------------------
# routing matrix
# ---------------------------------------------------------------------------

def _hs(proto, marker=False, next_state=2):
    return Handshake(protocol=proto, address=("w8.mom\x00FML3\x00" if marker else "w8.mom"),
                     port=25565, next_state=next_state, has_fml_marker=marker)


def test_route_modded_client_goes_to_modded():
    verdict, _ = route_login(_hs(9999, marker=True), modded_proto=9999, room_proto=777)
    assert verdict == VERDICT_MODDED


def test_route_wrong_version_modloader_gets_kicked():
    verdict, _ = route_login(_hs(340, marker=True), modded_proto=9999, room_proto=777)
    assert verdict == VERDICT_KICK


def test_route_matching_vanilla_goes_to_room():
    verdict, _ = route_login(_hs(777), modded_proto=9999, room_proto=777)
    assert verdict == VERDICT_ROOM


def test_route_wrong_version_vanilla_gets_kicked():
    verdict, _ = route_login(_hs(763), modded_proto=9999, room_proto=777)
    assert verdict == VERDICT_KICK


def test_route_unknown_loader_without_marker_treated_as_vanilla():
    # Fabric sends no marker: if its protocol happens to match the room it can
    # at least reach the lobby.
    verdict, _ = route_login(_hs(777), modded_proto=9999, room_proto=777)
    assert verdict == VERDICT_ROOM


# ---------------------------------------------------------------------------
# loader-aware unmarked-client policy (Fabric packs route to the pack server)
# ---------------------------------------------------------------------------

def test_route_fabric_policy_sends_matching_unmarked_to_modded():
    verdict, _ = route_login(_hs(775), modded_proto=775, room_proto=775,
                             unmarked_target=VERDICT_MODDED)
    assert verdict == VERDICT_MODDED


def test_route_fabric_policy_wrong_version_still_kicked():
    verdict, _ = route_login(_hs(340), modded_proto=775, room_proto=775,
                             unmarked_target=VERDICT_MODDED)
    assert verdict == VERDICT_KICK


def test_route_forge_family_policy_keeps_unmarked_in_lobby():
    verdict, _ = route_login(_hs(775), modded_proto=775, room_proto=775,
                             unmarked_target=VERDICT_ROOM)
    assert verdict == VERDICT_ROOM


def test_proxy_auto_policy_fabric_loader_targets_modded():
    cfg = ServerConfig(hostname="w8.mom", mc_port=25565,
                       backend_modded_port=25570, holding_cell_port=1234,
                       loader="fabric")
    assert ConnectionProxy(cfg)._unmarked_target() == "modded"


def test_proxy_auto_policy_neoforge_targets_lobby():
    cfg = ServerConfig(hostname="w8.mom", mc_port=25565,
                       backend_modded_port=25570, holding_cell_port=1234,
                       loader="neoforge")
    assert ConnectionProxy(cfg)._unmarked_target() == "room"


# ---------------------------------------------------------------------------
# kick payload
# ---------------------------------------------------------------------------

def test_kick_json_has_both_click_schemas_and_visible_url():
    js = json.loads(build_kick_json("Get mods:", "https://w8.mom/dl/mods.zip"))
    text = json.dumps(js)
    assert "click_event" in text          # modern (snake_case) schema
    assert "clickEvent" in text           # legacy (camelCase) schema
    link_pieces = [p for p in js["extra"] if p["text"] == "https://w8.mom/dl/mods.zip"]
    assert link_pieces, "URL must also be visible plain text"
    piece = link_pieces[0]
    assert piece["click_event"]["action"] == "open_url"
    assert piece["clickEvent"]["action"] == "open_url"


def test_kick_packet_is_valid_framed_disconnect():
    pkt = kick_packet("reason", "https://w8.mom/dl/mods.zip")
    frame, rest = split_first_frame(pkt)
    assert rest == b""
    length, pos = decode_varint(frame, 0)
    assert len(frame) == pos + length
    pid, p2 = decode_varint(frame, pos)
    assert pid == 0x00                    # login-state Disconnect
    slen, p3 = decode_varint(frame, p2)
    payload = json.loads(frame[p3:p3 + slen].decode("utf-8"))
    assert "extra" in payload


# ---------------------------------------------------------------------------
# live integration: real sockets against fake loopback backends
# ---------------------------------------------------------------------------

class _FakeBackend:
    """Tiny threaded TCP sink that records what it received and echoes a reply."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.received = []
        self.reply = b"BACKEND-REPLY"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stop = False
        self._thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            data = conn.recv(4096)
            self.received.append(data)
            try:
                conn.sendall(self.reply)
                time.sleep(0.05)
            except OSError:
                pass
            finally:
                conn.close()

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _hs_packet(proto, addr="w8.mom", next_state=2):
    return frame_packet(0x00, encode_varint(proto) + pack_string(addr)
                        + struct.pack(">H", 25565) + encode_varint(next_state))


@pytest.fixture()
def proxy_stack():
    modded = _FakeBackend()
    room = _FakeBackend()
    listen = _free_port()

    cfg = ServerConfig(
        hostname="w8.mom",
        mc_port=listen,
        backend_modded_port=modded.port,
        holding_cell_port=room.port,
        holding_cell_enabled=True,
    )
    proxy = ConnectionProxy(cfg)
    # Seed learned protocols so the integration test doesn't depend on the
    # fake backends speaking real status-ping protocol.
    proxy.protocols = {"modded": 9999, "room": 777}
    proxy._proto_ts = time.monotonic()
    assert proxy.start(), "proxy failed to start"
    time.sleep(0.2)
    yield {"proxy": proxy, "cfg": cfg, "modded": modded, "room": room,
           "listen": listen}
    proxy.stop()
    modded.close()
    room.close()


def _recv_all(sock, want=b"", timeout=3.0) -> bytes:
    sock.settimeout(timeout)
    chunks = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            break
        if not data:
            break
        chunks += data
        if want and want in chunks:
            break
    return chunks


def test_integration_modded_client_routed_to_modded_backend(proxy_stack):
    pkt = _hs_packet(9999, addr="w8.mom\x00FML3\x00")
    with socket.create_connection(("127.0.0.1", proxy_stack["listen"]), timeout=5) as s:
        s.sendall(pkt + b"FOLLOWUP")
        got = _recv_all(s, want=b"BACKEND-REPLY")
    assert b"BACKEND-REPLY" in got
    recved = b"".join(proxy_stack["modded"].received)
    assert b"w8.mom\x00FML3\x00" in recved   # original bytes forwarded untouched
    assert b"FOLLOWUP" in recved             # pipelined frames arrive too
    assert proxy_stack["room"].received == []


def test_integration_vanilla_client_routed_to_room_backend(proxy_stack):
    pkt = _hs_packet(777)
    with socket.create_connection(("127.0.0.1", proxy_stack["listen"]), timeout=5) as s:
        s.sendall(pkt)
        got = _recv_all(s, want=b"BACKEND-REPLY")
    assert b"BACKEND-REPLY" in got
    assert proxy_stack["modded"].received == []


def test_integration_wrong_version_gets_clickable_kick(proxy_stack):
    pkt = _hs_packet(123)  # matches neither backend
    with socket.create_connection(("127.0.0.1", proxy_stack["listen"]), timeout=5) as s:
        s.sendall(pkt)
        got = _recv_all(s)
    assert got, "expected a disconnect packet"
    frame, _ = split_first_frame(got)
    pid, p = decode_varint(frame, decode_varint(frame, 0)[1])
    slen, p2 = decode_varint(frame, p)
    payload = json.loads(frame[p2:p2 + slen].decode("utf-8"))
    blob = json.dumps(payload)
    assert "https://w8.mom" in blob
    assert "click_event" in blob and "clickEvent" in blob
    assert proxy_stack["modded"].received == [] and proxy_stack["room"].received == []


def test_integration_status_ping_forwarded_to_room(proxy_stack):
    pkt = _hs_packet(777, next_state=1)
    with socket.create_connection(("127.0.0.1", proxy_stack["listen"]), timeout=5) as s:
        s.sendall(pkt)
        got = _recv_all(s, want=b"BACKEND-REPLY")
    assert b"BACKEND-REPLY" in got
    assert proxy_stack["modded"].received == []


def test_integration_backend_down_yields_friendly_kick(proxy_stack):
    proxy_stack["proxy"].protocols = {"modded": 9999, "room": 777}
    dead_port = _free_port()
    cfg = ServerConfig(hostname="w8.mom", mc_port=_free_port(),
                       backend_modded_port=dead_port,
                       holding_cell_port=proxy_stack["room"].port)
    proxy = ConnectionProxy(cfg)
    proxy.protocols = {"modded": 9999, "room": 777}
    proxy._proto_ts = time.monotonic()
    try:
        assert proxy.start()
        time.sleep(0.2)
        pkt = _hs_packet(777)  # would go to the (dead) room? no - room alive; use modded path
        pkt = _hs_packet(9999, addr="w8.mom\x00FML3\x00")
        with socket.create_connection(("127.0.0.1", cfg.mc_port), timeout=5) as s:
            s.sendall(pkt)
            got = _recv_all(s)
        assert got
        assert b"https://w8.mom" in got or b"w8.mom" in got
    finally:
        proxy.stop()


def test_proxy_refuses_port_collision():
    port = _free_port()
    cfg = ServerConfig(mc_port=port, backend_modded_port=port, holding_cell_port=_free_port())
    proxy = ConnectionProxy(cfg)
    assert proxy.start() is False


def test_probe_parses_status_with_multibyte_length_prefix():
    """Regression: a status response whose FRAME length needs 2 varint bytes
    (>127) used to misparse -- the payload's own string-length varint got read
    as the packet id, so every backend probe returned None forever."""
    import uuid

    # Long MOTD so the outer frame length exceeds 127 (2-byte varint).
    status = json.dumps({
        "version": {"name": "26.1.2", "protocol": 775},
        "description": {"text": "x" * 200},
        "enforcesSecureChat": True,
    })
    payload = pack_string(status)
    frame = encode_varint(len(payload) + 1) + b"\x00" + payload
    assert len(encode_varint(len(payload) + 1)) >= 2, "test needs a multibyte length prefix"

    served = threading.Event()

    async def fake_backend(reader, writer):
        await reader.read(1024)
        writer.write(frame)
        await writer.drain()
        writer.close()

    async def scenario():
        server = await asyncio.start_server(fake_backend, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        proxy = ConnectionProxy(ServerConfig(hostname="w8.mom", mc_port=_free_port(),
                                             backend_modded_port=port,
                                             holding_cell_port=_free_port()))
        try:
            proto = await proxy._probe_protocol(port)
            assert proto == 775, f"expected 775, got {proto!r}"
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
