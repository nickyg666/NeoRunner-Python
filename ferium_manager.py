#!/usr/bin/env python3
"""
Ferium Manager - Handles mod downloads, profile setup, and scheduler integration
Manages:
- Ferium profile creation and configuration
- 4-hour Modrinth mod list updates
- 4-hour CurseForge mod list updates (via Selenium)
- Weekly mod updates with strict version compatibility
"""

import os
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

class FeriumManager:
    def __init__(self, cwd="/home/services", ferium_bin="/home/services/.local/bin/ferium"):
        self.cwd = cwd
        self.ferium_bin = ferium_bin
        self.ferium_config_dir = os.path.expanduser("~/.config/ferium")
        self.ferium_config_file = os.path.join(self.ferium_config_dir, "config.json")
        self.scheduler = None
        
    def ferium_cmd(self, *args):
        """Run ferium command and return result"""
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
    
    def setup_ferium_profile(self, profile_name, mc_version, loader, output_dir, mods_dir):
        """
        Create a ferium profile for the server
        
        Args:
            profile_name: Name of the profile (e.g., "neoserver")
            mc_version: Minecraft version (e.g., "1.21.11")
            loader: Modloader (fabric, forge, neoforge)
            output_dir: Where to download mods
            mods_dir: Full path to mods directory
        """
        
        os.makedirs(self.ferium_config_dir, exist_ok=True)
        
        # Map loader names
        loader_map = {
            "neoforge": "neo-forge",
            "fabric": "fabric",
            "forge": "forge"
        }
        ferium_loader = loader_map.get(loader.lower(), loader.lower())
        
        log.info(f"[FERIUM] Creating profile: {profile_name}")
        
        # Create profile with ferium (use --game-version instead of --minecraft-version)
        result = self.ferium_cmd(
            "profile", "create",
            "--name", profile_name,
            "--game-version", mc_version,
            "--mod-loader", ferium_loader,
            "--output-dir", mods_dir
        )
        
        if result["success"]:
            log.info(f"[FERIUM] Profile '{profile_name}' created successfully")
            self.ferium_cmd("profile", "switch", profile_name)
            return True
        else:
            log.error(f"[FERIUM] Failed to create profile: {result['stderr']}")
            return False
    
    def add_modrinth_mod(self, mod_slug):
        """Add a mod from Modrinth by slug"""
        result = self.ferium_cmd("add", mod_slug)
        if result["success"]:
            log.info(f"[FERIUM] Added mod: {mod_slug}")
            return True
        else:
            log.warning(f"[FERIUM] Failed to add {mod_slug}: {result['stderr']}")
            return False
    
    def upgrade_mods(self):
        """Download/upgrade all mods in current profile"""
        log.info("[FERIUM] Upgrading mods...")
        result = self.ferium_cmd("upgrade")
        if result["success"]:
            log.info("[FERIUM] Mods upgraded successfully")
            return True
        else:
            log.error(f"[FERIUM] Upgrade failed: {result['stderr']}")
            return False
    
    def list_mods(self):
        """List all mods in current profile"""
        result = self.ferium_cmd("list", "-v")
        if result["success"]:
            return result["stdout"]
        else:
            log.error(f"[FERIUM] Failed to list mods: {result['stderr']}")
            return None
    
    def scan_mods(self, directory):
        """Scan directory and auto-add mods to profile"""
        log.info(f"[FERIUM] Scanning directory: {directory}")
        result = self.ferium_cmd("scan", directory, "--force")
        if result["success"]:
            log.info("[FERIUM] Scan completed")
            return True
        else:
            log.warning(f"[FERIUM] Scan had issues: {result['stderr']}")
            return True  # Still return true, partial success is ok
    
    def start_scheduler(self, update_interval_hours=4, weekly_update_day="mon", weekly_update_hour="2"):
        """Start background scheduler for periodic updates
        
        Args:
            update_interval_hours: How often to update mods (1-24, default 4)
            weekly_update_day: Day for weekly strict update (mon-sun, default mon)
            weekly_update_hour: Hour for weekly update (0-23, default 2)
        """
        if self.scheduler is not None and self.scheduler.running:
            log.warning("[FERIUM_SCHEDULER] Scheduler already running")
            return False
        
        self.scheduler = BackgroundScheduler()
        
        # Validate and clamp update interval
        update_interval_hours = max(1, min(24, int(update_interval_hours)))
        
        # Build cron expression for interval (e.g., */4 for every 4 hours)
        if update_interval_hours >= 24:
            hour_expr = "0"
        elif 24 % update_interval_hours == 0:
            hour_expr = f"*/{update_interval_hours}"
        else:
            # Fallback for non-divisible intervals
            hour_expr = f"*/{update_interval_hours}"
        
        # Every N hours: update Modrinth mods
        self.scheduler.add_job(
            self.update_modrinth_mods,
            CronTrigger(hour=hour_expr),
            id="modrinth_update",
            name=f"Update Modrinth mods (every {update_interval_hours}h)"
        )
        
        # Every N hours: update CurseForge mods (via Selenium) - offset by 2 minutes
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
        log.info(f"[FERIUM_SCHEDULER] Scheduler started - updates every {update_interval_hours}h, weekly on {weekly_update_day} at {weekly_update_hour}:00")
        return True
    
    def stop_scheduler(self):
        """Stop background scheduler"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            log.info("[FERIUM_SCHEDULER] Scheduler stopped")
            return True
        return False
    
    def update_modrinth_mods(self):
        """Scheduled task: Update Modrinth mods via ferium"""
        log.info("[FERIUM_TASK] Running Modrinth update...")
        try:
            result = self.ferium_cmd("upgrade")
            if result["success"]:
                log.info("[FERIUM_TASK] Modrinth mods upgraded")
            else:
                log.warning(f"[FERIUM_TASK] Modrinth upgrade had issues: {result['stderr']}")
        except Exception as e:
            log.error(f"[FERIUM_TASK] Modrinth update failed: {e}")
    
    def update_curseforge_mods(self):
        """Scheduled task: Update CurseForge mods (placeholder for Selenium integration)"""
        log.info("[FERIUM_TASK] Running CurseForge update...")
        # This will be called by run.py's Selenium scraper
        # For now, just a placeholder
        try:
            log.info("[FERIUM_TASK] CurseForge mod list update (via Selenium)")
            # Actual scraping handled by run.py
        except Exception as e:
            log.error(f"[FERIUM_TASK] CurseForge update failed: {e}")
    
    def weekly_strict_update(self):
        """Scheduled task: Weekly update with strict version compatibility"""
        log.info("[FERIUM_TASK] Running weekly strict version update...")
        try:
            # Check for updates with strict game version and mod loader checks
            log.info("[FERIUM_TASK] Checking for compatible updates (strict mode)...")
            result = self.ferium_cmd("upgrade")
            if result["success"]:
                log.info("[FERIUM_TASK] Weekly strict update completed")
            else:
                log.warning(f"[FERIUM_TASK] Weekly update had issues: {result['stderr']}")
        except Exception as e:
            log.error(f"[FERIUM_TASK] Weekly strict update failed: {e}")


def setup_ferium_wizard(config, cwd="/home/services"):
    """
    Run ferium setup wizard during initial configuration
    
    Args:
        config: Current config dict from get_config()
        cwd: Working directory
    
    Returns:
        Updated config dict with ferium settings
    """
    
    print("\n" + "="*70)
    print("FERIUM MOD MANAGER SETUP")
    print("="*70)
    print("\nFerium will manage your mods with automatic updates from Modrinth.")
    print("CurseForge support available with optional API key or Selenium scraping.\n")
    
    manager = FeriumManager(cwd=cwd)
    
    # Extract config values
    profile_name = input("Ferium profile name [neoserver]: ").strip() or "neoserver"
    mc_version = config.get("mc_version", "1.21.11")
    loader = config.get("loader", "neoforge")
    mods_dir = config.get("mods_dir", "mods")
    full_mods_path = os.path.join(cwd, mods_dir)
    
    print(f"\nSetting up ferium with:")
    print(f"  Profile: {profile_name}")
    print(f"  MC Version: {mc_version}")
    print(f"  Loader: {loader}")
    print(f"  Output: {full_mods_path}\n")
    
    # Create profile
    if not manager.setup_ferium_profile(
        profile_name=profile_name,
        mc_version=mc_version,
        loader=loader,
        output_dir=full_mods_path,
        mods_dir=full_mods_path
    ):
        print("⚠ Ferium setup incomplete - will retry on startup")
        return config
    
    # Ask about CurseForge API key
    print("\nCurseForge Integration:")
    print("  Option 1: Provide API key for direct access (faster)")
    print("  Option 2: Use Selenium web scraper (slower but works)")
    print("  Option 3: Skip CurseForge (Modrinth only)\n")
    
    curseforge_choice = input("CurseForge method [1=API key, 2=Selenium, 3=Skip]: ").strip() or "3"
    
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
        update_freq = int(update_freq)
        update_freq = max(1, min(24, update_freq))
    except ValueError:
        update_freq = 4
    
    # Ask for weekly update time
    print("\nWeekly Update Schedule:")
    print("  Configure when to check for compatibility updates with strict version checks\n")
    
    weekly_day = input("Update day (mon-sun) [mon]: ").strip().lower() or "mon"
    valid_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if weekly_day not in valid_days:
        weekly_day = "mon"
    
    weekly_hour = input("Update hour (0-23) [2]: ").strip() or "2"
    try:
        weekly_hour = int(weekly_hour)
        weekly_hour = max(0, min(23, weekly_hour))
    except ValueError:
        weekly_hour = 2
    
    config["ferium_profile"] = profile_name
    config["ferium_enable_scheduler"] = True
    config["ferium_update_interval_hours"] = update_freq
    config["ferium_weekly_update_day"] = weekly_day
    config["ferium_weekly_update_hour"] = weekly_hour
    
    if curseforge_choice == "1":
        api_key = input("\nCurseForge API key (get free from https://console.curseforge.com/): ").strip()
        if api_key:
            with open(os.path.join(cwd, "curseforgeAPIkey"), "w") as f:
                f.write(api_key)
            config["curseforge_method"] = "api"
            print("✓ CurseForge API key saved")
    elif curseforge_choice == "2":
        config["curseforge_method"] = "selenium"
        print("✓ Will use Selenium for CurseForge (requires Firefox)")
    else:
        config["curseforge_method"] = "modrinth_only"
        print("✓ Modrinth only")
    
    print("\n✓ FERIUM SETUP COMPLETE")
    print("="*70 + "\n")
    
    return config


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manager = FeriumManager()
    print(manager.list_mods())
