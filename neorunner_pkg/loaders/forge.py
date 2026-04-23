"""Forge modloader implementation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from . import LoaderBase, _get_cfg_value
from ..log import log_event


class ForgeLoader(LoaderBase):
    """Forge-specific server launcher and management."""
    
    def prepare_environment(self) -> None:
        """Setup Forge server environment."""
        log_event("LOADER_FORGE", f"Preparing {self.get_loader_display_name()} environment ({self.mc_version})")
        
        self._setup_jvm_args()
        self._setup_server_properties()
        self._setup_eula()
        
        log_event("LOADER_FORGE", "Environment ready")
    
    def _validate_jvm_args(self, jvm_file: str) -> bool:
        """Validate user_jvm_args.txt contains valid JVM args, not bash echo."""
        if not os.path.exists(jvm_file):
            return False
        try:
            with open(jvm_file, 'r') as f:
                content = f.read()
            if 'echo ' in content or 'Dashboard' in content or '#!/bin/bash' in content:
                log_event("WARN", f"user_jvm_args.txt corrupted (contains bash code), regenerating...")
                return False
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
-XX:G1NewCollectionPercentage=30
-XX:G1MaxNewCollectionLength=16777216
-XX:+PerfDisableSharedMem
-XX:+AlwaysPreTouch
-XX:+UseLargePagesInMetaspace
-XX:MaxGCPauseMillis=100
-XX:-OmitStackTraceInFastThrow
-XX:+ExplicitGCInvokesConcurrent
-Djava.net.preferIPv4Stack=true
-Dforge.logging.console.level=DEBUG
-Dfml.query.verbose=true
"""
        with open(jvm_file, 'w') as f:
            f.write(jvm_args)
    
    def _setup_server_properties(self) -> None:
        """Setup server.properties."""
        props_file = self.cwd / "server.properties" if isinstance(self.cwd, Path) else os.path.join(self.cwd, "server.properties")
        
        properties = {
            "enable-rcon": "true",
            "rcon.password": _get_cfg_value(self.cfg, "rcon_pass", "changeme"),
            "rcon.port": str(_get_cfg_value(self.cfg, "rcon_port", 25575)),
            "server-port": str(_get_cfg_value(self.cfg, "server_port", 1234)),
            "motd": "NeoRunner - Forge Server",
            "online-mode": "false"
        }
        
        if os.path.exists(props_file):
            existing = {}
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
        """Build Forge launch command."""
        jar_file = self.cwd / _get_cfg_value(self.cfg, "server_jar", "forge.jar") if isinstance(self.cwd, Path) else os.path.join(self.cwd, _get_cfg_value(self.cfg, "server_jar", "forge.jar"))
        java_cmd = [
            "java",
            "@user_jvm_args.txt",
            "-jar", str(jar_file),
            "nogui"
        ]
        return java_cmd
    
    def detect_crash_reason(self, log_output: str) -> Dict[str, Any]:
        """Parse Forge crash logs."""
        log_text = log_output.lower() if isinstance(log_output, str) else ""
        MOD_ID = r'[\w.\-]+'
        
        missing_patterns = [
            (r"requires?\s+(" + MOD_ID + r")\s+(?:but|not\s+found|[0-9.])", 1),
            (r"missing\s+(?:mandatory\s+)?dependenc(?:y|ies)[:\s]+(" + MOD_ID + r")", 1),
            (r"could\s+not\s+find\s+(?:required\s+mod[:\s]+)?(" + MOD_ID + r")", 1),
        ]
        
        for pattern, dep_group in missing_patterns:
            match = re.search(pattern, log_text)
            if match:
                return {
                    "type": "missing_dep",
                    "dep": match.group(dep_group),
                    "culprit": None,
                    "culprits": [],
                    "message": log_text[:500]
                }
        
        if "version" in log_text and ("mismatch" in log_text or "incompatible" in log_text):
            return {
                "type": "version_mismatch",
                "culprit": None,
                "culprits": [],
                "message": log_text[:500]
            }
        
        if "error" in log_text and any(kw in log_text for kw in ["fml", "forge", "modloading"]):
            return {
                "type": "mod_error",
                "culprit": None,
                "culprits": [],
                "message": log_text[:500]
            }
        
        return {
            "type": "unknown",
            "culprit": None,
            "culprits": [],
            "message": log_text[:500]
        }
