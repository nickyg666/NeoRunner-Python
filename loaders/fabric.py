"""Fabric modloader implementation"""
import os
import re
from loaders.base import LoaderBase


class FabricLoader(LoaderBase):
    """Fabric-specific server launcher and management"""
    
    def prepare_environment(self):
        """Setup Fabric server environment"""
        self.log_message("LOADER_FABRIC", f"Preparing {self.get_loader_display_name()} environment ({self.mc_version})")
        
        self._setup_jvm_args()
        self._setup_server_properties()
        self._setup_eula()
        
        self.log_message("LOADER_FABRIC", "Environment ready")
    
    def _setup_jvm_args(self):
        jvm_file = os.path.join(self.cwd, "user_jvm_args.txt")
        if os.path.exists(jvm_file):
            return
        
        with open(jvm_file, 'w') as f:
            f.write("-Xmx6G\n-Xms4G\n")
    
    def _setup_server_properties(self):
        props_file = os.path.join(self.cwd, "server.properties")
        
        properties = {
            "enable-rcon": "true",
            "rcon.password": self.cfg.get("rcon_pass", "changeme"),
            "rcon.port": str(self.cfg.get("rcon_port", 25575)),
            "server-port": str(self.cfg.get("server_port", 1234)),
            "motd": "NeoRunner - Fabric Server",
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
        """Build Fabric launch command"""
        jar_file = os.path.join(self.cwd, self.cfg.get("server_jar", "fabric.jar"))
        java_cmd = [
            "java",
            "@user_jvm_args.txt",
            "-jar", jar_file,
            "nogui"
        ]
        return java_cmd
    
    def detect_crash_reason(self, log_output):
        """Parse Fabric crash logs"""
        log_text = log_output.lower() if isinstance(log_output, str) else ""
        
        if "missing" in log_text:
            match = re.search(r"(\w+)(?:\s+mod|\s+dependency)?", log_text)
            if match:
                return {
                    "type": "missing_dep",
                    "dep": match.group(1),
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
