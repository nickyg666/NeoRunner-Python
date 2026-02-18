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
        missing_patterns = [
            r"mod\s+(\w+)\s+requires?\s+(\w+)\s+([0-9.]+)\s+or\s+above",
            r"(\w+)\s+requires?\s+(\w+)\s+([0-9.]+)",
            r"missing\s+dependency:\s+(\w+)",
            r"could not find\s+(\w+)"
        ]
        
        for pattern in missing_patterns:
            match = re.search(pattern, log_text)
            if match:
                dep_name = match.group(1) if match.groups() else "unknown"
                return {
                    "type": "missing_dep",
                    "dep": dep_name,
                    "message": log_text[:200]
                }
        
        # Check for mod loading errors
        if "fml" in log_text and "error" in log_text:
            return {
                "type": "mod_error",
                "message": log_text[:200]
            }
        
        # Check for version mismatch
        if "version" in log_text and "mismatch" in log_text:
            return {
                "type": "version_mismatch",
                "message": log_text[:200]
            }
        
        return {
            "type": "unknown",
            "message": log_text[:200]
        }
