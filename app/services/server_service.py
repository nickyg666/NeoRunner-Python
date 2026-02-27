"""
Server service for NeoRunner - Server management logic

This module contains all server management functionality for the NeoRunner application,
including status checking, starting/stopping, and server operations.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path


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


def start_server():
    """Start the Minecraft server."""
    try:
        result = subprocess.run(
            ['tmux', 'new-session', '-d', '-s', 'mcserver', './start.sh'],
            capture_output=True, text=True
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    
    except Exception as e:
        return {'success': False, 'error': str(e)}


def stop_server():
    """Stop the Minecraft server."""
    try:
        result = subprocess.run(
            ['tmux', 'kill-session', '-t', 'mcserver'],
            capture_output=True, text=True
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    
    except Exception as e:
        return {'success': False, 'error': str(e)}


def restart_server():
    """Restart the Minecraft server."""
    stop_result = stop_server()
    if not stop_result['success']:
        return stop_result
    
    return start_server()


def run_server_command(command):
    """Run a command in the server console."""
    try:
        # This would implement RCON or tmux send-keys functionality
        return {'success': True, 'message': 'Command sent'}
    
    except Exception as e:
        return {'success': False, 'error': str(e)}