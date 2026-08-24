"""Tests for the vanilla holding cell (download lobby) module."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg.config import ServerConfig
from neorunner_pkg.holding_cell import (
    _strip_ansi,
    join_welcome_raws,
    room_build_commands,
    room_join_address,
    room_properties,
)
from neorunner_pkg.mod_hosting import game_join_address


def _cfg(**overrides) -> ServerConfig:
    base = {
        "mc_version": "26.1.2",
        "loader": "neoforge",
        "hostname": "W8.mom",
        "game_address": "174.49.233.151",
        "mc_port": 1234,
        "holding_cell_port": 25565,
        "holding_cell_room_size": 20,
        "holding_cell_max_players": 10,
    }
    base.update(overrides)
    return ServerConfig(**{k: v for k, v in base.items()})


# ---------------------------------------------------------------------------
# server.properties
# ---------------------------------------------------------------------------
def test_room_properties_has_vanilla_settings():
    props = room_properties(_cfg())
    assert "level-type=minecraft:flat" in props
    assert '"block":"minecraft:bedrock","height":1' in props
    assert '"block":"minecraft:grass_block","height":1' in props
    assert "server-port=25565" in props
    assert "online-mode=true" in props
    # Secure-profile enforcement hides/restricts server chat + links (the client
    # shows "chat is restricted by your profile" and blocks direct open/copy).
    # The wait room must disable it so the plaintext URL opens directly.
    assert "enforce-secure-profile=false" in props
    assert "gamemode=adventure" in props
    assert "difficulty=peaceful" in props
    assert "max-players=10" in props
    assert "allow-nether=false" in props


def test_room_properties_uses_configured_port():
    props = room_properties(_cfg(holding_cell_port=25566))
    assert "server-port=25566" in props


# ---------------------------------------------------------------------------
# room build commands
# ---------------------------------------------------------------------------
def test_room_build_commands_dimensions():
    cmds = room_build_commands(_cfg(holding_cell_room_size=20))
    # Floor + ceiling + 4 walls + lights + 4 corners (ground level, floor y=4,
    # 5-tall room: floor y=4, sea-lanterns y=7, ceiling y=8)
    assert any(c.startswith("fill -10 4 -10 10 4 10 minecraft:white_concrete") for c in cmds)
    assert any("minecraft:sea_lantern" in c for c in cmds)
    assert any(c.startswith("fill -10 8 -10 10 8 10 minecraft:barrier") for c in cmds)
    assert "setworldspawn 0 5 -3" in cmds
    assert "gamemode adventure @a" in cmds
    assert "gamerule doDaylightCycle false" in cmds
    assert "tp @a 0 5 -3" in cmds
    assert any(c.startswith("forceload add -10 -10 10 10") for c in cmds)


def test_room_build_commands_capped_at_20():
    cmds = room_build_commands(_cfg(holding_cell_room_size=40))
    # Despite requesting 40, the room footprint is capped at 20 (half=10).
    assert any(c.startswith("fill -10 4 -10 10 4 10 minecraft:white_concrete") for c in cmds)
    assert any(c.startswith("fill 10 5 -10 10 7 10 minecraft:glass") for c in cmds)


def test_room_build_commands_includes_four_glass_walls():
    cmds = room_build_commands(_cfg(holding_cell_room_size=20))
    wall_fills = [c for c in cmds if "minecraft:glass" in c and c.startswith("fill")]
    # 4 walls: -x, +x, -z, +z
    assert len(wall_fills) >= 4
    assert all("minecraft:glass" in c for c in wall_fills)


def test_room_build_commands_include_lectern_with_book():
    cmds = room_build_commands(_cfg(holding_cell_room_size=20))
    lectern = [c for c in cmds if "minecraft:lectern" in c]
    assert len(lectern) == 1
    assert "setblock 0 5 0 minecraft:lectern[facing=north,has_book=true]" in lectern[0]
    assert 'Book:{id:"minecraft:written_book"' in lectern[0]
    assert "written_book_content" in lectern[0]
    assert "NeoRunner Guide" in lectern[0]
    # User-guide pages: welcome/lobby, how to join, about NeoRunner, features
    assert "Download Lobby" in lectern[0]
    assert "https://W8.mom" in lectern[0]
    assert "github.com/nickyg666/NeoRunner-Python" in lectern[0]
    assert "open-source" in lectern[0]
    # Vanilla books cannot route clicks: the book shows the URL as plain
    # readable text (no click_event), while the clickable link lives in chat.
    assert "click_event" not in lectern[0]
    assert "https://W8.mom" in lectern[0]  # still visible/copyable
    # No secrets / internals exposed
    assert "174.49.233.151" not in lectern[0]
    assert "rcon" not in lectern[0].lower()
    assert "password" not in lectern[0].lower()


# ---------------------------------------------------------------------------
# join welcome tellraw
# ---------------------------------------------------------------------------
def test_join_welcome_has_plaintext_download_link():
    raws_list = join_welcome_raws(_cfg())
    assert len(raws_list) == 2
    download = json.loads(raws_list[1])  # second message = download instructions
    texts = [p for p in download if isinstance(p, dict) and "text" in p]
    # The URL is the bare root (hostname) - the server UA-routes the root.
    url_parts = [p for p in texts if p.get("text") == "https://W8.mom"]
    assert url_parts
    # It is visible as plain text AND carries the modern (1.21.5+) click_event
    # open_url (like the client's own "Chat is restricted" message), so
    # clicking it opens the browser confirmation / copy dialog.
    ce = url_parts[0].get("click_event")
    assert ce and ce["action"] == "open_url"
    assert ce["url"] == "https://W8.mom"


def test_join_welcome_includes_modded_address():
    raws_list = join_welcome_raws(_cfg(holding_cell_port=25565))
    download = json.loads(raws_list[1])
    texts = [p.get("text", "") for p in download if isinstance(p, dict)]
    joined = "\n".join(texts)
    # Join address uses the configured DNS hostname (never the public IP).
    assert "W8.mom:1234" in joined
    assert "174.49.233.151" not in joined


def test_join_welcome_first_message_is_plain():
    raws_list = join_welcome_raws(_cfg())
    welcome = json.loads(raws_list[0])
    assert any("staging area" in p.get("text", "") for p in welcome if isinstance(p, dict))


# ---------------------------------------------------------------------------
# room join address
# ---------------------------------------------------------------------------
def test_room_join_address_is_the_single_shared_entrance():
    # The proxy routes vanilla clients to the room from the SAME public
    # address modded clients use; holding_cell_port is loopback-internal.
    cfg = _cfg(game_address="w8.mom", hostname="w8.mom", mc_port=25565,
               holding_cell_port=1234)
    assert room_join_address(cfg) == "w8.mom"
    assert room_join_address(cfg) == game_join_address(cfg)


def test_room_join_address_ignores_internal_room_port():
    # The holding-cell port is bound to loopback behind the proxy and must
    # never leak into player-facing addresses.
    cfg = _cfg(game_address="w8.mom", mc_port=25565, holding_cell_port=25566)
    addr = room_join_address(cfg)
    assert addr == "w8.mom"
    assert ":25566" not in addr


# (room join address tests moved above: single shared entrance via proxy)


# ---------------------------------------------------------------------------
# ANSI stripping (console log lines)
# ---------------------------------------------------------------------------
def test_strip_ansi_removes_color_codes():
    assert _strip_ansi("\x1b[32mSteve joined the game\x1b[m") == "Steve joined the game"


def test_strip_ansi_passthrough_plain():
    assert _strip_ansi("[Server thread/INFO]: Steve joined the game") == \
        "[Server thread/INFO]: Steve joined the game"

# ---------------------------------------------------------------------------
# description (MOTD) wiring
# ---------------------------------------------------------------------------
def test_room_properties_uses_holding_cell_description():
    props = room_properties(_cfg(holding_cell_description="Join us for the modpack!"))
    assert "motd=Join us for the modpack!" in props


def test_room_properties_default_description_when_empty():
    props = room_properties(_cfg(holding_cell_description=""))
    assert "motd=NeoRunner Download Lobby - get the modpack link in chat!" in props


def test_room_join_address_waiting_room_no_longer_owns_a_port():
    # Pre-proxy, the vanilla room owned the forwarded 1234 entrance; now the
    # proxy routes to its loopback port and players only ever see one address.
    cfg = _cfg(game_address="w8.mom", mc_port=25565, holding_cell_port=1234)
    assert room_join_address(cfg) == "w8.mom"


def test_room_properties_port_uses_holding_cell_port():
    props = room_properties(_cfg(holding_cell_port=1234))
    assert "server-port=1234" in props


# ---------------------------------------------------------------------------
# hostname-based join address (no public IP exposure)
# ---------------------------------------------------------------------------
def test_host_join_address_uses_hostname():
    from neorunner_pkg.holding_cell import _host_join_address
    assert _host_join_address(_cfg(mc_port=25565)) == "W8.mom"
    assert _host_join_address(_cfg(mc_port=1234)) == "W8.mom:1234"


def test_welcome_never_exposes_public_ip():
    raws_list = join_welcome_raws(_cfg())
    all_text = " ".join(
        p.get("text", "") for r in raws_list for p in json.loads(r) if isinstance(p, dict)
    )
    assert "174.49.233.151" not in all_text
    assert "W8.mom" in all_text


def test_join_welcome_url_is_clickable_open_url():
    raws_list = join_welcome_raws(_cfg())
    download = json.loads(raws_list[1])
    url_parts = [p for p in download if isinstance(p, dict) and p.get("text") == "https://W8.mom"]
    assert len(url_parts) == 1
    # The URL text is visible AND carries the modern (1.21.5+) click_event
    # open_url syntax (same mechanism as the client's "Chat is restricted"
    # message), so clicking opens the browser-confirmation / copy dialog.
    ce = url_parts[0].get("click_event")
    assert ce is not None
    assert ce["action"] == "open_url"
    assert ce["url"] == "https://W8.mom"


def test_greet_player_broadcasts_to_all(monkeypatch):
    """_greet_player sends tellraw @a (not the name) so a just-joining player
    can't be missed by target resolution timing."""
    from neorunner_pkg.holding_cell import VanillaHoldingCell
    cell = VanillaHoldingCell(_cfg())
    sent = []
    monkeypatch.setattr(cell, "send_command", lambda cmd: sent.append(cmd) or True)
    monkeypatch.setattr("neorunner_pkg.holding_cell.time.sleep", lambda s: None)
    cell._greet_player("TestPlayer")
    tellraws = [c for c in sent if c.startswith("tellraw")]
    assert len(tellraws) == 2
    assert all("@a" in t for t in tellraws)


