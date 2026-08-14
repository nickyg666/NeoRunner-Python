"""
Web dashboard for NeoRunner using Flask.
Provides server management, mod management, world management, and configuration UI.
"""


import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from .config import ServerConfig, load_cfg, save_cfg
from .constants import CWD
from .log import log_event
from .version import get_latest_minecraft_version

# Setup logging
log = logging.getLogger(__name__)

# Create Flask app
template_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"
app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))
DASHBOARD_PORT = None
app.secret_key = os.urandom(24)

# Admin auth: checked against the user store (.neorunner-users.json), falling
# back to env bootstrap credentials only when no users exist yet. Download and
# other client-facing routes are public by default — only the admin UI and the
# /api/* control surface require authentication.
ADMIN_USER = os.environ.get("NEORUNNER_ADMIN_USER", "mc")
ADMIN_PASS = os.environ.get("NEORUNNER_ADMIN_PASS", "123")

# Paths that ALWAYS require auth (admin surface). Everything else is public
# unless it starts with /api/ (see require_basic_auth).
AUTH_REQUIRED_PREFIXES = ("/admin",)
AUTH_PUBLIC_PREFIXES = ("/download", "/static/", "/favicon.ico", "/socket.io")


def _check_auth(user: str, password: str) -> bool:
    """Return True if the supplied credentials are valid.

    Prefers the persisted user store; falls back to env bootstrap credentials
    only when no users have been provisioned yet (first run before setup).
    """
    from .users import has_users, verify_credentials
    if has_users():
        return verify_credentials(user, password)
    return user == ADMIN_USER and password == ADMIN_PASS


def _requires_auth(path: str) -> bool:
    """True when a request path must be authenticated.

    Protected: the admin dashboard UI (/ and /admin), the setup wizard, and the
    entire /api/* control surface. Public: /download/*, static assets, favicon,
    and websocket handshakes (so the installer JAR + download scripts stay open).
    """
    if any(path.startswith(p) for p in AUTH_PUBLIC_PREFIXES):
        return False
    if path.startswith("/api/"):
        return True
    return path in ("/", "/admin", "/admin/") or path.startswith("/admin/")


@app.before_request
def require_basic_auth():
    """Gate the admin dashboard and API with HTTP Basic Auth.

    Client-facing routes (/download/*, websocket, static assets) are public so
    the installer JAR and download scripts keep working unauthenticated.
    """
    if request.method == "OPTIONS":
        return None
    if not _requires_auth(request.path):
        return None
    auth = request.authorization
    if not auth or not _check_auth(auth.username, auth.password):
        return Response(
            "NeoRunner admin requires authentication",
            401,
            {"WWW-Authenticate": 'Basic realm="NeoRunner Admin"'},
        )
    return None


class DashboardState:
    """Shared state for dashboard."""
    def __init__(self):
        self.last_zip_creation: float | None = None
        self.client_mod_status: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.max_events = 200
        
    def add_event(self, event_type: str, message: str):
        """Add an event to the event log."""
        self.events.append({
            "type": event_type,
            "message": message,
            "time": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        })
        # Trim to max
        while len(self.events) > self.max_events:
            self.events.pop(0)


# Global state
state = DashboardState()


def get_config_path() -> Path:
    """Get the config file path."""
    return CWD / "config.json"


