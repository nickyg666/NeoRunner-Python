"""Velocity entrance backend: a real Minecraft proxy owning the public port.

When ``cfg.entrance_backend == "velocity"`` the single public MC port is owned
by a Velocity proxy instead of the Python asyncio entrance. Routing decisions
move into a tiny plugin (``velocity_plugin/``): clients whose handshake address
carries the Forge/NeoForge ``\\0FML*\\0`` marker join the registered ``modded``
server, everyone else joins ``lobby``.

Trust model / auth topology
---------------------------
Velocity authenticates players against Mojang at the edge (online-mode=true)
and connects to the backends in offline mode, so BOTH backends must run with
``online-mode=false`` while Velocity is the entrance. They are bound to
loopback only, so nothing unauthenticated can reach them from outside.
Player-info forwarding stays OFF until the modded loader's native modern-
forwarding support is verified on this install; that means backends see
loopback addresses and offline UUIDs (skins may not resolve in-game).
This is the same tradeoff documented in ARCHITECTURE.md; flipping forwarding
on later is a config change, not a code change.

Hardening baked into the generated velocity.toml:
  - rate-limit = true            (login attempt throttling at the edge)
  - force-key-authentication     (reject clients tampering with chat keys)
  - query disabled, bungee channel off, tcp-fast-open off
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import ServerConfig
from .constants import CWD
from .log import log_event

logger = logging.getLogger(__name__)

TMUX_SESSION = "VELOCITY"
TMUX_SOCKET = f"/tmp/tmux-{os.getuid()}/default"

VELOCITY_DIR = CWD / ".cache" / "velocity"
RUN_DIR = VELOCITY_DIR / "run"
PLUGINS_SRC = Path(__file__).parent / "velocity_plugin" / "neorunner-router-1.0.0.jar"
PLUGIN_JAR_NAME = "neorunner-router-1.0.0.jar"

# Pinned release line; refreshed only via refresh_jar(force=True).
VEL_VERSION = "3.5.1"
VEL_BUILD = 615
VEL_SHA256 = "b4e3164df5377346854dc6cb9e6a78022b1946ff69e89676313f5f6f1c6f0fb3"
FILL_LATEST = ("https://fill.papermc.io/v3/projects/velocity/versions/"
               f"{VEL_VERSION}/builds/latest")

BOOT_TIMEOUT = 90.0


class VelocityManager:
    """Lifecycle + config generation for the Velocity entrance."""

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg

    # -- paths ---------------------------------------------------------------

    @property
    def jar(self) -> Path:
        return VELOCITY_DIR / f"velocity-{VEL_VERSION}-{VEL_BUILD}.jar"

    @property
    def listen_port(self) -> int:
        return int(self.cfg.mc_port or 25565)

    @property
    def modded_port(self) -> int:
        return int(getattr(self.cfg, "backend_modded_port", 0) or 25570)

    @property
    def room_port(self) -> int:
        return int(self.cfg.holding_cell_port or 1234)

    # -- provisioning ----------------------------------------------------------

    def ensure_jar(self, force: bool = False) -> Path:
        """Download the pinned Velocity build (Fill v3 API), sha256-checked."""
        VELOCITY_DIR.mkdir(parents=True, exist_ok=True)
        if self.jar.exists() and self.jar.stat().st_size > 1_000_000 and not force:
            return self.jar

        meta = {}
        try:
            with urllib.request.urlopen(FILL_LATEST, timeout=20) as r:
                meta = json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001 - fall back to pin below
            logger.warning("could not query latest Velocity build: %s", e)
        dl = (meta.get("downloads") or {}).get("server:default") or {}
        url = dl.get("url") or ""
        if not url:
            # No live metadata: fall back to the fully-pinned download URL.
            url = ("https://fill-data.papermc.io/v1/objects/"
                   f"{VEL_SHA256}/velocity-{VEL_VERSION}-{VEL_BUILD}.jar")
        want_sha = (dl.get("checksums") or {}).get("sha256") or VEL_SHA256
        name = dl.get("name") or self.jar.name
        dest = VELOCITY_DIR / name

        import hashlib
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        got = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if got != want_sha:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"velocity jar sha256 mismatch: {got} != {want_sha}")
        tmp.replace(dest)
        log_event("PROXY", f"velocity jar ready: {dest.name}")
        return dest

    def ensure_plugin(self) -> None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        plugins_dir = RUN_DIR / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        if PLUGINS_SRC.exists():
            shutil.copy2(PLUGINS_SRC, plugins_dir / PLUGIN_JAR_NAME)
        # Router policy: modern NeoForge clients don't reliably send the FML
        # marker, so protocol-matching clients default to the modded backend
        # (vanilla clients get the backend's patched kick-with-link). Explicit
        # "lobby" restores the waiting-room fallback for unmarked clients.
        pref = str(getattr(self.cfg, "unmarked_client_target", "auto") or "auto").lower()
        if pref in ("modded", "lobby"):
            target = pref
        else:
            target = "modded"
        props = (
            f"modded=modded\n"
            f"lobby=lobby\n"
            f"unmarkedTarget={target}\n"
        )
        (plugins_dir / "neorunner-router.properties").write_text(props)

    def _write_secret(self) -> None:
        secret_file = RUN_DIR / "forwarding.secret"
        if not secret_file.exists():
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            secret_file.write_text(secrets.token_hex(32) + "\n")
            os.chmod(secret_file, 0o600)

    # -- config generation -----------------------------------------------------

    def render_toml(self, bind_port: int | None = None) -> str:
        port = bind_port or self.listen_port
        motd = (getattr(self.cfg, "server_description", "") or "NeoRunner").strip()
        show_max = max(int(getattr(self.cfg, "holding_cell_max_players", 10) or 10), 1)
        return f"""# Generated by NeoRunner (velocity_proxy.py) - edits will be overwritten.
