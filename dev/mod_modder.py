"""
Mixin conflict resolution system for mod compatibility

================================================================================
MIXIN CRASH SOLUTIONS - DOCUMENTATION
================================================================================

WHAT CAUSES MIXIN CRASHES:
--------------------------
1. **Conflicting Targets**: Multiple mods target the same class with mixins
   that have incompatible transformations
   
2. **Duplicate Field Declarations**: Two or more mixins try to inject the same
   field into a target class, causing "Field X already defined" errors
   
3. **Priority Conflicts**: When mixin application order matters (e.g., one mixin
   needs to transform before another), incorrect priority causes crashes
   
4. **Refmap Issues**: Missing or incorrect obfuscation mappings cause mixins to
   fail at runtime when trying to access renamed methods/fields

5. **Transformer Chain Problems**: Mixins applied in wrong phase (pre-init vs
   default) can cause classloader issues


SOLUTION APPROACHES:
--------------------
1. **Load Order Manipulation**:
   - Forge/NeoForge: Uses mods.toml with `ordering` field
     - `ordering="AFTER"` ensures mod loads after dependency
     - `ordering="BEFORE"` ensures mod loads before dependency
   - Fabric: Uses fabric.mod.json `depends` array
     - Mods auto-load after their dependencies
   - Filename prefixes (!, aa_, zz_) are LESS RELIABLE and loader-specific
     - Some launchers ignore filename ordering entirely
     - Only works if the loader uses alphabetical mod discovery
   
2. **@Unique Annotation** (recommended for field conflicts):
   - Add `@Unique` to mixin field declarations
   - Causes mixin to gracefully skip if field already exists
   - Example: `@Unique private int myMod$customValue;`
   
3. **Mixin Config Priority**:
   - Set `priority` in mixin config JSON
   - Lower priority = applied FIRST (default: 1000)
   - Higher priority = applied LAST (can override earlier mixins)
   - Use when one mod needs to apply after another mod's mixins
   
4. **Mixins Config Merging**:
   - Create a "compat" mixin that coordinates between conflicting mods
   - Single mixin config can handle shared targets properly
   - Requires modpack-level coordination
   
5. **Refmap Patching**:
   - Merge refmap files from conflicting mods
   - Or regenerate refmaps with combined mappings
   - Needed when mods use different obfuscation contexts

6. **Dependency Injection**:
   - Add proper `depends` entries in mods.toml or fabric.mod.json
   - This is the PROPER way to control load order
   - Requires JAR modification/republishing


LOAD ORDER MECHANISMS BY LOADER:
--------------------------------
| Loader       | Mechanism              | How to Set                    |
|--------------|------------------------|-------------------------------|
| Forge        | mods.toml ordering     | [[dependencies.modid]]        |
| NeoForge     | mods.toml ordering     | [[dependencies.modid]]        |
| Fabric       | fabric.mod.json depends| "depends": ["modid"]          |
| Quilt        | quilt.mod.json depends | "depends": {"id": "modid"}    |
| Sponge       | Mixin config priority  | "priority": 500               |


LIMITATIONS - CANNOT BE FIXED AUTOMATICALLY:
--------------------------------------------
1. **Fundamental Incompatibilities**: Two mods that modify the same game logic
   in incompatible ways (e.g., both override the same method differently)
   
2. **Version Mismatches**: Mods compiled for different MC versions or mappings
   
3. **Missing Required Dependencies**: Mod requires another mod that isn't installed
   
4. **Class Transform Conflicts**: When two mods completely replace a class rather
   than mixin into it, they cannot coexist
   
5. **Native/JNI Conflicts**: C++ libraries or LWJGL version conflicts

6. **Coremod Conflicts**: Old-style coremods (pre-mixin) cannot be resolved


BEST PRACTICES FOR MODPACK AUTHORS:
-----------------------------------
1. Use dependency declarations, not filename prefixes (unless using a launcher
   that supports alphabetical ordering)
   
2. When two mods conflict:
   a. Check if one has a compatibility addon
   b. Check mod wikki/issues for known incompatibilities
   c. Try removing one mod
   
3. For mixin-specific crashes:
   a. Use --mixin.debug argument for detailed logs
   b. Check which mod's mixin is failing
   c. Look for @Unique in the failing mixin (if source available)
   
4. File name prefix approach (!aa_, !bb_, !zz_) is a WORKAROUND that may help
   with some launchers but is NOT guaranteed to work

================================================================================
"""
import os
import json
import subprocess
import re
import zipfile
import tempfile
import shutil
import logging
from typing import Dict, List, Set, Tuple, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MixinConflictResolver:
    """Detects and resolves mixin conflicts between mods"""
    
    def __init__(self, mods_dir: str, mc_version: str):
        self.mods_dir = mods_dir
        self.mc_version = mc_version
        self.conflicts: List[Dict] = []
        self.mixin_targets: Dict[str, List[str]] = {}
        
    def scan_mod_mixins(self, jar_path: str) -> Dict:
        """Scan a single mod JAR for mixin definitions"""
        result = {
            "mod": os.path.basename(jar_path),
            "mixin_configs": [],
            "targets": [],
            "package": None
        }
        
        try:
            with zipfile.ZipFile(jar_path, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('.json') and 'mixin' in name.lower():
                        try:
                            content = zf.read(name).decode('utf-8')
                            config = json.loads(content)
                            result["mixin_configs"].append(name)
                            
                            if isinstance(config, dict):
                                if "package" in config:
                                    result["package"] = config["package"]
                                targets = config.get("targets", [])
                                if isinstance(targets, list):
                                    result["targets"].extend(targets)
                                for pkg in config.get("mixins", []):
                                    if pkg:
                                        result["targets"].append(pkg)
                        except:
                            pass
                    
                    if name.endswith('mods.toml') or name.endswith('fabric.mod.json'):
                        try:
                            content = zf.read(name).decode('utf-8')
                            if 'mixin' in content.lower():
                                mixin_refs = re.findall(r'mixin[s]?["\']?\s*[:=]\s*["\']?([^\s"\',}]+)', content, re.IGNORECASE)
                                result["targets"].extend(mixin_refs)
                        except:
                            pass
        except Exception as e:
            pass
        
        return result
    
    def scan_all_mods(self) -> Dict[str, Dict]:
        """Scan all mods in the mods directory for mixins"""
        mods_data = {}
        
        if not os.path.isdir(self.mods_dir):
            return mods_data
        
        for filename in os.listdir(self.mods_dir):
            if filename.endswith('.jar'):
                jar_path = os.path.join(self.mods_dir, filename)
                mods_data[filename] = self.scan_mod_mixins(jar_path)
        
        return mods_data
    
    def detect_conflicts(self, mods_data: Dict[str, Dict]) -> List[Dict]:
        """Detect potential mixin conflicts between mods"""
        conflicts = []
        target_to_mods: Dict[str, List[str]] = {}
        
        for mod_name, data in mods_data.items():
            for target in data.get("targets", []):
                if target not in target_to_mods:
                    target_to_mods[target] = []
                target_to_mods[target].append(mod_name)
        
        for target, mods in target_to_mods.items():
            if len(mods) > 1:
                conflicts.append({
                    "target": target,
                    "mods": mods,
                    "type": "shared_target",
                    "severity": "warning"
                })
        
        self.conflicts = conflicts
        self.mixin_targets = target_to_mods
        return conflicts
    
    def resolve_by_load_order(self) -> Dict:
        """Attempt to resolve conflicts by adjusting mod load order via file prefixes"""
        results = {"resolved": 0, "renamed": [], "errors": [], "skipped": []}
        
        if not self.conflicts:
            logger.info("No conflicts to resolve")
            return results
        
        for conflict in self.conflicts:
            if conflict["type"] == "shared_target":
                mods = conflict["mods"]
                priority_mod = self._determine_priority(mods, conflict["target"])
                
                if not priority_mod:
                    logger.warning(f"Could not determine priority for conflict: {conflict['target']}")
                    continue
                
                logger.info(f"Resolving conflict for target {conflict['target']}: priority mod is {priority_mod}")
                
                for i, mod in enumerate(mods):
                    old_path = os.path.join(self.mods_dir, mod)
                    
                    prefix_pattern = re.compile(r'^(!?[a-z]{2}_\d{2}_|!|\d{2}_)', re.IGNORECASE)
                    clean_name = prefix_pattern.sub('', mod)
                    
                    if mod == priority_mod:
                        new_name = f"!aa_{i:02d}_{clean_name}"
                    else:
                        new_name = f"!zz_{i:02d}_{clean_name}"
                    
                    if new_name == mod:
                        results["skipped"].append(mod)
                        logger.debug(f"Skipping {mod} - already has correct prefix")
                        continue
                    
                    new_path = os.path.join(self.mods_dir, new_name)
                    
                    try:
                        logger.info(f"Renaming {mod} -> {new_name}")
                        os.rename(old_path, new_path)
                        results["renamed"].append({"old": mod, "new": new_name, "is_priority": mod == priority_mod})
                        results["resolved"] += 1
                    except OSError as e:
                        err_msg = f"Failed to rename {mod}: {e}"
                        logger.error(err_msg)
                        results["errors"].append(err_msg)
        
        logger.info(f"Conflict resolution complete: {results['resolved']} resolved, {len(results['errors'])} errors")
        return results
    
    def _determine_priority(self, mods: List[str], target: str) -> Optional[str]:
        """Determine which mod should have priority"""
        priority_mod = None
        highest_score = -1
        
        for mod in mods:
            score = 0
            mod_lower = mod.lower()
            
            if any(x in mod_lower for x in ["library", "api", "core", "lib"]):
                score += 10
            if any(x in mod_lower for x in ["compat", "patch", "fix"]):
                score += 5
            if any(x in mod_lower for x in ["optional", "addon", "plugin"]):
                score -= 5
            
            if score > highest_score:
                highest_score = score
                priority_mod = mod
        
        if priority_mod:
            return priority_mod
        return mods[0] if mods else None


class ModModder:
    """High-level mod modulation interface for mixin conflict resolution"""
    
    def __init__(self, mods_dir: str, mc_version: str):
        self.mods_dir = mods_dir
        self.mc_version = mc_version
        self.resolver = MixinConflictResolver(mods_dir, mc_version)
        
    def analyze_and_resolve(self) -> Dict:
        """Full analysis and conflict resolution workflow"""
        mods_data = self.resolver.scan_all_mods()
        
        if not mods_data:
            return {
                "status": "success",
                "message": "No mods found to analyze",
                "mods_scanned": 0,
                "conflicts": [],
                "resolved": 0
            }
        
        conflicts = self.resolver.detect_conflicts(mods_data)
        
        if not conflicts:
            return {
                "status": "success",
                "message": "No mixin conflicts detected",
                "mods_scanned": len(mods_data),
                "conflicts": [],
                "resolved": 0
            }
        
        resolution = self.resolver.resolve_by_load_order()
        
        return {
            "status": "success",
            "message": f"Found {len(conflicts)} conflicts, resolved {resolution['resolved']}",
            "mods_scanned": len(mods_data),
            "conflicts": conflicts,
            "resolution": resolution,
            "resolved": resolution["resolved"]
        }
    
    def get_mod_load_order(self) -> List[str]:
        """Get current mod load order based on filename prefixes"""
        if not os.path.isdir(self.mods_dir):
            return []
        
        mods = [f for f in os.listdir(self.mods_dir) if f.endswith('.jar')]
        return sorted(mods)
    
    def _strip_prefix(self, filename: str) -> str:
        prefix_pattern = re.compile(r'^(!?[a-z]{2}_\d{2}_|!|\d{2}_)', re.IGNORECASE)
        return prefix_pattern.sub('', filename)
    
    def _get_loader_type(self) -> str:
        """Detect mod loader type based on mods directory contents"""
        try:
            for f in os.listdir(self.mods_dir):
                if f.endswith('.jar'):
                    jar_path = os.path.join(self.mods_dir, f)
                    try:
                        with zipfile.ZipFile(jar_path, 'r') as zf:
                            names = zf.namelist()
                            if any('fabric.mod.json' in n for n in names):
                                return "fabric"
                            if any('quilt.mod.json' in n for n in names):
                                return "quilt"
                            if any('mods.toml' in n for n in names):
                                return "forge"
                    except:
                        continue
        except Exception as e:
            logger.warning(f"Could not detect loader type: {e}")
        return "unknown"
    
    def optimize_load_order(self) -> Dict:
        """
        Optimize load order for all mods (APIs first, then regular mods, addons last).
        
        Uses filename prefixes as a fallback approach. Note that for proper load
        ordering, mods.toml (Forge/NeoForge) or fabric.mod.json (Fabric) dependency
        declarations are preferred. Filename ordering may not work with all launchers.
        
        Prefix scheme:
        - API/library mods: !aa_XX_ (load first, high priority)
        - Regular mods: !bb_XX_ (normal load order)
        - Addon/compat mods: !zz_XX_ (load last, after dependencies)
        """
        if not os.path.isdir(self.mods_dir):
            logger.error(f"Mods directory not found: {self.mods_dir}")
            return {"status": "error", "message": "Mods directory not found"}
        
        mods = [f for f in os.listdir(self.mods_dir) if f.endswith('.jar')]
        
        if not mods:
            logger.info("No mods found to optimize")
            return {"status": "success", "message": "No mods found", "renamed": [], "api_mods": 0, "regular_mods": 0, "addon_mods": 0}
        
        loader_type = self._get_loader_type()
        logger.info(f"Detected loader type: {loader_type}")
        
        api_mods = []
        regular_mods = []
        addon_mods = []
        
        for mod in mods:
            clean_name = self._strip_prefix(mod)
            mod_lower = clean_name.lower()
            if any(x in mod_lower for x in ["library", "api", "core", "lib", "bukkit", "spigot"]):
                api_mods.append(mod)
            elif any(x in mod_lower for x in ["addon", "plugin", "optional", "compat"]):
                addon_mods.append(mod)
            else:
                regular_mods.append(mod)
        
        renamed = []
        errors = []
        skipped = []
        
        for i, mod in enumerate(sorted(api_mods, key=lambda x: self._strip_prefix(x).lower())):
            clean_name = self._strip_prefix(mod)
            new_name = f"!aa_{i:02d}_{clean_name}"
            old_path = os.path.join(self.mods_dir, mod)
            new_path = os.path.join(self.mods_dir, new_name)
            
            if mod == new_name:
                skipped.append(mod)
                logger.debug(f"Skipping {mod} - already has correct prefix")
                continue
            
            try:
                logger.info(f"Renaming API mod: {mod} -> {new_name}")
                os.rename(old_path, new_path)
                renamed.append({"old": mod, "new": new_name, "category": "api"})
            except OSError as e:
                err_msg = f"Failed to rename {mod}: {e}"
                logger.error(err_msg)
                errors.append(err_msg)
        
        for i, mod in enumerate(sorted(regular_mods, key=lambda x: self._strip_prefix(x).lower())):
            clean_name = self._strip_prefix(mod)
            new_name = f"!bb_{i:02d}_{clean_name}"
            old_path = os.path.join(self.mods_dir, mod)
            new_path = os.path.join(self.mods_dir, new_name)
            
            if mod == new_name:
                skipped.append(mod)
                logger.debug(f"Skipping {mod} - already has correct prefix")
                continue
            
            try:
                logger.info(f"Renaming regular mod: {mod} -> {new_name}")
                os.rename(old_path, new_path)
                renamed.append({"old": mod, "new": new_name, "category": "regular"})
            except OSError as e:
                err_msg = f"Failed to rename {mod}: {e}"
                logger.error(err_msg)
                errors.append(err_msg)
        
        for i, mod in enumerate(sorted(addon_mods, key=lambda x: self._strip_prefix(x).lower())):
            clean_name = self._strip_prefix(mod)
            new_name = f"!zz_{i:02d}_{clean_name}"
            old_path = os.path.join(self.mods_dir, mod)
            new_path = os.path.join(self.mods_dir, new_name)
            
            if mod == new_name:
                skipped.append(mod)
                logger.debug(f"Skipping {mod} - already has correct prefix")
                continue
            
            try:
                logger.info(f"Renaming addon mod: {mod} -> {new_name}")
                os.rename(old_path, new_path)
                renamed.append({"old": mod, "new": new_name, "category": "addon"})
            except OSError as e:
                err_msg = f"Failed to rename {mod}: {e}"
                logger.error(err_msg)
                errors.append(err_msg)
        
        status = "success" if not errors else "partial"
        message = f"Optimized load order: {len(renamed)} renamed, {len(skipped)} skipped"
        if errors:
            message += f", {len(errors)} errors"
        
        logger.info(f"Load order optimization complete: {message}")
        
        if loader_type in ("forge", "fabric"):
            logger.warning(
                f"Note: Filename prefixes may not affect load order for {loader_type}. "
                "Consider using dependency declarations in mods.toml or fabric.mod.json instead."
            )
        
        return {
            "status": status,
            "message": message,
            "renamed": renamed,
            "errors": errors,
            "skipped": len(skipped),
            "api_mods": len(api_mods),
            "regular_mods": len(regular_mods),
            "addon_mods": len(addon_mods),
            "loader_type": loader_type,
            "warning": f"Filename prefixes may not affect {loader_type} load order" if loader_type != "unknown" else None
        }
