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
