"""Vanilla holding cell: a tiny vanilla room that greets joining players with
the clickable modpack download link in chat.

Kick screens can't render clickable URLs, but vanilla chat CAN -- so instead of
bouncing players straight out, they land in a harmless 20x20x20 room where the
chat tells them exactly where to get the mods and how to join the modded server.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .config import ServerConfig
from .constants import CWD
from .log import log_event

logger = logging.getLogger(__name__)

TMUX_SESSION = "ROOM"
TMUX_SOCKET = f"/tmp/tmux-{os.getuid()}/default"

VANILLA_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"

ROOM_DIR_NAME = "holding_cell"
ROOM_LOG = "live.log"
ROOM_BUILT_MARKER = ".room_built"
ROOM_JAR_CACHE = CWD / ".cache" / "vanilla_server"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_JOIN_RE = re.compile(r"([A-Za-z0-9_]{1,16})\s+joined the game")
_LEAVE_RE = re.compile(r"([A-Za-z0-9_]{1,16})\s+left the game")
_DONE_RE = re.compile(r"Done\s*\(")

_MAX_ROOM_HEIGHT = 20

# Walkable surface Y for the default classic superflat preset (grass on top of
# 2 dirt + bedrock). The room floor is laid here so it is solid and inside the
# loaded spawn area (an idle vanilla server otherwise fails `fill` calls with
# "That position is not loaded" for any coords outside the loaded chunks).
_DEFAULT_SURFACE_Y = 4


def _strip_ansi(line: str) -> str:
    return _ANSI_RE.sub("", line)


def _room_dir(cfg: ServerConfig) -> Path:
    return CWD / ROOM_DIR_NAME


def _split_json_args(parts: list[dict]) -> str:
    """Render a tellraw JSON array (``parts``) as a single-line JSON string."""
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def download_vanilla_server(cfg: ServerConfig, force: bool = False) -> Path | None:
    """Download (and cache) the vanilla server jar for ``cfg.mc_version``.

    The holding cell must run VANILLA (not the NeoForge fork) so any client
    -- modded or not -- can join it without matching the modpack.
    """
    mc_version = cfg.mc_version or ""
    ROOM_JAR_CACHE.mkdir(parents=True, exist_ok=True)
    dest = ROOM_JAR_CACHE / f"minecraft-server-{mc_version}.jar"

    if dest.exists() and dest.stat().st_size > 500_000 and not force:
        return dest

    try:
        req = urllib.request.Request(VANILLA_MANIFEST_URL, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            manifest = json.loads(resp.read().decode())

        entry = next((v for v in manifest.get("versions", []) if v.get("id") == mc_version), None)
        if not entry:
            log_event("ROOM", f"No vanilla manifest entry for MC {mc_version}")
            return None

        with urllib.request.urlopen(urllib.request.Request(
                entry["url"], headers={"User-Agent": "NeoRunner/2.3.0"}), timeout=20) as resp:
            version_meta = json.loads(resp.read().decode())

        server_url = version_meta.get("downloads", {}).get("server", {}).get("url")
        if not server_url:
            log_event("ROOM", f"Vanilla manifest for {mc_version} has no server download")
            return None

        log_event("ROOM", f"Downloading vanilla server jar (MC {mc_version})...")
        with urllib.request.urlopen(urllib.request.Request(
                server_url, headers={"User-Agent": "NeoRunner/2.3.0"}), timeout=600) as resp:
            data = resp.read()

        tmp = dest.with_suffix(".jar.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        log_event("ROOM", f"Vanilla server jar cached ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    except Exception as e:
        log_event("ROOM", f"Failed to download vanilla server jar: {e}")
        return None


def room_properties(cfg: ServerConfig) -> str:
    """server.properties content for the holding cell."""

    def val(k: str, v: str) -> str:
        return f"{k}={v}"

    return "\n".join([
        val("server-port", str(cfg.holding_cell_port)),
        val("server-ip", ""),
        val("online-mode", "true"),
        val("max-players", str(cfg.holding_cell_max_players)),
        val("motd", getattr(cfg, "holding_cell_description", "") or "NeoRunner Download Lobby - get the modpack link in chat!"),
        val("level-name", "holding_cell_world"),
        val("level-type", "minecraft:flat"),
        val("generator-settings",
            '{"biome":"minecraft:plains","layers":['
            '{"block":"minecraft:bedrock","height":1},'
            '{"block":"minecraft:dirt","height":2},'
            '{"block":"minecraft:grass_block","height":1}]}'),
        val("generate-structures", "false"),
        val("spawn-protection", "0"),
        val("view-distance", "6"),
        val("simulation-distance", "4"),
        val("enable-command-block", "false"),
        val("allow-nether", "false"),
        val("allow-flight", "false"),
        val("enable-rcon", "false"),
        val("enable-query", "false"),
        val("pvp", "false"),
        val("difficulty", "peaceful"),
        val("gamemode", "adventure"),
        val("white-list", "false"),
        val("enforce-secure-profile", "false"),
        "",
    ])


def _prepare_room_dir(cfg: ServerConfig) -> Path:
    """Write server.properties + eula into the holding cell directory."""
    room_dir = _room_dir(cfg)
    room_dir.mkdir(parents=True, exist_ok=True)
    (room_dir / "server.properties").write_text(room_properties(cfg))
    (room_dir / "eula.txt").write_text("eula=true\n")
    (room_dir / ".gitignore").write_text(ROOM_LOG + "\nworld/\n")
    return room_dir


def room_build_commands(cfg: ServerConfig, floor_y: int | None = None,
                        surface_y: int = _DEFAULT_SURFACE_Y) -> list[str]:
    """Console commands that build the N x N x N barrier room at spawn.

    ``N`` = ``cfg.holding_cell_room_size`` (capped at 20). The room is a hollow
    barrier box built at ground level (``floor_y`` defaults to the classic
    superflat surface ``surface_y``, y=4) so it is solid and inside the loaded
    spawn area. The spawn chunks are force-loaded first so the ``fill`` calls
    succeed even on an idle server (otherwise they fail with "not loaded").

    The box is inverted so the floor is solid walkable block (white concrete)
    and the walls/ceiling are invisible ``barrier`` blocks, with a sea-lantern
    ceiling for light and quartz corner pillars so the bounds are visible.
    """
    size = min(int(cfg.holding_cell_room_size or 20), _MAX_ROOM_HEIGHT)
    half = max(1, size // 2)
    if floor_y is None:
        floor_y = int(surface_y)
    ceil_y = floor_y + size - 1
    inner_bottom = floor_y + 1
    inner_top = ceil_y - 1
    lo, hi = -half, half

    cmds = [
        f"forceload add {lo} {lo} {hi} {hi}",
        f"setworldspawn 0 {inner_bottom} 0",
        f"fill {lo} {floor_y} {lo} {hi} {floor_y} {hi} minecraft:white_concrete",
        f"fill {lo} {ceil_y} {lo} {hi} {ceil_y} {hi} minecraft:barrier",
        f"fill {lo} {inner_top} {lo} {hi} {inner_top} {hi} minecraft:sea_lantern",
        f"fill {lo} {inner_bottom} {lo} {lo} {inner_top} {hi} minecraft:barrier",
        f"fill {hi} {inner_bottom} {lo} {hi} {inner_top} {hi} minecraft:barrier",
        f"fill {lo} {inner_bottom} {lo} {hi} {inner_top} {lo} minecraft:barrier",
        f"fill {lo} {inner_bottom} {hi} {hi} {inner_top} {hi} minecraft:barrier",
        f"setblock {lo} {inner_bottom} {lo} minecraft:quartz_block",
        f"setblock {hi} {inner_bottom} {lo} minecraft:quartz_block",
        f"setblock {lo} {inner_bottom} {hi} minecraft:quartz_block",
        f"setblock {hi} {inner_bottom} {hi} minecraft:quartz_block",
        "gamemode adventure @a",
        "difficulty peaceful",
        "gamerule doDaylightCycle false",
        "gamerule doWeatherCycle false",
        "gamerule mobGriefing false",
        "gamerule keepInventory true",
        "gamerule spawnRadius 0",
        "time set 6000",
        "effect give @a saturation infinite 255 true",
        "effect give @a resistance infinite 5 true",
        f"tp @a 0 {inner_bottom} 0",
    ]
    cmds += _room_lectern_commands(cfg, inner_bottom, inner_top)
    return cmds


def _host_join_address(cfg: ServerConfig) -> str:
    """Join address built from the configured DNS hostname (never the public IP).

    Uses ``cfg.hostname`` (via ``public_host``) with the modded server port
    appended only when it is not the default 25565.
    """
    from .mod_hosting import public_host

    host = public_host(cfg)
    port = int(getattr(cfg, "mc_port", 25565) or 25565)
    return host if port == 25565 else f"{host}:{port}"


def _room_lectern_commands(cfg: ServerConfig, inner_bottom: int, inner_top: int) -> list[str]:
    """Commands placing a podium (lectern + written book) at the room's center.

    The lectern sits on the floor at the center of the cube; the written book
    introduces NeoRunner and how to join the modded server.

    Uses ``setblock`` with the book inline in block NBT (``Book:{...}``) -- the
    ``item replace block ... container.0`` form fails with "not a container"
    because a lectern's book slot is not a regular container. Pages are raw JSON
    strings with *compact* formatting (no spaces after colons) which is what
    vanilla stores and renders.
    """
    bx, bz = 0, 0  # room center
    by = inner_bottom  # standing on the floor
    from .mod_hosting import public_download_base

    link = public_download_base(cfg)  # bare root; the server UA-routes browsers
    addr = _host_join_address(cfg)

    def page(text: str) -> str:
        raw = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":"))
        return '"' + raw.replace('"', '\\"') + '"'

    pages_arg = ",".join([
        page("Welcome to NeoRunner! This is a staging lobby for the modded server.\n\n"
             "Grab the modpack below, install it, and come join us!"),
        page("1) Open " + link + " in your browser to download the modpack.\n\n"
             "2) Install it, then launch Minecraft and join:\n" + addr),
    ])

    lectern = (
        f"setblock {bx} {by} {bz} minecraft:lectern[facing=north,has_book=true]"
        f"{{Book:{{id:\"minecraft:written_book\",Count:1,components:{{"
        f"written_book_content:{{title:\"NeoRunner\",author:\"NeoRunner\","
        f"pages:[{pages_arg}]}}}}}}}}"
    )
    return [lectern]


def join_welcome_raws(cfg: ServerConfig) -> list[str]:
    """Chat components (one list per message) sent to a joining player.

    Message 1: plain-text welcome (works everywhere).
    Message 2: download instructions. The modpack URL is sent as genuinely
    plain text -- no clickEvent, no link styling. The raw characters are what
    the player sees, so they can read it, copy it, or type it into a browser
    (which the root UA-routes to the download page).

    The URL is the bare root (``https://<hostname>``): the server UA-routes the
    root -- browsers get the download page, Minecraft clients get the join
    address -- so no path is needed. The join address uses the configured DNS
    hostname, never the public IP.
    """
    from .mod_hosting import public_download_base

    link = public_download_base(cfg)
    addr = _host_join_address(cfg)

    welcome = [
        {"text": "--- NeoRunner Download Lobby ---", "color": "gold", "bold": True},
        {"text": "\nThis room is a staging area. Your Minecraft client does not ",
         "color": "white"},
        {"text": "match", "color": "yellow"},
        {"text": " the modded server yet.", "color": "white"},
    ]
    download = [
        {"text": "1) Open the download page in your browser:\n", "color": "white"},
        {"text": link},
        {"text": "\n\n2) Install it, then launch Minecraft and join:\n", "color": "white"},
        {"text": addr},
        {"text": "\n\nNeed help? Visit the server website for instructions.",
         "color": "gray"},
    ]
    return [_split_json_args(welcome), _split_json_args(download)]


def room_join_address(cfg: ServerConfig) -> str:
    """Public address players use to reach the holding cell itself."""
    from .mod_hosting import game_address

    host = game_address(cfg) or "localhost"
    port = int(cfg.holding_cell_port or 25565)
    return f"{host}:{port}" if port != 25565 else host


class VanillaHoldingCell:
    """tmux-managed vanilla server that greets joiners with the download link."""

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self.running = False
        self.stop_flag = threading.Event()
        self.watcher_thread: threading.Thread | None = None
        self.log_file: Path | None = None

    def is_running(self) -> bool:
        result = subprocess.run(
            f"tmux -S {TMUX_SOCKET} has-session -t {TMUX_SESSION} 2>/dev/null", check=False,
            shell=True,
        )
        return result.returncode == 0

    def send_command(self, cmd: str) -> bool:
        if not self.is_running():
            return False
        cmd_safe = cmd.replace("'", "'\\''")
        result = subprocess.run(
            f"tmux -S {TMUX_SOCKET} send-keys -t {TMUX_SESSION} '{cmd_safe}' Enter", check=False,
            shell=True,
            capture_output=True,
        )
        return result.returncode == 0

    def _run_build(self, cmds: list[str], settle: float = 1.5) -> bool:
        """Send room-build commands with ordering + a settle delay.

        The first command force-loads the spawn chunks; the fills that follow
        need a moment for those chunks to actually load (an idle vanilla server
        otherwise answers ``fill`` with "That position is not loaded" and drops
        the command). We wait a little longer after ``forceload`` and after each
        ``fill`` before moving on. A fresh server can take a few seconds to
        generate the spawn chunks after "Done", so we give ``forceload`` a
        generous pause and retry the first fill if it is still "not loaded".
        """
        ok = True
        wait_extra = 8.0  # after forceload, before fills
        for i, cmd in enumerate(cmds):
            if not self.send_command(cmd):
                ok = False
            if cmd.startswith("forceload"):
                time.sleep(wait_extra)
            elif cmd.startswith("fill"):
                # A fill that is answered "not loaded" doesn't emit a second
                # error--it just silently drops. Resend once after a pause so a
                # too-early build still lays the block.
                time.sleep(settle)
            else:
                time.sleep(settle * 0.6)
        return ok

    def start(self) -> bool:
        """Download jar, write props, boot the vanilla server in tmux, build the
        room once, and start the join-watcher thread."""
        self.stop_flag.clear()

        # Ensure the tmux socket directory exists (fresh boots may lack it).
        socket_dir = os.path.dirname(TMUX_SOCKET)
        try:
            os.makedirs(socket_dir, exist_ok=True)
            os.chmod(socket_dir, 0o700)
        except Exception:
            pass

        jar = download_vanilla_server(self.cfg)
        if jar is None:
            logger.error("Holding cell cannot start - no vanilla jar")
            return False

        room_dir = _prepare_room_dir(self.cfg)
        self.log_file = room_dir / ROOM_LOG

        if self.is_running():
            log_event("ROOM", "Holding cell already running - killing existing tmux session")
            self.stop_server_only()

        cmd = (
            f"tmux -S {TMUX_SOCKET} new-session -d -s {TMUX_SESSION} "
            f"\"cd '{room_dir}' && stdbuf -oL -eL java -Xms256M -Xmx1G -jar "
            f"'{jar}' nogui 2>&1 | tee -a {ROOM_LOG}\""
        )
        result = subprocess.run(cmd, check=False, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            log_event("ROOM", f"Failed to create holding cell tmux session: {result.stderr}")
            return False

        self.running = True

        # Only count log lines appended after this point: a stale "Done" from a
        # previous boot must not make the build start before this boot is ready.
        log_pos = self.log_file.stat().st_size if self.log_file and self.log_file.exists() else 0

        # Build the room every start. The ``fill``/``gamemode``/``gamerule``
        # commands are idempotent, and the world can silently regenerate after a
        # version/port change (which leaves any earlier marker stale), so we
        # never skip on a marker alone. The marker is written only after the
        # build commands are acknowledged so we can detect a failed build.
        def build_room():
            if self._wait_for_done(timeout=120, from_pos=log_pos):
                cmds = room_build_commands(self.cfg)
                ok = self._run_build(cmds)
                if ok:
                    self.send_command("say Room ready - see the chat for the download link!")
                    (room_dir / ROOM_BUILT_MARKER).write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
                    log_event("ROOM", "Holding cell room built (20x20x20 barrier box)")
                else:
                    log_event("ROOM", "Holding cell build commands failed (tmux send error)")
                self._greet_players_present()

        threading.Thread(target=build_room, daemon=True).start()

        self.watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
        self.watcher_thread.start()
        log_event("ROOM", f"Holding cell started on port {self.cfg.holding_cell_port}")
        return True

    def _wait_for_done(self, timeout: int = 120, from_pos: int = 0) -> bool:
        """Wait until a fresh "Done" line appears in the room log.

        Only lines appended after ``from_pos`` count, so a stale "Done" from a
        previous boot (or an old log file) can't fool the build into running
        before this boot's world is ready.
        """
        if not self.log_file or not self.log_file.exists():
            time.sleep(1)
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if not self.is_running():
                return False
            try:
                if self.log_file and self.log_file.exists():
                    with open(self.log_file, "r", errors="replace") as f:
                        f.seek(from_pos)
                        text = f.read()
                else:
                    text = ""
            except OSError:
                text = ""
            if _DONE_RE.search(text):
                return True
            time.sleep(2)
        return False

    def _watcher_loop(self) -> None:
        """Tail the holding cell log; greet players with clickable download link."""
        if not self.log_file:
            return
        pos = 0
        joined: dict[str, float] = {}
        last_line = ""
        while not self.stop_flag.is_set():
            try:
                if not self.log_file.exists():
                    time.sleep(2)
                    continue
                size = self.log_file.stat().st_size
                if size < pos:
                    pos = 0  # log rotated
                if size == pos:
                    time.sleep(2)
                    continue
                with open(self.log_file, "r", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    clean = _strip_ansi(line)
                    m = _JOIN_RE.search(clean)
                    if m and "joined the game" in clean:
                        name = m.group(1)
                        if name not in joined:
                            joined[name] = time.monotonic()
                            self._greet_player(name)
                            last_line = clean
                        continue
                    lm = _LEAVE_RE.search(clean)
                    if lm:
                        joined.pop(lm.group(1), None)
            except Exception as e:
                logger.warning("Holding cell watcher error: %s", e)
            time.sleep(2)

    def _greet_player(self, name: str) -> None:
        # Broadcast to @a (everyone in the room) rather than targeting the
        # joining player by name: right after the "joined the game" log line the
        # player entity may not yet be a valid `tellraw <name>` target, which
        # silently drops the message. @a is immune to that timing/casing issue,
        # and the room is a tiny lobby so everyone seeing the link is fine.
        time.sleep(2)  # let the player finish logging in
        try:
            for raws in join_welcome_raws(self.cfg):
                self.send_command(f"tellraw @a {raws}")
            self.send_command(f"say Welcome {name} - the download link is in chat above!")
            log_event("ROOM", f"Welcomed {name} with clickable download link")
        except Exception as e:
            logger.warning("Holding cell greet error: %s", e)

    def _greet_players_present(self) -> None:
        """Re-send the download link to anyone already in the room.

        Called after a room rebuild so players who were present while the world
        regenerated still get the clickable modpack link.
        """
        try:
            for raws in join_welcome_raws(self.cfg):
                self.send_command(f"tellraw @a {raws}")
            self.send_command("say The download link is in chat - see it above!")
        except Exception as e:
            logger.warning("Holding cell greet-present error: %s", e)

    def stop_server_only(self) -> None:
        if self.is_running():
            self.send_command("stop")
            time.sleep(4)
            if self.is_running():
                subprocess.run(
                    f"tmux -S {TMUX_SOCKET} kill-session -t {TMUX_SESSION}", check=False,
                    shell=True,
                )

    def stop(self) -> bool:
        log_event("ROOM", "Stopping holding cell")
        self.stop_flag.set()
        if self.watcher_thread and self.watcher_thread.is_alive():
            self.watcher_thread.join(timeout=8)
        self.stop_server_only()
        self.running = False
        return True

    def status(self) -> dict:
        from .mod_hosting import game_join_address, public_download_link

        running = self.is_running()
        return {
            "running": running,
            "port": self.cfg.holding_cell_port,
            "address": room_join_address(self.cfg),
            "modpack_link": public_download_link(self.cfg),
            "modded_server": game_join_address(self.cfg),
            "room_size": min(int(self.cfg.holding_cell_room_size or 20), _MAX_ROOM_HEIGHT),
            "started": running,
        }


_cell_instance: VanillaHoldingCell | None = None


def get_holding_cell(cfg: ServerConfig | None = None) -> VanillaHoldingCell:
    """Get or create the shared holding cell instance."""
    global _cell_instance
    if _cell_instance is None:
        _cell_instance = VanillaHoldingCell(cfg or ServerConfig())
    return _cell_instance


def room_is_running() -> bool:
    return get_holding_cell().is_running()


__all__ = [
    "ROOM_BUILT_MARKER",
    "ROOM_DIR_NAME",
    "ROOM_LOG",
    "TMUX_SESSION",
    "VanillaHoldingCell",
    "download_vanilla_server",
    "get_holding_cell",
    "join_welcome_raws",
    "room_build_commands",
    "room_join_address",
    "room_properties",
    "room_is_running",
]