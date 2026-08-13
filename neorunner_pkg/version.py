"""Version management for NeoRunner - dynamic Minecraft version fetching."""

import json
import logging
import urllib.parse
import urllib.request
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
                if v.get("type") == "release" and vid and vid[0].isdigit() and '.' in vid:
                    latest = vid
                    break
            
            cache_data = {"latest_release": latest, "versions": [v["id"] for v in data.get("versions", [])]}
            VERSIONS_CACHE.write_text(json.dumps(cache_data, indent=2))
            
            return latest
    except Exception as e:
        logger.warning(f"Failed to fetch latest MC version: {e}")
        return DEFAULT_MC_VERSION


def get_all_minecraft_versions() -> list[str]:
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


def get_loaders_for_minecraft(mc_version: str | None = None) -> dict:
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


def _get_all_neoforge_versions() -> list[dict]:
    """Get NeoForge versions - latest 5 (including beta)."""
    try:
        url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            versions = data.get("versions", [])
            
            # Get latest 5 (beta versions are basically stable in NeoForge)
            latest_5 = []
            count = 0
            for v in reversed(versions):
                # Include all except alpha/snapshot
                if "alpha" in v.lower() or "snapshot" in v.lower():
                    continue
                latest_5.append({"version": v, "type": "latest"})
                count += 1
                if count >= 5:
                    break
            
            return latest_5
    except Exception as e:
        logger.warning(f"Failed to fetch NeoForge: {e}")
        return []


def _get_fabric_versions() -> list[dict]:
    """Get Fabric versions."""
    try:
        url = "https://meta.fabricmc.net/v2/versions/loader"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            
            # Get latest 5 versions
            latest_5 = []
            for count, d in enumerate(data):
                latest_5.append({"version": d.get("version"), "type": "latest"})
                if count >= 4:
                    break
            
            return latest_5
    except Exception as e:
        logger.warning(f"Failed to fetch Fabric: {e}")
        return []


def get_latest_for_loader(loader: str = "neoforge") -> str | None:
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
    """Get required Java version for MC.

    Handles both the classic scheme (1.x) and the year-based scheme (26.x+).
    - 26.x and newer year-based releases require Java 25
    - 1.21.x / 1.20.5+ require Java 21
    - 1.18.x - 1.20.4 require Java 17
    - 1.17.x requires Java 16
    """
    ver = (mc_version or "").strip()
    parts = ver.split(".")
    if not parts:
        return "17"

    # Year-based versioning (25.x, 26.x, ...) - requires Java 25
    major = int(parts[0]) if parts[0].isdigit() else 0
    if major >= 25:
        return "25"

    if ver.startswith("1.21"):
        return "21"

    # 1.20.5 and 1.20.6 require Java 21
    if ver.startswith("1.20") and len(parts) >= 3:
        try:
            if int(parts[2]) >= 5:
                return "21"
        except ValueError:
            pass

    if ver.startswith("1.20"):
        return "17"
    if ver.startswith(("1.19", "1.18")):
        return "17"
    if ver.startswith("1.17"):
        return "16"
    return "17"


__all__ = [
    "DEFAULT_MC_VERSION",
    "get_all_minecraft_versions",
    "get_java_version_for_mc",
    "get_latest_for_loader",
    "get_latest_minecraft_version",
    "get_loaders_for_minecraft",
]
