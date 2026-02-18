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
        """Parse NeoForge crash logs for common issues"""
        log_text = log_output.lower() if isinstance(log_output, str) else ""
        
        # Check for missing mod dependency
        # NeoForge/FML patterns: mod names can contain hyphens, underscores, dots
        MOD_ID = r'[\w.\-]+'
        missing_patterns = [
            # "mod X requires Y Z or above"
            (r"mod\s+(" + MOD_ID + r")\s+requires?\s+(" + MOD_ID + r")", 2),
            # "missing or unsupported mandatory dependencies: X"
            (r"missing\s+(?:or\s+unsupported\s+)?(?:mandatory\s+)?dependenc(?:y|ies)[:\s]+(" + MOD_ID + r")", 1),
            # "Mod X requires Y"
            (r"requires?\s+(" + MOD_ID + r")\s+(?:[0-9.]+|or\s+above|but)", 1),
            # "could not find required mod: X" / "could not find X"
            (r"could\s+not\s+find\s+(?:required\s+mod[:\s]+)?(" + MOD_ID + r")", 1),
            # "Failure message: Mod X requires Y"
            (r"failure\s+message:\s+mod\s+" + MOD_ID + r"\s+requires?\s+(" + MOD_ID + r")", 1),
            # Generic "missing dependency: X"
            (r"missing\s+dependency[:\s]+(" + MOD_ID + r")", 1),
        ]
        
        for pattern, dep_group in missing_patterns:
            match = re.search(pattern, log_text)
            if match:
                dep_name = match.group(dep_group)
                return {
                    "type": "missing_dep",
                    "dep": dep_name,
                    "message": log_text[:500]
                }
        
        # Check for mod loading errors (FML/NeoForge specific)
        if any(kw in log_text for kw in ["fml", "neoforge", "modloading"]) and "error" in log_text:
            return {
                "type": "mod_error",
                "message": log_text[:500]
            }
        
        # Check for version mismatch
        if "version" in log_text and ("mismatch" in log_text or "incompatible" in log_text):
            return {
                "type": "version_mismatch",
                "message": log_text[:500]
            }
        
        return {
            "type": "unknown",
            "message": log_text[:500]
        }
