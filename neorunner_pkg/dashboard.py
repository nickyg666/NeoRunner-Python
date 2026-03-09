"""
Web dashboard for NeoRunner using Flask.
Provides server management, mod management, world management, and configuration UI.
"""

from __future__ import annotations

import os
import json
import logging
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from functools import wraps

from flask import Flask, render_template, jsonify, request, send_file, Response

from .config import ServerConfig, load_cfg, save_cfg
from .constants import CWD
from .log import log_event

# Setup logging
log = logging.getLogger(__name__)

# Create Flask app
template_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"
app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))
app.secret_key = os.urandom(24)


class DashboardState:
    """Shared state for dashboard."""
    def __init__(self):
        self.server_process: Optional[Any] = None
        self.last_zip_creation: Optional[float] = None
        self.client_mod_status: Dict[str, Any] = {}
        self.download_threads: List[threading.Thread] = []
        self.events: List[Dict[str, Any]] = []
        self.max_events = 200
        
    def add_event(self, event_type: str, message: str):
        """Add an event to the event log."""
        self.events.append({
            "type": event_type,
            "message": message,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        # Trim to max
        while len(self.events) > self.max_events:
            self.events.pop(0)


# Global state
state = DashboardState()


def get_config_path() -> Path:
    """Get the config file path."""
    return CWD / "config.json"


def parse_server_properties() -> Dict[str, str]:
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


def scan_worlds() -> List[Dict[str, Any]]:
    """Scan for world folders (folders containing level.dat)."""
    cfg = load_cfg()
    server_mc_version = cfg.mc_version
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
                        except:
                            version_info = {}
                            world_version = None
                            compatible = True
                        
                        # Calculate size
                        size = 0
                        for dirpath, _, filenames in os.walk(entry_path):
                            for f in filenames:
                                try:
                                    size += os.path.getsize(os.path.join(dirpath, f))
                                except:
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
                    except Exception as e:
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
        try:
            from .nbt_parser import get_world_version
            version_info = get_world_version(str(level_dat))
            world_version = version_info.get("version")
            if world_version and world_version != server_mc_version:
                return False, f"Version mismatch: world is MC {world_version}, server is MC {server_mc_version}"
        except:
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


def get_server_status() -> Dict[str, Any]:
    """Get server status (running, player count, etc)."""
    import subprocess
    
    running = False
    status_detail = "Stopped"
    
    # Check if tmux session exists
    uid = os.getuid()
    tmux_socket = f"/tmp/tmux-{uid}/default"
    result = subprocess.run(
        f"tmux -S {tmux_socket} list-sessions 2>/dev/null | grep -c MC",
        shell=True, capture_output=True, text=True
    )
    running = result.stdout.strip() == "1"
    
    # Also check for java process as backup
    if not running:
        ps_result = subprocess.run(
            ["ps", "aux"],
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
        except:
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
            except:
                world_version = "unknown"
    except:
        pass
    
    # Try to get player list from RCON
    players = []
    if running and cfg.rcon_pass:
        try:
            rcon_result = subprocess.run(
                f"echo 'list' | nc -w 1 localhost {cfg.rcon_port} 2>/dev/null",
                shell=True, capture_output=True, text=True
            )
            if rcon_result.returncode == 0:
                players_text = rcon_result.stdout
                if "player" in players_text.lower():
                    players = players_text.split("\n")
        except:
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
    
    return {
        "running": running,
        "status_detail": status_detail,
        "loader": cfg.loader,
        "mc_version": cfg.mc_version,
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
            "ps aux | grep '[m]inecraft.*nogui' | awk '{print $2}'",
            shell=True, capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip()
            result = subprocess.run(
                f"ps -o etime= -p {pid}",
                shell=True, capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
    except:
        pass
    return "unknown"


def get_mod_list() -> List[Dict[str, Any]]:
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
                except:
                    pass
    
    return sorted(mods, key=lambda x: x["name"])


def get_client_mods() -> List[Dict[str, Any]]:
    """Get list of client-side mods from clientonly folder."""
    cfg = load_cfg()
    mods_dir = CWD / cfg.mods_dir
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
                except:
                    pass
    
    return mods


# ═══════════════════════════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    """Main dashboard page."""
    # Check if first start (no server.properties)
    if app.config.get('FIRST_START', False) or not (CWD / "server.properties").exists():
        return render_template("setup_wizard.html")
    return render_template("dashboard.html")


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
    
    # Get server IP for display
    import socket
    try:
        server_ip = socket.gethostbyname(socket.gethostname())
    except:
        server_ip = "0.0.0.0"
    config_dict["server_ip"] = server_ip
    
    return jsonify(config_dict)


@app.route("/api/config", methods=["POST"])
def api_config_update():
    """Update configuration."""
    try:
        data = request.json
        cfg = load_cfg()
        
        # Update allowed fields
        allowed_fields = [
            "ferium_update_interval_hours",
            "ferium_weekly_update_day",
            "ferium_weekly_update_hour",
            "rcon_port",
            "http_port",
            "mc_version",
            "loader",
            "mods_dir",
            "broadcast_enabled",
        ]
        
        for field in allowed_fields:
            if field in data:
                setattr(cfg, field, data[field])
        
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


@app.route("/api/server/start", methods=["POST"])
def api_server_start():
    """Start server."""
    try:
        from .server import run_server, is_server_running
        
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
        from .server import stop_server, is_server_running
        
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
        from .server import restart_server, is_server_running
        
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
        from .server import is_server_running, get_server, get_events
        
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
        from .server import send_command, is_server_running
        
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


@app.route("/api/mods/upgrade", methods=["POST"])
def api_upgrade_mods():
    """Upgrade all mods via ferium."""
    try:
        cfg = load_cfg()
        ferium_bin = CWD / ".local" / "bin" / "ferium"
        
        import subprocess
        result = subprocess.run(
            [str(ferium_bin), "upgrade"],
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
        except:
            pass
    
    return jsonify({"logs": logs})


@app.route("/api/logs/stream")
def logs_stream():
    """Raw log stream for real-time monitoring.
    
    Returns a continuous stream of new log lines as they are written.
    Useful for external systems to react to server events.
    """
    import time
    
    log_file = CWD / "live.log"
    
    def generate():
        if not log_file.exists():
            return
        
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)
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
    from .mods import curate_mod_list, parse_mod_manifest
    
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


@app.route("/api/install-mods", methods=["POST"])
def api_install_mods():
    """Install selected mods from curated list."""
    try:
        data = request.json
        selected = data.get("selected", [])
        if not selected:
            return jsonify({"success": False, "error": "No mods selected"}), 400
        
        cfg = load_cfg()
        mods_dir = CWD / cfg.mods_dir
        mods_dir.mkdir(exist_ok=True)
        
        from .mod_browser import ModInstaller
        installer = ModInstaller(cfg)
        
        installed = []
        failed = []
        
        for mod in selected:
            mod_id = mod.get("id") or mod.get("project_id")
            source = mod.get("source", "modrinth")
            
            success, msg = installer.install_mod(mod_id, source)
            if success:
                installed.append(mod.get("name", mod_id))
            else:
                failed.append(mod.get("name", mod_id))
        
        log_event("MOD_INSTALL", f"Installed {len(installed)} mods, {len(failed)} failed")
        
        if installed:
            from .mod_hosting import conditional_create_mod_zip
            threading.Thread(target=conditional_create_mod_zip, args=(mods_dir,), daemon=True).start()
        
        return jsonify({
            "success": len(failed) == 0,
            "installed": installed,
            "failed": failed
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


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


@app.route("/download/install")
def download_install():
    """Download PowerShell install script (for curl | iex)."""
    try:
        from .mod_hosting import generate_powershell_script
        cfg = load_cfg()
        script = generate_powershell_script(cfg)
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=install-mods.ps1"}
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
        from pathlib import Path
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


@app.route("/api/worlds")
def api_worlds():
    """Return list of available worlds."""
    worlds = scan_worlds()
    props = parse_server_properties()
    current = props.get("level-name", "world")
    cfg = load_cfg()
    server_mc_version = getattr(cfg, 'mc_version', '1.21.11')
    server_loader = getattr(cfg, 'loader', 'neoforge')
    return jsonify({"worlds": worlds, "current": current, "server_mc_version": server_mc_version, "server_loader": server_loader})


@app.route("/api/worlds/scan", methods=["POST"])
def api_worlds_scan():
    """Scan for world folders."""
    worlds = scan_worlds()
    props = parse_server_properties()
    current = props.get("level-name", "world")
    cfg = load_cfg()
    server_mc_version = getattr(cfg, 'mc_version', '1.21.11')
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
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{world_name}_{timestamp}.tar.gz"
        backup_path = backup_dir / backup_name
        
        import subprocess
        result = subprocess.run(
            ["tar", "-czf", str(backup_path), "-C", str(CWD), world_name],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            log_event("WORLD_BACKUP", f"Backed up {world_name} to {backup_name}")
            return jsonify({"success": True, "backup": backup_name})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500
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
                        version = sorted(versions)[-1]
            
            elif name == "forge":
                forge_dir = CWD / "libraries" / "net" / "minecraftforge" / "forge"
                if forge_dir.exists():
                    versions = [d for d in os.listdir(forge_dir) if (forge_dir / d).is_dir()]
                    if versions:
                        version = sorted(versions)[-1]
            
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
        return jsonify({
            "loaders": loaders,
            "current": cfg.loader.lower(),
            "mc_version": cfg.mc_version
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400


@app.route("/api/events")
def api_events():
    """Get recent events."""
    return jsonify({"events": state.events})


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
                f"echo 'tellraw @a [{{\"text\":\"[NeoRunner] Server updated - {mod_count} mods installed\",\"color\":\"green\"}}]' | nc -w 1 localhost {cfg.rcon_port} 2>/dev/null",
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
                    except:
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
            except:
                pass
        
        if whitelist_file.exists():
            try:
                with open(whitelist_file) as f:
                    whitelist = json.load(f)
            except:
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
    """Update blacklist."""
    try:
        data = request.json
        blacklist_file = CWD / "config" / "mod_blacklist.json"
        blacklist_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(blacklist_file, "w") as f:
            json.dump(data, f, indent=2)
        
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
            except:
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
                except:
                    pass
        
        return jsonify({"snapshots": snapshots})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/loaders/install", methods=["POST"])
def api_loaders_install():
    """Install a new loader."""
    try:
        data = request.json
        loader = data.get("loader", "neoforge")
        mc_version = data.get("mc_version", "1.21.11")
        
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
    """Switch to a different loader."""
    try:
        data = request.json
        loader = data.get("loader", "neoforge")
        mc_version = data.get("mc_version", "1.21.11")
        
        cfg = load_cfg()
        cfg.loader = loader
        cfg.mc_version = mc_version
        save_cfg(cfg)
        
        return jsonify({"success": True, "message": f"Switched to {loader} {mc_version}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/broadcast-mods", methods=["POST"])
def api_broadcast_mods():
    """Broadcast mod update to players."""
    try:
        cfg = load_cfg()
        from .server import send_command
        
        cmd = "say Mod update available! Download from the server dashboard."
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
    """Install one or more mods."""
    try:
        data = request.json
        mods = data.get("mods", [])
        
        if not mods:
            return jsonify({"success": False, "error": "No mods specified"}), 400
        
        from .mod_browser import ModInstaller
        installer = ModInstaller()
        results = installer.install_multiple(mods)
        
        successful = sum(1 for success, _ in results if success)
        failed = len(results) - successful
        
        return jsonify({
            "success": True,
            "installed": successful,
            "failed": failed,
            "results": [{"success": s, "message": m} for s, m in results]
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
            "results": [{"success": s, "message": m} for s, m in results]
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
        
        command = manager.get_install_command()
        
        return jsonify({"success": True, "command": command})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/health")
def api_health():
    """Health check endpoint."""
    import shutil
    import sys
    
    # Check Java
    java_ok = False
    try:
        result = subprocess.run(["java", "-version"], capture_output=True)
        java_ok = result.returncode == 0
    except:
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
        
        commands = []
        
        # Detect package manager
        if shutil.which("apt-get"):
            commands.append("sudo apt-get update && sudo apt-get install -y tmux curl rsync unzip zip")
            commands.append("sudo apt-get install -y openjdk-21-jre-headless || sudo apt-get install -y default-jre")
        elif shutil.which("dnf"):
            commands.append("sudo dnf install -y tmux curl rsync unzip zip java-21-openjdk-headless")
        elif shutil.which("yum"):
            # Check for Amazon Linux
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    if "amzn" in f.read():
                        commands.append("sudo amazon-linux-extras install java-openjdk21 -y || sudo yum install -y java-21-amazon-corretto")
                    else:
                        commands.append("sudo yum install -y tmux curl rsync unzip zip java-21-openjdk")
            else:
                commands.append("sudo yum install -y tmux curl rsync unzip zip java-21-openjdk")
        elif shutil.which("pacman"):
            commands.append("sudo pacman -Sy --noconfirm tmux curl rsync unzip zip jre21-openjdk-headless")
        
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
        cfg.mc_version = data.get("mc_version", "1.21.11")
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


def run_dashboard(host: str = "0.0.0.0", port: int = 8000, debug: bool = False):
    """Run the dashboard with Waitress production server."""
    from waitress import serve
    log_event("DASHBOARD", f"Starting dashboard on {host}:{port} with Waitress")
    serve(app, host=host, port=port, threads=4)


if __name__ == "__main__":
    run_dashboard()
