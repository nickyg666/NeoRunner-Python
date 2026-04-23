"""NeoForge modloader implementation."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any

from . import LoaderBase, _get_cfg_value
from ..log import log_event


class NeoForgeLoader(LoaderBase):
    """NeoForge-specific server launcher and management."""
    
    def prepare_environment(self) -> None:
        """Setup NeoForge server environment."""
        log_event("LOADER_NEOFORGE", f"Preparing {self.get_loader_display_name()} environment ({self.mc_version})")
        
        self._setup_jvm_args()
        self._setup_server_properties()
        self._setup_eula()
        
        log_event("LOADER_NEOFORGE", "Environment ready (using @args files)")
    
    def _validate_jvm_args(self, jvm_file: str) -> bool:
        """Validate user_jvm_args.txt contains valid JVM args, not bash echo."""
        if not os.path.exists(jvm_file):
            return False
        try:
            with open(jvm_file, 'r') as f:
                content = f.read()
            # Check for corruption patterns
            if 'echo ' in content or 'Dashboard' in content or '#!/bin/bash' in content:
                log_event("WARN", f"user_jvm_args.txt corrupted (contains bash code), regenerating...")
                return False
            # Ensure it starts with -Xmx
            lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
            if not lines or not lines[0].startswith('-Xm'):
                log_event("WARN", "user_jvm_args.txt invalid format, regenerating...")
                return False
            return True
        except Exception:
            return False
    
    def _setup_jvm_args(self) -> None:
        """Create user_jvm_args.txt with memory and performance settings."""
        jvm_file = self.cwd / "user_jvm_args.txt" if isinstance(self.cwd, Path) else os.path.join(self.cwd, "user_jvm_args.txt")
        
        # Validate existing file, regenerate if corrupted
        if os.path.exists(jvm_file) and not self._validate_jvm_args(jvm_file):
            os.remove(jvm_file)
        
        xmx = _get_cfg_value(self.cfg, "xmx", "6G")
        xms = _get_cfg_value(self.cfg, "xms", "4G")
        
        jvm_args = f"""-Xmx{xmx}
