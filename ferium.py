"""
Ferium Manager - Handles mod downloads, profile setup, and scheduler integration.
Manages Modrinth and CurseForge mod updates with automatic scheduling.
"""

from __future__ import annotations

import os
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

from .config import ServerConfig, load_cfg
from .constants import CWD
from .log import log_event

log = logging.getLogger(__name__)


class FeriumManager:
    """Manages ferium mod manager integration."""
    
    def __init__(self, cwd: Optional[Path] = None, ferium_bin: Optional[str] = None):
        self.cwd = cwd or CWD
        self.ferium_bin = ferium_bin or str(self.cwd / ".local" / "bin" / "ferium")
        self.ferium_config_dir = Path.home() / ".config" / "ferium"
        self.ferium_config_file = self.ferium_config_dir / "config.json"
        self.scheduler: Optional[Any] = None
        
    def ferium_cmd(self, *args) -> Dict[str, Any]:
        """Run ferium command and return result."""
        cmd = [self.ferium_bin] + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": ""
            }
    
    def setup_ferium_profile(
        self, 
        profile_name: str, 
        mc_version: str, 
        loader: str, 
        output_dir: Path
    ) -> bool:
        """Create a ferium profile for the server."""
        self.ferium_config_dir.mkdir(parents=True, exist_ok=True)
        
        # Map loader names
        loader_map = {
            "neoforge": "neo-forge",
            "fabric": "fabric",
            "forge": "forge"
        }
        ferium_loader = loader_map.get(loader.lower(), loader.lower())
        
        log.info(f"[FERIUM] Creating profile: {profile_name}")
        
        # Create profile
        result = self.ferium_cmd(
            "profile", "create",
            "--name", profile_name,
            "--game-version", mc_version,
            "--mod-loader", ferium_loader,
            "--output-dir", str(output_dir)
        )
        
        if result["success"]:
            log.info(f"[FERIUM] Profile '{profile_name}' created successfully")
            self.ferium_cmd("profile", "switch", profile_name)
            return True
        else:
            log.error(f"[FERIUM] Failed to create profile: {result.get('stderr', 'Unknown error')}")
            return False
    
    def add_mod(self, mod_slug: str) -> bool:
        """Add a mod from Modrinth by slug."""
        result = self.ferium_cmd("add", mod_slug)
        if result["success"]:
            log.info(f"[FERIUM] Added mod: {mod_slug}")
            return True
        else:
            log.warning(f"[FERIUM] Failed to add {mod_slug}: {result.get('stderr', 'Unknown error')}")
            return False
    
    def upgrade_mods(self) -> bool:
        """Download/upgrade all mods in current profile."""
        log.info("[FERIUM] Upgrading mods...")
        result = self.ferium_cmd("upgrade")
        if result["success"]:
            log.info("[FERIUM] Mods upgraded successfully")
            return True
        else:
            log.error(f"[FERIUM] Upgrade failed: {result.get('stderr', 'Unknown error')}")
            return False
    
    def list_mods(self) -> Optional[str]:
        """List all mods in current profile."""
        result = self.ferium_cmd("list", "-v")
        if result["success"]:
            return result["stdout"]
        else:
            log.error(f"[FERIUM] Failed to list mods: {result.get('stderr', 'Unknown error')}")
            return None
    
    def scan_mods(self, directory: Path) -> bool:
        """Scan directory and auto-add mods to profile."""
        log.info(f"[FERIUM] Scanning directory: {directory}")
        result = self.ferium_cmd("scan", str(directory), "--force")
        if result["success"]:
            log.info("[FERIUM] Scan completed")
            return True
        else:
            log.warning(f"[FERIUM] Scan had issues: {result.get('stderr', 'Unknown error')}")
            return True  # Still return true, partial success is ok
    
    def start_scheduler(
        self, 
        update_interval_hours: int = 4,
        weekly_update_day: str = "mon", 
        weekly_update_hour: int = 2
    ) -> bool:
        """Start background scheduler for periodic updates."""
        if not APSCHEDULER_AVAILABLE:
            log.warning("[FERIUM_SCHEDULER] APScheduler not available")
            return False
        
        if self.scheduler is not None and self.scheduler.running:
            log.warning("[FERIUM_SCHEDULER] Scheduler already running")
            return False
        
        self.scheduler = BackgroundScheduler()
        
        # Validate and clamp update interval
        update_interval_hours = max(1, min(24, int(update_interval_hours)))
        
        # Build cron expression for interval
        if update_interval_hours >= 24:
            hour_expr = "0"
        elif 24 % update_interval_hours == 0:
            hour_expr = f"*/{update_interval_hours}"
        else:
            hour_expr = f"*/{update_interval_hours}"
        
        # Every N hours: update Modrinth mods
        self.scheduler.add_job(
            self.update_modrinth_mods,
            CronTrigger(hour=hour_expr),
            id="modrinth_update",
            name=f"Update Modrinth mods (every {update_interval_hours}h)"
        )
        
        # Every N hours: update CurseForge mods - offset by 2 minutes
        self.scheduler.add_job(
            self.update_curseforge_mods,
            CronTrigger(hour=hour_expr, minute="2"),
            id="curseforge_update",
            name=f"Update CurseForge mods (every {update_interval_hours}h)"
        )
        
        # Weekly: strict version update check
        self.scheduler.add_job(
            self.weekly_strict_update,
            CronTrigger(day_of_week=weekly_update_day, hour=weekly_update_hour),
            id="weekly_strict_update",
            name=f"Weekly strict version update ({weekly_update_day} at {weekly_update_hour}:00)"
        )
        
        self.scheduler.start()
        log.info(f"[FERIUM_SCHEDULER] Scheduler started - updates every {update_interval_hours}h")
        return True
    
    def stop_scheduler(self) -> bool:
        """Stop background scheduler."""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            log.info("[FERIUM_SCHEDULER] Scheduler stopped")
            return True
        return False
    
    def update_modrinth_mods(self):
        """Scheduled task: Update Modrinth mods via ferium."""
        log_event("FERIUM_TASK", "Running Modrinth update...")
        try:
            result = self.ferium_cmd("upgrade")
            if result["success"]:
                log_event("FERIUM_TASK", "Modrinth mods upgraded")
            else:
                log_event("FERIUM_TASK", f"Modrinth upgrade had issues: {result.get('stderr', '')}")
        except Exception as e:
            log_event("FERIUM_TASK", f"Modrinth update failed: {e}")
    
    def update_curseforge_mods(self):
        """Scheduled task: Update CurseForge mods."""
        log_event("FERIUM_TASK", "Running CurseForge update...")
        # Placeholder - actual CurseForge scraping handled elsewhere
        pass
    
    def weekly_strict_update(self):
        """Scheduled task: Weekly update with strict version compatibility."""
        log_event("FERIUM_TASK", "Running weekly strict version update...")
        try:
            result = self.ferium_cmd("upgrade")
            if result["success"]:
                log_event("FERIUM_TASK", "Weekly strict update completed")
            else:
                log_event("FERIUM_TASK", f"Weekly update had issues: {result.get('stderr', '')}")
        except Exception as e:
            log_event("FERIUM_TASK", f"Weekly strict update failed: {e}")


