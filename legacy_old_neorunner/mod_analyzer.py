"""Mod analyzer - JAR inspection and database management.

Inspects mod JAR files to extract metadata and detect client-only mods.
Uses mods.toml and neoforge.mods.toml for metadata extraction.
Builds a mod database for caching analysis results.

Client-Only Mod Detection Patterns:
====================================
1. KNOWN_CLIENT_ONLY: Mod IDs that are DEFINITELY client-only (sodium, iris, optifine, etc.)
2. CLIENT_CLASS_PATTERNS: Class file paths that indicate client-side code:
   - net/minecraft/client/ - Minecraft client classes (FATAL on server)
   - com/mojang/blaze3d/ - Graphics/rendering classes
   - net/optifine/ - OptiFine classes
   - net/iris/ - Iris shader classes
   - client/renderer, client/gui, client/options - GUI classes
3. MIXIN_CLIENT_TARGETS: Mixin config targets that crash server:
   - net.minecraft.client.* - Any mixin targeting client classes
   - com.mojang.blaze3d.* - Graphics mixins
4. FABRIC environment: Mods with "server" not in environment are client-only

Note: NeoForge 1.21.11 beta has entity_texture_features baked into server.jar
This is a BUG in NeoForge itself, not fixable by moving mods.
"""

import json
import zipfile
import re
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, asdict
from datetime import datetime

from .constants import CWD

log = logging.getLogger(__name__)

MODS_TOML_PATTERNS = [
    "META-INF/neoforge.mods.toml",
    "META-INF/mods.toml",
    "neoforge.mods.toml",
    "mods.toml",
]

FABRIC_MOD_JSON = "fabric.mod.json"

CLIENT_CLASS_PATTERNS = {
    "net/minecraft/client/",
    "com/mojang/blaze3d/",
    "net/optifine/",
    "net/iris/",
    "net/sodium/",
    "client/renderer",
    "client/gui",
    "client/options",
    "client/settings",
    "MixinClient",
    "IClient",
    "ClientSide",
}

MIXIN_CLIENT_TARGETS = {
    "net.minecraft.client.",
    "net.minecraft.src.",
    "com.mojang.blaze3d.",
    "net.optifine.",
    "net.iris.",
}

FATAL_MOD_IDS = {
    "sodium", "optifine", "iris", "modmenu", "entity_texture_features",
    "xaerominimap", "xaeroworldmap", "dynamicfps", "notenoughanimations",
    "roughlyenoughitems", "emi", "journeymap", "replaymod", "worldedit",
    "litematica", "minihud", "citr", "continuity", "lambdadynamiclights",
    "essential", "pepsi", "okzoomer", "fancymenu", "emotecraft",
    "customskinloader", "xaerobetterpvp", "okzoomer", " Maldona",
    "xaeros_world_map", "xaeros_minimap",
}