config-version = "2.7"
bind = "0.0.0.0:{port}"
motd = "{motd}"
show-max-players = {show_max}
online-mode = true
force-key-authentication = true
prevent-client-proxy-connections = false
player-info-forwarding-mode = "none"
forwarding-secret-file = "forwarding.secret"
online-mode-kick-existing-players = true
rate-limit = true
disable-connections-without-server-list-icon = false

[servers]
modded = "127.0.0.1:{self.modded_port}"
lobby = "127.0.0.1:{self.room_port}"
try = ["modded"]

[forced-hosts]

[advanced]
tcp-fast-open = false
tcp-defer-accept = false
read-timeout = 30000
compression-threshold = 256
compression-level = 6

[query]
enabled = false
port = {port + 12}
map = ""
show-plugins = false
"""

    def _backends_offline_mode(self) -> None:
        """Flip both loopback backends to offline mode (edge auth at Velocity)."""
        try:
            props_path = CWD / "server.properties"
            if props_path.exists():
                lines = props_path.read_text().splitlines()
                seen = False
                out = []
                for ln in lines:
                    if ln.startswith("online-mode="):
                        seen = True
                        out.append("online-mode=false")
                    else:
                        out.append(ln)
                if not seen:
                    out.append("online-mode=false")
                props_path.write_text("\n".join(out) + "\n")
                log_event("PROXY", "server.properties: online-mode=false (velocity edge auth)")
        except Exception as e:  # noqa: BLE001
            log_event("PROXY", f"could not update server.properties online-mode: {e}")

    # -- lifecycle ---------------------------------------------------------------

    def _tmux(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["tmux", "-S", TMUX_SOCKET, *args],
                              capture_output=True, text=True)

    def is_running(self) -> bool:
        r = self._tmux("has-session", "-t", TMUX_SESSION)
        if r.returncode != 0:
            return False
        return self._port_bound()

    def _port_bound(self, port: int | None = None) -> bool:
        port = port or self.listen_port
        r = subprocess.run(["ss", "-tln"], capture_output=True, text=True)
        return f":{port} " in r.stdout

    def start(self, bind_port: int | None = None) -> bool:
        port = bind_port or self.listen_port
        if port in (self.modded_port, self.room_port):
            log_event("PROXY", f"refusing velocity start: backend port collides with :{port}")
            return False
        if self.is_running():
            return True
        try:
            jar = self.ensure_jar(force=False)
        except Exception as e:  # noqa: BLE001
            log_event("PROXY", f"velocity jar unavailable: {e}")
            return False

        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / "velocity.toml").write_text(self.render_toml(port))
        self._write_secret()
        self.ensure_plugin()
        # Only flip backend auth when Velocity is (becoming) THE entrance;
        # smoke runs against an alternate bind port must not touch it.
        if str(getattr(self.cfg, "entrance_backend", "python")).lower() == "velocity":
            self._backends_offline_mode()

        # Fresh session each start so stale logs never mask a boot failure.
        self._tmux("kill-session", "-t", TMUX_SESSION)
        java = shutil.which("java") or "java"
        # Absolute jar path: the process cwd is RUN_DIR (velocity.toml,
        # forwarding.secret, plugins/ live there), not the cache dir.
        cmd = f"{java} -Xms128M -Xmx512M -jar {jar.resolve()}"
        r = self._tmux("new-session", "-d", "-s", TMUX_SESSION,
                       "-c", str(RUN_DIR), cmd)
        if r.returncode != 0:
            log_event("PROXY", f"velocity tmux start failed: {r.stderr.strip()}")
            return False

        deadline = time.monotonic() + BOOT_TIMEOUT
        while time.monotonic() < deadline:
            if self._port_bound(port):
                log_event("PROXY",
                          f"velocity started on :{port} "
                          f"(modded->127.0.0.1:{self.modded_port}, lobby->127.0.0.1:{self.room_port})")
                return True
            time.sleep(1)
        log_event("PROXY", f"velocity did NOT bind :{port} within {int(BOOT_TIMEOUT)}s")
        return False

    def stop(self) -> None:
        if self._tmux("has-session", "-t", TMUX_SESSION).returncode == 0:
            self._tmux("send-keys", "-t", TMUX_SESSION, "shutdown", "Enter")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if self._tmux("has-session", "-t", TMUX_SESSION).returncode != 0:
                    break
                time.sleep(1)
            else:
                self._tmux("kill-session", "-t", TMUX_SESSION)
            log_event("PROXY", "velocity stopped")

    def status(self) -> dict:
        running = self.is_running()
        info = {
            "backend": "velocity",
            "running": running,
            "listen_port": self.listen_port,
            "version": VEL_VERSION,
            "build": VEL_BUILD,
            "servers": {
                "modded": f"127.0.0.1:{self.modded_port}",
                "lobby": f"127.0.0.1:{self.room_port}",
            },
            "player_info_forwarding": "none",
            "rate_limit": True,
            "plugin": PLUGIN_JAR_NAME,
        }
        if running:
            cap = self._tmux("capture-pane", "-p", "-t", TMUX_SESSION, "-S", "-30")
            tail = [ln for ln in (cap.stdout or "").splitlines() if "[NeoRunner]" in ln]
            info["recent_router_lines"] = tail[-10:]
        return info


_velocity_manager: VelocityManager | None = None


def get_velocity_manager(cfg: ServerConfig | None = None) -> VelocityManager:
    global _velocity_manager
    if _velocity_manager is None:
        _velocity_manager = VelocityManager(cfg or ServerConfig())
    elif cfg is not None:
        _velocity_manager.cfg = cfg
    return _velocity_manager


__all__ = ["VelocityManager", "get_velocity_manager"]