def setup_ferium_wizard(config: ServerConfig, cwd: Optional[Path] = None) -> ServerConfig:
    """Run ferium setup wizard during initial configuration."""
    if cwd is None:
        cwd = CWD
    
    print("\n" + "="*70)
    print("FERIUM MOD MANAGER SETUP")
    print("="*70)
    print("\nFerium will manage your mods with automatic updates from Modrinth.")
    print("CurseForge support available with optional API key.\n")
    
    manager = FeriumManager(cwd=cwd)
    
    # Extract config values
    profile_name = input("Ferium profile name [neoserver]: ").strip() or "neoserver"
    mc_version = config.mc_version
    loader = config.loader
    mods_dir = cwd / config.mods_dir
    
    print(f"\nSetting up ferium with:")
    print(f"  Profile: {profile_name}")
    print(f"  MC Version: {mc_version}")
    print(f"  Loader: {loader}")
    print(f"  Output: {mods_dir}\n")
    
    # Create profile
    if not manager.setup_ferium_profile(
        profile_name=profile_name,
        mc_version=mc_version,
        loader=loader,
        output_dir=mods_dir
    ):
        print("⚠ Ferium setup incomplete - will retry on startup")
        return config
    
    # Ask for update frequency
    print("\nMod Update Frequency:")
    print("  1 = every 1 hour")
    print("  2 = every 2 hours")
    print("  4 = every 4 hours (default)")
    print("  6 = every 6 hours")
    print("  12 = every 12 hours")
    print("  24 = once daily\n")
    
    update_freq = input("Update frequency [4]: ").strip() or "4"
    try:
        update_freq = max(1, min(24, int(update_freq)))
    except ValueError:
        update_freq = 4
    
    # Ask for weekly update time
    print("\nWeekly Update Schedule:")
    weekly_day = input("Update day (mon-sun) [mon]: ").strip().lower() or "mon"
    valid_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if weekly_day not in valid_days:
        weekly_day = "mon"
    
    weekly_hour = input("Update hour (0-23) [2]: ").strip() or "2"
    try:
        weekly_hour = max(0, min(23, int(weekly_hour)))
    except ValueError:
        weekly_hour = 2
    
    config.ferium_profile = profile_name
    config.ferium_enable_scheduler = True
    config.ferium_update_interval_hours = update_freq
    config.ferium_weekly_update_day = weekly_day
    config.ferium_weekly_update_hour = weekly_hour
    
    print("\n✓ FERIUM SETUP COMPLETE")
    print("="*70 + "\n")
    
    return config
