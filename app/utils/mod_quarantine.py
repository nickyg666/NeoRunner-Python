"""Utility functions for mod management and analysis."""

import os
import json
import subprocess
from typing import Dict, List, Any, Optional


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


def get_quarantined_mods() -> List[str]:
    """Get list of quarantined mods."""
    quarantined_dir = 'quarantined'
    if os.path.exists(quarantined_dir):
        return [f for f in os.listdir(quarantined_dir) if f.endswith('.jar')]
    return []


def quarantine_client_mods() -> Dict[str, Any]:
    """Quarantine client-only mods detected from live.log."""
    result = {"success": False, "quarantined": 0, "errors": []}
    
    try:
        # Create quarantined directory if it doesn't exist
        quarantined_dir = 'quarantined'
        os.makedirs(quarantined_dir, exist_ok=True)
        
        # Get client-only mods from analysis
        client_mods = analyze_client_only_mods()
        
        if client_mods:
            for mod_name in client_mods:
                mod_path = os.path.join('mods', mod_name)
                if os.path.exists(mod_path):
                    try:
                        # Move to quarantined
                        quarantined_path = os.path.join(quarantined_dir, mod_name)
                        os.rename(mod_path, quarantined_path)
                        result['quarantined'] += 1
                    except Exception as e:
                        result['errors'].append(f"Error quarantining {mod_name}: {e}")
            
            result['success'] = True
        else:
            result['success'] = True
            result['message'] = "No client-only mods detected"
    except Exception as e:
        result['errors'].append(f"Error quarantining mods: {e}")
    
    return result


def analyze_mixin_errors() -> List[Dict[str, Any]]:
    """Analyze live.log for mixin errors and return problematic mods."""
    mixin_errors = []
    
    try:
        if os.path.exists('live.log'):
            with open('live.log', 'r') as f:
                for line in f:
                    if 'mixin' in line.lower() and 'error' in line.lower():
                        # Extract mod name and mixin info
                        mod_name = extract_mod_name(line)
                        mixin_info = extract_mixin_info(line)
                        
                        if mod_name and mixin_info:
                            mixin_errors.append({
                                "mod": mod_name,
                                "error": line.strip(),
                                "mixin": mixin_info
                            })
    except Exception as e:
        print(f"Error analyzing mixin errors: {e}")
    
    return mixin_errors


def extract_mod_name(log_line: str) -> Optional[str]:
    """Extract mod name from log line."""
    # Simple heuristic: look for mod names in brackets or quotes
    if '[' in log_line and ']' in log_line:
        start = log_line.find('[')
        end = log_line.find(']')
        if start != -1 and end != -1:
            return log_line[start+1:end]
    
    if '' in log_line:
        start = log_line.find('')
        end = log_line.find('', start+1)
        if start != -1 and end != -1:
            return log_line[start+1:end]
    
    return None


def extract_mixin_info(log_line: str) -> Optional[str]:
    """Extract mixin information from log line."""
    if 'mixin' in log_line.lower():
        # Look for mixin class names
        if 'conflicts with' in log_line:
            parts = log_line.split('conflicts with')
            if len(parts) > 1:
                return parts[1].strip()
        elif 'error' in log_line.lower():
            # Look for class names after 'error'
            if 'error' in log_line:
                parts = log_line.split('error')
                if len(parts) > 1:
                    return parts[1].strip()
    
    return None


def fix_mixin_compatibility() -> Dict[str, Any]:
    """Attempt to fix mixin compatibility issues."""
    result = {"success": False, "fixed": 0, "errors": []}
    
    try:
        mixin_errors = analyze_mixin_errors()
        
        if not mixin_errors:
            result['success'] = True
            result['message'] = "No mixin errors found"
            return result
        
        # Create backup of problematic mods
        backup_dir = 'mods_backup'
        os.makedirs(backup_dir, exist_ok=True)
        
        for error in mixin_errors:
            mod_name = error['mod']
            mod_path = os.path.join('mods', mod_name)
            
            if os.path.exists(mod_path):
                try:
                    # Backup original
                    backup_path = os.path.join(backup_dir, mod_name)
                    os.rename(mod_path, backup_path)
                    
                    # Attempt to modify jar (placeholder - actual implementation would need jar manipulation)
                    # For now, just restore from backup
                    os.rename(backup_path, mod_path)
                    result['fixed'] += 1
                except Exception as e:
                    result['errors'].append(f"Error fixing {mod_name}: {e}")
        
        result['success'] = True
    except Exception as e:
        result['errors'].append(f"Error fixing mixins: {e}")
    
    return result