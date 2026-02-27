#!/usr/bin/env python3
"""
NeoRunner Hosting Dashboard
- Server status and control
- Player list from RCON
- Mod management and installation
- Configuration UI for RCON, ferium, update frequency
- Real-time updates via WebSocket
"""

import os
import json
import logging
from flask import Flask, render_template, jsonify, request, session
from datetime import datetime
from pathlib import Path
import subprocess
import threading
import time

def _get_cwd():
    """Determine the working directory dynamically."""
    env_cwd = os.environ.get("NEORUNNER_HOME")
    if env_cwd:
        return env_cwd
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()

CWD = _get_cwd()
CONFIG = os.path.join(CWD, "config.json")
LOG_FILE = os.path.join(CWD, "live.log")
FERIUM_BIN = os.path.join(CWD, ".local/bin/ferium")

app = Flask(__name__, template_folder=CWD, static_folder=os.path.join(CWD, "static"))
app.secret_key = os.urandom(24)

log = logging.getLogger(__name__)

def load_config():
    """Load config.json"""
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    """Save config.json"""
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)

def run_command(cmd):
    """Run shell command"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def parse_props():
    """Parse server.properties file"""
    path = os.path.join(CWD, "server.properties")
    props = {}
    if os.path.exists(path):
        for line in open(path):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                props[k] = v
    return props

def scan_worlds():
    """Scan for world folders (folders containing level.dat)"""
    worlds = []
    for entry in os.listdir(CWD):
        entry_path = os.path.join(CWD, entry)
        if os.path.isdir(entry_path):
            level_dat = os.path.join(entry_path, "level.dat")
            if os.path.exists(level_dat):
                try:
                    stat = os.stat(entry_path)
                    worlds.append({
                        "name": entry,
                        "path": entry_path,
                        "size": sum(
                            os.path.getsize(os.path.join(dirpath, f))
                            for dirpath, dirnames, filenames in os.walk(entry_path)
                            for f in filenames
                        ),
                        "modified": stat.st_mtime
                    })
                except:
                    worlds.append({"name": entry, "path": entry_path})
    return sorted(worlds, key=lambda w: w.get("name", ""))

def switch_world(world_name):
    """Switch to a different world by updating server.properties"""
    props_path = os.path.join(CWD, "server.properties")
    if not os.path.exists(props_path):
        return False, "server.properties not found"
    
    world_path = os.path.join(CWD, world_name)
    level_dat = os.path.join(world_path, "level.dat")
    if not os.path.exists(level_dat):
        return False, f"World '{world_name}' not found (no level.dat)"
    
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
    
    return True, f"World switched to '{world_name}'. Restart server to apply."

def get_server_status():
    """Get server status (running, player count, etc)"""
    # Check if tmux session exists on the shared socket
    uid = os.getuid()
    tmux_socket = f"/tmp/tmux-{uid}/default"
    result = run_command(f"tmux -S {tmux_socket} list-sessions 2>/dev/null | grep -c MC")
    running = result["stdout"].strip() == "1"
    
    # Also check for java process as backup
    if not running:
        java_check = run_command("pgrep -f 'java.*neoforge.*nogui' || pgrep -f 'java.*forge.*nogui' || pgrep -f 'java.*fabric.*nogui'")
        running = java_check["stdout"].strip() != ""
    
    cfg = load_config()
    
    # Try to get player list from RCON
    players = []
    if running and cfg.get("rcon_pass"):
        try:
            # Use mcrcon or similar to query RCON
            rcon_result = run_command(
                f"echo 'list' | nc -w 1 localhost {cfg.get('rcon_port', 25575)} 2>/dev/null"
            )
            if rcon_result["success"]:
                players_text = rcon_result["stdout"]
                # Parse player list - format varies by server, this is approximate
                if "player" in players_text.lower():
                    players = players_text.split("\n")
        except:
            pass
    
    # Get mod count
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    mod_count = len([f for f in os.listdir(mods_dir) if f.endswith(".jar")]) if os.path.exists(mods_dir) else 0
    
    return {
        "running": running,
        "loader": cfg.get("loader", "unknown"),
        "mc_version": cfg.get("mc_version", "unknown"),
        "mod_count": mod_count,
        "player_count": len([p for p in players if p.strip()]) if players else 0,
        "rcon_enabled": cfg.get("rcon_pass") is not None,
        "uptime": get_uptime() if running else 0
    }

def get_uptime():
    """Get server uptime in seconds"""
    try:
        result = run_command("ps aux | grep '[m]inecraft.*nogui' | awk '{print $2}'")
        if result["success"] and result["stdout"].strip():
            pid = result["stdout"].strip()
            result = run_command(f"ps -o etime= -p {pid}")
            if result["success"]:
                return result["stdout"].strip()
    except:
        pass
    return "unknown"

def get_recent_logs(lines=50):
    """Get last N lines from live.log"""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                return f.readlines()[-lines:]
        except:
            pass
    return []

def get_mod_list():
    """Get list of installed mods"""
    cfg = load_config()
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    
    mods = []
    if os.path.exists(mods_dir):
        for filename in sorted(os.listdir(mods_dir)):
            if filename.endswith(".jar"):
                path = os.path.join(mods_dir, filename)
                size = os.path.getsize(path)
                mods.append({
                    "name": filename,
                    "size": size,
                    "size_mb": round(size / (1024*1024), 2),
                    "path": filename
                })
    
    return sorted(mods, key=lambda x: x["name"])

@app.route("/")
def dashboard():
    """Main dashboard page"""
    return render_template("dashboard.html")

@app.route("/api/status")
def api_status():
    """Get server status"""
    return jsonify(get_server_status())

@app.route("/api/config")
def api_config():
    """Get current config"""
    cfg = load_config()
    # Don't expose passwords in API
    cfg["rcon_pass"] = "***"
    return jsonify(cfg)

@app.route("/api/config", methods=["POST"])
def api_config_update():
    """Update configuration"""
    try:
        data = request.json
        cfg = load_config()
        
        # Update allowed fields
        allowed_fields = [
            "ferium_update_interval_hours",
            "ferium_weekly_update_day",
            "ferium_weekly_update_hour",
            "rcon_port",
            "http_port",
            "mc_version"
        ]
        
        for field in allowed_fields:
            if field in data:
                cfg[field] = data[field]
        
        save_config(cfg)
        log.info(f"[DASHBOARD] Config updated: {list(data.keys())}")
        
        return jsonify({"success": True, "message": "Config updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/mods")
def api_mods():
    """Get mod list"""
    return jsonify(get_mod_list())

@app.route("/api/server-mods")
def api_server_mods():
    """Get list of server-side mods"""
    cfg = load_config()
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    mods = []
    
    if os.path.exists(mods_dir):
        for filename in sorted(os.listdir(mods_dir)):
            if filename.endswith(".jar"):
                path = os.path.join(mods_dir, filename)
                size = os.path.getsize(path)
                mods.append({
                    "id": filename,
                    "name": filename,
                    "size": f"{round(size / (1024*1024), 2)} MB",
                    "type": "server"
                })
    
    return jsonify({"mods": mods})

@app.route("/api/client-mods")
def api_client_mods():
    """Get list of client-side mods from clientonly folder"""
    cfg = load_config()
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    clientonly_dir = os.path.join(mods_dir, "clientonly")
    mods = []
    
    if os.path.exists(clientonly_dir):
        for filename in sorted(os.listdir(clientonly_dir)):
            if filename.endswith(".jar"):
                path = os.path.join(clientonly_dir, filename)
                size = os.path.getsize(path)
                mods.append({
                    "id": filename,
                    "name": filename,
                    "size": f"{round(size / (1024*1024), 2)} MB",
                    "type": "client"
                })
    
    return jsonify({"mods": mods})

@app.route("/api/quarantine-all-client-mods", methods=["POST"])
def api_quarantine_all_client_mods():
    """Quarantine ALL client-side mods"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        clientonly_dir = os.path.join(mods_dir, "clientonly")
        quarantine_dir = os.path.join(mods_dir, "quarantine")
        
        os.makedirs(quarantine_dir, exist_ok=True)
        
        quarantined = 0
        if os.path.exists(clientonly_dir):
            import shutil
            for filename in list(os.listdir(clientonly_dir)):
                if filename.endswith(".jar"):
                    src = os.path.join(clientonly_dir, filename)
                    dst = os.path.join(quarantine_dir, filename)
                    
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                        quarantined += 1
        
        log.info(f"[DASHBOARD] Quarantined {quarantined} client mods")
        return jsonify({"success": True, "quarantined": quarantined})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/sort-client-mods", methods=["POST"])
