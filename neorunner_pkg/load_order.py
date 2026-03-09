"""Load order management for NeoRunner - uses load.order file instead of renaming mods."""

import os
import re
from pathlib import Path
from typing import List, Dict

from .constants import CWD


def strip_prefix(filename: str) -> str:
    """Remove !aa_XX_, !bb_XX_, !zz_XX_ prefixes from filename."""
    return re.sub(r'^![a-z]{2}_\d+_', '', filename)


def restore_mod_names(mods_dir: Path = None) -> Dict:
    """Restore all mods to original names (strip prefixes)."""
    if mods_dir is None:
        mods_dir = CWD / "mods"
    
    mods_dir = Path(mods_dir)
    if not mods_dir.exists():
        return {"status": "error", "message": "Mods directory not found"}
    
    renamed = []
    skipped = []
    
    for f in mods_dir.glob("*.jar"):
        original = strip_prefix(f.name)
        if f.name != original:
            new_path = mods_dir / original
            if new_path.exists():
                skipped.append(f.name)
            else:
                f.rename(new_path)
                renamed.append({"old": f.name, "new": original})
    
    return {
        "status": "success",
        "renamed": renamed,
        "skipped": skipped,
    }


def generate_load_order(mods_dir: Path = None) -> List[str]:
    """Generate load order based on mod categories (API -> regular -> addons)."""
    if mods_dir is None:
        mods_dir = CWD / "mods"
    
    mods_dir = Path(mods_dir)
    if not mods_dir.exists():
        return []
    
    # Categories
    api_mods = []
    regular_mods = []
    addon_mods = []
    
    for f in sorted(mods_dir.glob("*.jar")):
        name = strip_prefix(f.name).lower()
        
        if any(x in name for x in ["library", "api", "core", "lib", "bukkit", "spigot", "geckolib", "architectury", "modmenu"]):
            api_mods.append(f.name)
        elif any(x in name for x in ["addon", "plugin", "compat", "patch"]):
            addon_mods.append(f.name)
        else:
            regular_mods.append(f.name)
    
    # Sort each category alphabetically
    api_mods.sort(key=lambda x: strip_prefix(x).lower())
    regular_mods.sort(key=lambda x: strip_prefix(x).lower())
    addon_mods.sort(key=lambda x: strip_prefix(x).lower())
    
    # Combine in load order: API first, then regular, then addons
    return api_mods + regular_mods + addon_mods


def save_load_order(mods_dir: Path = None) -> Path:
    """Save load order to load.order file. Returns path to the file."""
    if mods_dir is None:
        mods_dir = CWD / "mods"
    
    mods_dir = Path(mods_dir)
    order = generate_load_order(mods_dir)
    
    load_order_file = mods_dir / "load.order"
    load_order_file.write_text("\n".join(order))
    
    return load_order_file


def read_load_order(mods_dir: Path = None) -> List[str]:
    """Read load order from load.order file."""
    if mods_dir is None:
        mods_dir = CWD / "mods"
    
    load_order_file = Path(mods_dir) / "load.order"
    
    if not load_order_file.exists():
        return []
    
    return [line.strip() for line in load_order_file.read_text().split("\n") if line.strip()]


def get_mod_load_order(mods_dir: Path = None) -> List[Path]:
    """Get mods in correct load order as Path objects."""
    if mods_dir is None:
        mods_dir = CWD / "mods"
    
    mods_dir = Path(mods_dir)
    order = read_load_order(mods_dir)
    
    if not order:
        # No load.order, fall back to alphabetical
        return sorted(mods_dir.glob("*.jar"))
    
    # Create a lookup dict
    mod_files = {f.name: f for f in mods_dir.glob("*.jar")}
    
    # Return in order, filtering out any that no longer exist
    result = []
    for name in order:
        if name in mod_files:
            result.append(mod_files[name])
    
    # Add any mods not in the order file
    for f in mod_files.values():
        if f not in result:
            result.append(f)
    
    return result
