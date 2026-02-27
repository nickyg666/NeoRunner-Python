"""Utility functions for server status and configuration."""

import json
import os
import subprocess
from typing import Dict, Any, Optional

from flask import current_app


def get_config() -> Dict[str, Any]:
    """Get configuration from config.json."""
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_server_status() -> str:
    """Check if Minecraft server is running."""
    try:
        # Check for running Java processes
        result = subprocess.run(["pgrep", "-f", "java.*server.jar"], 
                               capture_output=True, text=True)
        if result.returncode == 0:
            return "running"
        else:
            # Check for process in config
            config = get_config()
            if config.get('server_status') == 'crashed':
                return "crashed"
            return "stopped"
    except Exception:
        return "unknown"


def get_server_ports() -> Dict[str, Optional[int]]:
    """Get configured ports from server.properties."""
    ports = {
        "minecraft": None,
        "loader": None,
        "rcon": None,
        "dashboard": None
    }
    
    try:
        with open('server.properties', 'r') as f:
            for line in f:
                if line.startswith('server-port'):
                    ports['minecraft'] = int(line.split('=')[1].strip())
                elif line.startswith('rcon.port'):
                    ports['rcon'] = int(line.split('=')[1].strip())
    except FileNotFoundError:
        pass
    
    # Get dashboard port from config
    config = get_config()
    ports['dashboard'] = config.get('dashboard_port', 8000)
    
    # Get loader port from loader config
    loader_info = get_loader_info()
    ports['loader'] = loader_info.get('port') if loader_info else None
    
    return ports


def get_loader_info() -> Optional[Dict[str, Any]]:
    """Get information about the current loader."""
    try:
        config = get_config()
        loader = config.get('loader', 'unknown')
        minecraft_version = config.get('minecraft_version', 'unknown')
        
        if loader == 'neoforge':
            return {
                "name": "NeoForge",
                "version": config.get('neoforge_version', 'unknown'),
                "port": 8000,
                "type": "mod_loader"
            }
        elif loader == 'forge':
            return {
                "name": "Forge",
                "version": config.get('forge_version', 'unknown'),
                "port": 8000,
                "type": "mod_loader"
            }
        elif loader == 'fabric':
            return {
                "name": "Fabric",
                "version": config.get('fabric_version', 'unknown'),
                "port": 8000,
                "type": "mod_loader"
            }
        else:
            return None
    except Exception:
        return None