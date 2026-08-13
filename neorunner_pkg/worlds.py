"""
World management for NeoRunner.
Handles world scanning, switching, backup, and restore operations.
"""


import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_cfg
from .constants import CWD
from .log import log_event
from .nbt_parser import get_world_version


def get_current_world() -> str:
    """Get the currently configured world name from server.properties."""
    props_path = CWD / "server.properties"
    if not props_path.exists():
        return "world"
    
    with open(props_path) as f:
        for line in f:
            if line.strip().startswith("level-name="):
                return line.strip().split("=", 1)[1]
    
    return "world"


def remediate_world_lock(world_dir: Path | None = None) -> dict[str, Any]:
    """Fix broken permissions/locks on a world folder's level.dat.

    Minecraft's level.dat occasionally ends up root-owned, read-only (0o600
    owned by a different uid) or with a stale ``session.lock`` that blocks
    the world from opening. This runs system-level commands to repair the
    condition so the server can boot without crashing.

    Args:
        world_dir: World folder (defaults to the current configured world).

    Returns:
        A dict describing what was fixed.
    """
    if world_dir is None:
        world_dir = CWD / get_current_world()

    result: dict[str, Any] = {
        "world": str(world_dir),
        "fixed_permissions": False,
        "removed_stale_lock": False,
        "errors": [],
    }

    if not world_dir.exists():
        return result

    level_dat = world_dir / "level.dat"

    # 1. level.dat permission remediation (chown/chmod to the running user).
    try:
        uid = os.getuid()
        gid = os.getgid()

        def _repair_perms(path: Path) -> bool:
            """Try to make ``path`` owned+writable by the current user."""
            try:
                os.chown(path, uid, gid)
            except PermissionError:
                # Owned by another user (e.g. root) -> escalate via sudo.
                try:
                    subprocess.run(
                        ["sudo", "chown", f"{uid}:{gid}", str(path)], check=False,
                        capture_output=True, timeout=20,
                    )
                    subprocess.run(
                        ["sudo", "chmod", "664", str(path)], check=False,
                        capture_output=True, timeout=20,
                    )
                except Exception as e:
                    result["errors"].append(f"sudo chown {path}: {e}")
                    return False
            try:
                os.chmod(path, 0o664)
            except PermissionError as e:
                result["errors"].append(f"chmod {path}: {e}")
                return False
            # Verify it's now readable & writable by us.
            return os.access(path, os.R_OK | os.W_OK)

        if level_dat.exists():
            if not os.access(level_dat, os.R_OK | os.W_OK):
                if _repair_perms(level_dat):
                    result["fixed_permissions"] = True
                    log_event("WORLD_LOCK", f"Repaired level.dat permissions on {world_dir.name}")
                else:
                    result["errors"].append(f"could not repair {level_dat}")
            # Also make sure the containing dir is traversable.
            if not os.access(world_dir, os.R_OK | os.X_OK):
                os.chmod(world_dir, 0o755)

        # 2. Stale session.lock removal (from crashes/forced kills).
        for lock_name in ("session.lock", "session.lock.old", "level.dat_lock"):
            lock = world_dir / lock_name
            if lock.exists():
                try:
                    lock.unlink()
                    result["removed_stale_lock"] = True
                    log_event("WORLD_LOCK", f"Removed stale lock {lock_name} in {world_dir.name}")
                except PermissionError:
                    try:
                        subprocess.run(
                            ["sudo", "rm", "-f", str(lock)], check=False,
                            capture_output=True, timeout=20,
                        )
                        result["removed_stale_lock"] = True
                        log_event("WORLD_LOCK", f"Removed stale lock {lock_name} (via sudo)")
                    except Exception as e:
                        result["errors"].append(f"could not remove {lock}: {e}")
    except Exception as e:
        result["errors"].append(f"remediation failed: {e}")

    return result


