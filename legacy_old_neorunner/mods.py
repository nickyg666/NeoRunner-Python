"""Mod management for NeoRunner."""

from __future__ import annotations

import zipfile
import json
import re
import os
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, Set, List
from dataclasses import dataclass
from functools import lru_cache

from .constants import CWD
from .config import ServerConfig
from .log import log_event

log = logging.getLogger(__name__)


@dataclass
class ModInfo:
    """Information about a mod."""
    file_path: Path
    mod_id: str
    name: str
    version: str
    side: str  # CLIENT, SERVER, BOTH
    network_channels: list[str]
    is_library: bool = False


# Cache for library detection to avoid repeated API calls
_library_cache: Dict[str, bool] = {}


def parse_mod_manifest(jar_path: Path) -> Optional[dict]:
    """Parse mod info from its MANIFEST.MF or mod.json.
    
    Args:
        jar_path: Path to the mod JAR file
        
    Returns:
        Dictionary with mod info or None
    """
    zf = None
    try:
        zf = zipfile.ZipFile(jar_path)
        # Try mod.json first (Fabric/Quilt)
        try:
            with zf.open("fabric.mod.json") as f:
                return json.load(f)
        except (KeyError, json.JSONDecodeError):
            pass
        
        # Try mods.toml (Forge/NeoForge)
        try:
            with zf.open("META-INF/mods.toml") as f:
                content = f.read().decode()
                # Parse TOML-like format
                data = {}
                for line in content.split('\n'):
                    if '=' in line and not line.strip().startswith('#'):
                        key, value = line.split('=', 1)
                        data[key.strip()] = value.strip().strip('"').strip("'")
                return data
        except (KeyError, Exception):
            pass
        
        # Try mod.json (older format)
        try:
            with zf.open("mod.json") as f:
                return json.load(f)
        except (KeyError, json.JSONDecodeError):
            pass
        
        # Try MANIFEST.MF
        try:
            with zf.open("META-INF/MANIFEST.MF") as f:
                manifest = f.read().decode()
                mod_id = None
                version = None
                for line in manifest.split("\n"):
                    if line.startswith("Mod-ID:"):
                        mod_id = line.split(":", 1)[1].strip()
                    if line.startswith("Mod-Version:"):
                        version = line.split(":", 1)[1].strip()
                if mod_id:
                    return {"mod_id": mod_id, "version": version}
        except KeyError:
            pass
    except Exception:
        pass
    finally:
        if zf:
            try:
                zf.close()
            except:
                pass
    
    return None


def check_if_library_modrinth(mod_id: str) -> bool:
    """Check if a mod is a library by querying Modrinth API.
    
    A mod is considered a library if it has more dependents than dependencies.
    """
    if mod_id in _library_cache:
        return _library_cache[mod_id]
    
    try:
        # Search for the mod
        search_url = f"https://api.modrinth.com/v2/search?query={mod_id}&limit=1"
        req = urllib.request.Request(search_url, headers={"User-Agent": "NeoRunner/2.1.0"})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            hits = data.get("hits", [])
            
            if not hits:
                _library_cache[mod_id] = False
                return False
            
            project_id = hits[0].get("project_id")
            
            # Get project details including dependencies
            project_url = f"https://api.modrinth.com/v2/project/{project_id}"
            req = urllib.request.Request(project_url, headers={"User-Agent": "NeoRunner/2.1.0"})
            
            with urllib.request.urlopen(req, timeout=10) as response:
                project_data = json.loads(response.read().decode())
                
                # Check if marked as library
                categories = project_data.get("categories", [])
                if "library" in categories:
                    _library_cache[mod_id] = True
                    return True
                
                # Get dependencies
                deps_url = f"https://api.modrinth.com/v2/project/{project_id}/dependencies"
                req = urllib.request.Request(deps_url, headers={"User-Agent": "NeoRunner/2.1.0"})
                
                with urllib.request.urlopen(req, timeout=10) as response:
                    deps_data = json.loads(response.read().decode())
                    
                    # Count dependents (mods that depend on this one)
                    dependents = deps_data.get("projects", [])
                    
                    # If any mods depend on this, it's a library/API
                    if len(dependents) >= 1:
                        _library_cache[mod_id] = True
                        return True
    
    except Exception:
        pass
    
    _library_cache[mod_id] = False
    return False


