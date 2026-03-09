"""Base loader abstraction for Minecraft server modloaders."""

from __future__ import annotations

from abc import ABC, abstractmethod
import os
import logging
from pathlib import Path
from typing import Dict, Optional, List, Union, Any

from ..constants import CWD

log = logging.getLogger(__name__)


def _get_cfg_value(cfg: Union[Any, dict], key: str, default: Any = None) -> Any:
    """Get config value from either object or dict."""
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default) or default


class LoaderBase(ABC):
    """Abstract base class for modloader implementations."""
    
    def __init__(self, cfg: Any, cwd: Optional[Path] = None):
        self.cfg = cfg
        self.cwd = cwd or CWD
        self.loader_name = _get_cfg_value(cfg, "loader", "unknown").lower()
        self.mc_version = _get_cfg_value(cfg, "mc_version", "1.21.11")
        mods_dir = _get_cfg_value(cfg, "mods_dir", "mods")
        self.mods_dir = self.cwd / mods_dir if isinstance(self.cwd, Path) else os.path.join(self.cwd, mods_dir)
    
    @abstractmethod
    def prepare_environment(self) -> None:
        """Setup server environment (EULA, server.properties, @args files, etc)."""
    
    @abstractmethod
    def build_java_command(self) -> List[str]:
        """Build Java command to launch server.
        
        Returns:
            List like ['java', '@user_jvm_args.txt', '@loader_args.txt', 'nogui']
        """
    
    @abstractmethod
    def detect_crash_reason(self, log_output: str) -> Dict[str, Any]:
        """Parse server output/error to detect crash cause.
        
        Returns:
            Dictionary with keys:
            - type: 'missing_dep' | 'mod_error' | 'mod_conflict' | 'version_mismatch' | 'benign_mixin_warning' | 'unknown'
            - dep: name of missing dependency (for missing_dep)
            - culprit: mod ID that caused the crash (if identifiable)
            - culprits: list of all involved mod IDs
            - message: relevant portion of the crash log
        """
    
    def get_loader_display_name(self) -> str:
        """Return display name for the loader."""
        names = {
            "neoforge": "NeoForge",
            "forge": "Forge",
            "fabric": "Fabric"
        }
        return names.get(self.loader_name, self.loader_name.title())


def get_loader(cfg: Any, cwd: Optional[Path] = None) -> LoaderBase:
    """Factory function to get the appropriate loader instance."""
    from .neoforge import NeoForgeLoader
    from .forge import ForgeLoader
    from .fabric import FabricLoader
    
    loader_name = _get_cfg_value(cfg, "loader", "neoforge").lower()
    
    loaders: Dict[str, type] = {
        "neoforge": NeoForgeLoader,
        "forge": ForgeLoader,
        "fabric": FabricLoader,
    }
    
    cls = loaders.get(loader_name)
    if cls is None:
        raise ValueError(f"Unknown loader: {loader_name}")
    
    return cls(cfg, cwd)


__all__ = [
    "LoaderBase",
    "get_loader",
    "NeoForgeLoader",
    "ForgeLoader", 
    "FabricLoader",
]
