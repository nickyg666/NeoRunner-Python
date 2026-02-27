"""
Services module for NeoRunner - Business logic layer

This module contains all business logic services for the NeoRunner application,
including configuration, server management, Java handling, mod management, and API utilities.
"""

import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

def load_cfg():
    """Load configuration from config.json."""
    config_path = os.path.join(os.getcwd(), 'config.json')
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def save_cfg(config):
    """Save configuration to config.json."""
    config_path = os.path.join(os.getcwd(), 'config.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)


def get_server_status():
    """Get current server status."""
    # Check if server process is running
    try:
        # Check for tmux session
        result = subprocess.run(
            ['tmux', 'list-sessions'], 
            capture_output=True, text=True
        )
        server_running = 'mcserver' in result.stdout
        
        return {
            'running': server_running,
            'status': 'online' if server_running else 'offline',
            'last_check': datetime.now().isoformat(),
            'uptime': 'N/A'  # Implement actual uptime calculation
        }
    
    except Exception as e:
        return {
            'running': False,
            'status': 'error',
            'last_check': datetime.now().isoformat(),
            'error': str(e)
        }


def parse_props():
    """Parse server.properties file."""
    props_path = os.path.join(os.getcwd(), 'server.properties')
    props = {}
    
    if os.path.exists(props_path):
        with open(props_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    props[key] = value
    
    return props


def _get_java_version():
    """Get current Java version."""
    try:
        result = subprocess.run(
            ['java', '-version'], 
            capture_output=True, text=True, 
            stderr=subprocess.STDOUT
        )
        version_line = result.stdout.split('\n')[0]
        return version_line.strip()
    
    except Exception:
        return 'Java not found'


def _check_jdk_upgrade_available():
    """Check if JDK upgrade is available."""
    # This would implement actual upgrade checking logic
    # For now, return False as placeholder
    return False


def get_mods():
    """Get list of installed mods."""
    # This would implement actual mod listing logic
    # For now, return empty list as placeholder
    return []


def delete_mod(mod_name):
    """Delete a mod."""
    # This would implement actual mod deletion logic
    pass


def quarantine_mod(mod_name):
    """Quarantine a mod."""
    # This would implement actual mod quarantine logic
    pass


def get_quarantine_list():
    """Get list of quarantined mods."""
    # This would implement actual quarantine listing logic
    return []


def run_cmd(cmd):
    """Run a shell command and return result."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, 
            text=True, timeout=10
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    
    except Exception as e:
        return {
            'success': False, 
            'error': str(e)
        }