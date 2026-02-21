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
        
        # Get memory settings from config
        xmx = self.cfg.get("xmx", "6G")
        xms = self.cfg.get("xms", "4G")
        
        # Always regenerate to pick up config changes
        jvm_args = f"""-Xmx{xmx}
-Xms{xms}
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
        MOD_ID = r'[\w.\-]+'
        
        # Missing mod dependency
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
                    "message": log_text[:500]
                }
        
        if "version" in log_text and ("mismatch" in log_text or "incompatible" in log_text):
            return {
                "type": "version_mismatch",
                "message": log_text[:500]
            }
        
        if "error" in log_text and any(kw in log_text for kw in ["fml", "forge", "modloading"]):
            return {
                "type": "mod_error",
                "message": log_text[:500]
            }
        
        return {
            "type": "unknown",
            "message": log_text[:500]
        }