def check_if_library_curseforge(mod_id: str, api_key: Optional[str] = None) -> bool:
    """Check if a mod is a library by querying CurseForge API.
    
    A mod is considered a library if it has more dependents than dependencies.
    """
    if mod_id in _library_cache:
        return _library_cache[mod_id]
    
    # Try to get API key from file
    if not api_key:
        key_file = CWD / "curseforgeAPIkey"
        if key_file.exists():
            api_key = key_file.read_text().strip()
    
    if not api_key:
        return False
    
    try:
        # Search for the mod
        search_url = f"https://api.curseforge.com/v1/mods/search?gameId=432&searchFilter={mod_id}"
        headers = {"Accept": "application/json", "x-api-key": api_key}
        req = urllib.request.Request(search_url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            mods = data.get("data", [])
            
            if not mods:
                _library_cache[mod_id] = False
                return False
            
            mod_data = mods[0]
            mod_id_cf = mod_data.get("id")
            
            # Get mod description to check for "library" keyword
            summary = mod_data.get("summary", "").lower()
            if "library" in summary or "api" in summary:
                _library_cache[mod_id] = True
                return True
            
            # Get relationships (reverse dependencies)
            # Note: CurseForge API doesn't have a direct "dependents" endpoint
            # We check categories instead
            categories = mod_data.get("categories", [])
            cat_names = [c.get("name", "").lower() for c in categories]
            if "library" in cat_names or "api" in cat_names:
                _library_cache[mod_id] = True
                return True
    
    except Exception:
        pass
    
    _library_cache[mod_id] = False
    return False


def is_library(mod_id: str, cfg: ServerConfig | None = None) -> bool:
    """Check if a mod is a library using heuristics and API calls."""
    # Check cache first
    if mod_id in _library_cache:
        return _library_cache[mod_id]
    
    # Try Modrinth first (free API)
    if check_if_library_modrinth(mod_id):
        return True
    
    # Try CurseForge if API key available
    if check_if_library_curseforge(mod_id):
        return True
    
    return False


def classify_mod(jar_path: Path, cfg: ServerConfig | None = None) -> str:
    """Classify a mod as client-only, server, or both.
    
    Args:
        jar_path: Path to the mod JAR file
        cfg: Optional server configuration with user overrides
        
    Returns:
        "clientonly", "server", or "both"
    """
    mod_id = jar_path.stem.lower()
    
    # Check if it's a library
    if is_library(mod_id, cfg):
        return "server"  # Libraries go to server folder
    
    # Check manifest for side
    manifest = parse_mod_manifest(jar_path)
    if manifest:
        # Check fabric.mod.json format
        if "environment" in manifest:
            env = manifest.get("environment", "*")
            if env == "client":
                return "clientonly"
            elif env == "server":
                return "server"
        
        # Check mods.toml format
        side = manifest.get("side", "BOTH")
        if side == "CLIENT" or side == "client":
            return "clientonly"
        if side == "SERVER" or side == "server":
            return "server"
        if side == "BOTH" or side == "both" or side == "*":
            return "server"
                    
        # Check for network channels (indicates server communication)
        if "networkChannels" in manifest or "customChannels" in manifest:
            return "server"
    
    # Check for client-side classes in the JAR
    try:
        with zipfile.ZipFile(jar_path) as zf:
            for name in zf.namelist():
                if name.endswith((".class", ".java")):
                    # Check for client-side class patterns
                    if "/client/" in name or "Client" in name:
                        # But also check for server classes
                        has_server = any("/server/" in n or "Server" in n for n in zf.namelist() if n.endswith(".class"))
                        if not has_server:
                            return "clientonly"
    except Exception:
        pass
    
    # Default to server (most mods are server-side or both)
    return "server"


def sort_mods_by_type(mods_dir: Path, cfg: ServerConfig | None = None) -> dict[str, list[Path]]:
    """Sort mods into clientonly, server, and both categories.
    
    Args:
        mods_dir: Directory containing mods
        cfg: Optional server configuration
        
    Returns:
        Dictionary with keys "clientonly", "server", "both"
    """
    mods_dir = Path(mods_dir)
    clientonly_dir = CWD / "clientonly"
    
    result = {
        "clientonly": [],
        "server": [],
    }
    
    if not mods_dir.exists():
        return result
    
    # Get blacklisted mods
    blacklist = set()
    blacklist_file = CWD / "config" / "mod_blacklist.json"
    if blacklist_file.exists():
        with open(blacklist_file) as f:
            blacklist = set(json.load(f))
    
    for jar in mods_dir.glob("*.jar"):
        # Skip blacklisted
        if any(b in jar.stem.lower() for b in blacklist):
            continue
        
        category = classify_mod(jar, cfg)
        if category == "clientonly":
            result["clientonly"].append(jar)
        elif category == "server":
            result["server"].append(jar)
    
    return result


def preflight_mod_compatibility_check(mods_dir: Path, cfg: ServerConfig) -> dict:
    """Check mod compatibility before server start.
    
    Checks:
    1. Loader compatibility: mod declares a loader dep that doesn't match config
    2. MC version compatibility: mod's MC version range doesn't include our version
    3. Moves client-only mods to clientonly/ directory
    4. Quarantines incompatible mods
    
    Args:
        mods_dir: Directory containing mods
        cfg: Server configuration
        
    Returns:
        Dictionary with compatibility results
    """
    import shutil
    from .log import log_event
    
    mods_dir = Path(mods_dir)
    if not mods_dir.exists():
        return {"compatible": True, "issues": [], "missing_deps": [], "warnings": [], "quarantined": [], "moved": []}
    
    log_event("INFO", f"Scanning {len(list(mods_dir.glob('*.jar')))} installed mods...")
    
    server_loader = cfg.loader.lower()
    server_mc_version = cfg.mc_version
    
    LOADER_COMPAT = {
        "neoforge": {"neoforge"},
        "forge": {"forge"},
        "fabric": {"fabric", "quilt"},
    }
    compatible_loaders = LOADER_COMPAT.get(server_loader, {server_loader})
    
    clientonly_dir = mods_dir / "clientonly"
    clientonly_dir.mkdir(exist_ok=True)
    
    quarantine_dir = mods_dir / "quarantine"
    quarantine_dir.mkdir(exist_ok=True)
    
    result = {
        "compatible": True,
        "issues": [],
        "missing_deps": [],
        "warnings": [],
        "quarantined": [],
        "moved": [],
    }
    
    for jar in sorted(mods_dir.glob("*.jar")):
        manifest = parse_mod_manifest(jar)
        mod_id = manifest.get("mod_id", jar.stem) if manifest else jar.stem
        
        # Check 0: Client-only mods go to clientonly/
        mod_type = classify_mod(jar, cfg)
        if mod_type == "clientonly":
            dest = clientonly_dir / jar.name
            if not dest.exists():
                shutil.move(str(jar), str(dest))
                result["moved"].append(jar.name)
                log_event("COMPAT", f"Moved client-only mod {jar.name} -> clientonly/")
            continue
        
        if not manifest:
            result["warnings"].append(f"{jar.name}: Could not parse manifest")
            continue
        
        # Check loader compatibility
        declared_loader = manifest.get("loader", "").lower()
        if declared_loader and declared_loader not in compatible_loaders:
            reason = f"Requires {declared_loader}, server has {server_loader}"
            result["issues"].append({
                "mod": jar.name,
                "mod_id": mod_id,
                "issue": reason
            })
            result["compatible"] = False
            
            # Quarantine the mod
            qfile = quarantine_dir / jar.name
            if not qfile.exists():
                shutil.move(str(jar), str(qfile))
                with open(quarantine_dir / f"{jar.stem}.reason.txt", "w") as f:
                    f.write(reason)
                result["quarantined"].append(jar.name)
                log_event("COMPAT", f"Quarantined {jar.name}: {reason}")
            continue
        
        # Check MC version compatibility  
        mc_versions = manifest.get("game_versions", [])
        if mc_versions and server_mc_version not in mc_versions:
            if isinstance(mc_versions, list) and len(mc_versions) > 0:
                result["warnings"].append(
                    f"{jar.name}: MC version {server_mc_version} not in {mc_versions}"
                )
    
    if result["compatible"]:
        log_event("INFO", f"All mods compatible with {cfg.loader}")
    
    return result


def curate_mod_list(
    mods: list[dict],
    mc_version: str,
    loader: str,
    include_required_deps: bool = True,
    optional_dep_audit: Optional[dict] = None,
) -> list[dict]:
    """Curate a mod list, adding required dependencies.
    
    Args:
        mods: List of mods (from Modrinth/CurseForge)
        mc_version: Minecraft version
        loader: Loader name (neoforge/forge/fabric)
        include_required_deps: Whether to include required dependencies
        optional_dep_audit: Optional audit of optional dependencies
        
    Returns:
        Curated list of mods with dependencies
    """
    # Libraries to filter out, ideally this would not be hard coded, I really hate AI.
    LIBRARIES = {
        "cloth-config", "dark-loading-screen",
        "entity_model_features", "entity_texture_features", "fabric-api", 
        "fabric-language-kotlin", "ferritecore", "geckolib",
        "patchouli", "reach-entity-attributes", "sodium", "sodium-extra",
        "indium", " Reese's Sodium Options", " continuity", " fabric-api",
        "fabric-language-kotlin", "fabricloader", "malilib", "modmenu",
    }
    
    curated = []
    seen_ids = set()
    
    for mod in mods:
        mod_id = mod.get("project_id") or mod.get("id")
        mod_name = mod.get("title") or mod.get("name", "")
        
        if not mod_id or mod_id in seen_ids:
            continue
        
        # Skip libraries
        is_lib = False
        for lib in LIBRARIES:
            if lib.lower() in mod_name.lower():
                is_lib = True
                break
        if is_lib:
            continue
        
        seen_ids.add(mod_id)
        curated.append({
            "id": mod_id,
            "name": mod_name,
            "downloads": mod.get("downloads", 0),
            "description": mod.get("description", "")[:100],
            "url": f"https://modrinth.com/mod/{mod_id}",
            "source": "curated"
        })
    
    # Sort by downloads descending
    curated.sort(key=lambda x: x.get("downloads", 0), reverse=True)
    
    return curated


def fetch_modrinth_mods(
    mc_version: str,
    loader: str,
    limit: int = 100,
    offset: int = 0,
    categories: Optional[list[str]] = None,
    sort: str = "downloads"
) -> List[Dict[str, Any]]:
    """Fetch mods from Modrinth API.
    
    Args:
        mc_version: Minecraft version (e.g., "1.21.11")
        loader: Loader name (neoforge, forge, fabric)
        limit: Number of mods to fetch
        offset: Offset for pagination
        categories: Optional list of categories to filter
        sort: Sort field (downloads, follows, newest, updated)
        
    Returns:
        List of mod dictionaries
    """
    loader_lower = loader.lower()
    
    params = {
        "limit": min(limit, 100),
        "offset": offset,
        "sort": f"{sort}:desc",
        "game_version": mc_version,
        "loader": loader_lower,
    }
    
    if categories:
        params["categories"] = ",".join(categories)
    
    mods = {}
    
    try:
        url = "https://api.modrinth.com/v2/search"
        query_params = "&".join(f"{k}={v}" for k, v in params.items() if v)
        full_url = f"{url}?{query_params}"
        
        req = urllib.request.Request(full_url, headers={"User-Agent": "NeoRunner/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            hits = data.get("hits", [])
            
            for mod in hits:
                slug = mod.get("slug")
                if not slug or slug in mods:
                    continue
                
                mods[slug] = {
                    "id": mod.get("project_id"),
                    "slug": slug,
                    "name": mod.get("title"),
                    "description": mod.get("description", ""),
                    "downloads": mod.get("downloads", 0),
                    "version": mod.get("versions", [mc_version])[-1] if mod.get("versions") else mc_version,
                    "loader": loader_lower,
                    "mc_version": mc_version,
                    "source": "modrinth",
                }
        
        log.info(f"Fetched {len(mods)} mods from Modrinth")
        
    except Exception as e:
        log.error(f"Error fetching Modrinth mods: {e}")
    
    return list(mods.values())


def download_mod_from_modrinth(
    mod_data: Dict[str, Any],
    mods_dir: Path,
    mc_version: str,
    loader: str,
) -> bool:
    """Download mod JAR from Modrinth.
    
    Args:
        mod_data: Dict with 'id', 'slug', 'name'
        mods_dir: Directory to download to
        mc_version: Minecraft version
        loader: Loader name
        
    Returns:
        True if downloaded successfully
    """
    mod_id = mod_data.get("id")
    mod_slug = mod_data.get("slug", mod_data.get("name", ""))
    mod_name = mod_data.get("name", "unknown")
    
    if not mod_id:
        log.warning(f"No mod ID for {mod_name}")
        return False
    
    base_url = "https://api.modrinth.com/v2"
    loader_lower = loader.lower()
    
    try:
        url = f"{base_url}/project/{mod_id}/version"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        
        with urllib.request.urlopen(req, timeout=30) as response:
            all_versions = json.loads(response.read().decode())
            
            matching_version = None
            for v in all_versions:
                if mc_version in v.get("game_versions", []) and loader_lower in [l.lower() for l in v.get("loaders", [])]:
                    matching_version = v
                    break
            
            if not matching_version:
                for v in all_versions:
                    if mc_version in v.get("game_versions", []):
                        matching_version = v
                        break
            
            if not matching_version:
                log.warning(f"No version of {mod_name} found for MC {mc_version}")
                return False
            
            files = matching_version.get("files", [])
            if not files:
                log.warning(f"No files for {mod_name}")
                return False
            
            file_info = files[0]
            for f in files:
                if f.get("primary"):
                    file_info = f
                    break
            
            download_url = file_info.get("url")
            file_name = file_info.get("filename")
            
            if not download_url or not file_name:
                log.warning(f"No download URL for {mod_name}")
                return False
            
            file_path = mods_dir / file_name
            if file_path.exists() and file_path.stat().st_size > 0:
                log.info(f"Already have {file_name}")
                return True
            
            log.info(f"Downloading {file_name}...")
            req = urllib.request.Request(download_url, headers={"User-Agent": "NeoRunner/2.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                with open(file_path, "wb") as f:
                    f.write(data)
            log.info(f"Downloaded {file_name} ({len(data)/1024:.0f} KB)")
            return True
            
    except Exception as e:
        log.error(f"Error downloading {mod_name}: {e}")
        return False


def get_mod_dependencies_modrinth(mod_id: str) -> List[str]:
    """Get required dependencies for a mod from Modrinth.
    
    Args:
        mod_id: Modrinth project ID
        
    Returns:
        List of required dependency project IDs
    """
    deps = []
    try:
        url = f"https://api.modrinth.com/v2/project/{mod_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            for dep in data.get("dependencies", []):
                if dep.get("dependency_type") == "required":
                    project_id = dep.get("project_id")
                    if project_id:
                        deps.append(project_id)
    except Exception as e:
        log.error(f"Error getting dependencies for {mod_id}: {e}")
    return deps


def resolve_mod_dependencies_modrinth(
    mod_id: str,
    mc_version: str,
    loader: str,
    resolved: Optional[set] = None,
    depth: int = 0,
    max_depth: int = 3
) -> Set[str]:
    """Recursively resolve all dependencies for a mod.
    
    Args:
        mod_id: Modrinth project ID
        mc_version: Minecraft version
        loader: Loader name
        resolved: Set of already resolved mod IDs
        depth: Current recursion depth
        max_depth: Maximum recursion depth
        
    Returns:
        Set of all required dependency mod IDs
    """
    if resolved is None:
        resolved = set()
    
    if depth >= max_depth or mod_id in resolved:
        return resolved
    
    resolved.add(mod_id)
    
    deps = get_mod_dependencies_modrinth(mod_id)
    for dep_id in deps:
        resolve_mod_dependencies_modrinth(dep_id, mc_version, loader, resolved, depth + 1, max_depth)
    
    return resolved


def download_file(url: str, dest_dir: Path, filename: Optional[str] = None) -> bool:
    """Download a file from URL.
    
    Args:
        url: URL to download
        dest_dir: Destination directory
        filename: Optional filename (extracted from URL if not provided)
        
    Returns:
        True if successful
    """
    try:
        if filename is None:
            filename = url.split("/")[-1].split("?")[0]
        
        dest_path = dest_dir / filename
        
        log.info(f"Downloading {filename}...")
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            with open(dest_path, "wb") as f:
                f.write(data)
        log.info(f"Downloaded {filename}")
        return True
    except Exception as e:
        log.error(f"Download failed: {e}")
        return False


__all__ = [
    "ModInfo",
    "parse_mod_manifest",
    "is_library",
    "classify_mod",
    "sort_mods_by_type",
    "preflight_mod_compatibility_check",
    "curate_mod_list",
    "fetch_modrinth_mods",
    "download_mod_from_modrinth",
    "get_mod_dependencies_modrinth",
    "resolve_mod_dependencies_modrinth",
    "download_file",
]