# ---------------------------------------------------------------------------
# downloads page: domain from settings, no public IP
# ---------------------------------------------------------------------------
def test_downloads_page_uses_hostname_not_ip(monkeypatch):
    from neorunner_pkg import public_site
    monkeypatch.setattr(
        "neorunner_pkg.mod_hosting.game_join_address",
        lambda cfg: "w8.mom",
    )
    info = public_site._server_info()
    assert "174.49.233.151" not in str(info)
    assert info["server_address"] == "w8.mom"
    # Single shared entrance: the room is reached at the same address.
    assert info["room_address"] == info["server_address"]


# ---------------------------------------------------------------------------
# bundle README: Linux Java install decision tree
# ---------------------------------------------------------------------------
def test_bundle_readme_has_linux_java_install_guide():
    from neorunner_pkg.mod_hosting import _mods_bundle_readme
    readme = _mods_bundle_readme(_cfg(), "neorunner-installer-test.jar")
    for key in ("apt", "dnf install", "yum install", "pacman",
                "amazonlinux", "temurin-25-jre", "portable JRE",
                "update-alternatives", "aarch64", "java -version"):
        assert key in readme, f"missing {key!r} in bundle README"


def test_greet_player_tps_into_room():
    """Joiners are teleported to the spawn point, not their saved roof pos."""
    from neorunner_pkg.holding_cell import VanillaHoldingCell, _DEFAULT_SURFACE_Y
    cell = VanillaHoldingCell(_cfg())
    sent = []
    cell.send_command = lambda cmd: sent.append(cmd) or True
    cell._greet_player("FoxNews")
    assert any(cmd == f"tp @a 0 {_DEFAULT_SURFACE_Y + 1} -3" for cmd in sent)
    assert any(cmd.startswith("tellraw @a") for cmd in sent)
