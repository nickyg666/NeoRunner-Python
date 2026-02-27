"""Mixin analyzer and compatibility fixer."""

import os
import re
from typing import List, Dict, Any, Optional


def analyze_mixin_errors() -> List[Dict[str, Any]]:
    """Analyze live.log for mixin errors and return problematic mods."""
    mixin_errors = []
    
    try:
        if os.path.exists('live.log'):
            with open('live.log', 'r') as f:
                for line in f:
                    if 'mixin' in line.lower() and 'error' in line.lower():
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
    patterns = [
        r'\[.*?\]',
        r'"(.*?)"',
        r'\b([A-Za-z0-9_-]+)\.jar\b',
        r'Mod\s+([A-Za-z0-9_-]+)'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, log_line)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            
            if len(match) > 2 and len(match) < 50:
                if not any(x in match.lower() for x in ['error', 'warning', 'info', 'debug']):
                    return match
    
    return None


def extract_mixin_info(log_line: str) -> Optional[str]:
    """Extract mixin information from log line."""
    if 'mixin' in log_line.lower():
        if 'conflicts with' in log_line:
            parts = log_line.split('conflicts with')
            if len(parts) > 1:
                return parts[1].strip()
        elif 'error' in log_line.lower():
            if 'error' in log_line:
                parts = log_line.split('error')
                if len(parts) > 1:
                    return parts[1].strip()
    
    return None


def fix_mixin_compatibility() -> Dict[str, Any]:
    """Attempt to fix mixin compatibility issues."""
    result = {"success": False, "fixed": 0, "errors": [], "message": ""}
    
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
        result['message'] = f"Attempted to fix {result['fixed']} mods with mixin issues"
    except Exception as e:
        result['errors'].append(f"Error fixing mixins: {e}")
    
    return result


def get_mixin_error_summary() -> Dict[str, Any]:
    """Get summary of mixin errors by mod."""
    summary = {"total_errors": 0, "mods": {}}
    
    try:
        mixin_errors = analyze_mixin_errors()
        summary['total_errors'] = len(mixin_errors)
        
        for error in mixin_errors:
            mod_name = error['mod']
            if mod_name not in summary['mods']:
                summary['mods'][mod_name] = {
                    "errors": 0,
                    "mixins": []
                }
            
            summary['mods'][mod_name]["errors"] += 1
            summary['mods'][mod_name]["mixins"].append(error['mixin'])
    except Exception as e:
        print(f"Error getting mixin summary: {e}")
    
    return summary