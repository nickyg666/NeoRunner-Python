"""Client-only mod detector - identifies and FIXES mods that crash dedicated servers.

Actions:
1. KNOWN_CLIENT_ONLY mods -> move to clientonly/
2. Mods with client class files -> strip client classes from JAR
3. Mods with client mixin targets -> patch mixin JSON to remove client targets
"""

import zipfile
import os
import re
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Patterns that DEFINITELY crash server when present as class files
FATAL_FILE_PATTERNS = [
    "net/minecraft/client/",
    "com/mojang/blaze3d/",
    "net/optifine/",
    "net/iris/",
]

# Mixin targets that crash on server (client-side only)
FATAL_MIXIN_TARGETS = [
    "net.minecraft.client.",
    "net.minecraft.src.",
    "com.mojang.blaze3d.",
    "net.optifine.",
    "net.iris.",
]

# Mod IDs that are client-only (cannot be fixed, must move to clientonly/)
KNOWN_CLIENT_ONLY = {
    "sodium", "optifine", "iris", "modmenu", "entity_texture_features",
    "xaerominimap", "xaeroworldmap", "dynamicfps", "notenoughanimations",
    "roughlyenoughitems", "emi", "journeymap", "replaymod", "worldedit",
    "litematica", "minihud", "citr", "continuity", "lambdadynamiclights",
    "essential", "pepsi", "okzoomer", "fancymenu", "emotecraft",
    "customskinloader", "xaerobetterpvp", "ok zoomer",
}


@dataclass
class ModAnalysis:
    """Result of analyzing a mod JAR."""
    filename: str
    mod_id: str = ""
    action: str = "keep"  # keep, move, strip, patch
    has_client_classes: bool = False
    has_client_mixins: bool = False
    client_files: List[str] = field(default_factory=list)
    client_mixins: List[str] = field(default_factory=list)
    description: str = ""


def analyze_mod(jar_path: Path) -> ModAnalysis:
    """Analyze a mod JAR to determine what action to take."""
    result = ModAnalysis(filename=jar_path.name)
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            names = zf.namelist()
            
            # Check for client-side class files
            for name in names:
                if name.endswith('.class'):
                    for pattern in FATAL_FILE_PATTERNS:
                        if pattern.replace("/", ".") in name:
                            result.client_files.append(name)
                            result.has_client_classes = True
                            break
            
            # Check for mixin configs with client targets
            mixin_files = [n for n in names if n.endswith('.json') and 'mixin' in n.lower()]
            for mixin_file in mixin_files:
                try:
                    content = zf.read(mixin_file).decode('utf-8', errors='ignore')
                    
                    # Look for client-side targets in mixin config
                    for target in FATAL_MIXIN_TARGETS:
                        if target in content:
                            result.client_mixins.append(f"{mixin_file}: {target}")
                            result.has_client_mixins = True
                except Exception:
                    pass
            
            # Try to extract mod ID
            for name in names:
                if 'neoforge.mods.toml' in name or 'mods.toml' in name:
                    try:
                        content = zf.read(name).decode('utf-8', errors='ignore')
                        mod_id_match = re.search(r'modId\s*=\s*"([^"]+)"', content)
                        if mod_id_match:
                            result.mod_id = mod_id_match.group(1)
                            break
                    except Exception:
                        pass
            
            # Determine action
            mod_id_lower = result.mod_id.lower() if result.mod_id else ""
            
            # Check if known client-only
            if mod_id_lower in KNOWN_CLIENT_ONLY:
                result.action = "move"
                result.description = f"Known client-only mod: {result.mod_id}"
            # Has client class files - need to strip
            elif result.has_client_classes:
                result.action = "strip"
                result.description = f"Has {len(result.client_files)} client class files"
            # Has client mixin targets - need to patch
            elif result.has_client_mixins:
                result.action = "patch"
                result.description = f"Has {len(result.client_mixins)} client mixin targets"
            else:
                result.description = "Safe for server"
    
    except Exception as e:
        log.warning(f"Error analyzing {jar_path}: {e}")
        result.description = f"Error: {e}"
    
    return result


