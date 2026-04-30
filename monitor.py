#!/usr/bin/env python3
"""NeoRunner Dashboard and Server Monitor - Continual health checking and self-healing."""

import os
import sys
import time
import subprocess
import requests
import logging
from pathlib import Path
from datetime import datetime

ROOT = Path("/home/host/neorunner")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(ROOT / "monitor.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DASHBOARD_URL = "http://192.168.0.150:8000"
SERVER_PORT = 1234
CHECK_INTERVAL = 15
MAX_RESTARTS = 5
RESTART_COOLDOWN = 30

restart_count = 0
last_server_start = 0


def check_dashboard():
    """Check if dashboard is responding."""
    try:
        r = requests.get(f"{DASHBOARD_URL}/api/status", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning(f"Dashboard not responding: {e}")
    return None


def check_server_running():
    """Check if Minecraft server is actually running (Java process)."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "java.*neoforge|java.*server.jar"],
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except:
        return False


def start_dashboard():
    """Start the dashboard if not running."""
    global restart_count
    
    log.info("Starting dashboard...")
    try:
        subprocess.Popen(
            ["python3", "start_dashboard.py"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(3)
        restart_count += 1
        return True
    except Exception as e:
        log.error(f"Failed to start dashboard: {e}")
        return False


def start_server():
    """Start the Minecraft server."""
    global last_server_start
    
    log.info("Starting Minecraft server...")
    try:
        r = requests.post(f"{DASHBOARD_URL}/api/server/start", timeout=10)
        last_server_start = time.time()
        return r.json().get("success", False)
    except Exception as e:
        log.error(f"Failed to start server: {e}")
        return False


def stop_server():
    """Stop the Minecraft server."""
    try:
        requests.post(f"{DASHBOARD_URL}/api/server/stop", timeout=10)
        time.sleep(2)
        return True
    except:
        pass


def get_status():
    """Get full system status."""
    data = check_dashboard()
    if not data:
        return {"dashboard": False, "server": False, "error": "no dashboard"}
    
    server_running = data.get("running", False)
    actual_running = check_server_running() if server_running else False
    
    return {
        "dashboard": True,
        "server": server_running,
        "server_actual": actual_running,
        "loader": data.get("loader", "?"),
        "mc_version": data.get("mc_version", "?"),
        "status_detail": data.get("status_detail", "?"),
        "world_version": data.get("world_version", "?"),
    }


def get_correct_mc_version(loader):
    """Get the correct Minecraft version for the loader."""
    for entry in os.listdir(ROOT / "libraries" / "net" / "neoforged" / "neoforge"):
        if entry.startswith("21.") or entry.startswith("26."):
            nf_ver = entry
            try:
                from neorunner_pkg.version import get_latest_minecraft_version
                mc_ver = get_latest_minecraft_version()
                return mc_ver
            except:
                return "1.21.11"
    return "1.21.11"


def heal():
    """Attempt to heal the system."""
    global restart_count, last_server_start
    
    status = get_status()
    log.info(f"System status: {status}")
    
    if not status.get("dashboard"):
        log.warning("Dashboard down, restarting...")
        start_dashboard()
        return
    
    server_actual = status.get("server_actual", False)
    if not server_actual:
        log.warning("Server process not running, attempting start...")
        
        if time.time() - last_server_start < RESTART_COOLDOWN:
            log.warning("In cooldown, waiting...")
            return
        
        start_server()


def monitor_loop():
    """Main monitoring loop."""
    global restart_count
    
    log.info("=" * 50)
    log.info("NeoRunner Monitor Started")
    log.info(f"Dashboard: {DASHBOARD_URL}")
    log.info("=" * 50)
    
    consecutive_errors = 0
    
    while True:
        try:
            status = get_status()
            
            if not status.get("dashboard"):
                consecutive_errors += 1
                log.warning(f"Dashboard check failed ({consecutive_errors}/5)")
                
                if consecutive_errors >= 2:
                    start_dashboard()
                    consecutive_errors = 0
            else:
                consecutive_errors = 0
            
            if status.get("dashboard"):
                health = "✓" if status.get("server_actual") else "✗"
                log.info(f"Health: dashboard=✓ server={health} | {status.get('loader')} {status.get('mc_version')}")
            
            heal()
            
        except KeyboardInterrupt:
            log.info("Monitor stopped by user")
            break
        except Exception as e:
            log.error(f"Monitor error: {e}")
        
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    monitor_loop()