-Xms{xms}
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200
-XX:+ParallelRefProcEnabled
-XX:+UnlockExperimentalVMOptions
-XX:+AlwaysPreTouch
-XX:-OmitStackTraceInFastThrow
-XX:+ExplicitGCInvokesConcurrent
-Djava.net.preferIPv4Stack=true
-Dusemtl=false
-DdisableAsyncChunkLoading=true
-Dneoforge.logging.debugNetwork=true
-Dforge.logging.console.level=DEBUG
"""
        with open(jvm_file, 'w') as f:
            f.write(jvm_args)
    
    def _setup_server_properties(self) -> None:
        """Setup server.properties with RCON and basic settings."""
        props_file = self.cwd / "server.properties" if isinstance(self.cwd, Path) else os.path.join(self.cwd, "server.properties")
        
        view_dist = _get_cfg_value(self.cfg, "view_distance", "10")
        sim_dist = _get_cfg_value(self.cfg, "simulation_distance", "8")
        max_tick = _get_cfg_value(self.cfg, "max_tick_time", "120000")
        
        properties = {
            "enable-rcon": "true",
            "rcon.password": _get_cfg_value(self.cfg, "rcon_pass", "changeme"),
            "rcon.port": str(_get_cfg_value(self.cfg, "rcon_port", 25575)),
            "server-port": str(_get_cfg_value(self.cfg, "server_port", 1234)),
            "motd": "NeoRunner - NeoForge Server",
            "level-name": "world",
            "gamemode": "survival",
            "difficulty": "normal",
            "max-players": "20",
            "online-mode": "false",
            "pvp": "true",
            "allow-flight": "true",
            "network-compression-threshold": "256",
            "max-tick-time": max_tick,
            "view-distance": view_dist,
            "simulation-distance": sim_dist,
        }
        
        existing = {}
        if os.path.exists(props_file):
            try:
                with open(props_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if '=' in line:
                                k, v = line.split('=', 1)
                                existing[k] = v
            except Exception:
                pass
            properties.update(existing)
        
        if not existing.get("enable-rcon"):
            properties["enable-rcon"] = "true"
            properties["rcon.password"] = _get_cfg_value(self.cfg, "rcon_pass", "changeme")
            properties["rcon.port"] = str(_get_cfg_value(self.cfg, "rcon_port", 25575))
        
        with open(props_file, 'w') as f:
            for k, v in sorted(properties.items()):
                f.write(f"{k}={v}\n")
    
    def _setup_eula(self) -> None:
        """Create eula.txt."""
        eula_file = self.cwd / "eula.txt" if isinstance(self.cwd, Path) else os.path.join(self.cwd, "eula.txt")
        if not os.path.exists(eula_file):
            with open(eula_file, 'w') as f:
                f.write("eula=true\n")
    
    def build_java_command(self) -> List[str]:
        """Build NeoForge launch command."""
        nf_ver = self._get_neoforge_version()
        
        # Run NeoForge installer --install to set up all files (ALL versions)
        log_event("LOADER_NEOFORGE", "Running installer to extract files...")
        jar = f"libraries/net/neoforged/neoforge/{nf_ver}/neoforge-{nf_ver}-universal.jar"
        
        try:
            subprocess.run(
                ["java", "-jar", jar, "--install", "."],
                capture_output=True,
                timeout=180,
                cwd=str(self.cwd)
            )
        except Exception as e:
            log_event("LOADER_NEOFORGE", f"Installer note: {e}")
        
        # Direct -jar launch (works after installer runs)
        cwd_str = str(self.cwd) if hasattr(self.cwd, '__fspath__') else str(self.cwd)
        jar = f"libraries/net/neoforged/neoforge/{nf_ver}/neoforge-{nf_ver}-universal.jar"
        jar_path = os.path.join(cwd_str, jar)
        
        java_cmd = [
            "java",
            "@user_jvm_args.txt",
            "-jar",
            jar_path,
            "nogui"
        ]
        return java_cmd
    
    def _get_neoforge_version(self) -> str:
        """Get NeoForge version - prefer local libraries, fallback to dynamic fetch."""
        lib_path = self.cwd / "libraries" / "net" / "neoforged" / "neoforge" if isinstance(self.cwd, Path) else os.path.join(self.cwd, "libraries/net/neoforged/neoforge")
        if os.path.exists(lib_path):
            versions = [d for d in os.listdir(lib_path) if os.path.isdir(os.path.join(lib_path, d))]
            if versions:
                latest = sorted(versions)[-1]
                jar_path = os.path.join(lib_path, latest, f"neoforge-{latest}-universal.jar")
                if os.path.exists(jar_path):
                    return latest
        
        # Fallback: fetch dynamically from Maven
        from ..version import get_latest_for_loader
        latest = get_latest_for_loader("neoforge")
        if latest:
            return latest.split("-")[0] if "-" in latest else latest
        return None
    
    def detect_crash_reason(self, log_output: str) -> Dict[str, Any]:
        """Parse NeoForge crash logs for common issues.
        
        Returns dict with:
            - type: 'missing_dep', 'mod_error', 'mod_conflict', 'version_mismatch', 'benign_mixin_warning', 'unknown'
            - dep: name of missing dependency (for missing_dep)
            - culprit: mod ID that caused the crash (if identifiable)
            - culprits: list of all involved mod IDs (for conflicts)
            - message: relevant portion of the crash log
        """
        log_text = log_output if isinstance(log_output, str) else ""
        log_lower = log_text.lower()
        
        crash_section = log_text
        crash_marker = log_text.find("---- Minecraft Crash Report ----")
        if crash_marker >= 0:
            crash_section = log_text[crash_marker:]
        
        fml_error = ""
        for marker in ["net.neoforged.fml.ModLoadingException", 
                        "LoadingExceptionModCrash",
                        "FML detected errors during loading"]:
            idx = log_lower.find(marker.lower())
            if idx >= 0:
                fml_error = log_text[max(0, idx - 200):idx + 1000]
                break
        
        relevant_log = fml_error or crash_section[:2000] or log_text[-2000:]
        
        MOD_ID = r'[\w.\-]+'
        
        bad_jar_match = re.search(r'file\s+mods/(\S+\.jar)\s+is\s+not\s+a\s+jar\s+file', log_lower)
        if bad_jar_match:
            bad_file = bad_jar_match.group(1)
            slug = re.sub(r'[-_]?\d.*$', '', bad_file.replace('.jar', '')).lower()
            return {
                "type": "mod_error",
                "culprit": slug or bad_file,
                "culprits": [slug or bad_file],
                "message": f"File mods/{bad_file} is not a valid JAR",
                "bad_file": bad_file
            }
        
        mixin_client_match = re.search(r"mixintransformererror|MixinPreProcessorException.*from\s+mod\s+(" + MOD_ID + r")", log_text, re.IGNORECASE)
        if mixin_client_match or (re.search(r"error\s+loading\s+class:.*client", log_lower) and re.search(r"from\s+mod\s+(" + MOD_ID + r")", log_text)):
            from_mod_match = re.search(r"from\s+mod\s+(" + MOD_ID + r")", log_text)
            culprit_mod = from_mod_match.group(1).lower() if from_mod_match else None
            culprit_file = None
            if culprit_mod:
                jar_pattern = rf"mods/([^\s/]*{re.escape(culprit_mod)}[^\s/]*\.jar)"
                jar_match = re.search(jar_pattern, log_lower)
                if jar_match:
                    culprit_file = jar_match.group(1)
            return {
                "type": "mod_error",
                "subtype": "client_only",
                "culprit": culprit_mod,
                "culprits": [culprit_mod] if culprit_mod else [],
                "message": f"Client-only mod mixin crash: {culprit_mod or 'unknown'}",
                "bad_file": culprit_file
            }
        
        client_class_patterns = [
            r"noclassdeffounderror:\s+net/minecraft/client/",
            r"classnotfoundexception:\s+net\.minecraft\.client\.",
            r"noclassdeffounderror:\s+com/mojang/blaze3d/",
            r"classnotfoundexception:\s+com\.mojang\.blaze3d\.",
            r"noclassdeffounderror:\s+net/minecraft/client/sounds/",
        ]
        
        all_client_crashes = []
        for cp in client_class_patterns:
            if re.search(cp, log_lower):
                fail_patterns = [
                    r"failed\s+to\s+create\s+mod\s+instance\.\s*modid:\s*(" + MOD_ID + r")",
                    r"modid:\s*(" + MOD_ID + r")[^\n]*noclassdeffounderror",
                    r"\[(" + MOD_ID + r")\][^\n]*failed",
                ]
                for fp in fail_patterns:
                    for match in re.finditer(fp, log_lower):
                        mod_id = match.group(1)
                        if mod_id not in all_client_crashes:
                            all_client_crashes.append(mod_id)
                
                for match in re.finditer(r"mod\s+file:\s+\S*mods/(\S+\.jar)", log_lower):
                    culprit_file = match.group(1)
                    culprit_mod = re.sub(r'[-_]?\d.*$', '', culprit_file.replace('.jar', '')).lower()
                    if culprit_mod and culprit_mod not in all_client_crashes:
                        all_client_crashes.append(culprit_mod)
                
                for match in re.finditer(r"from\s+mod\s+(" + MOD_ID + r")", log_text):
                    mod_id = match.group(1).lower()
                    if mod_id not in all_client_crashes:
                        all_client_crashes.append(mod_id)
                
                break
        
        if all_client_crashes:
            bad_files = []
            for culprit_mod in all_client_crashes:
                jar_pattern = rf"mods/([^\s/]*{re.escape(culprit_mod)}[^\s/]*\.jar)"
                jar_match = re.search(jar_pattern, log_lower)
                if jar_match:
                    bad_files.append(jar_match.group(1))
            
            return {
                "type": "mod_error",
                "subtype": "client_only",
                "culprit": all_client_crashes[0] if all_client_crashes else None,
                "culprits": all_client_crashes,
                "message": f"Client-only mod crash: {', '.join(all_client_crashes)} reference client classes",
                "bad_file": bad_files[0] if bad_files else None,
                "bad_files": bad_files
            }
        
        missing_patterns = [
            (r"mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 1, 2),
            (r"failure\s+message:\s+mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 1, 2),
            (r"missing\s+(?:or\s+unsupported\s+)?(?:mandatory\s+)?dependenc(?:y|ies)[:\s]+(" + MOD_ID + r")", None, 1),
            (r"could\s+not\s+find\s+(?:required\s+mod[:\s]+)?(" + MOD_ID + r")", None, 1),
            (r"missing\s+dependency[:\s]+(" + MOD_ID + r")", None, 1),
            (r"mod\s+file\s+\S+\s+needs\s+(" + MOD_ID + r")", None, 1),
        ]
        
        for pattern, culprit_group, dep_group in missing_patterns:
            match = re.search(pattern, log_lower)
            if match:
                dep_name = match.group(dep_group)
                culprit = match.group(culprit_group) if culprit_group else None
                return {
                    "type": "missing_dep",
                    "dep": dep_name,
                    "culprit": culprit,
                    "culprits": [culprit] if culprit else [],
                    "message": relevant_log[:1000]
                }
        
        def _extract_mod_id_from_mixin_path(path_or_id):
            if not path_or_id:
                return None
            s = path_or_id.lower().strip()
            if '.' not in s:
                return s
            parts = s.split('.')
            skip_words = {'mixin', 'mixins', 'common', 'client', 'server', 'api', 'impl', 'core', 'internal', 'util', 'handler', 'access', 'wrapper', 'hook', 'patch', 'transform', 'chunk', 'world', 'entity', 'block', 'item', 'screen', 'container', 'packet', 'network', 'data', 'config'}
            mixin_idx = -1
            for i, part in enumerate(parts):
                if 'mixin' in part:
                    mixin_idx = i
                    break
            if mixin_idx > 0:
                for i in range(mixin_idx - 1, -1, -1):
                    part = parts[i]
                    if part in skip_words or part in ('dev', 'com', 'org', 'net', 'io', 'me', 'xyz'):
                        continue
                    if len(part) >= 3:
                        return part
            for part in reversed(parts):
                if part in skip_words:
                    continue
                if len(part) >= 3 and not part.startswith('class') and not part.startswith('mixin'):
                    return part
            return parts[-1] if parts else s
        
        benign_mixin_match = re.search(
            r"overwrite\s+conflict\s+for\s+(\S+)\s+in\s+(\S+)\s+from\s+(?:mod\s+)?(" + MOD_ID + r")[\s,].*?"
            r"previously\s+(?:written|defined)\s+by\s+(.+?)\.?\s+Skipping\s+method\.?",
            log_text, re.IGNORECASE
        )
        if benign_mixin_match:
            return {
                "type": "benign_mixin_warning",
                "conflict_type": "mixin_overwrite_handled",
                "culprit": None,
                "culprits": [],
                "message": "Mixin overwrite warning (handled gracefully)"
            }
        
        conflict_patterns = [
            (r"duplicatemodsfoundexception.*?(\S+\.jar).*?(\S+\.jar)", "duplicate"),
            (r"duplicate\s+(?:registry\s+)?(?:key|entry|id)[:\s]+(" + MOD_ID + r"[:/]" + MOD_ID + r")", "registry"),
            (r"(" + MOD_ID + r"[:/]" + MOD_ID + r")\s+is\s+already\s+registered", "registry"),
            (r"mixin\s+apply\s+for\s+mod\s+(" + MOD_ID + r")\s+failed", "mixin_fail"),
            (r"mixinapplyerror.*?mod[:\s]+(" + MOD_ID + r")", "mixin_fail"),
            (r"mixintransformererror.*?from\s+mod\s+(" + MOD_ID + r")", "mixin_error"),
            (r"incompatible\s+mod(?:s)?\s+(?:set|found|detected)", "incompatible"),
            (r"(" + MOD_ID + r")\s+conflicts?\s+with\s+(" + MOD_ID + r")", "conflict"),
        ]
        
        for pattern, conflict_type in conflict_patterns:
            match = re.search(pattern, log_lower)
            if match:
                culprits = [g for g in match.groups() if g]
                if conflict_type == "registry" and culprits:
                    ns = culprits[0].split(":")[0] if ":" in culprits[0] else culprits[0].split("/")[0]
                    culprits = [ns]
                
                if conflict_type in ("mixin_fail", "mixin_error"):
                    culprits = [_extract_mod_id_from_mixin_path(c) for c in culprits]
                
                primary_culprit = culprits[-1] if culprits else None
                
                return {
                    "type": "mod_conflict",
                    "conflict_type": conflict_type,
                    "culprit": primary_culprit,
                    "culprits": culprits,
                    "message": relevant_log[:1000]
                }
        
        mod_error_patterns = [
            (r"error\s+loading\s+mod[:\s]+(" + MOD_ID + r")", 1),
            (r"mod\s+(" + MOD_ID + r")\s+has\s+crashed", 1),
            (r"exception\s+.*?mod[:\s]+(" + MOD_ID + r")", 1),
            (r"caused\s+by\s+mod[:\s]+(" + MOD_ID + r")", 1),
            (r"modloadingexception.*?(" + MOD_ID + r")", 1),
            (r"mod\s+\S+\s+\((" + MOD_ID + r")\)\s+encountered\s+an?\s+error", 1),
        ]
        
        for pattern, group in mod_error_patterns:
            match = re.search(pattern, log_lower)
            if match:
                culprit = match.group(group)
                if culprit not in ("minecraft", "neoforge", "fml", "forge", "java", "net"):
                    return {
                        "type": "mod_error",
                        "culprit": culprit,
                        "culprits": [culprit],
                        "message": relevant_log[:1000]
                    }
        
        if "exception" in log_lower or "error" in log_lower or "crash" in log_lower:
            stack_mods = re.findall(r"at\s+(?:com|net|dev|io|org)\.([\w]+)\.([\w]+)\.", log_lower)
            framework_pkgs = {"mojang", "minecraft", "neoforged", "neoforge", "cpw", "fml",
                              "google", "gson", "apache", "netty", "oshi", "slf4j", "log4j",
                              "java", "sun", "jdk", "spongepowered", "mixin"}
            mod_pkgs = [(a, m) for a, m in stack_mods if a not in framework_pkgs and m not in framework_pkgs]
            
            if mod_pkgs:
                author, modname = mod_pkgs[0]
                return {
                    "type": "mod_error",
                    "culprit": modname,
                    "culprits": [modname],
                    "message": relevant_log[:1000]
                }
        
        if any(kw in log_lower for kw in ["fml", "neoforge", "modloading"]) and "error" in log_lower:
            return {
                "type": "mod_error",
                "culprit": None,
                "culprits": [],
                "message": relevant_log[:1000]
            }
        
        if "version" in log_lower and ("mismatch" in log_lower or "incompatible" in log_lower):
            return {
                "type": "version_mismatch",
                "culprit": None,
                "culprits": [],
                "message": relevant_log[:1000]
            }
        
        return {
            "type": "unknown",
            "culprit": None,
            "culprits": [],
            "message": relevant_log[:1000]
        }
