"""
API service for NeoRunner - Utility functions

This module contains utility functions for the NeoRunner application,
including command execution and common API operations.
"""

import subprocess
import json
from pathlib import Path

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


def validate_json(data):
    """Validate JSON data."""
    try:
        json.loads(data)
        return True
    except json.JSONDecodeError:
        return False


def check_port_availability(port):
    """Check if a port is available."""
    import socket
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) != 0