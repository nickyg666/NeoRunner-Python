"""Forge modloader implementation"""
import os
import re
from loaders.base import LoaderBase


class ForgeLoader(LoaderBase):
    """Forge-specific server launcher and management"""
    
    def prepare_environment(self):
        """Setup Forge server environment"""
        self.log_message("LOADER_FORGE", f"Preparing {self.get_loader_display_name()} environment ({self.mc_version})")
        
        self._setup_jvm_args()
        self._setup_server_properties()
        self._setup_eula()
        
        self.log_message("LOADER_FORGE", "Environment ready")
    
    def _setup_jvm_args(self):
        """Create user_jvm_args.txt"""
        jvm_file = os.path.join(self.cwd, "user_jvm_args.txt")
        if os.path.exists(jvm_file):
            return
        
        jvm_args = """-Xmx6G
-Xms4G
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200
"""
        with open(jvm_file, 'w') as f:
            f.write(jvm_args)
    
    def _setup_server_properties(self):
        """Setup server.properties"""
        props_file = os.path.join(self.cwd, "server.properties")
        
        properties = {
            "enable-rcon": "true",
            "rcon.password": self.cfg.get("rcon_pass", "changeme"),
            "rcon.port": str(self.cfg.get("rcon_port", 25575)),
            "server-port": str(self.cfg.get("server_port", 1234)),
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
            except:
                pass
            properties.update(existing)
        
        with open(props_file, 'w') as f:
            for k, v in sorted(properties.items()):
                f.write(f"{k}={v}\n")
    
    def _setup_eula(self):
        eula_file = os.path.join(self.cwd, "eula.txt")
        if not os.path.exists(eula_file):
            with open(eula_file, 'w') as f:
                f.write("eula=true\n")
    
    def build_java_command(self):
        """Build Forge launch command - simpler than NeoForge"""
        jar_file = os.path.join(self.cwd, self.cfg.get("server_jar", "forge.jar"))
        java_cmd = [
            "java",
            "@user_jvm_args.txt",
            "-jar", jar_file,
            "nogui"
        ]
        return java_cmd
    
    def detect_crash_reason(self, log_output):
        """Parse Forge crash logs"""
        log_text = log_output.lower() if isinstance(log_output, str) else ""
        
        # Missing mod dependency
        if "requires" in log_text and "not found" in log_text:
            match = re.search(r"(\w+)\s+requires?\s+(\w+)", log_text)
            if match:
                return {
                    "type": "missing_dep",
                    "dep": match.group(2),
                    "message": log_text[:200]
                }
        
        if "error" in log_text:
            return {
                "type": "mod_error",
                "message": log_text[:200]
            }
        
        return {
            "type": "unknown",
            "message": log_text[:200]
        }
