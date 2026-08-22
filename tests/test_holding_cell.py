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
    assert "level-type=minecraft:superflat" in props
    assert "server-port=25565" in props
    assert "online-mode=true" in props
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
    # Floor + ceiling + 4 walls + lights + 4 corners (ground level, floor y=4)
    assert any(c.startswith("fill -10 4 -10 10 4 10 minecraft:white_concrete") for c in cmds)
    assert any("minecraft:sea_lantern" in c for c in cmds)
    assert any("minecraft:barrier" in c for c in cmds)
    assert "setworldspawn 0 5 0" in cmds
    assert "gamemode adventure @a" in cmds
    assert "gamerule doDaylightCycle false" in cmds
    assert "tp @a 0 5 0" in cmds
    assert any(c.startswith("forceload add -10 -10 10 10") for c in cmds)


def test_room_build_commands_capped_at_20():
    cmds = room_build_commands(_cfg(holding_cell_room_size=40))
    # Despite requesting 40, the room is capped at 20 (half=10, floor 4-23)
    assert any(c.startswith("fill -10 4 -10 10 4 10 minecraft:white_concrete") for c in cmds)
    assert any(c.startswith("fill 10 5 -10 10 22 10 minecraft:barrier") for c in cmds)


def test_room_build_commands_includes_four_walls():
    cmds = room_build_commands(_cfg(holding_cell_room_size=20))
    wall_fills = [c for c in cmds if "minecraft:barrier" in c and c.startswith("fill")]
    # 4 walls: -x, +x, -z, +z
    assert len(wall_fills) >= 4


# ---------------------------------------------------------------------------
# join welcome tellraw
# ---------------------------------------------------------------------------
def test_join_welcome_has_clickable_download_link():
    raws_list = join_welcome_raws(_cfg())
    assert len(raws_list) == 2
    download = json.loads(raws_list[1])  # second message = download instructions
    texts = [p for p in download if isinstance(p, dict) and "text" in p]
    link_part = next(p for p in texts if p.get("clickEvent"))
    assert link_part["clickEvent"]["action"] == "open_url"
    assert link_part["clickEvent"]["value"] == "https://W8.mom/dl/mods.zip"
    assert "DOWNLOAD MODS" in link_part["text"]


def test_join_welcome_includes_modded_address():
    raws_list = join_welcome_raws(_cfg(holding_cell_port=25565))
    download = json.loads(raws_list[1])
    texts = [p.get("text", "") for p in download if isinstance(p, dict)]
    joined = "\n".join(texts)
    assert "174.49.233.151:1234" in joined


def test_join_welcome_first_message_is_plain():
    raws_list = join_welcome_raws(_cfg())
    welcome = json.loads(raws_list[0])
    assert any("staging area" in p.get("text", "") for p in welcome if isinstance(p, dict))


# ---------------------------------------------------------------------------
# room join address
# ---------------------------------------------------------------------------
def test_room_join_address_default_port_hidden():
    addr = room_join_address(_cfg(holding_cell_port=25565))
    assert addr == "174.49.233.151"


def test_room_join_address_custom_port_shown():
    addr = room_join_address(_cfg(holding_cell_port=25566))
    assert addr == "174.49.233.151:25566"


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


def test_room_join_address_waiting_room_owns_forwarded_port():
    # Waiting room should own the externally-forwarded port (1234).
    addr = room_join_address(_cfg(mc_port=25565, holding_cell_port=1234))
    assert addr == "174.49.233.151:1234"


def test_room_properties_port_uses_holding_cell_port():
    props = room_properties(_cfg(holding_cell_port=1234))
    assert "server-port=1234" in props
