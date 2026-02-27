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
        
        # Get memory settings from config
        xmx = self.cfg.get("xmx", "6G")
        xms = self.cfg.get("xms", "4G")
        
        # Always regenerate to pick up config changes
        with open(jvm_file, 'w') as f:
            f.write(f"-Xmx{xmx}\n-Xms{xms}\n")
    
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
        MOD_ID = r'[\w.\-]+'
        
        # Fabric-specific missing dependency patterns
        missing_patterns = [
            # "Mod X requires Y" / "requires any version of Y"
            (r"requires?\s+(?:any\s+version\s+of\s+)?(" + MOD_ID + r")", 1),
            # "Unmet dependency: X"
            (r"unmet\s+dependency[:\s]+(" + MOD_ID + r")", 1),
            # "missing mod: X" / "missing dependency: X"
            (r"missing\s+(?:mod|dependency)[:\s]+(" + MOD_ID + r")", 1),
            # Fabric loader: "Resolution failed for X"
            (r"resolution\s+failed\s+for\s+(" + MOD_ID + r")", 1),
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
        
        if "error" in log_text and any(kw in log_text for kw in ["fabric", "loader", "modloading"]):
            return {
                "type": "mod_error",
                "message": log_text[:500]
            }
        
        return {
            "type": "unknown",
            "message": log_text[:500]
        }
