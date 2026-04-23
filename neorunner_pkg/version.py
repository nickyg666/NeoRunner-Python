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


def _parse_minecraft_version(version_str: str) -> tuple:
    """Parse version string into (major, minor, patch) tuple for comparison."""
    # Handle various formats: "1.21.11", "26w14a", "1.21.11-pre1", "26.1.2"
    version_str = version_str.split('-')[0]  # Remove -pre, -rc suffixes
    
    # Check if new format (26.x.x)
    if version_str.startswith("26.") or version_str.startswith("25.") or version_str.startswith("24."):
        parts = version_str.split('.')
        if len(parts) >= 2:
            try:
                major_year = int(parts[0])
                minor = int(parts[1])
                patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                # Convert 26.x to 1.2x.x format
                return (1, minor - 9 if minor >= 10 else 20 + minor, patch)
            except:
                pass
    
    # Normal format (1.xx.x)
    parts = version_str.split('.')
    try:
        if len(parts) >= 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        elif len(parts) >= 2:
            return (int(parts[0]), int(parts[1]), 0)
    except:
        pass
    
    return (0, 0, 0)


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
            
            # Find latest RELEASE that looks like a valid game version
            # Accept: 1.x.x, 24.xx.x, 25.xx.x, 26.x.x format
            for v in data.get("versions", []):
                vid = v.get("id", "")
                vtype = v.get("type", "")
                
                if vtype == "release":
                    # Must start with digit + dot
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


def get_loaders_for_minecraft(mc_version: str) -> dict:
    """Get all compatible loader versions for a given Minecraft version."""
    loaders = {}
    
    # Get NeoForge versions
    loaders["neoforge"] = _get_neoforge_versions_for_mc(mc_version)
    
    # Get Fabric versions
    loaders["fabric"] = _get_fabric_versions_for_mc(mc_version)
    
    # Forge is deprecated, map to NeoForge
    loaders["forge"] = loaders.get("neoforge", [])
    
    return loaders


def _get_neoforge_versions_for_mc(mc_version: str) -> List[dict]:
    """Get all NeoForge versions for a specific Minecraft version."""
    try:
        url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            versions = data.get("versions", [])
            
            # Parse MC version - extract minor and patch ("21.11" from "1.21.11")
            mc_parts = mc_version.split('.')
            mc_minor = ""
            mc_patch = ""
            if len(mc_parts) >= 2:
                mc_minor = mc_parts[1]  # "21" from "1.21.11"
            if len(mc_parts) >= 3:
                mc_patch = mc_parts[2]  # "11" from "1.21.11"
            
            # Convert MC 1.xx.y to NeoForge version
            # MC 1.21.11 → NeoForge 26.1.x (where x is patch level)
            # MC minor 21 → NeoForge major 26, minor is 1.xx - 20
            neo_major = ""
            if mc_minor:
                try:
                    minor_num = int(mc_minor)
                    if minor_num >= 21:
                        # New format: 1.21.x → 26.1.x
                        neo_major = f"26.1.{mc_patch}" if mc_patch else "26.1"
                    else:
                        # Old format: 1.20.x → 20.x.x.x
                        neo_major = f"20.{minor_num}"
                        if mc_patch:
                            neo_major += f".{mc_patch}"
                except:
                    pass
            
            matching = []
            for v in versions:
                # Skip alpha/beta for stable releases
                if "alpha" in v.lower() or "beta" in v.lower():
                    continue
                if "snapshot" in v.lower():
                    continue
                    
                # Match by direct MC version in version string
                if mc_version in v or f"{mc_minor}.{mc_patch}" in v:
                    matching.append({"version": v, "type": "release"})
                # Also try matching just minor.patch
                elif mc_minor and mc_patch and f"{mc_minor}.{mc_patch}" in v:
                    matching.append({"version": v, "type": "release"})
                # Match new NeoForge format
                elif neo_major and (v.startswith(neo_major) or v.startswith(f"26.{mc_minor}")):
                    matching.append({"version": v, "type": "release"})
            
            # If no stable matches, include recent releases
            if not matching:
                for v in reversed(versions):
                    if "alpha" not in v.lower() and "snapshot" not in v.lower():
                        matching.append({"version": v, "type": "release"})
                        if len(matching) >= 5:
                            break
            
            return matching[:10]
    except Exception as e:
        logger.warning(f"Failed to fetch NeoForge versions: {e}")
        return []


def _get_fabric_versions_for_mc(mc_version: str) -> List[dict]:
    """Get Fabric version for MC."""
    try:
        url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return [{"version": d.get("version"), "type": d.get("type")} for d in data[:5]]
    except Exception as e:
        logger.warning(f"Failed to fetch Fabric: {e}")
        return []


def get_latest_for_loader(loader: str = "neoforge") -> Optional[str]:
    """Get latest loader version for current MC."""
    mc_version = get_latest_minecraft_version()
    
    if loader.lower() == "neoforge":
        versions = _get_neoforge_versions_for_mc(mc_version)
        if versions:
            return versions[0].get("version")
    elif loader.lower() == "fabric":
        versions = _get_fabric_versions_for_mc(mc_version)
        if versions:
            return versions[0].get("version")
    
    versions = _get_neoforge_versions_for_mc(mc_version)
    return versions[0].get("version") if versions else None


def _get_latest_neoforge(mc_version: str) -> Optional[str]:
    """Fetch latest NeoForge version (legacy)."""
    versions = _get_neoforge_versions_for_mc(mc_version)
    if versions:
        return versions[0].get("version")
    return None


def _get_latest_fabric(mc_version: str) -> Optional[str]:
    """Fetch latest Fabric version (legacy)."""
    versions = _get_fabric_versions_for_mc(mc_version)
    if versions:
        return versions[0].get("version")
    return None


def get_java_version_for_mc(mc_version: str) -> str:
    """Get required Java version for MC."""
    mc = _parse_minecraft_version(mc_version)
    if mc[0] >= 1 and mc[1] >= 21:
        return "21"
    elif mc[0] >= 1 and mc[1] >= 17:
        return "17"
    return "17"


__all__ = [
    "get_latest_minecraft_version",
    "get_all_minecraft_versions",
    "get_loaders_for_minecraft",
    "get_latest_for_loader",
    "get_java_version_for_mc",
    "DEFAULT_MC_VERSION",
    "VERSIONS_CACHE",
]