@dataclass
class ModMetadata:
    """Extracted metadata from a mod JAR."""
    filename: str
    mod_id: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    url: str = ""
    dependencies: Optional[List[Dict[str, str]]] = None
    is_client_only: bool = False
    client_reason: str = ""
    has_client_classes: bool = False
    has_client_mixins: bool = False
    file_hash: str = ""
    file_size: int = 0
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class ModDatabase:
    """Manages the mod analysis database with caching."""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = CWD / "config" / "mod_database.json"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data: Dict[str, Any] = {"mods": {}, "last_updated": "", "version": "1.0"}
        self.load()
    
    def load(self) -> None:
        """Load database from disk."""
        if self.db_path.exists():
            try:
                with open(self.db_path) as f:
                    self.data = json.load(f)
            except Exception as e:
                log.warning(f"Failed to load mod database: {e}")
                self.data = {"mods": {}, "last_updated": "", "version": "1.0"}
    
    def save(self) -> None:
        """Save database to disk."""
        self.data["last_updated"] = datetime.now().isoformat()
        with open(self.db_path, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get_mod(self, filename: str) -> Optional[ModMetadata]:
        """Get cached mod metadata."""
        if filename in self.data.get("mods", {}):
            return ModMetadata(**self.data["mods"][filename])
        return None
    
    def has_changed(self, filename: str, file_hash: str, file_size: int) -> bool:
        """Check if a mod has changed since last analysis."""
        mod = self.get_mod(filename)
        if mod is None:
            return True
        return mod.file_hash != file_hash or mod.file_size != file_size
    
    def update_mod(self, metadata: ModMetadata) -> None:
        """Update mod in database."""
        self.data["mods"][metadata.filename] = asdict(metadata)
    
    def remove_mod(self, filename: str) -> None:
        """Remove mod from database."""
        if filename in self.data.get("mods", {}):
            del self.data["mods"][filename]
    
    def get_all_mods(self) -> Dict[str, ModMetadata]:
        """Get all cached mods."""
        return {name: ModMetadata(**data) for name, data in self.data.get("mods", {}).items()}


def analyze_jar(jar_path: Path, use_cache: bool = True) -> ModMetadata:
    """Analyze a mod JAR file and extract metadata."""
    db = ModDatabase()
    
    try:
        file_hash = _compute_hash(jar_path)
        file_size = jar_path.stat().st_size
        
        if use_cache and not db.has_changed(jar_path.name, file_hash, file_size):
            cached = db.get_mod(jar_path.name)
            if cached:
                return cached
    except Exception:
        pass
    
    metadata = ModMetadata(filename=jar_path.name)
    
    try:
        file_hash = _compute_hash(jar_path)
        file_size = jar_path.stat().st_size
        metadata.file_hash = file_hash
        metadata.file_size = file_size
    except Exception:
        pass
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            names = zf.namelist()
            
            metadata.has_client_classes = _has_client_classes(names)
            metadata.has_client_mixins = _has_client_mixins(zf, names)
            
            _extract_mod_metadata(zf, names, metadata)
            
            _determine_client_only(metadata)
            
    except Exception as e:
        log.warning(f"Error analyzing {jar_path.name}: {e}")
        metadata.description = f"Analysis error: {e}"
    
    db.update_mod(metadata)
    db.save()
    
    return metadata


def _compute_hash(jar_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(jar_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def _has_client_classes(names: List[str]) -> bool:
    """Check if JAR contains client-side class files."""
    for name in names[:300]:
        for pattern in CLIENT_CLASS_PATTERNS:
            if pattern.replace("/", ".") in name or pattern in name:
                return True
    return False


def _has_client_mixins(zf: zipfile.ZipFile, names: List[str]) -> bool:
    """Check if JAR has mixin configs targeting client classes."""
    mixin_files = [n for n in names if n.endswith('.json') and 'mixin' in n.lower()]
    
    for mixin_file in mixin_files:
        try:
            content = zf.read(mixin_file).decode('utf-8', errors='ignore')
            for target in MIXIN_CLIENT_TARGETS:
                if target in content:
                    return True
        except Exception:
            pass
    
    return False


def _extract_mod_metadata(zf: zipfile.ZipFile, names: List[str], metadata: ModMetadata) -> None:
    """Extract mod metadata from mods.toml or fabric.mod.json."""
    for toml_path in MODS_TOML_PATTERNS:
        if toml_path in names:
            try:
                content = zf.read(toml_path).decode('utf-8', errors='ignore')
                _parse_neoforge_toml(content, metadata)
                return
            except Exception:
                pass
    
    if FABRIC_MOD_JSON in names:
        try:
            content = zf.read(FABRIC_MOD_JSON).decode('utf-8', errors='ignore')
            _parse_fabric_json(content, metadata)
        except Exception:
            pass


def _parse_neoforge_toml(content: str, metadata: ModMetadata) -> None:
    """Parse NeoForge mods.toml format."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    try:
        data = tomllib.loads(content)
        
        if "mods" in data and isinstance(data["mods"], list) and data["mods"]:
            mod_info = data["mods"][0]
            metadata.mod_id = mod_info.get("modId", "")
            metadata.name = mod_info.get("displayName", "")
            metadata.version = mod_info.get("version", "")
            metadata.description = mod_info.get("description", "")
            metadata.url = mod_info.get("updateJSON", "") or mod_info.get("displayURL", "")
            
            if "authors" in mod_info and isinstance(mod_info["authors"], list):
                metadata.author = ", ".join(str(a) for a in mod_info["authors"])
            elif "authors" in mod_info:
                metadata.author = str(mod_info["authors"])
        
        if "dependencies" in data and isinstance(data["dependencies"], dict):
            for dep_type, deps in data["dependencies"].items():
                if isinstance(deps, list):
                    for dep in deps:
                        if isinstance(dep, dict):
                            dep_id = dep.get("modId", "")
                            version = dep.get("versionRange", "")
                            dep_info = {"modId": dep_id, "version": version, "type": dep_type}
                            if metadata.dependencies is None:
                                metadata.dependencies = []
                            metadata.dependencies.append(dep_info)
        
    except Exception as e:
        pass


def _parse_fabric_json(content: str, metadata: ModMetadata) -> None:
    """Parse Fabric mod JSON format."""
    try:
        data = json.loads(content)
        
        metadata.mod_id = data.get("id", "")
        metadata.name = data.get("name", "")
        metadata.version = data.get("version", "")
        metadata.description = data.get("description", "")
        metadata.author = ", ".join(data.get("authors", [])) if isinstance(data.get("authors"), list) else str(data.get("authors", ""))
        metadata.url = data.get("contact", {}).get("homepage", "")
        
        if "depends" in data:
            for dep_id, version in data["depends"].items():
                dep_info = {"modId": dep_id, "version": str(version), "type": "required"}
                if metadata.dependencies is None:
                    metadata.dependencies = []
                metadata.dependencies.append(dep_info)
        
    except Exception:
        pass


def _determine_client_only(metadata: ModMetadata) -> None:
    """Determine if a mod is client-only based on analysis."""
    mod_id_lower = metadata.mod_id.lower() if metadata.mod_id else ""
    filename_lower = metadata.filename.lower()
    
    if mod_id_lower in FATAL_MOD_IDS:
        metadata.is_client_only = True
        metadata.client_reason = f"Known client-only mod: {metadata.mod_id}"
        return
    
    for fatal_id in FATAL_MOD_IDS:
        if fatal_id in filename_lower:
            metadata.is_client_only = True
            metadata.client_reason = f"Filename contains known client-only mod: {fatal_id}"
            return
    
    if metadata.has_client_classes:
        metadata.is_client_only = True
        metadata.client_reason = "Contains client-side class files (net.minecraft.client.*)"
        return
    
    if metadata.has_client_mixins:
        metadata.is_client_only = True
        metadata.client_reason = "Contains mixin configurations targeting client classes"
        return
    
    env = _get_environment(metadata)
    if env == "client":
        metadata.is_client_only = True
        metadata.client_reason = "Mod environment is client-only (fabric)"
        return
    
    if env == "server":
        metadata.is_client_only = False
        return


def _get_environment(metadata: ModMetadata) -> Optional[str]:
    """Check mod environment from metadata."""
    if not metadata.dependencies:
        return None
    
    for dep in metadata.dependencies:
        if dep.get("modId", "").lower() in ["fabric", "fabric-api-base"]:
            return "client"
    
    return None


def analyze_mods_directory(mods_dir: Path, clientonly_dir: Optional[Path] = None, use_cache: bool = True) -> Dict[str, ModMetadata]:
    """Analyze all mods in a directory."""
    if clientonly_dir is None:
        clientonly_dir = mods_dir.parent / "clientonly"
    
    results: Dict[str, ModMetadata] = {}
    
    dirs_to_scan = [mods_dir]
    if clientonly_dir.exists():
        dirs_to_scan.append(clientonly_dir)
    
    for scan_dir in dirs_to_scan:
        if not scan_dir.exists():
            continue
        
        for jar_path in sorted(scan_dir.glob("*.jar")):
            if jar_path.name.endswith(".server.jar"):
                continue
            
            metadata = analyze_jar(jar_path, use_cache=use_cache)
            results[jar_path.name] = metadata
    
    return results


def get_mod_dependencies(metadata: ModMetadata) -> Dict[str, Set[str]]:
    """Get mod dependencies categorized by type."""
    required: Set[str] = set()
    optional: Set[str] = set()
    embedded: Set[str] = set()
    
    if metadata.dependencies is None:
        return {"required": required, "optional": optional, "embedded": embedded}
    
    for dep in metadata.dependencies:
        dep_id = dep.get("modId", "").lower()
        if not dep_id:
            continue
        
        dep_type = dep.get("type", "required").lower()
        
        if dep_type == "required":
            required.add(dep_id)
        elif dep_type == "optional":
            optional.add(dep_id)
        elif dep_type == "embedded":
            embedded.add(dep_id)
    
    return {
        "required": required,
        "optional": optional,
        "embedded": embedded,
    }


def find_missing_dependencies(mods_dir: Path, clientonly_dir: Optional[Path] = None) -> Dict[str, Set[str]]:
    """Find missing dependencies across all mods in directories."""
    all_mods = analyze_mods_directory(mods_dir, clientonly_dir)
    
    installed_ids: Set[str] = set()
    for metadata in all_mods.values():
        if metadata.mod_id:
            installed_ids.add(metadata.mod_id.lower())
    
    required_deps: Dict[str, Set[str]] = {}
    
    for filename, metadata in all_mods.items():
        deps = get_mod_dependencies(metadata)
        
        for dep_id in deps["required"]:
            if dep_id not in installed_ids:
                required_deps.setdefault(dep_id, set()).add(filename)
    
    return required_deps


def get_clientonly_mods(mods_dir: Path, clientonly_dir: Optional[Path] = None) -> List[ModMetadata]:
    """Get list of client-only mods from both directories."""
    all_mods = analyze_mods_directory(mods_dir, clientonly_dir)
    
    clientonly = []
    for metadata in all_mods.values():
        if metadata.is_client_only:
            clientonly.append(metadata)
    
    return clientonly


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    if len(sys.argv) > 1:
        mods_dir = Path(sys.argv[1])
    else:
        mods_dir = CWD / "mods"
    
    if not mods_dir.exists():
        print(f"Error: {mods_dir} does not exist")
        sys.exit(1)
    
    clientonly_dir = mods_dir.parent / "clientonly"
    
    print(f"Analyzing mods in {mods_dir}...")
    results = analyze_mods_directory(mods_dir, clientonly_dir)
    
    print(f"\n=== Analysis Results ===")
    print(f"Total mods: {len(results)}")
    
    clientonly = [m for m in results.values() if m.is_client_only]
    print(f"Client-only mods: {len(clientonly)}")
    
    if clientonly:
        print("\nClient-only mods detected:")
        for m in clientonly:
            print(f"  - {m.filename}: {m.client_reason}")
