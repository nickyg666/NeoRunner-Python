"""Version management for NeoRunner - dynamic Minecraft version fetching."""

import json
import logging
import urllib.request
import urllib.parse
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MC_VERSION = "1.21.11"

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

VERSIONS_CACHE = CACHE_DIR / "mc_versions.json"


def get_latest_minecraft_version(force_refresh: bool = False) -> str:
    """Fetch latest Minecraft RELEASE version from Mojang."""
    if not force_refresh and VERSIONS_CACHE.exists():
        try:
            import time
            age = time.time() - VERSIONS_CACHE.stat().st_mtime
            if age < 3600:
                data = json.loads(VERSIONS_CACHE.read_text())
                return data.get("latest_release", DEFAULT_MC_VERSION)
        except Exception:
            pass
    
    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            # Find latest RELEASE (not snapshot)
            for v in data.get("versions", []):
                if v.get("type") == "release":
                    latest = v.get("id", DEFAULT_MC_VERSION)
                    break
            else:
                latest = data.get("latest", {}).get("release", DEFAULT_MC_VERSION)
            
            cache_data = {"latest_release": latest, "versions": [v["id"] for v in data.get("versions", [])]}
            VERSIONS_CACHE.write_text(json.dumps(cache_data, indent=2))
            
            return latest
    except Exception as e:
        logger.warning(f"Failed to fetch latest MC version: {e}")
        return DEFAULT_MC_VERSION


def get_all_minecraft_versions() -> List[str]:
    """Get all available Minecraft versions."""
    if VERSIONS_CACHE.exists():
        try:
            data = json.loads(VERSIONS_CACHE.read_text())
            return data.get("versions", [DEFAULT_MC_VERSION])
        except Exception:
            pass
    
    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            versions = [v["id"] for v in data.get("versions", [])]
            
            cache_data = {"latest_release": get_latest_minecraft_version(), "versions": versions}
            VERSIONS_CACHE.write_text(json.dumps(cache_data, indent=2))
            
            return versions
    except Exception:
        return [DEFAULT_MC_VERSION]


def get_latest_for_loader(loader: str = "neoforge") -> Optional[str]:
    """Get latest loader version for current MC."""
    mc_version = get_latest_minecraft_version()
    
    if loader.lower() == "neoforge":
        return _get_latest_neoforge(mc_version)
    elif loader.lower() == "fabric":
        return _get_latest_fabric(mc_version)
    return _get_latest_neoforge(mc_version)


def _get_latest_neoforge(mc_version: str) -> Optional[str]:
    """Fetch latest NeoForge version."""
    try:
        mc_prefix = mc_version.replace(".", "")[:4]
        
        url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            versions = data.get("versions", [])
            
            for v in reversed(versions):
                if mc_version in v or mc_prefix in v:
                    return v
            
            return versions[-1] if versions else None
    except Exception as e:
        logger.warning(f"Failed to fetch NeoForge: {e}")
    return None


def _get_latest_fabric(mc_version: str) -> Optional[str]:
    """Fetch latest Fabric version."""
    try:
        url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data:
                return data[0].get("version")
    except Exception as e:
        logger.warning(f"Failed to fetch Fabric: {e}")
    return None


def get_java_version_for_mc(mc_version: str) -> str:
    """Get required Java version for MC."""
    if mc_version.startswith("1.21"):
        return "21"
    return "17"


__all__ = [
    "get_latest_minecraft_version",
    "get_all_minecraft_versions", 
    "get_latest_for_loader",
    "get_java_version_for_mc",
    "DEFAULT_MC_VERSION",
]