def api_sort_client_mods():
    """Sort mods into clientonly folder (placeholder - requires classify_mod from run.py)"""
    return jsonify({"success": True, "moved": 0, "message": "Use run.py for full mod sorting"})

@app.route("/api/mods/<mod_name>", methods=["DELETE"])
def api_remove_mod(mod_name):
    """Remove a mod"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        mod_path = os.path.join(mods_dir, mod_name)
        
        # Security: prevent path traversal
        if not os.path.abspath(mod_path).startswith(os.path.abspath(mods_dir)):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        if os.path.exists(mod_path) and mod_path.endswith(".jar"):
            os.remove(mod_path)
            log.info(f"[DASHBOARD] Removed mod: {mod_name}")
            return jsonify({"success": True, "message": f"Removed {mod_name}"})
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/server/start", methods=["POST"])
def api_server_start():
    """Start server"""
    try:
        result = run_command(f"cd {CWD} && python3 run.py run &")
        return jsonify({"success": True, "message": "Server starting..."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    """Stop server via RCON"""
    try:
        cfg = load_config()
        if cfg.get("rcon_pass"):
            # Send stop command via RCON
            run_command(f"echo 'stop' | nc localhost {cfg.get('rcon_port', 25575)} 2>/dev/null")
            return jsonify({"success": True, "message": "Stop command sent"})
        else:
            return jsonify({"success": False, "error": "RCON not configured"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/mods/upgrade", methods=["POST"])
def api_upgrade_mods():
    """Upgrade all mods via ferium"""
    try:
        result = run_command(f"{FERIUM_BIN} upgrade")
        if result["success"]:
            log.info("[DASHBOARD] Mods upgraded via ferium")
            return jsonify({"success": True, "message": "Mods upgraded"})
        else:
            return jsonify({"success": False, "error": result["stderr"]}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/logs")
def api_logs():
    """Get recent log lines"""
    lines_param = request.args.get("lines", 50, type=int)
    logs = get_recent_logs(min(lines_param, 500))  # Max 500 lines
    return jsonify({"logs": logs})

@app.route("/api/download/<mod_name>")
def api_download_mod(mod_name):
    """Download a mod"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        mod_path = os.path.join(mods_dir, mod_name)
        
        # Security: prevent path traversal
        if not os.path.abspath(mod_path).startswith(os.path.abspath(mods_dir)):
            return jsonify({"success": False, "error": "Invalid path"}), 400
        
        if os.path.exists(mod_path) and mod_path.endswith(".jar"):
            from flask import send_file
            return send_file(mod_path, as_attachment=True)
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/worlds")
def api_worlds():
    """Return list of available worlds"""
    worlds = scan_worlds()
    props = parse_props()
    current = props.get("level-name", "world")
    return jsonify({"worlds": worlds, "current": current})

