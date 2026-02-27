"""Utility functions for configuration and settings."""

import json
import os
from typing import Dict, Any, Optional


def get_config() -> Dict[str, Any]:
    """Get configuration from config.json."""
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_mod_info() -> Dict[str, Any]:
    """Get information about installed mods."""
    mods_info = {
        "total": 0,
        "client_only": 0,
        "server_only": 0,
        "quarantined": 0,
        "mods": []
    }
    
    try:
        # Check mods directory
        mods_dir = 'mods'
        if os.path.exists(mods_dir):
            for mod_file in os.listdir(mods_dir):
                if mod_file.endswith('.jar'):
                    mods_info['total'] += 1
                    mods_info['mods'].append({
                        "name": mod_file,
                        "type": "unknown",
                        "size": os.path.getsize(os.path.join(mods_dir, mod_file))
                    })
    except Exception as e:
        print(f"Error getting mod info: {e}")
    
    return mods_info