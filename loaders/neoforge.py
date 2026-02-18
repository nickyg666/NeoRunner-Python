"""NeoForge modloader implementation"""
import os
import re
from loaders.base import LoaderBase


class NeoForgeLoader(LoaderBase):
    """NeoForge-specific server launcher and management"""
    
    def prepare_environment(self):
        """Setup NeoForge server environment"""
        self.log_message("LOADER_NEOFORGE", f"Preparing {self.get_loader_display_name()} environment ({self.mc_version})")
        
        # NeoForge uses @args files
        self._setup_jvm_args()
        self._setup_server_properties()
        self._setup_eula()
        
        self.log_message("LOADER_NEOFORGE", "Environment ready (using @args files)")
    
    def _setup_jvm_args(self):
        """Create user_jvm_args.txt with memory settings"""
        jvm_file = os.path.join(self.cwd, "user_jvm_args.txt")
        
        if os.path.exists(jvm_file):
            return  # Don't overwrite
        
        jvm_args = """-Xmx6G
-Xms4G
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200
-XX:+ParallelRefProcEnabled
-XX:+UnlockExperimentalVMOptions
-XX:G1NewCollectionPercentage=30
-XX:G1MaxNewCollectionLength=16777216
-XX:+PerfDisableSharedMem
-XX:+AlwaysPreTouch
"""
        with open(jvm_file, 'w') as f:
            f.write(jvm_args)
    
    def _setup_server_properties(self):
        """Setup server.properties with RCON and basic settings"""
        props_file = os.path.join(self.cwd, "server.properties")
        
        properties = {
            "enable-rcon": "true",
            "rcon.password": self.cfg.get("rcon_pass", "changeme"),
            "rcon.port": str(self.cfg.get("rcon_port", 25575)),
            "server-port": str(self.cfg.get("server_port", 1234)),
            "motd": "NeoRunner - NeoForge Server",
            "level-name": "world",
            "gamemode": "survival",
            "difficulty": "normal",
            "max-players": "20",
            "online-mode": "false",
            "pvp": "true",
            "allow-flight": "true"
        }
        
        # Read existing if present
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
            except:
                pass
            properties.update(existing)
        
        # Only override RCON settings if not set
        if not existing.get("enable-rcon"):
            properties["enable-rcon"] = "true"
            properties["rcon.password"] = self.cfg.get("rcon_pass", "changeme")
            properties["rcon.port"] = str(self.cfg.get("rcon_port", 25575))
        
        # Write back
        with open(props_file, 'w') as f:
            for k, v in sorted(properties.items()):
                f.write(f"{k}={v}\n")
    
    def _setup_eula(self):
        """Create eula.txt"""
        eula_file = os.path.join(self.cwd, "eula.txt")
        if not os.path.exists(eula_file):
            with open(eula_file, 'w') as f:
                f.write("eula=true\n")
    
    def build_java_command(self):
        """Build NeoForge launch command"""
        # NeoForge uses @args files
        java_cmd = [
            "java",
            "@user_jvm_args.txt",
            f"@libraries/net/neoforged/neoforge/{self._get_neoforge_version()}/unix_args.txt",
            "nogui"
        ]
        return java_cmd
    
    def _get_neoforge_version(self):
        """Extract NeoForge version from libraries"""
        lib_path = os.path.join(self.cwd, "libraries/net/neoforged/neoforge")
        if os.path.exists(lib_path):
            versions = [d for d in os.listdir(lib_path) if os.path.isdir(os.path.join(lib_path, d))]
            if versions:
                return sorted(versions)[-1]  # Latest version
        return "21.11.38-beta"  # Fallback
    
    def detect_crash_reason(self, log_output):
        """Parse NeoForge crash logs for common issues.
        
        Returns dict with:
            type: 'missing_dep', 'mod_error', 'version_mismatch', 'unknown'
            dep: name of missing dependency (for missing_dep)
            culprit: mod ID that caused the crash (if identifiable)
            message: first 500 chars of relevant log
        """
        log_text = log_output.lower() if isinstance(log_output, str) else ""
        
        # Check for missing mod dependency
        # NeoForge/FML patterns: mod names can contain hyphens, underscores, dots
        MOD_ID = r'[\w.\-]+'
        missing_patterns = [
            # "mod X requires Y Z or above" — X is the culprit, Y is the missing dep
            (r"mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 1, 2),
            # "Failure message: Mod X requires Y" — X is culprit, Y is missing
            (r"failure\s+message:\s+mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 1, 2),
            # "missing or unsupported mandatory dependencies: X" — no culprit
            (r"missing\s+(?:or\s+unsupported\s+)?(?:mandatory\s+)?dependenc(?:y|ies)[:\s]+(" + MOD_ID + r")", None, 1),
            # "could not find required mod: X"
            (r"could\s+not\s+find\s+(?:required\s+mod[:\s]+)?(" + MOD_ID + r")", None, 1),
            # Generic "missing dependency: X"
            (r"missing\s+dependency[:\s]+(" + MOD_ID + r")", None, 1),
        ]
        
        for pattern, culprit_group, dep_group in missing_patterns:
            match = re.search(pattern, log_text)
            if match:
                dep_name = match.group(dep_group)
                culprit = match.group(culprit_group) if culprit_group else None
                return {
                    "type": "missing_dep",
                    "dep": dep_name,
                    "culprit": culprit,
                    "message": log_text[:500]
                }
        
        # Check for specific mod errors — try to extract the mod that crashed
        # Common NeoForge patterns:
        # "Exception caught during firing of event ... mod_id"
        # "Error loading mod: mod_id"
        # "Mod mod_id has crashed"
        mod_error_patterns = [
            (r"error\s+loading\s+mod[:\s]+(" + MOD_ID + r")", 1),
            (r"mod\s+(" + MOD_ID + r")\s+has\s+crashed", 1),
            (r"exception\s+.*?mod[:\s]+(" + MOD_ID + r")", 1),
            (r"caused\s+by\s+mod[:\s]+(" + MOD_ID + r")", 1),
        ]
        
        for pattern, group in mod_error_patterns:
            match = re.search(pattern, log_text)
            if match:
                return {
                    "type": "mod_error",
                    "culprit": match.group(group),
                    "message": log_text[:500]
                }
        
        # Generic mod loading error (no specific mod identified)
        if any(kw in log_text for kw in ["fml", "neoforge", "modloading"]) and "error" in log_text:
            return {
                "type": "mod_error",
                "culprit": None,
                "message": log_text[:500]
            }
        
        # Check for version mismatch
        if "version" in log_text and ("mismatch" in log_text or "incompatible" in log_text):
            return {
                "type": "version_mismatch",
                "culprit": None,
                "message": log_text[:500]
            }
        
        return {
            "type": "unknown",
            "culprit": None,
            "message": log_text[:500]
        }
