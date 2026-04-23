"""Version management for NeoRunner - dynamic Minecraft version fetching."""

import json
import logging
import urllib.request
import urllib.parse
from typing import Optional, List
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
    
    latest = DEFAULT_MC_VERSION
    
    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            
            for v in data.get("versions", []):
                vid = v.get("id", "")
                if v.get("type") == "release":
                    if vid[0].isdigit() and '.' in vid:
                        latest = vid
                        break
            
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


def get_loaders_for_minecraft(mc_version: str = None) -> dict:
    """Get all compatible loader versions for Minecraft."""
    if mc_version is None:
        mc_version = get_latest_minecraft_version()
    
    loaders = {}
    
    # NeoForge - get all versions, filter for MC compatible + latest 5
    loaders["neoforge"] = _get_all_neoforge_versions()
    
    # Fabric
    loaders["fabric"] = _get_fabric_versions()
    
    # Forge (deprecated, use NeoForge)
    loaders["forge"] = []
    
    return loaders


def _get_all_neoforge_versions() -> List[dict]:
    """Get NeoForge versions - latest 5 + MC compatible."""
    try:
        url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            versions = data.get("versions", [])
            
            # Get latest 5 stable releases (not alpha/beta/snapshot)
            latest_5 = []
            count = 0
            for v in reversed(versions):
                if any(x in v.lower() for x in ["alpha", "beta", "snapshot", "pre", "rc"]):
                    continue
                latest_5.append({"version": v, "type": "latest"})
                count += 1
                if count >= 5:
                    break
            
            return latest_5
    except Exception as e:
        logger.warning(f"Failed to fetch NeoForge: {e}")
        return []


def _get_fabric_versions() -> List[dict]:
    """Get Fabric versions."""
    try:
        url = "https://meta.fabricmc.net/v2/versions/loader"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            
            # Get latest 5 versions
            latest_5 = []
            count = 0
            for d in data:
                latest_5.append({"version": d.get("version"), "type": "latest"})
                count += 1
                if count >= 5:
                    break
            
            return latest_5
    except Exception as e:
        logger.warning(f"Failed to fetch Fabric: {e}")
        return []


def get_latest_for_loader(loader: str = "neoforge") -> Optional[str]:
    """Get latest version for a loader."""
    loaders = get_loaders_for_minecraft()
    
    if loader.lower() == "neoforge":
        versions = loaders.get("neoforge", [])
        return versions[0].get("version") if versions else None
    elif loader.lower() == "fabric":
        versions = loaders.get("fabric", [])
        return versions[0].get("version") if versions else None
    
    return None


def get_java_version_for_mc(mc_version: str) -> str:
    """Get required Java version for MC."""
    if mc_version.startswith("1.21"):
        return "21"
    elif mc_version.startswith("1.20"):
        return "17"
    return "17"


__all__ = [
    "get_latest_minecraft_version",
    "get_all_minecraft_versions",
    "get_loaders_for_minecraft",
    "get_latest_for_loader",
    "get_java_version_for_mc",
    "DEFAULT_MC_VERSION",
]
