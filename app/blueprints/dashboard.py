"""
Dashboard blueprint for NeoRunner's web interface

This module contains all dashboard routes and API endpoints for the
NeoRunner web interface, organized as a Flask Blueprint.
"""

import os
import json
import subprocess
from datetime import datetime
from flask import (
    Blueprint, render_template, jsonify, request, 
    send_file, Response, session, url_for
)
from pathlib import Path
from urllib.parse import urljoin

# Import core functionality
from app.services.config_service import load_cfg, save_cfg
from app.services.server_service import get_server_status, parse_props
from app.services.java_service import _get_java_version, _check_jdk_upgrade_available
from app.services.mod_service import get_mods, delete_mod, quarantine_mod, get_quarantine_list
from app.services.download_service import get_download_link, download_manifest
from app.services.api_service import run_cmd

# Create blueprint
dashboard_bp = Blueprint('dashboard', __name__, 
                         template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
                         static_folder=os.path.join(os.path.dirname(__file__), 'static'))


@dashboard_bp.route("/")
def dashboard():
    """Main dashboard route."""
    
    # Get server status and configuration
    status = get_server_status()
    config = load_cfg()
    props = parse_props()
    
    # Get current Java version
    java_version = _get_java_version()
    
    # Prepare data for template
    context = {
        'status': status,
        'config': config,
        'server_props': {
            'server_port': props.get('server-port', config.get('server_port', '25565')),
            'query_port': props.get('query.port', '25565'),
            'rcon_port': props.get('rcon.port', '25575')
        },
        'java_version': java_version,
        'java_upgrade_available': _check_jdk_upgrade_available(),
        'current_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'powershell_url': 'https://raw.githubusercontent.com/NeoRunner/NeoRunner/main/install.ps1',
        'powershell_one_liner': 'powershell -Command "iwr -useb https://raw.githubusercontent.com/NeoRunner/NeoRunner/main/install.ps1 | iex"',
        'motd_show_download_url': config.get('motd_show_download_url', False)
    }
    
    return render_template('dashboard.html', **context)


@dashboard_bp.route("/api/status")
def api_status():
    """API endpoint for server status."""
    return jsonify(get_server_status())


@dashboard_bp.route("/api/config")
def api_config():
    """API endpoint for configuration."""
    c = load_cfg()
    c['rcon_pass'] = '***'
    props = parse_props()
    c['server_port'] = props.get('server-port', c.get('server_port', '25565'))
    c['query_port'] = props.get('query.port', '25565')
    c['rcon_port'] = props.get('rcon.port', '25575')
    return jsonify(c)


@dashboard_bp.route("/api/config", methods=["POST"])
def api_config_update():
    """API endpoint for updating configuration."""
    try:
        data = request.json
        c = load_cfg()
        
        allowed = [
            "ferium_update_interval_hours", "ferium_weekly_update_day",
            "ferium_weekly_update_hour", "mc_version",
            "hostname", "curator_sort", "curator_limit",
            "broadcast_enabled", "broadcast_auto_on_install",
            "nag_show_mod_list_on_join", "nag_first_visit_modal",
            "motd_show_download_url", "install_script_types",
        ]
        
        for field in allowed:
            if field in data:
                c[field] = data[field]
        
        save_cfg(c)
        return jsonify({"success": True, "message": "Config updated"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@dashboard_bp.route("/api/java")
def api_java_status():
    """API endpoint for Java status."""
    current = _get_java_version()
    available = _check_jdk_upgrade_available()
    
    # Find mods quarantined for Java version mismatch
    c = load_cfg()
    mods_dir = os.path.join(os.getcwd(), c.get("mods_dir", "mods"))
    quarantine_dir = os.path.join(mods_dir, "quarantine")
    
    return jsonify({
        "current_version": current,
        "upgrade_available": available,
        "quarantined_mods": []  # Placeholder, implement actual logic
    })


@dashboard_bp.route("/api/mods")
def api_mods():
    """API endpoint for mods list."""
    return jsonify(get_mods())


@dashboard_bp.route("/api/mods/<mod_name>", methods=["DELETE"])
def api_delete_mod(mod_name):
    """API endpoint for deleting a mod."""
    try:
        delete_mod(mod_name)
        return jsonify({"success": True, "message": f"Mod {mod_name} deleted"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@dashboard_bp.route("/api/mods/<mod_name>/quarantine", methods=["POST"])
def api_quarantine_mod(mod_name):
    """API endpoint for quarantining a mod."""
    try:
        quarantine_mod(mod_name)
        return jsonify({"success": True, "message": f"Mod {mod_name} quarantined"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@dashboard_bp.route("/api/download/<mod_name>")
def api_download_mod(mod_name):
    """API endpoint for downloading a mod."""
    try:
        download_link = get_download_link(mod_name)
        if download_link:
            return jsonify({"success": True, "download_link": download_link})
        else:
            return jsonify({"success": False, "error": "Mod not found"}), 404
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/download/<filename>")
def download_file(filename):
    """Download static files."""
    return send_file(os.path.join(os.getcwd(), filename))


@dashboard_bp.route("/download/manifest")
def download_manifest():
    """Download mod manifest."""
    return download_manifest()


@dashboard_bp.route("/api/server/start", methods=["POST"])
def api_server_start():
    """API endpoint for starting server."""
    try:
        result = run_cmd("start-server.sh")
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    """API endpoint for stopping server."""
    try:
        result = run_cmd("stop-server.sh")
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/server/restart", methods=["POST"])
def api_server_restart():
    """API endpoint for restarting server."""
    try:
        result = run_cmd("restart-server.sh")
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dashboard_bp.route("/api/logs")
def api_logs():
    """API endpoint for server logs."""
    try:
        log_path = os.path.join(os.getcwd(), "logs", "server.log")
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                logs = f.read()
            return jsonify({"success": True, "logs": logs})
        else:
            return jsonify({"success": False, "error": "Log file not found"}), 404
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500