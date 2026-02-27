"""Utility functions for live log analysis and client mod detection."""

import os
import re
from typing import List, Dict, Any, Optional


def get_live_log_tail(lines: int = 50) -> List[str]:
    """Get last N lines from live.log."""
    try:
        if os.path.exists('live.log'):
            with open('live.log', 'r') as f:
                # Read last N lines
                lines_list = f.readlines()
                return lines_list[-lines:]
        return []
    except Exception as e:
        print(f"Error reading live log: {e}")
        return []


def analyze_client_only_mods() -> List[str]:
    """Analyze live.log to detect client-only mods."""
    client_mods = []
    
    try:
        if os.path.exists('live.log'):
            with open('live.log', 'r') as f:
                for line in f:
                    # Look for client-side mod loading errors
                    if "client" in line.lower() and "error" in line.lower():
                        # Extract mod name from error message
                        mod_name = extract_mod_name(line)
                        if mod_name and mod_name not in client_mods:
                            client_mods.append(mod_name)
                    
                    # Look for missing client-side dependencies
                    if "missing" in line.lower() and "client" in line.lower():
                        mod_name = extract_mod_name(line)
                        if mod_name and mod_name not in client_mods:
                            client_mods.append(mod_name)
                    
                    # Look for client-side rendering errors
                    if "rendering" in line.lower() and "error" in line.lower():
                        mod_name = extract_mod_name(line)
                        if mod_name and mod_name not in client_mods:
                            client_mods.append(mod_name)
    except Exception as e:
        print(f"Error analyzing client mods: {e}")
    
    return client_mods


def extract_mod_name(log_line: str) -> Optional[str]:
    """Extract mod name from log line using regex patterns."""
    patterns = [
        r'\[.*?\]',  # Content in square brackets
        r'"(.*?)"',  # Content in quotes
        r'\b([A-Za-z0-9_-]+)\.jar\b',  # .jar file names
        r'Mod\s+([A-Za-z0-9_-]+)'  # Mod followed by name
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, log_line)
        for match in matches:
            # Filter out common non-mod strings
            if len(match) > 2 and len(match) < 50:
                if not any(x in match.lower() for x in ['error', 'warning', 'info', 'debug']):
                    return match
    
    return None