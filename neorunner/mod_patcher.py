"""Automated mod patching system for maximum mixin compatibility"""
import os
import json
import zipfile
import tempfile
import shutil
import re
from typing import Dict, List, Optional

class ModPatcher:
    """Automated mod patching for mixin compatibility"""
    
    def __init__(self, mods_dir: str, mc_version: str):
        self.mods_dir = mods_dir
        self.mc_version = mc_version
        self.patched_log: List[str] = []
        
    def scan_mixin_configs(self, jar_path: str) -> List[Dict]:
        """Extract mixin configuration data from a JAR"""
        configs = []
        
        try:
            with zipfile.ZipFile(jar_path, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('.json') and 'mixin' in name.lower():
                        try:
                            content = zf.read(name).decode('utf-8')
                            config = json.loads(content)
                            configs.append({
                                "file": name,
                                "config": config,
                                "package": config.get("package", ""),
                                "targets": config.get("targets", []),
                                "mixins": config.get("mixins", [])
                            })
                        except:
                            pass
        except Exception as e:
            pass
        
        return configs
    
    def detect_conflict_risk(self, mod_name: str) -> Dict:
        """Analyze a mod for potential mixin conflict risks"""
        jar_path = os.path.join(self.mods_dir, mod_name)
        
        if not os.path.exists(jar_path):
            return {"mod": mod_name, "error": "File not found"}
        
        configs = self.scan_mixin_configs(jar_path)
        
        risks = {
            "mod": mod_name,
            "mixin_configs": len(configs),
            "targets": [],
            "mixins": [],
            "risk_level": "low"
        }
        
        all_targets = []
        for cfg in configs:
            all_targets.extend(cfg.get("targets", []))
            risks["mixins"].extend(cfg.get("mixins", []))
        
        risks["targets"] = list(set(all_targets))
        
        if len(configs) > 3:
            risks["risk_level"] = "medium"
        if len(risks["targets"]) > 5:
            risks["risk_level"] = "high"
        
        return risks
    
    def patch_mixin_refmap(self, jar_path: str, output_path: str) -> bool:
        """Patch mixin refmap for compatibility"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(jar_path, 'r') as zf:
                    zf.extractall(temp_dir)
                
                patched = False
                
                for root, dirs, files in os.walk(temp_dir):
                    for f in files:
                        if f.endswith('.json') and 'refmap' in f.lower():
                            file_path = os.path.join(root, f)
                            try:
                                with open(file_path, 'r') as fh:
                                    content = fh.read()
                                
                                if '"mappings":' not in content and '"data":' not in content:
                                    patched_data = {
                                        "mappings": {},
                                        "data": {}
                                    }
                                    with open(file_path, 'w') as fh:
                                        json.dump(patched_data, fh)
                                    patched = True
                            except:
                                pass
                
                if patched:
                    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, dirs, files in os.walk(temp_dir):
                            for f in files:
                                file_path = os.path.join(root, f)
                                arcname = os.path.relpath(file_path, temp_dir)
                                zf.write(file_path, arcname)
                
                return patched
        except Exception as e:
            return False
    
    def add_mixin_priority(self, jar_path: str, output_path: str, priority: int) -> bool:
        """Add mixin priority configuration"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(jar_path, 'r') as zf:
                    zf.extractall(temp_dir)
                
                mixin_config_path = None
                for root, dirs, files in os.walk(temp_dir):
                    for f in files:
                        if f.endswith('.json') and 'mixin' in f.lower():
                            mixin_config_path = os.path.join(root, f)
                            break
                    if mixin_config_path:
                        break
                
                if mixin_config_path:
                    try:
                        with open(mixin_config_path, 'r') as fh:
                            config = json.load(fh)
                        
                        if "priority" not in config:
                            config["priority"] = priority
                            
                            with open(mixin_config_path, 'w') as fh:
                                json.dump(config, fh, indent=2)
                            
                            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                                for root, dirs, files in os.walk(temp_dir):
                                    for f in files:
                                        file_path = os.path.join(root, f)
                                        arcname = os.path.relpath(file_path, temp_dir)
                                        zf.write(file_path, arcname)
                            
                            return True
                    except:
                        pass
                
                return False
        except Exception as e:
            return False
    
    def auto_patch_mod(self, mod_name: str) -> Dict:
        """Automatically patch a single mod for compatibility"""
        jar_path = os.path.join(self.mods_dir, mod_name)
        
        if not os.path.exists(jar_path):
            return {"success": False, "error": "Mod not found"}
        
        backup_path = jar_path + ".backup"
        
        if not os.path.exists(backup_path):
            shutil.copy2(jar_path, backup_path)
        
        temp_output = jar_path + ".patched"
        
        patches_applied = []
        
        if self.patch_mixin_refmap(jar_path, temp_output):
            patches_applied.append("refmap_patched")
            shutil.move(temp_output, jar_path)
        
        if self.add_mixin_priority(jar_path, temp_output, 1000):
            patches_applied.append("priority_added")
            shutil.move(temp_output, jar_path)
        
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        if patches_applied:
            self.patched_log.append(f"{mod_name}: {', '.join(patches_applied)}")
            marker_path = os.path.join(self.mods_dir, f"{mod_name}.patched")
            with open(marker_path, 'w') as f:
                f.write(f"Patched: {', '.join(patches_applied)}")
        
        return {
            "success": True,
            "mod": mod_name,
            "patches": patches_applied,
            "patched": len(patches_applied) > 0
        }
    
    def auto_patch_all(self) -> Dict:
        """Automatically patch all mods for compatibility"""
        if not os.path.isdir(self.mods_dir):
            return {"status": "error", "message": "Mods directory not found"}
        
        results = {
            "status": "success",
            "patched": 0,
            "skipped": 0,
            "errors": 0,
            "details": []
        }
        
        for filename in os.listdir(self.mods_dir):
            if not filename.endswith('.jar'):
                continue
            
            marker_path = os.path.join(self.mods_dir, f"{filename}.patched")
            if os.path.exists(marker_path):
                results["skipped"] += 1
                continue
            
            try:
                patch_result = self.auto_patch_mod(filename)
                if patch_result.get("patched"):
                    results["patched"] += 1
                    results["details"].append(f"Patched {filename}")
                else:
                    results["skipped"] += 1
            except Exception as e:
                results["errors"] += 1
                results["details"].append(f"Error patching {filename}: {str(e)}")
        
        return results


class ModCompatibilityManager:
    """High-level compatibility management"""
    
    def __init__(self, mods_dir: str, mc_version: str):
        self.mods_dir = mods_dir
        self.mc_version = mc_version
        self.patcher = ModPatcher(mods_dir, mc_version)
    
    def full_compatibility_pass(self) -> Dict:
        """Run a full compatibility optimization pass"""
        results = {
            "status": "success",
            "mods_analyzed": 0,
            "patched": 0,
            "conflicts_resolved": 0,
            "details": []
        }
        
        if not os.path.isdir(self.mods_dir):
            return {"status": "error", "message": "Mods directory not found"}
        
        mods = [f for f in os.listdir(self.mods_dir) if f.endswith('.jar')]
        results["mods_analyzed"] = len(mods)
        
        patch_results = self.patcher.auto_patch_all()
        results["patched"] = patch_results.get("patched", 0)
        results["details"].extend(patch_results.get("details", []))
        
        return results
    
    def analyze_mod_pack(self) -> Dict:
        """Analyze the mod pack for compatibility issues"""
        if not os.path.isdir(self.mods_dir):
            return {"status": "error", "message": "Mods directory not found"}
        
        mods = [f for f in os.listdir(self.mods_dir) if f.endswith('.jar')]
        
        analysis = {
            "status": "success",
            "total_mods": len(mods),
            "mods_with_mixins": 0,
            "high_risk_mods": [],
            "recommendations": []
        }
        
        for mod in mods:
            risk = self.patcher.detect_conflict_risk(mod)
            if risk.get("mixin_configs", 0) > 0:
                analysis["mods_with_mixins"] += 1
            if risk.get("risk_level") == "high":
                analysis["high_risk_mods"].append(mod)
        
        if analysis["mods_with_mixins"] > 10:
            analysis["recommendations"].append("Consider reducing number of core mixin mods")
        
        if analysis["high_risk_mods"]:
            analysis["recommendations"].append(f"Review high-risk mods: {', '.join(analysis['high_risk_mods'][:5])}")
        
        return analysis