def strip_client_classes(jar_path: Path, backup: bool = True) -> bool:
    """Strip client-side class files from a mod JAR."""
    temp_path = jar_path.parent / f"{jar_path.stem}.stripping.tmp"
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as dst_zip:
                for item in src_zip.infolist():
                    # Skip client-side class files
                    if item.filename.endswith('.class'):
                        is_client = False
                        for pattern in FATAL_FILE_PATTERNS:
                            if pattern.replace("/", ".") in item.filename:
                                is_client = True
                                break
                        if is_client:
                            continue
                    
                    # Copy everything else
                    dst_zip.writestr(item, src_zip.read(item.filename))
        
        # Backup original
        if backup:
            backup_path = jar_path.parent / f"{jar_path.stem}.backup.jar"
            shutil.copy2(jar_path, backup_path)
        
        # Replace original
        temp_path.rename(jar_path)
        log.info(f"Stripped client classes from {jar_path.name}")
        return True
        
    except Exception as e:
        log.error(f"Failed to strip {jar_path.name}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False


def patch_mixin_config(jar_path: Path) -> bool:
    """Patch mixin configs to remove client-side targets."""
    temp_path = jar_path.parent / f"{jar_path.stem}.patching.tmp"
    patches_applied = 0
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as dst_zip:
                for item in src_zip.infolist():
                    content = src_zip.read(item.filename)
                    
                    # Only process mixin JSON files
                    if item.filename.endswith('.json') and 'mixin' in item.filename.lower():
                        try:
                            text = content.decode('utf-8')
                            original = text
                            
                            # Try to parse and modify JSON
                            try:
                                data = json.loads(text)
                                modified = False
                                
                                # Remove client targets from mixins
                                if 'mixins' in data and isinstance(data['mixins'], list):
                                    new_mixins = []
                                    for mixin in data['mixins']:
                                        if isinstance(mixin, dict):
                                            # Check for client targets
                                            if 'target' in mixin:
                                                target = mixin['target']
                                                if any(t in target for t in FATAL_MIXIN_TARGETS):
                                                    modified = True
                                                    continue
                                            # Check refmap for client targets
                                            if 'refmap' in mixin:
                                                refmap = mixin['refmap']
                                                if any(t.replace(".", "/") in refmap for t in FATAL_MIXIN_TARGETS):
                                                    modified = True
                                                    continue
                                        new_mixins.append(mixin)
                                    data['mixins'] = new_mixins
                                
                                # Remove client plugin
                                if 'plugin' in data:
                                    plugin = data['plugin']
                                    if any(t in plugin for t in FATAL_MIXIN_TARGETS):
                                        del data['plugin']
                                        modified = True
                                
                                if modified:
                                    text = json.dumps(data, indent=2)
                                    patches_applied += 1
                            except json.JSONDecodeError:
                                # Not valid JSON, skip
                                pass
                            
                        except Exception:
                            pass
                    
                    dst_zip.writestr(item, content if isinstance(content, bytes) else content.encode('utf-8'))
        
        if patches_applied > 0:
            # Backup original
            backup_path = jar_path.parent / f"{jar_path.stem}.backup.jar"
            shutil.copy2(jar_path, backup_path)
            
            # Replace
            temp_path.rename(jar_path)
            log.info(f"Patched {patches_applied} mixin configs in {jar_path.name}")
            return True
        else:
            # No patches needed
            if temp_path.exists():
                temp_path.unlink()
            return True
            
    except Exception as e:
        log.error(f"Failed to patch {jar_path.name}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False


def process_mod(analysis: ModAnalysis, mods_dir: Path, clientonly_dir: Path) -> bool:
    """Process a mod based on analysis - move, strip, or patch."""
    jar_path = mods_dir / analysis.filename
    
    if analysis.action == "move":
        clientonly_dir.mkdir(parents=True, exist_ok=True)
        dst = clientonly_dir / analysis.filename
        jar_path.rename(dst)
        log.info(f"Moved to clientonly: {analysis.filename}")
        return True
        
    elif analysis.action == "strip":
        return strip_client_classes(jar_path)
        
    elif analysis.action == "patch":
        return patch_mixin_config(jar_path)
    
    return True  # "keep" - no action needed


def fix_server_mods(mods_dir: Path, clientonly_dir: Path = None, verbose: bool = True) -> Dict:
    """Scan and fix all mods in directory."""
    if clientonly_dir is None:
        clientonly_dir = mods_dir.parent / "clientonly"
    
    results = {
        "scanned": 0,
        "moved": [],
        "stripped": [],
        "patched": [],
        "kept": [],
        "failed": [],
    }
    
    for jar in sorted(mods_dir.glob("*.jar")):
        results["scanned"] += 1
        analysis = analyze_mod(jar)
        
        try:
            if analysis.action == "move":
                process_mod(analysis, mods_dir, clientonly_dir)
                results["moved"].append(analysis.filename)
                if verbose:
                    log.warning(f"MOVED (client-only): {analysis.filename}")
                    
            elif analysis.action == "strip":
                process_mod(analysis, mods_dir, clientonly_dir)
                results["stripped"].append(analysis.filename)
                if verbose:
                    log.warning(f"STRIPPED (client classes): {analysis.filename}")
                    
            elif analysis.action == "patch":
                process_mod(analysis, mods_dir, clientonly_dir)
                results["patched"].append(analysis.filename)
                if verbose:
                    log.warning(f"PATCHED (client mixins): {analysis.filename}")
                    
            else:
                results["kept"].append(analysis.filename)
                
        except Exception as e:
            log.error(f"Failed to process {analysis.filename}: {e}")
            results["failed"].append(analysis.filename)
    
    if verbose:
        print(f"\n=== Fix Summary ===")
        print(f"Scanned: {results['scanned']}")
        print(f"Moved to clientonly: {len(results['moved'])}")
        print(f"Stripped client classes: {len(results['stripped'])}")
        print(f"Patched mixins: {len(results['patched'])}")
        print(f"Kept (safe): {len(results['kept'])}")
        print(f"Failed: {len(results['failed'])}")
    
    return results


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    
    if len(sys.argv) > 1:
        mods_dir = Path(sys.argv[1])
    else:
        mods_dir = Path("mods")
    
    if not mods_dir.exists():
        print(f"Error: {mods_dir} does not exist")
        sys.exit(1)
    
    clientonly_dir = mods_dir.parent / "clientonly"
    
    print(f"Scanning {mods_dir}...")
    results = fix_server_mods(mods_dir, clientonly_dir)
