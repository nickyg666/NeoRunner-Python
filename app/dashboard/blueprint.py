"""Update dashboard template to use new modular structure."""

from flask import Blueprint, render_template, jsonify, request, send_file
import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..utils.server_status import get_server_status, get_server_ports, get_loader_info
from ..utils.config import get_config, get_mod_info
from ..utils.mod_quarantine import quarantine_client_mods, get_quarantined_mods
from ..utils.mixin_analyzer import analyze_mixin_errors, fix_mixin_compatibility
from ..utils.live_log import get_live_log_tail
from ..utils.modpack_converter import convert_modpack
from ..utils.client_mod_notifier import analyze_client_only_mods, move_client_only_mods_to_folder, get_client_mod_notifications

# Create blueprint
bp = Blueprint('dashboard', __name__, template_folder='../templates', static_folder='../static')

@bp.route('/')
def dashboard():
    """Main dashboard view."""
    try:
        # Get server status and info
        status = get_server_status()
        ports = get_server_ports()
        loader_info = get_loader_info()
        config = get_config()
        
        # Get mod information
        mod_info = get_mod_info()
        
        # Get live log tail
        live_log = get_live_log_tail(50)
        
        # Get mixin errors if available
        mixin_errors = analyze_mixin_errors()
        
        # Get client mod notifications
        client_notifications = get_client_mod_notifications()
        
        # Get quarantined mods
        quarantined_mods = get_quarantined_mods()
        
        return render_template('dashboard.html',
                             status=status,
                             ports=ports,
                             loader_info=loader_info,
                             config=config,
                             mod_info=mod_info,
                             live_log=live_log,
                             mixin_errors=mixin_errors,
                             client_notifications=client_notifications,
                             quarantined_mods=quarantined_mods)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/status')
def api_status():
    """API endpoint for server status."""
    try:
        status = get_server_status()
        ports = get_server_ports()
        loader_info = get_loader_info()
        return jsonify({"status": status, "ports": ports, "loader_info": loader_info})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/mods')
def api_mods():
    """API endpoint for mod information."""
    try:
        mod_info = get_mod_info()
        return jsonify(mod_info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/live-log')
def api_live_log():
    """API endpoint for live log tail."""
    try:
        lines = int(request.args.get('lines', 50))
        live_log = get_live_log_tail(lines)
        return jsonify({"log": live_log})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/quarantine')
def api_quarantine():
    """API endpoint to quarantine client mods."""
    try:
        result = quarantine_client_mods()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/mixin-fix')
def api_mixin_fix():
    """API endpoint to fix mixin compatibility."""
    try:
        result = fix_mixin_compatibility()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/convert-modpack', methods=['POST'])
def api_convert_modpack():
    """API endpoint to convert modpack."""
    try:
        data = request.get_json()
        modpack_path = data.get('modpack_path')
        target_version = data.get('target_version')
        target_loader = data.get('target_loader')
        
        if not modpack_path or not target_version or not target_loader:
            return jsonify({"error": "Missing required parameters"}), 400
        
        result = convert_modpack(modpack_path, target_version, target_loader)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/settings')
def api_settings():
    """API endpoint for settings."""
    try:
        config = get_config()
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/logs')
def api_logs():
    """API endpoint for server logs."""
    try:
        log_files = [f for f in os.listdir('logs') if f.endswith('.log')]
        return jsonify({"logs": log_files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/events')
def api_events():
    """API endpoint for server events."""
    try:
        # This would integrate with your event system
        return jsonify({"events": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/quick-actions', methods=['POST'])
def quick_actions():
    """Handle quick actions like start/stop server."""
    try:
        action = request.form.get('action')
        
        if action == 'start':
            # Start server logic
            return jsonify({"message": "Server starting..."})
        elif action == 'stop':
            # Stop server logic
            return jsonify({"message": "Server stopping..."})
        elif action == 'restart':
            # Restart service logic
            return jsonify({"message": "Service restarting..."})
        else:
            return jsonify({"error": "Unknown action"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/download/ps1-script')
def download_ps1_script():
    """Download PowerShell script for mod syncing."""
    try:
        config = get_config()
        ps1_content = f"""# NeoRunner Mod Sync Script
# Minecraft Instance: {config.get('minecraft_instance', 'default')}
# Loader: {config.get('loader', 'unknown')}
# Version: {config.get('minecraft_version', 'unknown')}

$ModsUrl = "http://localhost:8000/api/mods"
$OutputDir = "$env:APPDATA\.minecraft\mods"

Invoke-RestMethod -Uri $ModsUrl -OutFile mods.json
$mods = Get-Content mods.json | ConvertFrom-Json

foreach ($mod in $mods) {{
    $modName = $mod.name
    $modUrl = $mod.download_url
    $modPath = Join-Path $OutputDir "$modName.jar"
    
    if (-Not (Test-Path $modPath)) {{
        Write-Host "Downloading $modName..."
        Invoke-WebRequest -Uri $modUrl -OutFile $modPath
    }}
}}

Write-Host "Mod sync complete!"
"""
        
        return send_file(
            io.BytesIO(ps1_content.encode()),
            mimetype='application/octet-stream',
            as_attachment=True,
            attachment_filename='neorunner_sync.ps1'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500