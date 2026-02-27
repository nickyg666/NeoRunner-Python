"""Client mod notification analysis utilities."""

import os
import re
from typing import List, Dict, Any, Optional


def analyze_client_only_mods() -> List[str]:
    """Analyze live.log to detect client-only mods that should not run on server."""
    client_mods = []
    
    try:
        if os.path.exists('live.log'):
            with open('live.log', 'r') as f:
                for line in f:
                    # Look for client-side mod loading errors
                    if "client" in line.lower() and "error" in line.lower():
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
                    
                    # Look for client-side GUI errors
                    if "gui" in line.lower() and "error" in line.lower():
                        mod_name = extract_mod_name(line)
                        if mod_name and mod_name not in client_mods:
                            client_mods.append(mod_name)
    except Exception as e:
        print(f"Error analyzing client mods: {e}")
    
    return client_mods


def extract_mod_name(log_line: str) -> Optional[str]:
    """Extract mod name from log line using enhanced patterns."""
    patterns = [
        r'\[.*?\]',  # Content in square brackets
        r'"(.*?)"',  # Content in quotes
        r'\b([A-Za-z0-9_-]+)\.jar\b',  # .jar file names
        r'Mod\s+([A-Za-z0-9_-]+)',  # Mod followed by name
        r'([A-Za-z0-9_-]+)\s+\(Client\)',  # Mod with (Client) suffix
        r'([A-Za-z0-9_-]+)\s+\(Client Side\)'  # Mod with (Client Side) suffix
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, log_line)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            
            # Filter out common non-mod strings
            if len(match) > 2 and len(match) < 50:
                if not any(x in match.lower() for x in ['error', 'warning', 'info', 'debug']):
                    return match
    
    return None


def move_client_only_mods_to_folder() -> Dict[str, Any]:
    """Move detected client-only mods to clientonly folder."""
    result = {"success": False, "moved": 0, "errors": []}
    
    try:
        client_mods = analyze_client_only_mods()
        
        if not client_mods:
            result['success'] = True
            result['message'] = "No client-only mods detected"
            return result
        
        # Create clientonly directory if it doesn't exist
        clientonly_dir = 'clientonly'
        os.makedirs(clientonly_dir, exist_ok=True)
        
        for mod_name in client_mods:
            mod_path = os.path.join('mods', mod_name)
            if os.path.exists(mod_path):
                try:
                    client_path = os.path.join(clientonly_dir, mod_name)
                    os.rename(mod_path, client_path)
                    result['moved'] += 1
                except Exception as e:
                    result['errors'].append(f"Error moving {mod_name}: {e}")
        
        result['success'] = True
    except Exception as e:
        result['errors'].append(f"Error moving client mods: {e}")
    
    return result


def get_client_mod_notifications() -> List[Dict[str, Any]]:
    """Get notifications about client mod issues."""
    notifications = []
    
    try:
        # Check for client-only mods in mods directory
        mods_dir = 'mods'
        if os.path.exists(mods_dir):
            for mod_file in os.listdir(mods_dir):
                if mod_file.endswith('.jar'):
                    # Check if mod is known client-only (simple heuristic)
                    if any(keyword in mod_file.lower() for keyword in ['client', 'render', 'gui']):
                        notifications.append({
                            "type": "client_only",
                            "mod": mod_file,
                            "message": f"{mod_file} appears to be client-only and may cause issues on server",
                            "action": "move_to_clientonly"
                        })
        
        # Check for mixin errors related to client mods
        mixin_errors = analyze_mixin_errors()
        for error in mixin_errors:
            if "client" in error['mod'].lower():
                notifications.append({
                    "type": "mixin_error",
                    "mod": error['mod'],
                    "message": f"{error['mod']} has mixin errors that may affect compatibility",
                    "action": "fix_mixin"
                })
    except Exception as e:
        print(f"Error getting client mod notifications: {e}")
    
    return notifications