"""Backup management for NeoRunner.

Handles world backups, scheduling, and restore operations.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from .constants import CWD
from .config import ServerConfig, load_cfg
from .log import log_event

log = logging.getLogger(__name__)


def get_current_world() -> str:
    """Get current world name from server.properties."""
    props_path = CWD / "server.properties"
    if props_path.exists():
        with open(props_path) as f:
            for line in f:
                if line.strip().startswith("level-name="):
                    return line.strip().split("=", 1)[1]
    return "world"


def backup_world(
    world_name: Optional[str] = None,
    backup_dir: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> Optional[Path]:
    """Create a backup of the current world.
    
    Args:
        world_name: Name of world to backup (default: current)
        backup_dir: Directory to store backups (default: cwd/backups)
        cwd: Working directory
        
    Returns:
        Path to backup file, or None on failure
    """
    if cwd is None:
        cwd = CWD
    
    if backup_dir is None:
        backup_dir = cwd / "backups"
    
    if world_name is None:
        world_name = get_current_world()
    
    world_path = cwd / world_name
    
    if not world_path.exists():
        log.warning(f"World {world_name} does not exist")
        return None
    
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{world_name}_{timestamp}.tar.gz"
    backup_path = backup_dir / backup_name
    
    try:
        log_event("BACKUP", f"Creating backup: {backup_name}")
        
        import tarfile
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(world_path, arcname=world_name)
        
        backup_size = backup_path.stat().st_size / (1024 * 1024)
        log_event("BACKUP", f"Backup created: {backup_name} ({backup_size:.1f} MB)")
        
        return backup_path
        
    except Exception as e:
        log.error(f"Backup failed: {e}")
        if backup_path.exists():
            backup_path.unlink()
        return None


def list_backups(
    world_name: Optional[str] = None,
    backup_dir: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List available backups.
    
    Args:
        world_name: Filter by world name
        backup_dir: Directory to search
        cwd: Working directory
        
    Returns:
        List of backup info dicts
    """
    if cwd is None:
        cwd = CWD
    
    if backup_dir is None:
        backup_dir = cwd / "backups"
    
    if not backup_dir.exists():
        return []
    
    backups = []
    
    for f in backup_dir.glob("*.tar.gz"):
        try:
            stat = f.stat()
            name = f.name
            
            world_part = name.rsplit("_", 2)[0] if "_" in name else name.replace(".tar.gz", "")
            
            if world_name and world_part != world_name:
                continue
            
            backups.append({
                "name": name,
                "world": world_part,
                "path": str(f),
                "size_mb": stat.st_size / (1024 * 1024),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            continue
    
    backups.sort(key=lambda x: x["created"], reverse=True)
    return backups


def restore_backup(
    backup_path: Path,
    world_name: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> bool:
    """Restore a world from backup.
    
    Args:
        backup_path: Path to backup file
        world_name: Name for restored world (default: extract from backup)
        cwd: Working directory
        
    Returns:
        True if successful
    """
    if cwd is None:
        cwd = CWD
    
    if not backup_path.exists():
        log.error(f"Backup not found: {backup_path}")
        return False
    
    if world_name is None:
        world_name = backup_path.stem.rsplit("_", 2)[0]
    
    target_path = cwd / world_name
    
    if target_path.exists():
        backup_target = cwd / f"{world_name}_old"
        if backup_target.exists():
            shutil.rmtree(backup_target)
        target_path.rename(backup_target)
        log.warning(f"Moved existing world to {backup_target}")
    
    try:
        log_event("BACKUP", f"Restoring from {backup_path.name}")
        
        import tarfile
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(cwd)
        
        log_event("BACKUP", f"Restored world: {world_name}")
        return True
        
    except Exception as e:
        log.error(f"Restore failed: {e}")
        return False


def cleanup_old_backups(
    keep_count: int = 7,
    backup_dir: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> int:
    """Clean up old backups, keeping only the most recent N.
    
    Args:
        keep_count: Number of backups to keep per world
        backup_dir: Directory to clean
        cwd: Working directory
        
    Returns:
        Number of backups deleted
    """
    if cwd is None:
        cwd = CWD
    
    if backup_dir is None:
        backup_dir = cwd / "backups"
    
    if not backup_dir.exists():
        return 0
    
    backups_by_world: Dict[str, List[Path]] = {}
    
    for f in backup_dir.glob("*.tar.gz"):
        world_name = f.stem.rsplit("_", 2)[0]
        backups_by_world.setdefault(world_name, []).append(f)
    
    deleted = 0
    
    for world_name, backups in backups_by_world.items():
        backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        for old_backup in backups[keep_count:]:
            try:
                old_backup.unlink()
                deleted += 1
                log.info(f"Deleted old backup: {old_backup.name}")
            except Exception as e:
                log.warning(f"Failed to delete {old_backup.name}: {e}")
    
    return deleted


__all__ = [
    "backup_world",
    "list_backups",
    "restore_backup",
    "cleanup_old_backups",
    "get_current_world",
]