@app.route("/api/worlds/scan", methods=["POST"])
def api_worlds_scan():
    """Scan for world folders"""
    worlds = scan_worlds()
    props = parse_props()
    current = props.get("level-name", "world")
    return jsonify({"success": True, "worlds": worlds, "current": current})

@app.route("/api/worlds/switch", methods=["POST"])
def api_worlds_switch():
    """Switch to a different world"""
    try:
        data = request.json
        world_name = data.get("world", "")
        if not world_name:
            return jsonify({"success": False, "error": "No world name provided"}), 400
        success, message = switch_world(world_name)
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/mods/analyze")
def api_mods_analyze():
    """Analyze mods for mixin conflicts"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        mc_version = cfg.get("mc_version", "1.21.11")
        
        from mod_modder import ModModder
        modder = ModModder(mods_dir, mc_version)
        result = modder.analyze_and_resolve()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route("/api/mods/optimize-load-order", methods=["POST"])
def api_mods_optimize_load_order():
    """Optimize mod load order"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        mc_version = cfg.get("mc_version", "1.21.11")
        
        from mod_modder import ModModder
        modder = ModModder(mods_dir, mc_version)
        result = modder.optimize_load_order()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route("/api/mods/patch", methods=["POST"])
def api_mods_patch():
    """Auto-patch mods for compatibility"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        mc_version = cfg.get("mc_version", "1.21.11")
        
        from mod_patcher import ModPatcher
        patcher = ModPatcher(mods_dir, mc_version)
        result = patcher.auto_patch_all()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route("/api/mods/compatibility-analysis")
def api_mods_compatibility_analysis():
    """Get compatibility analysis"""
    try:
        cfg = load_config()
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        mc_version = cfg.get("mc_version", "1.21.11")
        
        from mod_patcher import ModCompatibilityManager
        manager = ModCompatibilityManager(mods_dir, mc_version)
        result = manager.analyze_mod_pack()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

def get_loader_version(loader_name):
    """Get the installed version of a loader"""
    loader_name = loader_name.lower()
    
    if loader_name == "neoforge":
        neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
        if os.path.exists(neoforge_dir):
            versions = [d for d in os.listdir(neoforge_dir) if os.path.isdir(os.path.join(neoforge_dir, d))]
            if versions:
                return sorted(versions)[-1]
    
    elif loader_name == "forge":
        forge_dir = os.path.join(CWD, "libraries", "net", "minecraftforge", "forge")
        if os.path.exists(forge_dir):
            versions = [d for d in os.listdir(forge_dir) if os.path.isdir(os.path.join(forge_dir, d))]
            if versions:
                return sorted(versions)[-1]
    
    elif loader_name == "fabric":
        fabric_jar = os.path.join(CWD, "fabric-server-launch.jar")
        if os.path.exists(fabric_jar):
            return "installed"
    
    return None

def get_available_loaders():
    """Get list of available loaders with their status"""
    loaders = []
    
    for name in ["neoforge", "forge", "fabric"]:
        version = get_loader_version(name)
        loaders.append({
            "name": name,
            "installed": version is not None,
            "version": version
        })
    
    return loaders

@app.route("/api/loaders")
def api_loaders():
    """Get available loaders and their status"""
    try:
        loaders = get_available_loaders()
        cfg = load_config()
        current = cfg.get("loader", "neoforge").lower()
        mc_version = cfg.get("mc_version", "1.21.11")
        return jsonify({
            "loaders": loaders,
            "current": current,
            "mc_version": mc_version
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route("/api/loaders/archives")
def api_loaders_archives():
    """List archived loader mods"""
    try:
        archive_dir = os.path.join(CWD, "loader_archive")
        archives = []
        
        if os.path.isdir(archive_dir):
            for loader in os.listdir(archive_dir):
                loader_path = os.path.join(archive_dir, loader)
                if os.path.isdir(loader_path):
                    for version in os.listdir(loader_path):
                        version_path = os.path.join(loader_path, version)
                        if os.path.isdir(version_path):
                            for mc in os.listdir(version_path):
                                mc_path = os.path.join(version_path, mc)
                                if os.path.isdir(mc_path):
                                    mod_count = len([f for f in os.listdir(mc_path) if f.endswith('.jar')])
                                    archives.append({
                                        "loader": loader,
                                        "version": version,
                                        "mc_version": mc,
                                        "mod_count": mod_count
                                    })
        
        return jsonify({"archives": archives})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # NOTE: dashboard.py is a standalone fallback. The primary dashboard is
    # served by run.py's embedded Flask app on the configured http_port.
    # Only use this file if you need to run the dashboard independently.
    try:
        with open(os.path.join(CWD, "config.json")) as _f:
            _port = int(json.load(_f).get("http_port", 8000))
    except Exception:
        _port = 8000
    app.run(host="0.0.0.0", port=_port, debug=False)
