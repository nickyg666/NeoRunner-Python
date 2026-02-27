"""Utility functions for modpack conversion and management."""

import os
import shutil
import zipfile
import json
from typing import Dict, Any, Optional


def convert_modpack(modpack_path: str, target_version: str, target_loader: str) -> Dict[str, Any]:
    """Convert modpack to target version and loader."""
    result = {"success": False, "message": "", "converted": 0, "errors": []}
    
    try:
        if not os.path.exists(modpack_path):
            result['message'] = "Modpack path does not exist"
            return result
        
        # Determine if it's a folder or zip file
        if os.path.isdir(modpack_path):
            mods_dir = modpack_path
        else:
            # Extract zip to temporary directory
            temp_dir = '_temp_modpack_'
            os.makedirs(temp_dir, exist_ok=True)
            with zipfile.ZipFile(modpack_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            mods_dir = temp_dir
        
        # Find mods in directory
        mods_found = []
        for root, dirs, files in os.walk(mods_dir):
            for file in files:
                if file.endswith('.jar'):
                    mods_found.append(os.path.join(root, file))
        
        if not mods_found:
            result['message'] = "No mods found in modpack"
            return result
        
        # Convert each mod (placeholder - actual implementation would need mod metadata)
        converted_mods = []
        for mod_path in mods_found:
            try:
                # Here we would check mod metadata and convert if needed
                # For now, just copy to mods directory
                mod_name = os.path.basename(mod_path)
                target_path = os.path.join('mods', mod_name)
                shutil.copy(mod_path, target_path)
                converted_mods.append(mod_name)
            except Exception as e:
                result['errors'].append(f"Error converting {mod_path}: {e}")
        
        result['success'] = True
        result['converted'] = len(converted_mods)
        result['message'] = f"Converted {len(converted_mods)} mods"
        
    except Exception as e:
        result['errors'].append(f"Error converting modpack: {e}")
    
    return result


def validate_mod_for_loader(mod_path: str, target_loader: str, target_version: str) -> Dict[str, Any]:
    """Validate if a mod is compatible with target loader and version."""
    result = {"success": False, "compatible": False, "message": ""}
    
    try:
        # Check mod metadata (placeholder implementation)
        mod_name = os.path.basename(mod_path)
        
        # Simple compatibility check based on naming conventions
        if target_loader.lower() in mod_name.lower():
            result['compatible'] = True
            result['success'] = True
            result['message'] = f"{mod_name} is compatible with {target_loader}"
        else:
            result['success'] = True
            result['message'] = f"{mod_name} compatibility unknown"
    except Exception as e:
        result['errors'].append(f"Error validating mod: {e}")
    
    return result