def parse_server_properties() -> dict[str, str]:
    """Parse server.properties file."""
    props = {}
    props_path = CWD / "server.properties"
    if props_path.exists():
        with open(props_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    props[k] = v
    return props


def write_server_properties(props: dict[str, str]) -> None:
    """Write server.properties, preserving existing keys and updating values."""
    props_path = CWD / "server.properties"
    updates = dict(props)
    if props_path.exists():
        lines = []
        seen = set()
        with open(props_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k = line.strip().split("=", 1)[0]
                    if k in updates:
                        lines.append(f"{k}={updates.pop(k)}\n")
                        seen.add(k)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
        for k, v in updates.items():
            lines.append(f"{k}={v}\n")
        with open(props_path, "w") as f:
            f.writelines(lines)
    else:
        with open(props_path, "w") as f:
            for k, v in updates.items():
                f.write(f"{k}={v}\n")


def scan_worlds() -> list[dict[str, Any]]:
    """Scan for world folders (folders containing level.dat)."""
    cfg = load_cfg()
    server_mc_version = cfg.mc_version
    if not server_mc_version:
        server_mc_version = get_latest_minecraft_version()
    worlds = []
    
    try:
        for entry in os.listdir(CWD):
            entry_path = CWD / entry
            if entry_path.is_dir():
                level_dat = entry_path / "level.dat"
                if level_dat.exists():
                    try:
                        stat = entry_path.stat()
                        # Try to get world version info
                        try:
                            from .nbt_parser import get_world_version
                            version_info = get_world_version(str(level_dat))
                            world_version = version_info.get("version")
                            compatible = world_version == server_mc_version if world_version else True
                        except Exception:
                            version_info = {}
                            world_version = None
                            compatible = True
                        
                        # Calculate size
                        size = 0
                        for dirpath, _, filenames in os.walk(entry_path):
                            for f in filenames:
                                try:
                                    size += os.path.getsize(os.path.join(dirpath, f))
                                except Exception:
                                    pass
                        
                        worlds.append({
                            "name": entry,
                            "path": str(entry_path),
                            "size": size,
                            "size_mb": round(size / (1024*1024), 2),
                            "modified": stat.st_mtime,
                            "mc_version": world_version,
                            "compatible": compatible
                        })
                    except Exception:
                        worlds.append({
                            "name": entry,
                            "path": str(entry_path),
                            "mc_version": None,
                            "compatible": True
                        })
    except Exception as e:
        log_event("ERROR", f"Failed to scan worlds: {e}")
    
    return sorted(worlds, key=lambda w: w.get("name", ""))


def switch_world(world_name: str, force: bool = False) -> tuple[bool, str]:
    """Switch to a different world by updating server.properties."""
    props_path = CWD / "server.properties"
    if not props_path.exists():
        return False, "server.properties not found"
    
    world_path = CWD / world_name
    level_dat = world_path / "level.dat"
    if not level_dat.exists():
        return False, f"World '{world_name}' not found (no level.dat)"
    
    cfg = load_cfg()
    if not force:
        server_mc_version = cfg.mc_version
        if not server_mc_version:
            server_mc_version = get_latest_minecraft_version()
        try:
            from .nbt_parser import get_world_version
            version_info = get_world_version(str(level_dat))
            world_version = version_info.get("version")
            if world_version and world_version != server_mc_version:
                return False, f"Version mismatch: world is MC {world_version}, server is MC {server_mc_version}"
        except Exception:
            pass
    
    lines = []
    found = False
    with open(props_path, "r") as f:
        for line in f:
            if line.strip().startswith("level-name="):
                lines.append(f"level-name={world_name}\n")
                found = True
            else:
                lines.append(line)
    
    if not found:
        lines.append(f"level-name={world_name}\n")
    
    with open(props_path, "w") as f:
        f.writelines(lines)
    
    log_event("WORLD_SWITCH", f"Switched to world: {world_name}")
    return True, f"World switched to '{world_name}'. Restart server to apply."


def get_server_status() -> dict[str, Any]:
    """Get server status (running, player count, etc)."""
    import subprocess
    
    running = False
    status_detail = "Stopped"
    
    # Check if tmux session exists
    uid = os.getuid()
    tmux_socket = f"/tmp/tmux-{uid}/default"
    result = subprocess.run(
        f"tmux -S {tmux_socket} list-sessions 2>/dev/null | grep -c MC", check=False,
        shell=True, capture_output=True, text=True
    )
    running = result.stdout.strip() == "1"
    
    # Also check for java process as backup
    if not running:
        ps_result = subprocess.run(
            ["ps", "aux"], check=False,
            capture_output=True,
            text=True,
        )
        for line in ps_result.stdout.split("\n"):
            if "java" in line.lower() and ("neoforge" in line.lower() or " forge" in line.lower() or "fabric" in line.lower()) and "grep" not in line.lower():
                running = True
                break
    
    if running:
        status_detail = "Running"
    
    cfg = load_cfg()
    
    # Check if preflight was run recently
    preflight_status = "Not run"
    preflight_cache = CWD / ".preflight_cache"
    if preflight_cache.exists():
        try:
            import time
            cache_time = float(preflight_cache.read_text().strip())
            age = time.time() - cache_time
            if age < 3600:  # Within last hour
                preflight_status = f"OK ({int(age/60)}m ago)"
            else:
                preflight_status = f"Stale ({int(age/3600)}h ago)"
        except Exception:
            preflight_status = "Unknown"
    
    # Get world info
    world_name = "world"
    world_version = None
    try:
        props = parse_server_properties()
        world_name = props.get("level-name", "world")
        level_dat = CWD / world_name / "level.dat"
        if level_dat.exists():
            try:
                from .nbt_parser import get_world_version
                version_info = get_world_version(str(level_dat))
                world_version = version_info.get("version", "unknown")
            except Exception:
                world_version = "unknown"
    except Exception:
        pass
    
    # Try to get player list from RCON
    players = []
    if running and cfg.rcon_pass:
        try:
            rcon_result = subprocess.run(
                f"echo 'list' | nc -w 1 localhost {cfg.rcon_port} 2>/dev/null", check=False,
                shell=True, capture_output=True, text=True
            )
            if rcon_result.returncode == 0:
                players_text = rcon_result.stdout
                if "player" in players_text.lower():
                    players = players_text.split("\n")
        except Exception:
            pass
    
    # Get mod count
    mods_dir = CWD / cfg.mods_dir
    mod_count = len([f for f in os.listdir(mods_dir) if f.endswith(".jar")]) if mods_dir.exists() else 0
    
    # Get clientonly mod count - check multiple possible locations
    client_mod_count = 0
    for check_dir in [CWD / "clientonly", CWD / cfg.clientonly_dir]:
        if check_dir.exists():
            client_mod_count = len([f for f in os.listdir(check_dir) if f.endswith(".jar")])
            break
    
    # Determine MC version - use dynamic fetch if missing from config
    mc_version = cfg.mc_version
    if not mc_version:
        mc_version = get_latest_minecraft_version()
    
    return {
        "running": running,
        "status_detail": status_detail,
        "loader": cfg.loader,
        "mc_version": mc_version,
        "mod_count": mod_count,
        "client_mod_count": client_mod_count,
        "player_count": len([p for p in players if p.strip()]) if players else 0,
        "rcon_enabled": cfg.rcon_pass is not None,
        "uptime": get_uptime() if running else 0,
        "preflight_status": preflight_status,
        "world_name": world_name,
        "world_version": world_version,
    }


def get_uptime() -> str:
    """Get server uptime in seconds."""
    import subprocess
    try:
        result = subprocess.run(
            "ps aux | grep '[m]inecraft.*nogui' | awk '{print $2}'", check=False,
            shell=True, capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip()
            result = subprocess.run(
                f"ps -o etime= -p {pid}", check=False,
                shell=True, capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def get_mod_list() -> list[dict[str, Any]]:
    """Get list of installed mods."""
    cfg = load_cfg()
    mods_dir = CWD / cfg.mods_dir
    
    mods = []
    if mods_dir.exists():
        for filename in sorted(os.listdir(mods_dir)):
            if filename.endswith(".jar"):
                path = mods_dir / filename
                try:
                    size = path.stat().st_size
                    mods.append({
                        "name": filename,
                        "size": size,
                        "size_mb": round(size / (1024*1024), 2),
                        "path": filename
                    })
                except Exception:
                    pass
    
    return sorted(mods, key=lambda x: x["name"])


def get_client_mods() -> list[dict[str, Any]]:
    """Get list of client-side mods from clientonly folder."""
    cfg = load_cfg()
    CWD / cfg.mods_dir
    clientonly_dir = Path(cfg.clientonly_dir)
    if not clientonly_dir.is_absolute():
        clientonly_dir = CWD / clientonly_dir
    mods = []
    
    if clientonly_dir.exists():
        for filename in sorted(os.listdir(clientonly_dir)):
            if filename.endswith(".jar"):
                path = clientonly_dir / filename
                try:
                    size = path.stat().st_size
                    mods.append({
                        "id": filename,
                        "name": filename,
                        "size": f"{round(size / (1024*1024), 2)} MB",
                        "type": "client"
                    })
                except Exception:
                    pass
    
    return mods


# ═══════════════════════════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/admin")
@app.route("/admin/")
def admin_index():
    """Alias for the dashboard (IP:8000/admin)."""
    return redirect(url_for("dashboard"))


@app.route("/")
def dashboard():
    """Main dashboard page."""
    # Check if first start (no server.properties)
    if app.config.get('FIRST_START', False) or not (CWD / "server.properties").exists():
        return render_template("setup_wizard.html")
    return render_template("dashboard.html")


@app.route("/download")
@app.route("/download/")
def download_landing():
    """Public download landing page (the classic choices page).

    Served without auth so players can grab the modpack. Renders the same
    options page the public_site app used to serve (installer JAR, launcher
    zip, CurseForge zip, install script).
    """
    from .public_site import index as public_index
    return public_index()


@app.route("/api/status")
def api_status():
    """Get server status."""
    return jsonify(get_server_status())


@app.route("/api/config")
def api_config():
    """Get current config."""
    cfg = load_cfg()
    props = parse_server_properties()
    
    config_dict = cfg.to_dict()
    config_dict["rcon_pass"] = "***"  # Hide password
    config_dict["server_port"] = props.get("server-port", cfg.mc_port)
    config_dict["query_port"] = props.get("query.port", "25565")
    config_dict["rcon_port"] = props.get("rcon.port", cfg.rcon_port)
    
    # Get server IP for display - dynamically detect LAN IP, never hardcode
    from .mod_hosting import get_server_ip as _detect_ip
    server_ip = _detect_ip() or "0.0.0.0"
    config_dict["server_ip"] = server_ip
    
    return jsonify(config_dict)


@app.route("/api/config", methods=["POST"])
def api_config_update():
    """Update configuration."""
    try:
        data = request.json
        cfg = load_cfg()
        
        # Update allowed fields (all settings exposed in the dashboard UI)
        allowed_fields = [
            "ferium_update_interval_hours",
            "ferium_weekly_update_day",
            "ferium_weekly_update_hour",
            "rcon_port",
            "rcon_host",
            "http_port",
            "mc_port",
            "mc_version",
            "loader",
            "mods_dir",
            "clientonly_dir",
            "quarantine_dir",
            "hostname",
            "curator_sort",
            "curator_limit",
            "curator_max_depth",
            "curator_show_optional_audit",
            "broadcast_enabled",
            "broadcast_auto_on_install",
            "nag_show_mod_list_on_join",
            "nag_first_visit_modal",
            "motd_show_download_url",
            "xmx",
            "xms",
            "view_distance",
            "simulation_distance",
            "max_tick_time",
            "max_download_mb",
            "rate_limit_seconds",
            "run_curator_on_startup",
            "install_script_types",
            "log_retention_days",
            "crash_report_retention_days",
            "live_log_max_size_mb",
            "live_log_backup_count",
            "max_restart_attempts",
            "max_crashes_before_quarantine",
        ]

        int_fields = {
            "ferium_update_interval_hours", "ferium_weekly_update_hour", "curator_limit",
            "max_download_mb", "rate_limit_seconds", "log_retention_days",
            "crash_report_retention_days", "live_log_max_size_mb", "live_log_backup_count",
            "max_restart_attempts", "max_crashes_before_quarantine",
        }
        bool_fields = {
            "curator_show_optional_audit", "broadcast_enabled", "broadcast_auto_on_install",
            "nag_show_mod_list_on_join", "nag_first_visit_modal", "motd_show_download_url",
            "run_curator_on_startup",
        }

        for field in allowed_fields:
            if field not in data:
                continue
            value = data[field]
            if field in int_fields:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif field in bool_fields:
                value = bool(value)
            elif field in ("http_port", "mc_port"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            setattr(cfg, field, value)
        
        save_cfg(cfg)
        log_event("CONFIG_UPDATE", f"Updated: {list(data.keys())}")
        
        return jsonify({"success": True, "message": "Config updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods")
def api_mods():
    """Get mod list."""
    return jsonify(get_mod_list())


@app.route("/api/server-mods")
def api_server_mods():
    """Get list of server-side mods."""
    mods = []
    for mod in get_mod_list():
        mods.append({
            "id": mod["name"],
            "name": mod["name"],
            "size": f"{mod['size_mb']} MB",
            "type": "server"
        })
    return jsonify({"mods": mods})


@app.route("/api/client-mods")
def api_client_mods():
    """Get list of client-side mods from clientonly folder."""
    return jsonify({"mods": get_client_mods()})


@app.route("/api/quarantine-all-client-mods", methods=["POST"])
def api_quarantine_all_client_mods():
    """Quarantine ALL client-side mods."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        clientonly_dir = mods_dir / "clientonly"
        quarantine_dir = mods_dir / "quarantine"
        
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        
        quarantined = 0
        if clientonly_dir.exists():
            import shutil
            for filename in list(os.listdir(clientonly_dir)):
                if filename.endswith(".jar"):
                    src = clientonly_dir / filename
                    dst = quarantine_dir / filename
                    
                    if not dst.exists():
                        shutil.move(str(src), str(dst))
                        quarantined += 1
        
        log_event("QUARANTINE", f"Quarantined {quarantined} client mods")
        return jsonify({"success": True, "quarantined": quarantined})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/sort-client-mods", methods=["POST"])
def api_sort_client_mods():
    """Sort mods into clientonly folder."""
    try:
        cfg = load_cfg()
        from .mods import sort_mods_by_type
        
        mods_dir = CWD / cfg.mods_dir
        result = sort_mods_by_type(mods_dir, cfg)
        
        # Move client mods to clientonly folder
        import shutil
        clientonly_dir = mods_dir / "clientonly"
        clientonly_dir.mkdir(exist_ok=True)
        
        moved = 0
        for jar_path in result.get("clientonly", []):
            dest = clientonly_dir / jar_path.name
            if not dest.exists():
                shutil.move(str(jar_path), str(dest))
                moved += 1
        
        return jsonify({"success": True, "moved": moved})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/<mod_name>", methods=["DELETE"])
def api_remove_mod(mod_name):
    """Remove a mod."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        mod_path = mods_dir / mod_name
        
        # Security: prevent path traversal
        if not str(mod_path.resolve()).startswith(str(mods_dir.resolve())):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        if mod_path.exists() and mod_path.suffix == ".jar":
            mod_path.unlink()
            log_event("MOD_REMOVE", f"Removed mod: {mod_name}")
            return jsonify({"success": True, "message": f"Removed {mod_name}"})
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/upload", methods=["POST"])
def api_upload_mod():
    """Upload a mod JAR file."""
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        
        file = request.files['file']
        if not file.filename or not file.filename.endswith('.jar'):
            return jsonify({"success": False, "error": "Only .jar files allowed"}), 400
        
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        mods_dir.mkdir(exist_ok=True)
        
        filename = file.filename
        save_path = mods_dir / filename
        
        # Don't overwrite existing
        if save_path.exists():
            return jsonify({"success": False, "error": f"Mod {filename} already exists"}), 400
        
        file.save(save_path)
        log_event("MOD_UPLOAD", f"Uploaded mod: {filename}")
        
        return jsonify({
            "success": True, 
            "message": f"Uploaded {filename}",
            "mod": filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


MODPACK_UPLOAD_DIR = CWD / "modpacks"


def _modpack_list() -> list[dict[str, Any]]:
    """List uploaded modpack zips with metadata."""
    MODPACK_UPLOAD_DIR.mkdir(exist_ok=True)
    packs = []
    for f in sorted(MODPACK_UPLOAD_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        packs.append({
            "filename": f.name,
            "size": f.stat().st_size,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return packs


@app.route("/api/modpacks", methods=["GET"])
def api_modpacks():
    """List uploaded modpack zips."""
    try:
        return jsonify({"success": True, "packs": _modpack_list()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/modpack/upload", methods=["POST"])
def api_upload_modpack():
    """Upload a CurseForge-format modpack zip."""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        file = request.files["file"]
        if not file.filename or not file.filename.endswith(".zip"):
            return jsonify({"success": False, "error": "Only .zip modpack files allowed"}), 400

        MODPACK_UPLOAD_DIR.mkdir(exist_ok=True)
        filename = Path(file.filename).name
        save_path = MODPACK_UPLOAD_DIR / filename
        if save_path.exists():
            save_path.unlink()
        file.save(save_path)

        # Validate it smells like a CurseForge pack before accepting.
        from .modpack_installer import parse_manifest
        manifest, files = parse_manifest(save_path)
        log_event(
            "MODPACK_UPLOAD",
            f"Uploaded modpack: {filename} ({len(files)} files, MC {manifest.get('minecraft', {}).get('version', '?')})",
        )
        return jsonify({
            "success": True,
            "message": f"Uploaded {filename}",
            "filename": filename,
            "manifest": {
                "name": manifest.get("name"),
                "version": manifest.get("version"),
                "mc_version": manifest.get("minecraft", {}).get("version"),
                "mod_count": len(files),
            },
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Invalid modpack zip: {e}"}), 400


@app.route("/api/modpack/install", methods=["POST"])
def api_install_modpack():
    """Install an uploaded modpack zip (downloads mods, applies overrides)."""
    try:
        data = request.json or {}
        filename = Path(data.get("filename", "")).name
        if not filename or not filename.endswith(".zip"):
            return jsonify({"success": False, "error": "No modpack specified"}), 400

        zip_path = MODPACK_UPLOAD_DIR / filename
        if not zip_path.exists():
            return jsonify({"success": False, "error": f"Modpack {filename} not found"}), 404

        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir

        from .modpack_installer import install_curseforge_pack
        result = install_curseforge_pack(
            zip_path,
            mods_dir,
            overrides_dir=CWD,
        )
        log_event(
            "MODPACK_INSTALL",
            f"Installed {filename}: {result.installed} mods, {result.failed} failed, overrides applied",
        )
        return jsonify({
            "success": result.failed == 0,
            "message": (
                f"Installed {result.installed}/{result.total} mods, "
                f"{result.failed} failed, overrides applied"
            ),
            "result": {
                "pack": result.pack_name,
                "pack_version": result.pack_version,
                "mc_version": result.mc_version,
                "loader": result.loader,
                "installed": result.installed,
                "failed": result.failed,
                "skipped": result.skipped,
                "total": result.total,
                "errors": result.errors,
                "files": result.files,
            },
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/modpack/delete", methods=["POST"])
def api_delete_modpack():
    """Delete an uploaded modpack zip."""
    try:
        data = request.json or {}
        filename = Path(data.get("filename", "")).name
        if not filename or not filename.endswith(".zip"):
            return jsonify({"success": False, "error": "No modpack specified"}), 400
        zip_path = MODPACK_UPLOAD_DIR / filename
        if not zip_path.exists():
            return jsonify({"success": False, "error": f"Modpack {filename} not found"}), 404
        zip_path.unlink()
        log_event("MODPACK_DELETE", f"Deleted modpack: {filename}")
        return jsonify({"success": True, "message": f"Deleted {filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/server/start", methods=["POST"])
def api_server_start():
    """Start server."""
    try:
        from .server import is_server_running, run_server
        
        if is_server_running():
            return jsonify({"success": False, "error": "Server is already running"}), 400
        
        success = run_server()
        if success:
            state.add_event("SERVER_START", "Server started via dashboard")
            return jsonify({"success": True, "message": "Server starting..."})
        else:
            return jsonify({"success": False, "error": "Failed to start server"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    """Stop server."""
    try:
        from .server import is_server_running, stop_server
        
        if not is_server_running():
            return jsonify({"success": False, "error": "Server is not running"}), 400
        
        if stop_server():
            state.add_event("SERVER_STOP", "Server stopped via dashboard")
            return jsonify({"success": True, "message": "Server stopped"})
        else:
            return jsonify({"success": False, "error": "Failed to stop server"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/server/restart", methods=["POST"])
def api_server_restart():
    """Restart server."""
    try:
        from .server import is_server_running, restart_server
        
        if not is_server_running():
            return jsonify({"success": False, "error": "Server is not running"}), 400
        
        state.add_event("SERVER_RESTART", "Server restarting via dashboard...")
        if restart_server():
            return jsonify({"success": True, "message": "Server restarting..."})
        else:
            return jsonify({"success": False, "error": "Failed to restart server"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/server/status")
def api_server_status():
    """Get server status."""
    try:
        from .server import get_server, is_server_running
        
        running = is_server_running()
        server = get_server()
        
        return jsonify({
            "success": True,
            "running": running,
            "loader": server.cfg.loader if server.cfg else "unknown",
            "mc_version": server.cfg.mc_version if server.cfg else "unknown",
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/server/send", methods=["POST"])
def api_server_send():
    """Send command to server."""
    try:
        from .server import is_server_running, send_command
        
        if not is_server_running():
            return jsonify({"success": False, "error": "Server is not running"}), 400
        
        data = request.get_json()
        cmd = data.get("command", "").strip()
        
        if not cmd:
            return jsonify({"success": False, "error": "No command provided"}), 400
        
        if send_command(cmd):
            return jsonify({"success": True, "message": f"Command sent: {cmd}"})
        else:
            return jsonify({"success": False, "error": "Failed to send command"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/system/stats")
def api_system_stats():
    """Return host system stats: CPU, RAM, and disk usage."""
    try:
        import os
        import shutil

        # Disk usage of the server working directory.
        disk = shutil.disk_usage(str(CWD))
        total_gb = disk.total / (1024 ** 3)
        used_gb = disk.used / (1024 ** 3)
        free_gb = disk.free / (1024 ** 3)
        disk_pct = round((disk.used / disk.total) * 100, 1) if disk.total else 0

        # RAM via /proc/meminfo (Linux) or os.sysconf.
        mem_total = mem_used = mem_free = 0
        try:
            with open("/proc/meminfo") as f:
                info = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        info[parts[0].strip()] = int(parts[1].strip().split()[0]) * 1024
            mem_total = info.get("MemTotal", 0)
            mem_free = info.get("MemAvailable", info.get("MemFree", 0))
            mem_used = max(0, mem_total - mem_free)
        except Exception:
            mem_total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            mem_used = mem_total - (os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
            mem_free = mem_total - mem_used
        mem_pct = round((mem_used / mem_total) * 100, 1) if mem_total else 0

        # Load average.
        load = []
        try:
            with open("/proc/loadavg") as f:
                load = f.read().split()[:3]
        except Exception:
            pass

        # Per-process memory of the java server if running.
        java_mb = 0
        try:
            import subprocess as sp
            out = sp.run(
                ["ps", "-o", "rss=", "-C", "java"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            java_mb = sum(int(line.strip()) for line in out.stdout.splitlines() if line.strip()) // 1024
        except Exception:
            pass

        return jsonify({
            "success": True,
            "cpu": {
                "load_1m": load[0] if load else None,
                "load_5m": load[1] if len(load) > 1 else None,
                "load_15m": load[2] if len(load) > 2 else None,
            },
            "memory": {
                "total_gb": round(mem_total / (1024 ** 3), 1),
                "used_gb": round(mem_used / (1024 ** 3), 1),
                "free_gb": round(mem_free / (1024 ** 3), 1),
                "percent": mem_pct,
                "java_mb": java_mb,
            },
            "disk": {
                "total_gb": round(total_gb, 1),
                "used_gb": round(used_gb, 1),
                "free_gb": round(free_gb, 1),
                "percent": disk_pct,
            },
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/upgrade", methods=["POST"])
def api_upgrade_mods():
    """Upgrade all mods via ferium."""
    try:
        load_cfg()
        ferium_bin = CWD / ".local" / "bin" / "ferium"
        
        import subprocess
        result = subprocess.run(
            [str(ferium_bin), "upgrade"], check=False,
            capture_output=True, text=True, timeout=300
        )
        
        if result.returncode == 0:
            log_event("MOD_UPGRADE", "Mods upgraded via ferium")
            return jsonify({"success": True, "message": "Mods upgraded"})
        else:
            return jsonify({"success": False, "error": result.stderr}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/logs")
def api_logs():
    """Get recent log lines."""
    lines_param = request.args.get("lines", 50, type=int)
    lines_param = min(lines_param, 500)  # Max 500 lines
    
    log_file = CWD / "live.log"
    logs = []
    
    if log_file.exists():
        try:
            with open(log_file) as f:
                all_lines = f.readlines()
                logs = all_lines[-lines_param:]
        except Exception:
            pass
    
    return jsonify({"logs": logs})


@app.route("/api/logs/stream")
def logs_stream():
    """Server-Sent Events stream for real-time log monitoring.
    
    Returns a continuous stream of new log lines as they are written.
    Uses SSE format for browser EventSource compatibility.
    """
    import time
    
    log_file = CWD / "live.log"
    
    def generate():
        if not log_file.exists():
            yield "data: <no logs>\n\n"
            return
        
        # Send initial connection message
        yield "data: <connected>\n\n"
        
        # Track position for efficient reading
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)  # Start at end

            while True:
                try:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    # SSE format: "data: <content>\n\n"
                    yield f"data: {line}"
                except GeneratorExit:
                    break
                except Exception:
                    time.sleep(1)
                    continue
    
    return Response(generate(), mimetype='text/event-stream')


@app.route("/stream/logs")
def raw_log_stream():
    """Raw text log stream for external monitoring.
    
    Returns plain text, one log line per line - no HTML, no JSON, no SSE.
    Perfect for curl/wget scripts or monitoring systems.
    
    Usage: curl -N http://IP:PORT/stream/logs
    """
    import time
    
    log_file = CWD / "live.log"
    
    def generate():
        if not log_file.exists():
            return
        
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)  # Start at end - only new lines
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                yield line
    
    return Response(generate(), mimetype='text/plain')


@app.route("/api/download/<mod_name>")
def api_download_mod(mod_name):
    """Download a mod."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        mod_path = mods_dir / mod_name
        
        # Security: prevent path traversal
        if not str(mod_path.resolve()).startswith(str(mods_dir.resolve())):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        if mod_path.exists() and mod_path.suffix == ".jar":
            return send_file(mod_path, as_attachment=True)
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mod-lists")
def api_mod_lists():
    """Return curated mod lists from cache, with installed status for each mod."""
    from .mods import parse_mod_manifest
    
    cfg = load_cfg()
    loader = cfg.loader
    mc_ver = cfg.mc_version
    mods_dir = CWD / cfg.mods_dir
    
    installed = set()
    if mods_dir.exists():
        for jar in mods_dir.glob("*.jar"):
            manifest = parse_mod_manifest(jar)
            if manifest:
                installed.add(manifest.get("mod_id", jar.stem))
            installed.add(jar.stem)
    
    cache_file = CWD / f"curator_cache_{mc_ver}_{loader}.json"
    
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                raw = json.load(f)
            
            if isinstance(raw, dict):
                for key in raw:
                    if isinstance(raw[key], list):
                        for mod in raw[key]:
                            mod_id = mod.get("id") or mod.get("project_id")
                            if mod_id in installed or mod.get("name", "").replace("-", "").replace("_", "").lower() in [i.replace("-", "").replace("_", "").lower() for i in installed]:
                                mod["installed"] = True
                            else:
                                mod["installed"] = False
            return jsonify(raw)
        except Exception as e:
            return jsonify({"error": f"Failed to load cache: {e}"}), 500
    
    return jsonify({"error": "No cached mod lists. Run curator first."}), 404


@app.route("/download/install-mods.bat")
def download_install_bat():
    """Download Batch install script for client mods."""
    try:
        from .mod_hosting import generate_bat_script
        cfg = load_cfg()
        script = generate_bat_script(cfg)
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=install-mods.bat"}
        )
    except Exception as e:
        return f"Error generating script: {e}", 500


@app.route("/download/install.sh")
def download_install_sh():
    """Native bootstrap (macOS/Linux) that ensures Java and runs the installer JAR."""
    try:
        from .mod_hosting import generate_java_bootstrap_sh
        cfg = load_cfg()
        return Response(
            generate_java_bootstrap_sh(cfg),
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": "attachment; filename=install.sh"},
        )
    except Exception as e:
        return f"Error generating script: {e}", 500


@app.route("/download/install.bat")
def download_install_bat_bootstrap():
    """Native bootstrap (Windows) that ensures Java and runs the installer JAR."""
    try:
        from .mod_hosting import generate_java_bootstrap_bat
        cfg = load_cfg()
        return Response(
            generate_java_bootstrap_bat(cfg),
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=install.bat"},
        )
    except Exception as e:
        return f"Error generating script: {e}", 500


@app.route("/download/curl")
def download_curl():
    """Download curl one-liner for quick install."""
    try:
        from .mod_hosting import get_server_ip
        ip = get_server_ip()
        cfg = load_cfg()
        port = cfg.http_port
        curl_cmd = f'curl.exe -sL "http://{ip}:{port}/download/install-mods.bat" -o "%TEMP%\\install-mods.bat" && "%TEMP%\\install-mods.bat" {ip} {port}'
        return Response(
            curl_cmd,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=curl-install.txt"}
        )
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/download/manifest")
def download_manifest():
    """Download mod manifest JSON."""
    try:

        from .mod_hosting import update_manifest
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        update_manifest(mods_dir)
        manifest_path = mods_dir / "manifest.json"
        if manifest_path.exists():
            return Response(
                manifest_path.read_text(),
                mimetype="application/json"
            )
        else:
            return "Manifest not found", 404
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/download/all")
@app.route("/download/mods_latest.zip")
def download_mods_zip():
    """Download full mods zip."""
    try:
        from .mod_hosting import create_mod_zip
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        zip_path = mods_dir / "mods_latest.zip"
        
        # Create zip if it doesn't exist
        if not zip_path.exists():
            create_mod_zip(mods_dir)
        
        if zip_path.exists():
            return Response(
                zip_path.read_bytes(),
                mimetype="application/zip",
                headers={"Content-Disposition": "attachment; filename=mods_latest.zip"}
            )
        else:
            return "Zip not found", 404
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/download/launcher.zip")
def download_launcher_zip():
    """Download the client launcher zip (mods + config + defaultconfigs)."""
    try:
        from .mod_hosting import build_launcher_zip_bytes
        cfg = load_cfg()
        buf = build_launcher_zip_bytes(cfg)
        if buf is None:
            return "Failed to build launcher zip", 500
        return Response(
            buf.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename=neorunner-launcher-{cfg.mc_version}.zip"}
        )
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/download/curseforge.zip")
def download_curseforge_zip():
    """Download CurseForge/Overwolf-importable modpack zip."""
    try:
        from .public_site import _build_curseforge_zip
        cfg = load_cfg()
        buf = _build_curseforge_zip()
        return Response(
            buf.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": f"attachment; filename=neorunner-curseforge-{cfg.mc_version}.zip"}
        )
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/download/installer.jar")
def download_installer_jar():
    """Download the self-contained Java client installer JAR."""
    try:
        from .installer_jar import build_installer_jar_bytes
        cfg = load_cfg()
        buf = build_installer_jar_bytes(cfg)
        return Response(
            buf.getvalue(),
            mimetype="application/java-archive",
            headers={
                "Content-Disposition": f"attachment; filename=neorunner-installer-{cfg.mc_version}.jar",
                "Cache-Control": "no-store, no-cache, must-revalidate",
            },
        )
    except Exception as e:
        return f"Error building installer jar: {e}", 500


@app.route("/download/loader-installer.jar")
def download_loader_installer():
    """Serve the mod loader's client installer jar."""
    try:
        cfg = load_cfg()
        from .mod_hosting import _loader_installer_path
        cand = _loader_installer_path(cfg)
        if cand is not None and cand.exists():
            return Response(
                cand.read_bytes(),
                mimetype="application/java-archive",
                headers={
                    "Content-Disposition": f"attachment; filename={cand.name}",
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                },
            )
        return "No loader installer jar available on server", 404
    except Exception as e:
        return f"Error: {e}", 500


@app.route("/api/worlds")
def api_worlds():
    """Return list of available worlds."""
    worlds = scan_worlds()
    props = parse_server_properties()
    current = props.get("level-name", "world")
    cfg = load_cfg()
    server_mc_version = getattr(cfg, 'mc_version', None)
    if not server_mc_version:
        server_mc_version = get_latest_minecraft_version()
    server_loader = getattr(cfg, 'loader', 'neoforge')
    return jsonify({"worlds": worlds, "current": current, "server_mc_version": server_mc_version, "server_loader": server_loader})


@app.route("/api/worlds/scan", methods=["POST"])
def api_worlds_scan():
    """Scan for world folders."""
    worlds = scan_worlds()
    props = parse_server_properties()
    current = props.get("level-name", "world")
    cfg = load_cfg()
    server_mc_version = getattr(cfg, 'mc_version', None)
    if not server_mc_version:
        server_mc_version = get_latest_minecraft_version()
    server_loader = getattr(cfg, 'loader', 'neoforge')
    return jsonify({"success": True, "worlds": worlds, "current": current, "server_mc_version": server_mc_version, "server_loader": server_loader})


@app.route("/api/worlds/switch", methods=["POST"])
def api_worlds_switch():
    """Switch to a different world."""
    try:
        data = request.json
        world_name = data.get("world", "")
        force = data.get("force", False)
        
        if not world_name:
            return jsonify({"success": False, "error": "No world name provided"}), 400
        
        success, message = switch_world(world_name, force)
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/backup", methods=["POST"])
def api_worlds_backup():
    """Backup a world."""
    try:
        data = request.json
        world_name = data.get("world", "")
        
        if not world_name:
            return jsonify({"success": False, "error": "No world name provided"}), 400
        
        world_path = CWD / world_name
        if not world_path.exists():
            return jsonify({"success": False, "error": "World not found"}), 404
        
        backup_dir = CWD / "backups"
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{world_name}_{timestamp}.tar.gz"
        backup_path = backup_dir / backup_name
        
        import subprocess
        result = subprocess.run(
            ["tar", "-czf", str(backup_path), "-C", str(CWD), world_name], check=False,
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            log_event("WORLD_BACKUP", f"Backed up {world_name} to {backup_name}")
            return jsonify({"success": True, "backup": backup_name})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/delete", methods=["POST"])
def api_worlds_delete():
    """Delete a world folder (moves to worlds_trash/, recoverable)."""
    try:
        data = request.json
        world_name = data.get("world", "")
        confirm = data.get("confirm", False)

        if not world_name:
            return jsonify({"success": False, "error": "No world name provided"}), 400
        if not confirm:
            return jsonify({"success": False, "error": "Confirmation required"}), 400

        props = parse_server_properties()
        current = props.get("level-name", "world")
        is_active = world_name == current
        if is_active and not data.get("force_active", False):
            return jsonify({"success": False, "error": f"Cannot delete the active world '{current}'. Use force_active to delete it and generate a fresh world."}), 400

        world_path = CWD / world_name
        if not world_path.exists():
            return jsonify({"success": False, "error": "World not found"}), 404

        import shutil
        import time

        # If deleting the active world, stop the server and reset level-name so
        # a fresh world generates on next start.
        server_stopped = False
        if is_active:
            try:
                from .server import is_server_running, stop_server
                if is_server_running():
                    server_stopped = stop_server()
                    time.sleep(2)
            except Exception:
                pass
            props["level-name"] = "world"
            write_server_properties(props)
            log_event("WORLD_DELETE", f"Active world '{world_name}' deleted; level-name reset to 'world' (fresh world will generate)")

        trash_dir = CWD / "worlds_trash"
        trash_dir.mkdir(exist_ok=True)
        dest = trash_dir / world_name
        if dest.exists():
            shutil.rmtree(str(dest))
        shutil.move(str(world_path), str(dest))
        msg = f"World '{world_name}' moved to worlds_trash/ (recoverable)"
        if server_stopped:
            msg += " | Server stopped - start it to generate a fresh world"
        log_event("WORLD_DELETE", f"Moved world '{world_name}' to worlds_trash/")
        return jsonify({"success": True, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/archives")
def api_worlds_archives():
    """List archived/trashed worlds (version-specific holding areas)."""
    try:
        from .world_upload import list_archived_worlds
        archived = list_archived_worlds()
        trash = CWD / "worlds_trash"
        if trash.is_dir():
            for world_dir in sorted(trash.iterdir()):
                if world_dir.is_dir():
                    archived.append({
                        "name": world_dir.name,
                        "location": "worlds_trash",
                        "mc_version": None,
                        "loader": None,
                        "kind": "folder",
                        "compressed": False,
                        "path": str(world_dir),
                    })
        return jsonify({"archived": sorted(archived, key=lambda a: a.get("mc_version") or "")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/restore", methods=["POST"])
def api_worlds_restore():
    """Restore an archived (folder or tar.gz) / trashed world to the main dir."""
    try:
        data = request.json
        world_name = data.get("world", "")
        location = data.get("location", "worlds_trash")
        if not world_name:
            return jsonify({"success": False, "error": "No world name provided"}), 400

        if location == "worlds_archive":
            from .world_upload import restore_archived_world
            ok, msg = restore_archived_world(world_name, cwd=CWD)
            if not ok:
                return jsonify({"success": False, "error": msg}), 404
            log_event("WORLD_RESTORE", f"Restored world '{world_name}' from archives")
            return jsonify({"success": True, "message": msg})

        import shutil
        src = CWD / location / world_name
        if not src.exists():
            return jsonify({"success": False, "error": "Trashed world not found"}), 404

        dest = CWD / world_name
        if dest.exists():
            return jsonify({"success": False, "error": f"World '{world_name}' already exists in main folder"}), 400
        shutil.move(str(src), str(dest))
        log_event("WORLD_RESTORE", f"Restored world '{world_name}' from {location}")
        return jsonify({"success": True, "message": f"World '{world_name}' restored to main folder"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/archive-load", methods=["POST"])
def api_worlds_archive_load():
    """Restore an archived (compressed) world and activate it as level-name."""
    try:
        data = request.json
        world_name = data.get("world", "")
        mc_version = data.get("mc_version")
        if not world_name:
            return jsonify({"success": False, "error": "No world name provided"}), 400

        from .world_upload import load_archived_world
        ok, msg = load_archived_world(world_name, mc_version=mc_version, cwd=CWD)
        if not ok:
            return jsonify({"success": False, "error": msg}), 400
        return jsonify({"success": True, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/conversion-formats")
def api_world_conversion_formats():
    """List Java output formats the installed Chunker CLI supports."""
    try:
        from .chunker import get_chunker_jar, java_formats
        jar = get_chunker_jar()
        if not jar.exists():
            return jsonify({"success": False, "error": "Chunker CLI not installed - run 'neorunner setup' to install it"}), 400
        formats = java_formats(jar)
        return jsonify({"success": True, "formats": formats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/upload/create", methods=["POST"])
def api_world_upload_create():
    """Create a staging slot for a world upload."""
    try:
        from .world_upload import create_staging
        result = create_staging()
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/upload/file", methods=["POST"])
def api_world_upload_file():
    """Upload a single file into a staging slot (path is relative to the world root)."""
    try:
        token = request.form.get("token", "")
        rel_path = request.form.get("path", "")
        if not token or not rel_path:
            return jsonify({"success": False, "error": "Missing token or path"}), 400
        upload = request.files.get("file")
        if upload is None:
            return jsonify({"success": False, "error": "No file part in request"}), 400

        from .world_upload import stage_file
        data = upload.read()
        result = stage_file(token, rel_path, data)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/upload/analyze", methods=["POST"])
def api_world_upload_analyze():
    """Validate and analyze a staged world upload before acceptance."""
    try:
        data = request.json
        token = data.get("token", "")
        if not token:
            return jsonify({"success": False, "error": "No upload token"}), 400

        cfg = load_cfg()
        from .world_upload import analyze_upload
        analysis = analyze_upload(token, server_mc_version=cfg.mc_version)
        analysis["success"] = analysis.get("valid", False)
        if not analysis.get("valid"):
            analysis["error"] = "; ".join(analysis.get("errors", [])) or "Not a valid Minecraft world"
        return jsonify(analysis)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/upload/confirm", methods=["POST"])
def api_world_upload_confirm():
    """Compress an accepted, analyzed upload into its versioned archive slot."""
    try:
        data = request.json
        token = data.get("token", "")
        name = data.get("name", "")
        loader = data.get("loader") or load_cfg().loader
        if not token or not name:
            return jsonify({"success": False, "error": "Missing token or world name"}), 400

        from .world_upload import accept_upload
        result = accept_upload(token, name, loader=loader)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/upload/cancel", methods=["POST"])
def api_world_upload_cancel():
    """Discard a pending world upload and clean its staging slot."""
    try:
        data = request.json
        token = data.get("token", "")
        if not token:
            return jsonify({"success": False, "error": "No upload token"}), 400
        from .world_upload import abort_upload
        abort_upload(token)
        return jsonify({"success": True, "message": "Upload discarded"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/upload/archive", methods=["POST"])
def api_world_upload_archive():
    """Upload a zipped/tar'ed world (.zip/.mcworld/.tar/.tar.gz), extract it
    into a staging slot and return the analysis in one step."""
    try:
        token = request.form.get("token", "")
        upload = request.files.get("file")
        if not token:
            return jsonify({"success": False, "error": "Missing upload token"}), 400
        if upload is None:
            return jsonify({"success": False, "error": "No file in request"}), 400
        if not upload.filename.lower().endswith((".zip", ".mcworld", ".tar", ".tar.gz")):
            return jsonify({"success": False, "error": "Only .zip/.mcworld/.tar/.tar.gz world archives allowed"}), 400

        filename = Path(upload.filename).name
        from .world_upload import extract_archive_upload, stage_file
        stage_file(token, f"_upload_{filename}", upload.read())
        try:
            extract_archive_upload(token)
        except ValueError:
            from .world_upload import abort_upload
            abort_upload(token)
            return jsonify({"success": False, "error": "Uploaded archive does not contain a Minecraft world"}), 400

        cfg = load_cfg()
        from .world_upload import analyze_upload
        analysis = analyze_upload(token, server_mc_version=cfg.mc_version)
        analysis["success"] = analysis.get("valid", False)
        return jsonify({"success": analysis.get("valid", False), "title": filename, **analysis})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/worlds/convert", methods=["POST"])
def api_world_convert():
    """Convert a staged world to a target Java version via Chunker.

    Converts Bedrock worlds to Java Edition (or up/down-grades a Java world),
    replacing the staged upload with the converted Java world so it can be
    re-analyzed and accepted.
    """
    try:
        data = request.json
        token = data.get("token", "")
        target_format = str(data.get("target_format", "")).upper()
        if not token:
            return jsonify({"success": False, "error": "No upload token"}), 400
        if not re.fullmatch(r"JAVA_\d[\d_]*", target_format):
            return jsonify({"success": False, "error": f"Invalid conversion format: {target_format}"}), 400

        from .chunker import convert_world
        from .world_upload import find_world_root, resolve_staging

        stage = resolve_staging(token)
        world_root = find_world_root(stage)
        if world_root is None:
            return jsonify({"success": False, "error": "Staged upload is not a Minecraft world"}), 400

        out = stage / "_converted"
        result = convert_world(world_root, target_format, out)
        if not result["success"]:
            return jsonify({"success": False, "error": result.get("error", "conversion failed")}), 500

        # Replace the staged world with the converted Java world.
        import shutil as _sh
        for item in list(stage.iterdir()):
            if item.name == "__meta__.json" or item.name == "_converted":
                continue
            if item.is_dir():
                _sh.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
        for item in out.iterdir():
            _sh.move(str(item), str(stage / item.name))

        # Refresh the size/file manifest for the converted world.
        from .world_upload import _walk_tree, _write_meta
        files = _walk_tree(stage)
        total = sum(f.stat().st_size for f in files if f.is_file()) if files else 0
        _write_meta(stage, {"files": len(files), "bytes": total})

        from .world_upload import analyze_upload
        cfg = load_cfg()
        analysis = analyze_upload(token, server_mc_version=cfg.mc_version)
        analysis["success"] = analysis.get("valid", False)
        return jsonify({"success": analysis.get("valid", False), "analysis": analysis})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/analyze")
def api_mods_analyze():
    """Analyze mods for mixin conflicts."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        
        from .mod_modder import ModModder
        modder = ModModder(str(mods_dir), cfg.mc_version)
        result = modder.analyze_and_resolve()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@app.route("/api/mods/optimize-load-order", methods=["POST"])
def api_mods_optimize_load_order():
    """Optimize mod load order."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        
        from .mod_modder import ModModder
        modder = ModModder(str(mods_dir), cfg.mc_version)
        result = modder.optimize_load_order()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@app.route("/api/mods/patch", methods=["POST"])
def api_mods_patch():
    """Auto-patch mods for compatibility."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        
        from .mod_patcher import ModPatcher
        patcher = ModPatcher(str(mods_dir), cfg.mc_version)
        result = patcher.auto_patch_all()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@app.route("/api/loaders")
def api_loaders():
    """Get available loaders and their status."""
    try:
        loaders = []
        
        for name in ["neoforge", "forge", "fabric"]:
            version = None
            
            if name == "neoforge":
                neoforge_dir = CWD / "libraries" / "net" / "neoforged" / "neoforge"
                if neoforge_dir.exists():
                    versions = [d for d in os.listdir(neoforge_dir) if (neoforge_dir / d).is_dir()]
                    if versions:
                        version = max(versions)
            
            elif name == "forge":
                forge_dir = CWD / "libraries" / "net" / "minecraftforge" / "forge"
                if forge_dir.exists():
                    versions = [d for d in os.listdir(forge_dir) if (forge_dir / d).is_dir()]
                    if versions:
                        version = max(versions)
            
            elif name == "fabric":
                fabric_jar = CWD / "fabric-server-launch.jar"
                if fabric_jar.exists():
                    version = "installed"
            
            loaders.append({
                "name": name,
                "installed": version is not None,
                "version": version
            })
        
        cfg = load_cfg()
        mc_ver = cfg.mc_version
        if not mc_ver:
            mc_ver = get_latest_minecraft_version()
        return jsonify({
            "loaders": loaders,
            "current": cfg.loader.lower(),
            "mc_version": mc_ver
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@app.route("/api/server-events")
def api_server_events():
    """Return server events (crash, heal, quarantine) for dashboard timeline."""
    try:
        from .server import get_events
        events = get_events()
        all_events = state.events + events
        return jsonify({"events": all_events})
    except Exception:
        return jsonify({"events": state.events})


@app.route("/api/server-events/clear", methods=["POST"])
def api_server_events_clear():
    """Clear the in-memory event store."""
    state.events.clear()
    return jsonify({"success": True})


@app.route("/api/broadcast", methods=["POST"])
def api_broadcast():
    """Send mod update notification to all online players via RCON tellraw."""
    try:
        from .server import is_server_running
        
        cfg = load_cfg()
        if not cfg.broadcast_enabled:
            return jsonify({"success": False, "error": "Broadcasts are disabled in config"}), 403
        
        mods_dir = CWD / cfg.mods_dir
        mod_count = len([f for f in os.listdir(mods_dir)]) if mods_dir.exists() else 0
        
        if is_server_running():
            result = subprocess.run(
                f"echo 'tellraw @a [{{\"text\":\"[NeoRunner] Server updated - {mod_count} mods installed\",\"color\":\"green\"}}]' | nc -w 1 localhost {cfg.rcon_port} 2>/dev/null", check=False,
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log_event("BROADCAST", f"Broadcast sent to all players ({mod_count} mods)")
                return jsonify({"success": True, "message": f"Broadcast sent to all players ({mod_count} mods)"})
            else:
                return jsonify({"success": False, "error": "RCON failed - is server running with RCON enabled?"}), 500
        else:
            return jsonify({"success": False, "error": "Server is not running"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/client-status", methods=["POST"])
def api_client_status():
    """Receive client mod status - used to determine if we need to create zip."""
    try:
        data = request.json
        client_id = data.get("client_id", "unknown")
        correct_mods = data.get("correct_mods", 0)
        total_mods = data.get("total_mods", 0)
        
        state.client_mod_status[client_id] = {
            "correct_mods": correct_mods,
            "total_mods": total_mods,
            "timestamp": time.time()
        }
        
        # If client reports 0 correct mods, we should create/update the zip
        if correct_mods == 0 and total_mods > 0:
            log_event("CLIENT_STATUS", f"Client {client_id} has 0 correct mods, zip update needed")
            # Trigger zip creation in background
            threading.Thread(target=_conditional_create_mod_zip, daemon=True).start()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


def _conditional_create_mod_zip():
    """Create mod zip only if needed (not recently created)."""
    cfg = load_cfg()
    
    # Check if we recently created a zip
    if state.last_zip_creation:
        time_since_last = time.time() - state.last_zip_creation
        if time_since_last < 300:  # Don't recreate within 5 minutes
            log_event("MOD_ZIP", f"Skipping zip creation - last created {time_since_last:.0f}s ago")
            return
    
    from .mod_hosting import create_mod_zip
    create_mod_zip(CWD / cfg.mods_dir)
    state.last_zip_creation = time.time()


@app.route("/api/quarantine")
def api_quarantine():
    """Get list of quarantined mods."""
    try:
        cfg = load_cfg()
        quarantine_dir = CWD / cfg.mods_dir / "quarantine"
        
        quarantined = []
        if quarantine_dir.exists():
            for filename in sorted(os.listdir(quarantine_dir)):
                if filename.endswith(".jar"):
                    path = quarantine_dir / filename
                    try:
                        size = path.stat().st_size
                        quarantined.append({
                            "id": filename,
                            "name": filename,
                            "size": f"{round(size / (1024*1024), 2)} MB",
                            "path": str(path)
                        })
                    except Exception:
                        pass
        
        return jsonify({"quarantined": quarantined})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/blacklist")
def api_blacklist():
    """Get blacklist and whitelist configuration."""
    try:
        blacklist_file = CWD / "config" / "mod_blacklist.json"
        whitelist_file = CWD / "config" / "mod_whitelist.json"
        
        blacklist = []
        patterns = []
        whitelist = []
        
        if blacklist_file.exists():
            try:
                with open(blacklist_file) as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        blacklist = data.get("mods", [])
                        patterns = data.get("patterns", [])
                    else:
                        blacklist = data
            except Exception:
                pass
        
        if whitelist_file.exists():
            try:
                with open(whitelist_file) as f:
                    whitelist = json.load(f)
            except Exception:
                pass
        
        return jsonify({
            "blacklist": blacklist,
            "patterns": patterns,
            "whitelist": whitelist
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/blacklist", methods=["POST"])
def api_update_blacklist():
    """Update blacklist/patterns/whitelist."""
    try:
        data = request.json
        config_dir = CWD / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        
        if "whitelist" in data:
            whitelist_file = config_dir / "mod_whitelist.json"
            with open(whitelist_file, "w") as f:
                json.dump(data["whitelist"], f, indent=2)
        
        blacklist_data = {
            "mods": data.get("mods", []),
            "patterns": data.get("patterns", []),
        }
        if "whitelist" not in data:
            blacklist_file = config_dir / "mod_blacklist.json"
            with open(blacklist_file, "w") as f:
                json.dump(data, f, indent=2)
        else:
            with open(config_dir / "mod_blacklist.json", "w") as f:
                json.dump(blacklist_data, f, indent=2)
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/rescan-mods", methods=["POST"])
def api_rescan_mods():
    """Rescan all mods for issues."""
    try:
        cfg = load_cfg()
        from .mods import sort_mods_by_type
        
        mods_dir = CWD / cfg.mods_dir
        result = sort_mods_by_type(mods_dir, cfg)
        
        # Check for corrupt mods
        corrupt = []
        import zipfile
        for jar in mods_dir.glob("*.jar"):
            try:
                with zipfile.ZipFile(jar) as zf:
                    zf.namelist()
            except Exception:
                corrupt.append(jar.name)
        
        return jsonify({
            "success": True,
            "server_mods": len(result.get("server", [])),
            "client_mods": len(result.get("clientonly", [])),
            "corrupt": corrupt
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/archives")
def api_loaders_archives():
    """List archived loader mods."""
    try:
        archive_dir = CWD / "loader_archive"
        archives = []
        
        if archive_dir.exists():
            for loader in os.listdir(archive_dir):
                loader_path = archive_dir / loader
                if loader_path.is_dir():
                    for version in os.listdir(loader_path):
                        version_path = loader_path / version
                        if version_path.is_dir():
                            for mc in os.listdir(version_path):
                                mc_path = version_path / mc
                                if mc_path.is_dir():
                                    mod_count = len([f for f in os.listdir(mc_path) if f.endswith(".jar")])
                                    archives.append({
                                        "loader": loader,
                                        "version": version,
                                        "mc_version": mc,
                                        "mod_count": mod_count
                                    })
        
        return jsonify({"archives": archives})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/snapshots")
def api_loaders_snapshots():
    """List loader snapshots."""
    try:
        snapshot_dir = CWD / "snapshots"
        snapshots = []
        
        if snapshot_dir.exists():
            for snapshot_file in snapshot_dir.glob("*.tar.gz"):
                try:
                    stat = snapshot_file.stat()
                    snapshots.append({
                        "name": snapshot_file.name,
                        "size": stat.st_size,
                        "size_mb": round(stat.st_size / (1024*1024), 2),
                        "created": stat.st_mtime
                    })
                except Exception:
                    pass
        
        return jsonify({"snapshots": snapshots})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/restore", methods=["POST"])
def api_loaders_restore():
    """Restore a pre-switch snapshot (config, mods, worlds)."""
    try:
        data = request.json
        snapshot_name = data.get("snapshot", "")
        if not snapshot_name or ".." in snapshot_name or "/" in snapshot_name:
            return jsonify({"success": False, "error": "Invalid snapshot name"}), 400
        
        import tarfile
        snapshot_path = CWD / "snapshots" / snapshot_name
        if not snapshot_path.exists():
            return jsonify({"success": False, "error": "Snapshot not found"}), 404
        
        # Extract over the current installation (config, server.properties, mods, worlds)
        with tarfile.open(str(snapshot_path), "r:gz") as tar:
            for member in tar.getmembers():
                # Prevent path traversal
                clean = member.name.lstrip("./")
                if ".." in clean:
                    continue
                member.name = clean
            tar.extractall(str(CWD), filter="data")
        
        log_event("LOADER_RESTORE", f"Restored snapshot {snapshot_name}")
        return jsonify({"success": True, "message": f"Snapshot '{snapshot_name}' restored. Restart required."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/restore-mods", methods=["POST"])
def api_loaders_restore_mods():
    """Restore archived loader mods back to the mods folder."""
    try:
        data = request.json
        loader = data.get("loader", "")
        version = data.get("version", "")
        mc_version = data.get("mc_version", "")
        
        if not loader or not version or not mc_version:
            return jsonify({"success": False, "error": "loader, version, mc_version required"}), 400
        
        import shutil
        src = CWD / "loader_archive" / loader / version / mc_version
        if not src.exists():
            return jsonify({"success": False, "error": "Archive not found"}), 404
        
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        mods_dir.mkdir(parents=True, exist_ok=True)
        
        restored = 0
        for f in src.glob("*.jar"):
            dest = mods_dir / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
                restored += 1
        
        co_src = src / "clientonly"
        if co_src.exists():
            co_dest = mods_dir / "clientonly"
            co_dest.mkdir(exist_ok=True)
            for f in co_src.glob("*.jar"):
                dest = co_dest / f.name
                if not dest.exists():
                    shutil.move(str(f), str(dest))
                    restored += 1
        
        log_event("LOADER_RESTORE", f"Restored {restored} mods from {loader}/{version}/{mc_version}")
        return jsonify({"success": True, "message": f"Restored {restored} mods to mods folder"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/install", methods=["POST"])
def api_loaders_install():
    """Install a new loader."""
    try:
        data = request.json
        loader = data.get("loader", "neoforge")
        mc_version = data.get("mc_version", None)
        if not mc_version:
            # Preserve existing config version
            cfg = load_cfg()
            mc_version = cfg.mc_version if cfg.mc_version else get_latest_minecraft_version()
        
        from .installer import install_loader
        cfg = load_cfg()
        cfg.loader = loader
        cfg.mc_version = mc_version
        
        if install_loader(cfg):
            return jsonify({"success": True, "message": f"Installed {loader}"})
        else:
            return jsonify({"success": False, "error": "Installation failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/switch", methods=["POST"])
def api_loaders_switch():
    """Switch to a different loader.

    Safety flow:
    1. Stop the server if running
    2. Snapshot current state (config + mods + worlds) into snapshots/
    3. Archive current loader's mods into loader_archive/<loader>/<ver>/<mc>/
    4. Archive worlds incompatible with the target MC version into worlds_archive/
    5. Clear mods folder for the new loader
    6. Update config and install the new loader
    """
    try:
        data = request.json
        loader = data.get("loader", "neoforge")
        mc_version = data.get("mc_version", None)
        keep_mods = data.get("keep_mods", False)
        
        if loader not in ("neoforge", "forge", "fabric"):
            return jsonify({"success": False, "error": f"Unknown loader: {loader}"}), 400
        
        if not mc_version:
            cfg = load_cfg()
            mc_version = cfg.mc_version if cfg.mc_version else get_latest_minecraft_version()
        
        import shutil
        import tarfile
        
        cfg = load_cfg()
        old_loader = cfg.loader
        old_mc = cfg.mc_version
        
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        
        # 1. Stop the server if running
        try:
            from .server import is_server_running, stop_server
            if is_server_running():
                stop_server()
                time.sleep(2)
        except Exception:
            pass
        
        # 2. Snapshot current state
        snapshot_dir = CWD / "snapshots"
        snapshot_dir.mkdir(exist_ok=True)
        snapshot_path = snapshot_dir / f"pre_{loader}_switch_{timestamp}.tar.gz"
        
        def _collect_snapshot_items():
            items = []
            if (CWD / "config.json").exists():
                items.append("config.json")
            if (CWD / "server.properties").exists():
                items.append("server.properties")
            mods_dir = CWD / cfg.mods_dir
            if mods_dir.exists():
                items.append(cfg.mods_dir)
            for world in scan_worlds():
                w = world.get("name")
                if w and (CWD / w).is_dir():
                    items.append(w)
            return items
        
        snapshot_ok = False
        try:
            with tarfile.open(str(snapshot_path), "w:gz") as tar:
                for item in _collect_snapshot_items():
                    tar.add(str(CWD / item), arcname=item)
            snapshot_ok = True
        except Exception as e:
            log_event("LOADER_SWITCH", f"Snapshot failed (continuing): {e}")
        
        # 3. Archive current loader's mods
        mods_dir = CWD / cfg.mods_dir
        archived_mods = 0
        if mods_dir.exists() and not keep_mods:
            archive_dir = CWD / "loader_archive" / old_loader / old_mc / mc_version
            archive_dir.mkdir(parents=True, exist_ok=True)
            try:
                for f in mods_dir.iterdir():
                    if f.is_file() and f.suffix == ".jar":
                        dest = archive_dir / f.name
                        if not dest.exists():
                            shutil.move(str(f), str(dest))
                            archived_mods += 1
                # also archive clientonly mods
                clientonly_dir = mods_dir / "clientonly"
                if clientonly_dir.exists():
                    co_archive = archive_dir / "clientonly"
                    co_archive.mkdir(exist_ok=True)
                    for f in clientonly_dir.iterdir():
                        if f.is_file() and f.suffix == ".jar":
                            dest = co_archive / f.name
                            if not dest.exists():
                                shutil.move(str(f), str(dest))
                                archived_mods += 1
            except Exception as e:
                log_event("LOADER_SWITCH", f"Mod archive error: {e}")
        
        # 4. Archive worlds incompatible with target MC version
        archived_worlds = 0
        if old_mc and old_mc != mc_version:
            try:
                from .nbt_parser import get_world_version
                archive_dir = CWD / "worlds_archive" / f"mc-{old_mc}"
                for world in scan_worlds():
                    w = world.get("name")
                    if not w:
                        continue
                    level_dat = CWD / w / "level.dat"
                    if not level_dat.exists():
                        continue
                    try:
                        info = get_world_version(str(level_dat))
                        world_ver = info.get("version")
                    except Exception:
                        world_ver = None
                    # only archive if we know the version differs (safe move)
                    if world_ver and world_ver != mc_version:
                        archive_dir.mkdir(parents=True, exist_ok=True)
                        dest = archive_dir / w
                        if not dest.exists():
                            shutil.move(str(CWD / w), str(dest))
                            archived_worlds += 1
            except Exception as e:
                log_event("LOADER_SWITCH", f"World archive error: {e}")
        
        # 5. Update config
        cfg.loader = loader
        cfg.mc_version = mc_version
        save_cfg(cfg)
        
        # 6. Install the new loader
        install_ok = True
        try:
            from .installer import install_loader
            install_ok = install_loader(cfg)
        except Exception as e:
            install_ok = False
            log_event("LOADER_SWITCH", f"Installer error: {e}")
        
        parts = [f"Switched to {loader} {mc_version}"]
        if snapshot_ok:
            parts.append(f"snapshot: {snapshot_path.name}")
        if archived_mods:
            parts.append(f"{archived_mods} mods archived")
        if archived_worlds:
            parts.append(f"{archived_worlds} incompatible worlds archived")
        if not install_ok:
            parts.append("(loader install deferred - run again or install manually)")
        
        return jsonify({
            "success": True,
            "message": " | ".join(parts),
            "snapshot": snapshot_path.name if snapshot_ok else None,
            "archived_mods": archived_mods,
            "archived_worlds": archived_worlds,
            "install_ok": install_ok,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


def _download_link(cfg: ServerConfig) -> str:
    """Public download URL shown to clients (installer JAR)."""
    from .mod_hosting import public_download_link
    return public_download_link(cfg)


@app.route("/api/broadcast-mods", methods=["POST"])
def api_broadcast_mods():
    """Broadcast mod update to players."""
    try:
        cfg = load_cfg()
        from .server import send_command
        
        link = _download_link(cfg)
        cmd = f"say Mod update available! Download from {link}/download/installer.jar"
        send_command(cmd)
        
        return jsonify({"success": True, "message": "Broadcast sent"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/quarantine-client-mods", methods=["POST"])
def api_quarantine_client_mods():
    """Quarantine specific client mods."""
    try:
        data = request.json
        mod_ids = data.get("mods", [])
        cfg = load_cfg()
        
        mods_dir = CWD / cfg.mods_dir
        clientonly_dir = mods_dir / "clientonly"
        quarantine_dir = mods_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        
        import shutil
        quarantined = 0
        for mod_id in mod_ids:
            for jar in clientonly_dir.glob(f"*{mod_id}*.jar"):
                dest = quarantine_dir / jar.name
                if not dest.exists():
                    shutil.move(str(jar), str(dest))
                    quarantined += 1
        
        return jsonify({"success": True, "quarantined": quarantined})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/restore-from-quarantine", methods=["POST"])
def api_restore_from_quarantine():
    """Restore all mods from quarantine."""
    try:
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        quarantine_dir = mods_dir / "quarantine"
        
        import shutil
        restored = 0
        
        if quarantine_dir.exists():
            for filename in os.listdir(quarantine_dir):
                if filename.endswith(".jar"):
                    src = quarantine_dir / filename
                    # Try to determine if it's a client mod
                    if "client" in filename.lower():
                        dest = mods_dir / "clientonly" / filename
                    else:
                        dest = mods_dir / filename
                    
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.move(str(src), str(dest))
                        restored += 1
        
        return jsonify({"success": True, "restored": restored})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/quarantine-mod", methods=["POST"])
def api_quarantine_mod():
    """Quarantine a specific mod."""
    try:
        data = request.json
        mod_name = data.get("mod", "")
        cfg = load_cfg()
        
        mods_dir = CWD / cfg.mods_dir
        mod_path = mods_dir / mod_name
        
        # Security check
        if not str(mod_path.resolve()).startswith(str(mods_dir.resolve())):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        quarantine_dir = mods_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        
        if mod_path.exists():
            import shutil
            dest = quarantine_dir / mod_name
            shutil.move(str(mod_path), str(dest))
            return jsonify({"success": True, "message": f"Quarantined {mod_name}"})
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/quarantine-mods", methods=["POST"])
def api_quarantine_mods():
    """Quarantine multiple mods at once."""
    try:
        data = request.json
        mod_ids = data.get("mod_ids", [])
        folder = data.get("folder", "clientonly")
        
        if not mod_ids:
            return jsonify({"success": False, "error": "No mods specified"}), 400
        
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir / folder
        quarantine_dir = mods_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        
        quarantined = []
        errors = []
        
        import shutil
        for mod_id in mod_ids:
            mod_path = mods_dir / mod_id
            if mod_path.exists():
                dest = quarantine_dir / mod_id
                shutil.move(str(mod_path), str(dest))
                quarantined.append(mod_id)
            else:
                errors.append(mod_id)
        
        return jsonify({
            "success": True,
            "message": f"Quarantined {len(quarantined)} mods",
            "quarantined": quarantined,
            "errors": errors
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/delete-mods", methods=["POST"])
def api_delete_mods():
    """Delete multiple mods at once."""
    try:
        data = request.json
        mod_ids = data.get("mod_ids", [])
        folder = data.get("folder", "clientonly")
        
        if not mod_ids:
            return jsonify({"success": False, "error": "No mods specified"}), 400
        
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir / folder
        
        deleted = []
        errors = []
        
        for mod_id in mod_ids:
            mod_path = mods_dir / mod_id
            if mod_path.exists():
                mod_path.unlink()
                deleted.append(mod_id)
            else:
                errors.append(mod_id)
        
        return jsonify({
            "success": True,
            "message": f"Deleted {len(deleted)} mods",
            "deleted": deleted,
            "errors": errors
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/search")
def api_mods_search():
    """Search for mods on Modrinth and CurseForge."""
    try:
        cfg = load_cfg()
        query = request.args.get("q", "")
        limit = request.args.get("limit", 50, type=int)
        sources = request.args.get("sources", "modrinth,curseforge").split(",")
        
        from .mod_browser import ModBrowser
        browser = ModBrowser(mc_version=cfg.mc_version, loader=cfg.loader)
        results = browser.search(query, limit, sources)
        
        return jsonify({
            "success": True,
            "mods": [asdict(r) for r in results],
            "query": query,
            "count": len(results)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/details/<mod_id>")
def api_mods_details(mod_id):
    """Get detailed information about a mod."""
    try:
        cfg = load_cfg()
        source = request.args.get("source", "modrinth")
        
        from .mod_browser import ModBrowser
        browser = ModBrowser(mc_version=cfg.mc_version, loader=cfg.loader)
        details = browser.get_mod_details(mod_id, source)
        
        if details:
            return jsonify({"success": True, "mod": details})
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/versions/<mod_id>")
def api_mods_versions(mod_id):
    """Get available versions for a mod."""
    try:
        cfg = load_cfg()
        source = request.args.get("source", "modrinth")
        
        from .mod_browser import ModBrowser
        browser = ModBrowser(mc_version=cfg.mc_version, loader=cfg.loader)
        versions = browser.get_mod_versions(mod_id, source)
        
        return jsonify({"success": True, "versions": versions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/install", methods=["POST"])
def api_mods_install():
    """Install one or more mods (by id/slug/name)."""
    try:
        data = request.json
        mods = data.get("mods", [])
        
        if not mods:
            return jsonify({"success": False, "error": "No mods specified"}), 400
        
        cfg = load_cfg()
        from .mod_manager import ModManager
        cfg_dict = {'loader': cfg.loader, 'mc_version': cfg.mc_version, 'mods_dir': cfg.mods_dir}
        mm = ModManager(cfg_dict, cwd=str(CWD))
        
        keywords = []
        for m in mods:
            mid = (m.get("mod_id") or m.get("id") or m.get("slug") or m.get("name") or "").strip()
            if mid and mid not in keywords:
                keywords.append(mid)
        
        if not keywords:
            return jsonify({"success": False, "error": "No valid mod identifiers supplied"}), 400
        
        result = mm.install_by_keywords(keywords, resolve_deps=True)
        
        return jsonify({
            "success": True,
            "installed": result.get("installed", []),
            "failed": result.get("failed", []),
            "status": result.get("status", "error")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/mods/install-by-keywords", methods=["POST"])
def api_mods_install_by_keywords():
    """Install mods by keywords."""
    try:
        data = request.json
        keywords = data.get("keywords", [])
        resolve_deps = data.get("resolve_deps", True)
        
        if not keywords:
            return jsonify({"success": False, "error": "No keywords specified"}), 400
        
        cfg = load_cfg()
        from .mod_manager import ModManager
        cfg_dict = {'loader': cfg.loader, 'mc_version': cfg.mc_version, 'mods_dir': cfg.mods_dir}
        mm = ModManager(cfg_dict, cwd=str(CWD))
        
        result = mm.install_by_keywords(keywords, resolve_deps=resolve_deps)
        
        return jsonify({
            "success": True,
            "keywords": keywords,
            "installed": result.get("installed", []),
            "failed": result.get("failed", []),
            "status": result.get("status", "error")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/quarantine/<mod_id>", methods=["DELETE"])
def api_delete_quarantined_mod(mod_id):
    """Delete a quarantined mod permanently."""
    try:
        cfg = load_cfg()
        quarantine_dir = CWD / cfg.mods_dir / "quarantine"
        mod_path = quarantine_dir / mod_id
        
        # Security check
        if not str(mod_path.resolve()).startswith(str(quarantine_dir.resolve())):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        if mod_path.exists():
            mod_path.unlink()
            log_event("QUARANTINE_DELETE", f"Deleted quarantined mod: {mod_id}")
            return jsonify({"success": True, "message": f"Deleted {mod_id}"})
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/quarantine/<mod_id>/restore", methods=["POST"])
def api_restore_quarantined_mod(mod_id):
    """Restore a specific quarantined mod."""
    try:
        cfg = load_cfg()
        quarantine_dir = CWD / cfg.mods_dir / "quarantine"
        mods_dir = CWD / cfg.mods_dir
        
        mod_path = quarantine_dir / mod_id
        
        # Security check
        if not str(mod_path.resolve()).startswith(str(quarantine_dir.resolve())):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        if not mod_path.exists():
            return jsonify({"success": False, "error": "Mod not found"}), 404
        
        # Determine destination
        if "client" in mod_id.lower():
            dest = mods_dir / "clientonly" / mod_id
        else:
            dest = mods_dir / mod_id
        
        import shutil
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mod_path), str(dest))
        
        log_event("QUARANTINE_RESTORE", f"Restored mod: {mod_id}")
        return jsonify({"success": True, "message": f"Restored {mod_id}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/modpack/analyze", methods=["POST"])
def api_modpack_analyze():
    """Analyze a modpack for conversion."""
    try:
        data = request.json
        filenames = data.get("filenames", [])
        source_loader = data.get("source_loader", "fabric")
        source_mc_version = data.get("source_mc_version", "1.21.4")
        
        if not filenames:
            return jsonify({"success": False, "error": "No filenames provided"}), 400
        
        from .modpack_converter import ModpackConverter
        converter = ModpackConverter()
        result = converter.analyze_modpack(filenames, source_loader, source_mc_version)
        
        return jsonify({"success": True, "analysis": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/modpack/convert", methods=["POST"])
def api_modpack_convert():
    """Convert a modpack by installing alternative versions."""
    try:
        data = request.json
        filenames = data.get("filenames", [])
        selected_alternatives = data.get("alternatives", {})
        source_loader = data.get("source_loader", "fabric")
        source_mc_version = data.get("source_mc_version", "1.21.4")
        
        if not filenames:
            return jsonify({"success": False, "error": "No filenames provided"}), 400
        
        from .modpack_converter import ModpackConverter
        converter = ModpackConverter()
        results = converter.convert_modpack(filenames, selected_alternatives, source_loader, source_mc_version)
        
        successful = sum(1 for success, _ in results if success)
        failed = len(results) - successful
        
        return jsonify({
            "success": True,
            "converted": successful,
            "failed": failed,
            "results": [{"success": s, "message": m, "file": filename} for s, m, filename in zip([r[0] for r in results], [r[1] for r in results], filenames)]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/modpack/install-converted", methods=["POST"])
def api_modpack_install():
    """Install converted modpack mods into the server mods folder."""
    try:
        data = request.json
        mod_ids = data.get("mod_ids", [])
        
        if not mod_ids:
            return jsonify({"success": False, "error": "No mods selected"}), 400
        
        cfg = load_cfg()
        from .mod_manager import ModManager
        from .modpack_converter import ModpackConverter
        cfg_dict = {'loader': cfg.loader, 'mc_version': cfg.mc_version, 'mods_dir': cfg.mods_dir}
        mm = ModManager(cfg_dict, cwd=str(CWD))
        converter = ModpackConverter()
        
        slugs = []
        for mid in mod_ids:
            info = converter.parse_mod_filename(mid)
            slug = (info.get("mod_id") or mid).strip().lower()
            if slug and slug not in slugs:
                slugs.append(slug)
        
        if not slugs:
            return jsonify({"success": False, "error": "Could not determine mod identifiers"}), 400
        
        result = mm.install_by_keywords(slugs, resolve_deps=True)
        
        installed = result.get("installed", [])
        failed = result.get("failed", [])
        
        if installed and not failed:
            log_event("MODPACK_CONVERT", f"Installed {len(installed)} mods from converted modpack")
        
        return jsonify({
            "success": True,
            "installed": installed,
            "failed": failed,
            "message": f"Installed {len(installed)} mods" + (f", {len(failed)} failed" if failed else "")
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/java")
def api_java_info():
    """Get Java installation information."""
    try:
        from .java_manager import get_java_info
        info = get_java_info()
        return jsonify({"success": True, "java": info})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/java/check-mods")
def api_java_check_mods():
    """Check Java compatibility with installed mods."""
    try:
        cfg = load_cfg()
        from .java_manager import JavaManager
        manager = JavaManager()
        
        mods_dir = CWD / cfg.mods_dir
        result = manager.check_java_compatibility(mods_dir)
        
        return jsonify({"success": True, "compatibility": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/java/set", methods=["POST"])
def api_java_set():
    """Set the active Java installation."""
    try:
        data = request.json
        java_path = data.get("path", "")
        
        if not java_path:
            return jsonify({"success": False, "error": "No Java path provided"}), 400
        
        from .java_manager import JavaManager
        manager = JavaManager()
        
        if manager.set_java_home(java_path):
            return jsonify({"success": True, "message": f"Set JAVA_HOME to {java_path}"})
        else:
            return jsonify({"success": False, "error": "Failed to set Java"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/java/install", methods=["POST"])
def api_java_install():
    """Install Java."""
    try:
        data = request.json
        version = data.get("version", 21)
        vendor = data.get("vendor", "openjdk")
        
        from .java_manager import JavaManager
        manager = JavaManager()
        
        success, message = manager.install_java(version, vendor)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/java/install-command")
def api_java_install_command():
    """Get the Java installation command for the current system."""
    try:
        from .java_manager import JavaManager
        manager = JavaManager()
        
        command = manager.get_install_command(manager.MIN_VERSION)
        
        return jsonify({"success": True, "command": command, "min_version": manager.MIN_VERSION})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/health")
def api_health():
    """Health check endpoint."""
    import shutil
    
    # Check Java
    java_ok = False
    try:
        result = subprocess.run(["java", "-version"], check=False, capture_output=True)
        java_ok = result.returncode == 0
    except Exception:
        pass
    
    # Check Python version
    python_ok = sys.version_info >= (3, 9)
    
    return jsonify({
        "status": "healthy",
        "java": java_ok,
        "python": python_ok,
        "tmux": shutil.which("tmux") is not None,
        "curl": shutil.which("curl") is not None,
        "first_start": not (CWD / "server.properties").exists()
    })


@app.route("/api/setup/install-prereqs", methods=["POST"])
def api_setup_install_prereqs():
    """Install prerequisites during setup."""
    try:
        import shutil
        
        from .version import get_java_version_for_mc, get_latest_minecraft_version
        cfg = load_cfg()
        mc_ver = getattr(cfg, "mc_version", None) or get_latest_minecraft_version()
        java_req = int(get_java_version_for_mc(mc_ver))
        
        commands = []
        
        # Detect package manager
        if shutil.which("apt-get"):
            commands.append("sudo apt-get update && sudo apt-get install -y tmux curl rsync unzip zip")
            commands.append(f"sudo apt-get install -y openjdk-{java_req}-jre-headless || sudo apt-get install -y default-jre")
        elif shutil.which("dnf"):
            commands.append(f"sudo dnf install -y tmux curl rsync unzip zip java-{java_req}-openjdk-headless")
        elif shutil.which("yum"):
            # Check for Amazon Linux
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    if "amzn" in f.read():
                        commands.append(f"sudo amazon-linux-extras install java-openjdk{java_req} -y || sudo yum install -y java-{java_req}-openjdk")
                    else:
                        commands.append(f"sudo yum install -y tmux curl rsync unzip zip java-{java_req}-openjdk")
            else:
                commands.append(f"sudo yum install -y tmux curl rsync unzip zip java-{java_req}-openjdk")
        elif shutil.which("pacman"):
            commands.append(f"sudo pacman -Sy --noconfirm tmux curl rsync unzip zip jre{java_req}-openjdk-headless")
        
        # Execute commands
        for cmd in commands:
            subprocess.run(cmd, shell=True, check=True)
        
        return jsonify({"success": True, "message": "Prerequisites installed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/setup/install", methods=["POST"])
def api_setup_install():
    """Install server from setup wizard."""
    try:
        data = request.json
        
        # Create config
        cfg = ServerConfig()
        mc_version = data.get("mc_version", None)
        if not mc_version:
            mc_version = get_latest_minecraft_version()
        cfg.mc_version = mc_version
        cfg.loader = data.get("loader", "neoforge")
        cfg.mc_port = data.get("mc_port", 25565)
        cfg.http_port = data.get("http_port", 8000)
        cfg.rcon_port = str(data.get("rcon_port", 25575))
        cfg.rcon_pass = data.get("rcon_pass", "changeme123")
        cfg.hostname = "localhost"
        
        # Save config
        save_cfg(cfg)
        
        # Create EULA
        if data.get("eula", False):
            eula_path = CWD / "eula.txt"
            eula_path.write_text("eula=true\n")
        
        # Create directories
        from .installer import ensure_directories
        ensure_directories(cfg)
        
        # Install loader
        from .installer import install_loader
        success = install_loader(cfg)
        
        if success:
            return jsonify({"success": True, "message": "Server installed successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to install mod loader"}), 500
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/analyze-crash-log", methods=["POST"])
def api_analyze_crash_log():
    """Analyze a crash log file to identify issues and auto-fetch missing mods."""
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            # Also accept raw text in JSON
            if request.is_json:
                log_text = request.json.get('log_text', '') or request.json.get('crash_log', '')
            else:
                return jsonify({"success": False, "error": "No file uploaded"}), 400
        else:
            file = request.files['file']
            if file.filename == '':
                return jsonify({"success": False, "error": "No file selected"}), 400
            
            # Read file content
            log_text = file.read().decode('utf-8', errors='ignore')
        
        if not log_text:
            return jsonify({"success": False, "error": "Empty log file"}), 400
        
        # Analyze the crash log
        from .crash_analyzer import CrashAnalyzer
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log_text)
        
        # Convert results to dict
        analysis_results = []
        for r in results:
            analysis_results.append({
                "error_type": r.error_type,
                "culprit": r.culprit,
                "message": r.message,
                "severity": r.severity,
                "recommendations": r.recommendations,
                "mod_to_fetch": r.mod_to_fetch,
                "fetch_to_folder": r.fetch_to_folder
            })
        
        # Auto-fetch missing mods if requested
        auto_fetch = request.form.get('auto_fetch', 'false').lower() == 'true'
        fetch_results = {}
        if auto_fetch and results:
            fetch_results = analyzer.auto_fetch_missing(results)
        
        return jsonify({
            "success": True,
            "analysis": analysis_results,
            "summary": {
                "total_issues": len(analysis_results),
                "critical": sum(1 for r in analysis_results if r["severity"] == "critical"),
                "high": sum(1 for r in analysis_results if r["severity"] == "high"),
                "medium": sum(1 for r in analysis_results if r["severity"] == "medium"),
            },
            "auto_fetch": fetch_results
        })
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/preflight/run", methods=["POST"])
def api_run_preflight():
    """Manually trigger preflight dependency check."""
    try:
        import threading

        from .self_heal import preflight_dep_check
        
        cfg = load_cfg()
        
        def run_preflight():
            try:
                # Convert config to dict if needed
                cfg_dict = dict(cfg) if hasattr(cfg, '__iter__') else cfg
                result = preflight_dep_check(cfg_dict)
                log_event("PREFLIGHT", f"Preflight completed: fetched {result.get('fetched', 0)} deps")
            except Exception as e:
                log_event("PREFLIGHT_ERROR", str(e))
        
        thread = threading.Thread(target=run_preflight, daemon=True)
        thread.start()
        
        return jsonify({"success": True, "message": "Preflight started in background"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/config/reset-memory", methods=["POST"])
def api_reset_memory():
    """Reset corrupted xmx/xms values in config.json."""
    try:
        from .config import load_cfg, save_cfg
        
        cfg = load_cfg()
        
        # Reset memory values to clean defaults
        cfg.xmx = "4G"
        cfg.xms = "2G"
        
        save_cfg(cfg)
        
        return jsonify({"success": True, "xmx": cfg.xmx, "xms": cfg.xms})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


def run_dashboard(host: str = "0.0.0.0", port: int = 8000, debug: bool = False):
    """Run the dashboard with Waitress production server."""
    import socket

    from waitress import serve
    
    # Ensure port is integer
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 8000
    
    def is_port_free(p: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, p))
                return True
        except OSError:
            return False
    
    # Try ports incrementally if in use
    original_port = port
    for try_port in range(port, port + 10):
        if is_port_free(try_port):
            port = try_port
            break
    else:
        log_event("ERROR", f"No free ports available in range {port}-{port+9}")
        return
    
    if port != original_port:
        log_event("DASHBOARD", f"Port {original_port} in use, using {port} instead")
    
    global DASHBOARD_PORT
    DASHBOARD_PORT = port
    
    log_event("DASHBOARD", f"Starting dashboard on {host}:{port} with Waitress")
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    run_dashboard()