def auto_move_incompatible_world(
    world_dir: Path | None = None,
    server_mc_version: str | None = None,
    loader: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Move a world whose version is incompatible with the running server.

    When a world folder's ``level.dat`` says it belongs to a different
    Minecraft version, booting will crash. This detects the world's version,
    relocates the whole folder to ``worlds_archive/mc-<version>/<loader>/``,
    and resets ``level-name`` so the server generates a fresh world.

    Args:
        world_dir: World folder to inspect (defaults to current world).
        server_mc_version: Server's MC version (defaults to config).
        loader: Loader name for the archive path (defaults to config).
        cwd: Server root (defaults to CWD).

    Returns:
        Dict with ``moved``, ``world_version``, ``server_version``,
        ``destination`` and any ``errors``.
    """
    if cwd is None:
        cwd = CWD
    if world_dir is None:
        world_dir = cwd / get_current_world()
    if server_mc_version is None or loader is None:
        try:
            cfg = load_cfg()
            server_mc_version = server_mc_version or cfg.mc_version
            loader = loader or cfg.loader
        except Exception:
            pass

    result: dict[str, Any] = {
        "moved": False,
        "world_version": None,
        "server_version": server_mc_version,
        "destination": None,
        "errors": [],
    }

    level_dat = world_dir / "level.dat"
    if not world_dir.exists() or not level_dat.exists():
        return result

    # Read the world version (repair perms first so we can even read it).
    remediate_world_lock(world_dir)
    version_info = get_world_version(level_dat)
    world_version = version_info.get("version")
    if not world_version or world_version in ("unknown", "unknown"):
        result["errors"].append(f"could not determine world version: {version_info.get('error', 'n/a')}")
        # If we can't read it, still try to read as current version but log a warning.
        return result

    result["world_version"] = world_version

    if server_mc_version and world_version != server_mc_version:
        # Incompatible -> relocate into worlds_archive/mc-<version>/<loader>/
        safe_version = re.sub(r"[^0-9A-Za-z.\-_]", "_", str(world_version)) or "unknown"
        archive_root = cwd / "worlds_archive" / f"mc-{safe_version}"
        if loader:
            archive_root = archive_root / str(loader).lower()
        archive_root.mkdir(parents=True, exist_ok=True)

        target = archive_root / world_dir.name
        try:
            if target.exists():
                target = archive_root / f"{world_dir.name}_{int(time.time())}"
            world_dir.rename(target)
            result["moved"] = True
            result["destination"] = str(target)
            log_event(
                "WORLD_ARCHIVE",
                f"World {world_dir.name} is MC {world_version} (server is {server_mc_version}) - "
                f"moved to {target.relative_to(cwd)}; fresh world will generate",
            )

            # Reset level-name so a new world generates on next boot.
            props_path = cwd / "server.properties"
            if props_path.exists():
                lines = []
                found = False
                with open(props_path, "r") as f:
                    for line in f:
                        if line.strip().startswith("level-name="):
                            lines.append("level-name=world\n")
                            found = True
                        else:
                            lines.append(line)
                if not found:
                    lines.append("level-name=world\n")
                with open(props_path, "w") as f:
                    f.writelines(lines)
        except Exception as e:
            result["errors"].append(f"move failed: {e}")
    else:
        log_event("WORLD_ARCHIVE", f"World {world_dir.name} is compatible (MC {world_version})")

    return result



def scan_worlds(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Scan for world folders (folders containing level.dat)."""
    if cwd is None:
        cwd = CWD
    
    manager = WorldManager(cwd)
    return manager.scan_worlds()


def switch_world(world_name: str, force: bool = False, cwd: Path | None = None) -> tuple[bool, str]:
    """Switch to a different world by updating server.properties."""
    if cwd is None:
        cwd = CWD
    
    manager = WorldManager(cwd)
    return manager.switch_world(world_name, force)


class WorldManager:
    """Manages Minecraft worlds."""
    
    def __init__(self, cwd: Path | None = None):
        self.cwd = cwd or CWD
        self.backup_dir = self.cwd / "backups"
        self.backup_dir.mkdir(exist_ok=True)
    
    def scan_worlds(self) -> list[dict[str, Any]]:
        """Scan for world folders (folders containing level.dat)."""
        cfg = load_cfg()
        server_mc_version = cfg.mc_version
        worlds = []
        
        try:
            for entry in os.listdir(self.cwd):
                entry_path = self.cwd / entry
                if entry_path.is_dir() and not entry.startswith("."):
                    level_dat = entry_path / "level.dat"
                    if level_dat.exists():
                        try:
                            stat = entry_path.stat()
                            
                            # Get world version info
                            try:
                                version_info = get_world_version(level_dat)
                                world_version = version_info.get("version")
                                compatible = world_version == server_mc_version if world_version else True
                            except Exception:
                                version_info = {}
                                world_version = None
                                compatible = True
                            
                            # Calculate size
                            size = 0
                            for dirpath, _, filenames in os.walk(entry_path):
                                for f in filenames:
                                    try:
                                        size += os.path.getsize(os.path.join(dirpath, f))
                                    except Exception:
                                        pass
                            
                            worlds.append({
                                "name": entry,
                                "path": str(entry_path),
                                "size": size,
                                "size_mb": round(size / (1024*1024), 2),
                                "modified": stat.st_mtime,
                                "mc_version": world_version,
                                "compatible": compatible
                            })
                        except Exception as e:
                            worlds.append({
                                "name": entry,
                                "path": str(entry_path),
                                "mc_version": None,
                                "compatible": True,
                                "error": str(e)
                            })
        except Exception as e:
            log_event("WORLD_SCAN_ERROR", f"Failed to scan worlds: {e}")
        
        return sorted(worlds, key=lambda w: w.get("name", ""))
    
    def get_current_world(self) -> str:
        """Get the currently configured world name from server.properties."""
        props_path = self.cwd / "server.properties"
        if not props_path.exists():
            return "world"
        
        with open(props_path) as f:
            for line in f:
                if line.strip().startswith("level-name="):
                    return line.strip().split("=", 1)[1]
        
        return "world"
    
    def switch_world(self, world_name: str, force: bool = False) -> tuple[bool, str]:
        """Switch to a different world by updating server.properties."""
        props_path = self.cwd / "server.properties"
        if not props_path.exists():
            return False, "server.properties not found"
        
        world_path = self.cwd / world_name
        level_dat = world_path / "level.dat"
        if not level_dat.exists():
            return False, f"World '{world_name}' not found (no level.dat)"
        
        # Check version compatibility
        if not force:
            cfg = load_cfg()
            server_mc_version = cfg.mc_version
            try:
                version_info = get_world_version(level_dat)
                world_version = version_info.get("version")
                if world_version and world_version != server_mc_version:
                    return False, (
                        f"Version mismatch: world is MC {world_version}, "
                        f"server is MC {server_mc_version}. Use force=true to override."
                    )
            except Exception:
                pass
        
        # Update server.properties
        lines = []
        found = False
        with open(props_path, "r") as f:
            for line in f:
                if line.strip().startswith("level-name="):
                    lines.append(f"level-name={world_name}\n")
                    found = True
                else:
                    lines.append(line)
        
        if not found:
            lines.append(f"level-name={world_name}\n")
        
        with open(props_path, "w") as f:
            f.writelines(lines)
        
        log_event("WORLD_SWITCH", f"Switched to world: {world_name}")
        return True, f"World switched to '{world_name}'. Restart server to apply."
    
    def create_world(self, world_name: str, seed: str | None = None) -> tuple[bool, str]:
        """Create a new world."""
        world_path = self.cwd / world_name
        
        if world_path.exists():
            return False, f"World '{world_name}' already exists"
        
        try:
            # Create world directory
            world_path.mkdir(parents=True, exist_ok=True)
            
            # Create minimal level.dat
            # Note: In a real implementation, you'd create a proper level.dat
            # For now, we'll just create an empty marker
            (world_path / "level.dat").touch()
            
            log_event("WORLD_CREATE", f"Created world: {world_name}")
            return True, f"World '{world_name}' created"
        except Exception as e:
            return False, f"Failed to create world: {e}"
    
    def delete_world(self, world_name: str, force: bool = False) -> tuple[bool, str]:
        """Delete a world."""
        world_path = self.cwd / world_name
        
        if not world_path.exists():
            return False, f"World '{world_name}' not found"
        
        # Check if this is the current world
        current = self.get_current_world()
        if current == world_name and not force:
            return False, "Cannot delete current world. Switch worlds first or use force=true."
        
        try:
            # Create backup before deletion
            backup_result = self.backup_world(world_name)
            if not backup_result[0] and not force:
                return False, f"Failed to create backup before deletion: {backup_result[1]}"
            
            # Delete the world
            shutil.rmtree(world_path)
            
            log_event("WORLD_DELETE", f"Deleted world: {world_name}")
            return True, f"World '{world_name}' deleted (backup: {backup_result[1] if backup_result[0] else 'failed'})"
        except Exception as e:
            return False, f"Failed to delete world: {e}"
    
    def backup_world(self, world_name: str) -> tuple[bool, str]:
        """Create a backup of a world."""
        world_path = self.cwd / world_name
        
        if not world_path.exists():
            return False, f"World '{world_name}' not found"
        
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{world_name}_{timestamp}.tar.gz"
        backup_path = self.backup_dir / backup_name
        
        try:
            result = subprocess.run(
                ["tar", "-czf", str(backup_path), "-C", str(self.cwd), world_name], check=False,
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                log_event("WORLD_BACKUP", f"Backed up {world_name} to {backup_name}")
                return True, backup_name
            else:
                return False, result.stderr
        except Exception as e:
            return False, str(e)
    
    def restore_world(self, backup_name: str, world_name: str | None = None) -> tuple[bool, str]:
        """Restore a world from backup."""
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            return False, f"Backup '{backup_name}' not found"
        
        # Extract world name from backup name if not specified
        if not world_name:
            # Parse backup name: worldname_20240101_120000.tar.gz
            parts = backup_name.rsplit("_", 2)
            if len(parts) >= 3:
                world_name = parts[0]
            else:
                return False, "Could not determine world name from backup"
        
        world_path = self.cwd / world_name
        
        # Check if world already exists
        if world_path.exists():
            # Create backup of existing world
            backup_result = self.backup_world(world_name)
            if not backup_result[0]:
                return False, f"Cannot backup existing world: {backup_result[1]}"
            
            # Delete existing world
            shutil.rmtree(world_path)
        
        try:
            # Extract backup
            result = subprocess.run(
                ["tar", "-xzf", str(backup_path), "-C", str(self.cwd)], check=False,
                capture_output=True, text=True
            )
            
            if result.returncode == 0:
                log_event("WORLD_RESTORE", f"Restored {world_name} from {backup_name}")
                return True, f"World '{world_name}' restored from {backup_name}"
            else:
                return False, result.stderr
        except Exception as e:
            return False, str(e)
    
    def list_backups(self, world_name: str | None = None) -> list[dict[str, Any]]:
        """List available backups."""
        backups = []
        
        if not self.backup_dir.exists():
            return backups
        
        for backup_file in self.backup_dir.glob("*.tar.gz"):
            try:
                stat = backup_file.stat()
                
                # Parse backup name
                parts = backup_file.stem.rsplit("_", 2)
                if len(parts) >= 3:
                    backup_world = parts[0]
                else:
                    backup_world = "unknown"
                
                # Filter by world name if specified
                if world_name and backup_world != world_name:
                    continue
                
                backups.append({
                    "name": backup_file.name,
                    "world": backup_world,
                    "size": stat.st_size,
                    "size_mb": round(stat.st_size / (1024*1024), 2),
                    "created": stat.st_mtime,
                    "path": str(backup_file)
                })
            except Exception:
                pass
        
        return sorted(backups, key=lambda b: b["created"], reverse=True)
    
    def get_world_info(self, world_name: str) -> dict[str, Any]:
        """Get detailed information about a world."""
        world_path = self.cwd / world_name
        
        if not world_path.exists():
            return {"error": "World not found"}
        
        level_dat = world_path / "level.dat"
        
        info = {
            "name": world_name,
            "path": str(world_path),
            "exists": True,
        }
        
        if level_dat.exists():
            try:
                version_info = get_world_version(level_dat)
                info["mc_version"] = version_info.get("version")
                info["snapshot"] = version_info.get("snapshot", False)
                info["platform"] = version_info.get("platform", "main")
            except Exception as e:
                info["version_error"] = str(e)
        
        # Calculate size
        try:
            size = 0
            file_count = 0
            for dirpath, _, filenames in os.walk(world_path):
                for f in filenames:
                    try:
                        size += os.path.getsize(os.path.join(dirpath, f))
                        file_count += 1
                    except Exception:
                        pass
            
            info["size"] = size
            info["size_mb"] = round(size / (1024*1024), 2)
            info["file_count"] = file_count
        except Exception as e:
            info["size_error"] = str(e)
        
        # Check if this is the current world
        info["is_current"] = self.get_current_world() == world_name
        
        # List backups for this world
        info["backups"] = self.list_backups(world_name)
        
        return info
