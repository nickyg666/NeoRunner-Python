"""Base loader abstraction for Minecraft server modloaders"""
from abc import ABC, abstractmethod
import os
import json


class LoaderBase(ABC):
    """Abstract base class for modloader implementations"""
    
    def __init__(self, cfg, cwd="/home/services"):
        self.cfg = cfg
        self.cwd = cwd
        self.loader_name = cfg.get("loader", "unknown").lower()
        self.mc_version = cfg.get("mc_version", "1.21.11")
        self.mods_dir = os.path.join(cwd, cfg.get("mods_dir", "mods"))
        
    @abstractmethod
    def prepare_environment(self):
        """Setup server environment (EULA, server.properties, @args files, etc)"""
        pass
    
    @abstractmethod
    def build_java_command(self):
        """Build Java command to launch server
        Returns: list like ['java', '@user_jvm_args.txt', '@loader_args.txt', 'nogui']
        """
        pass
    
    @abstractmethod
    def detect_crash_reason(self, log_output):
        """Parse server output/error to detect crash cause
        Returns: {
            'type': 'missing_dep' | 'mod_error' | 'version_mismatch' | 'unknown',
            'dep': 'modname' (if type=missing_dep),
            'message': 'full error message'
        }
        """
        pass
    
    def log_message(self, tag, msg):
        """Consistent logging format"""
        import time
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} | [{tag}] {msg}")
    
    def get_loader_display_name(self):
        """Return: NeoForge | Forge | Fabric"""
        return {
            "neoforge": "NeoForge",
            "forge": "Forge",
            "fabric": "Fabric"
        }.get(self.loader_name, self.loader_name.title())
