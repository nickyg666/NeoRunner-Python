#!/home/services/neorunner_env/bin/python3
"""
Minecraft Modded Server - HTTP Mod Distribution via RCON
- Hosts mods on HTTP (with security checks)
- Auto-generates install scripts for Windows/Linux/Mac
- Daily world backups
- RCON messaging on player join
- Crash detection & auto-restart
- Full-featured hosting dashboard for server management
"""

import os, json, subprocess, sys, time, threading, logging, hashlib, urllib.request, urllib.error
from http.server import SimpleHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, quote as url_quote
from ferium_manager import FeriumManager, setup_ferium_wizard

# Loader abstraction classes
from loaders.neoforge import NeoForgeLoader
from loaders.forge import ForgeLoader
from loaders.fabric import FabricLoader

LOADER_CLASSES = {
    "neoforge": NeoForgeLoader,
    "forge": ForgeLoader,
    "fabric": FabricLoader,
}

def get_loader(cfg):
    """Factory: return the right loader instance for this config"""
    loader_name = cfg.get("loader", "neoforge").lower()
    cls = LOADER_CLASSES.get(loader_name)
    if cls is None:
        raise ValueError(f"Unknown loader: {loader_name}")
    return cls(cfg, cwd=CWD)

try:
    from flask import Flask
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Playwright stealth browser for CurseForge scraping (Cloudflare bypass)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    from playwright_stealth import Stealth
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# CurseForge scraper constants
CF_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
import re
import random

CWD = "/home/services"
CONFIG = os.path.join(CWD, "config.json")

# Setup logging to file and console
LOG_FILE = os.path.join(CWD, "live.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

def log_event(event_type, msg):
    """Log with event type tag"""
    log.info(f"[{event_type}] {msg}")

def run(cmd):
    """Execute shell command"""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def have(cmd):
    """Check if command exists"""
    return subprocess.run(f"which {cmd}", shell=True, capture_output=True).returncode == 0

def install_pkg(pkg):
    """Install package via apt/dnf/pacman"""
    if have("apt"):
        run(f"sudo apt update && sudo apt install -y {pkg}")
    elif have("dnf"):
        run(f"sudo dnf install -y {pkg}")
    elif have("pacman"):
        run(f"sudo pacman -Sy --noconfirm {pkg}")

def ensure_deps():
    """Verify system dependencies"""
    print("[BOOT] Checking prerequisites...")
    for pkg in ["tmux", "curl", "rsync", "unzip", "zip"]:
        if not have(pkg):
            print(f"[BOOT] Installing {pkg}...")
            install_pkg(pkg)
    
    if not have("java"):
        print("[BOOT] Installing OpenJDK 21...")
        install_pkg("openjdk-21-jre-headless")

def parse_props():
    """Parse server.properties file"""
    path = os.path.join(CWD, "server.properties")
    props = {}
    if os.path.exists(path):
        for line in open(path):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                props[k] = v
    return props

def download_loader(loader):
    """Verify modloader is available and return the startup command"""
    loader = loader.lower()
    
    if loader == "neoforge":
        neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
        if os.path.exists(neoforge_dir):
            log_event("LOADER", f"{loader} server environment ready (using @args files)")
            return True
        else:
            log_event("LOADER_ERROR", f"{loader} libraries not found at {neoforge_dir}")
            log_event("LOADER_ERROR", "Install NeoForge from https://neoforged.net")
            return False
    
    elif loader == "fabric":
        if os.path.exists(os.path.join(CWD, "fabric-server.jar")):
            log_event("LOADER", f"{loader} server JAR found")
            return True
        
        fabric_dir = os.path.join(CWD, "libraries", "net", "fabricmc")
        if os.path.exists(fabric_dir):
            log_event("LOADER", f"{loader} libraries found (need to build server JAR)")
            log_event("LOADER", f"{loader} libraries detected - download fabric-server.jar from https://fabricmc.net/use/server/")
            return False
        else:
            log_event("LOADER_ERROR", f"{loader} server JAR or libraries not found")
            log_event("LOADER_INFO", "Download from: https://fabricmc.net/use/server/")
            return False
    
    elif loader == "forge":
        if os.path.exists(os.path.join(CWD, "forge-server.jar")) or os.path.exists(os.path.join(CWD, "server.jar")):
            log_event("LOADER", f"{loader} server JAR found")
            return True
        else:
            log_event("LOADER_ERROR", f"{loader} server JAR not found")
            log_event("LOADER_INFO", "Download from: https://files.minecraftforge.net/")
            return False
    
    else:
        log_event("LOADER_ERROR", f"Unknown loader: {loader}")
        return False

def ensure_rcon_enabled(cfg):
    """Ensure RCON is enabled and configured in server.properties"""
    props_path = os.path.join(CWD, "server.properties")
    
    if not os.path.exists(props_path):
        log_event("RCON_SETUP", f"server.properties not found at {props_path}")
        return False
    
    # Read current properties
    with open(props_path, "r") as f:
        lines = f.readlines()
    
    # Track what we need to add/update
    rcon_enabled = False
    rcon_password_set = False
    rcon_port_set = False
    updated_lines = []
    
    rcon_pass = cfg.get("rcon_pass", "changeme")
    rcon_port = cfg.get("rcon_port", "25575")
    
    # Process existing lines
    for line in lines:
        line_lower = line.lower()
        
        if line_lower.startswith("enable-rcon"):
            updated_lines.append(f"enable-rcon=true\n")
            rcon_enabled = True
        elif line_lower.startswith("rcon.password"):
            updated_lines.append(f"rcon.password={rcon_pass}\n")
            rcon_password_set = True
        elif line_lower.startswith("rcon.port"):
            updated_lines.append(f"rcon.port={rcon_port}\n")
            rcon_port_set = True
        else:
            updated_lines.append(line)
    
    # Add missing RCON settings
    if not rcon_enabled:
        updated_lines.append(f"\nenable-rcon=true\n")
        rcon_enabled = True
    
    if not rcon_password_set:
        updated_lines.append(f"rcon.password={rcon_pass}\n")
        rcon_password_set = True
    
    if not rcon_port_set:
        updated_lines.append(f"rcon.port={rcon_port}\n")
        rcon_port_set = True
    
    # Write back updated properties
    with open(props_path, "w") as f:
        f.writelines(updated_lines)
    
    log_event("RCON_SETUP", f"Enabled RCON: password set, port={rcon_port}")
    return True


def detect_loader_from_disk():
    """Auto-detect which modloader is installed by scanning disk"""
    # Check NeoForge first
    neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
    if os.path.exists(neoforge_dir):
        versions = [d for d in os.listdir(neoforge_dir) if os.path.isdir(os.path.join(neoforge_dir, d))]
        if versions:
            return "neoforge"
    
    # Check Fabric
    fabric_dir = os.path.join(CWD, "libraries", "net", "fabricmc")
    if os.path.exists(fabric_dir) or os.path.exists(os.path.join(CWD, "fabric-server.jar")):
        return "fabric"
    
    # Check Forge
    if os.path.exists(os.path.join(CWD, "forge-server.jar")):
        return "forge"
    
    return None

def detect_mc_version_from_disk():
    """Try to detect MC version from installed files"""
    # Check NeoForge version dir naming (e.g., 21.11.38-beta -> MC 1.21.11)
    neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
    if os.path.exists(neoforge_dir):
        versions = [d for d in os.listdir(neoforge_dir) if os.path.isdir(os.path.join(neoforge_dir, d))]
        for v in sorted(versions, reverse=True):
            # NeoForge versions like "21.11.38-beta" map to MC 1.21.11
            parts = v.split(".")
            if len(parts) >= 2:
                try:
                    major = int(parts[0])
                    minor = parts[1].split("-")[0]
                    return f"1.{major}.{minor}"
                except ValueError:
                    pass
    return None

def build_config_from_properties():
    """Auto-generate config.json from server.properties and disk detection"""
    props = parse_props()
    loader = detect_loader_from_disk()
    mc_version = detect_mc_version_from_disk()
    
    cfg = {
        "rcon_pass": props.get("rcon.password", "changeme"),
        "rcon_port": props.get("rcon.port", "25575"),
        "rcon_host": "localhost",
        "http_port": "8000",
        "mods_dir": "mods",
        "clientonly_dir": "clientonly",
        "mc_version": mc_version or props.get("mc-version", "1.21.11"),
        "loader": loader or "neoforge",
        "server_jar": props.get("server-jar", None),
        "max_download_mb": 600,
        "rate_limit_seconds": 2,
        "run_curator_on_startup": True,
        "curator_limit": 100,
        "curator_show_optional_audit": True,
        "curator_max_depth": 3
    }
    
    # Read server port from properties
    if "server-port" in props:
        cfg["server_port"] = props["server-port"]
    
    return cfg

def get_config():
    """Load config: from file, auto-detect from disk, or prompt user"""
    reconfigure = "--reconfigure" in sys.argv
    
    if os.path.exists(CONFIG) and not reconfigure:
        # Existing config -- load and return with defaults filled in
        log_event("CONFIG", "Loading existing config.json")
        cfg = json.load(open(CONFIG))
    elif os.path.exists(os.path.join(CWD, "server.properties")):
        # No config but server exists -- auto-detect
        log_event("CONFIG", "No config.json found, auto-detecting from server.properties")
        cfg = build_config_from_properties()
        
        loader = cfg.get("loader", "unknown")
        mc_ver = cfg.get("mc_version", "unknown")
        log_event("CONFIG", f"Detected: {loader} server, MC {mc_ver}")
        
        # Only prompt if interactive
        if sys.stdin.isatty():
            print(f"\nDetected {loader} server for MC {mc_ver}")
            confirm = input("Use these settings? [Y/n]: ").strip().lower()
            if confirm == "n":
                cfg["loader"] = input(f"Modloader (fabric/forge/neoforge) [{loader}]: ").strip() or loader
                cfg["mc_version"] = input(f"MC version [{mc_ver}]: ").strip() or mc_ver
                cfg["rcon_pass"] = input(f"RCON password [{cfg['rcon_pass']}]: ").strip() or cfg["rcon_pass"]
                cfg["http_port"] = input(f"HTTP port [{cfg['http_port']}]: ").strip() or cfg["http_port"]
        
        json.dump(cfg, open(CONFIG, "w"), indent=2)
        log_event("CONFIG", "Config saved from auto-detection")
    else:
        # Nothing on disk -- full wizard
        log_event("CONFIG", "No server detected, running setup wizard")
        
        loader_default = "neoforge"
        cfg = {
            "rcon_pass": input("RCON password [changeme]: ").strip() or "changeme",
            "rcon_port": input("RCON port [25575]: ").strip() or "25575",
            "rcon_host": "localhost",
            "http_port": input("HTTP mod port [8000]: ").strip() or "8000",
            "mods_dir": input("Mods folder [mods]: ").strip() or "mods",
            "clientonly_dir": "clientonly",
            "mc_version": input("Minecraft version [1.21.11]: ").strip() or "1.21.11",
            "loader": input(f"Modloader (fabric/forge/neoforge) [{loader_default}]: ").strip() or loader_default,
            "max_download_mb": 600,
            "rate_limit_seconds": 2,
            "run_curator_on_startup": True,
            "curator_limit": 100,
            "curator_show_optional_audit": True,
            "curator_max_depth": 3
        }
        
        loader = cfg.get("loader", "neoforge").lower()
        if loader in ["fabric", "forge"]:
            server_jar = input("Server JAR path [fabric-server.jar]: ").strip() or "fabric-server.jar"
            cfg["server_jar"] = server_jar
        else:
            cfg["server_jar"] = None
        
        json.dump(cfg, open(CONFIG, "w"), indent=2)
        
        # Ferium manager setup (only on fresh install)
        cfg = setup_ferium_wizard(cfg, cwd=CWD)
        json.dump(cfg, open(CONFIG, "w"), indent=2)
        
        print("\n" + "="*70)
        print("CONFIGURATION SAVED")
        print("="*70 + "\n")
    
    # Fill in missing defaults (backwards compatibility)
    defaults = {
        "curator_limit": 100,
        "curator_show_optional_audit": True,
        "curator_max_depth": 3,
        "ferium_profile": f"{cfg.get('loader', 'neoforge')}-{cfg.get('mc_version', '1.21.11')}",
        "ferium_enable_scheduler": True,
        "ferium_update_interval_hours": 4,
        "ferium_weekly_update_day": "mon",
        "ferium_weekly_update_hour": 2,
        "curseforge_method": "modrinth_only",
        "http_port": "8000",
        "loader": "neoforge",
        "mc_version": "1.21.11"
    }
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v
    
    # Ensure RCON is enabled in server.properties (only if not already set)
    props_path = os.path.join(CWD, "server.properties")
    if os.path.exists(props_path):
        props = parse_props()
        if props.get("enable-rcon", "false").lower() != "true":
            ensure_rcon_enabled(cfg)
        else:
            log_event("CONFIG", "RCON already enabled in server.properties")
    
    return cfg

def classify_mod(jar_path):
    """
    Detect if a mod is client-only, server-only, or both.
    Returns: "client", "server", or "both"
    """
    import zipfile
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            # Check for client-only markers
            has_client = False
            has_server = False
            
            # Check for common client packages/classes
            for name in zf.namelist():
                lower_name = name.lower()
                
                # Client-only indicators
                if any(x in lower_name for x in ['client', 'screen', 'render', 'gui', 'shader', 'texture']):
                    has_client = True
                
                # Server-only indicators  
                if any(x in lower_name for x in ['command', 'worldgen', 'structure', 'loot']):
                    has_server = True
            
            # Check mods.toml or fabric.mod.json for environment hints
            try:
                if 'META-INF/mods.toml' in zf.namelist():
                    toml_content = zf.read('META-INF/mods.toml').decode('utf-8', errors='ignore')
                    if 'side = "client"' in toml_content.lower():
                        return "client"
                    elif 'side = "server"' in toml_content.lower():
                        return "server"
            except:
                pass
            
            try:
                if 'fabric.mod.json' in zf.namelist():
                    fabric_content = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                    if '"environment": "client"' in fabric_content.lower():
                        return "client"
            except:
                pass
            
            # Fallback: if has client markers and no server markers, it's likely client-only
            if has_client and not has_server:
                return "client"
            elif has_server and not has_client:
                return "server"
            else:
                return "both"
    except:
        # Default to "both" if we can't read the jar
        return "both"

def sort_mods_by_type(mods_dir):
    """
    Scan mods directory and move client-only mods to clientonly folder.
    Returns count of mods moved.
    """
    clientonly_dir = os.path.join(mods_dir, "clientonly")
    os.makedirs(clientonly_dir, exist_ok=True)
    
    moved_count = 0
    
    for filename in os.listdir(mods_dir):
        if not filename.endswith('.jar'):
            continue
        
        jar_path = os.path.join(mods_dir, filename)
        if not os.path.isfile(jar_path):
            continue
        
        # Skip if already in clientonly
        if jar_path == os.path.join(clientonly_dir, filename):
            continue
        
        mod_type = classify_mod(jar_path)
        
        if mod_type == "client":
            # Move to clientonly
            dest = os.path.join(clientonly_dir, filename)
            try:
                if not os.path.exists(dest):
                    import shutil
                    shutil.move(jar_path, dest)
                    log_event("MOD_SORT", f"Moved {filename} to clientonly/")
                    moved_count += 1
            except Exception as e:
                log_event("MOD_SORT_ERROR", f"Failed to move {filename}: {e}")
    
    if moved_count > 0:
        log_event("MOD_SORT", f"Sorted {moved_count} client-only mods")
    
    return moved_count

def create_install_scripts(mods_dir, cfg=None):
    """Generate client install scripts with correct port from config"""
    os.makedirs(mods_dir, exist_ok=True)
    http_port = int(cfg.get("http_port", 8000)) if cfg else 8000
    
    # PowerShell script for Windows
    ps = f'''# Minecraft Mod Installer (Windows)
param([string]$ServerIP="localhost", [int]$Port={http_port})
$modsPath = "$env:APPDATA\\.minecraft\\mods"
$oldmodsPath = "$env:APPDATA\\.minecraft\\oldmods"
$zipPath = "$env:TEMP\\mods_latest.zip"

Write-Host "Downloading mods..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $oldmodsPath -Force | Out-Null
if (Test-Path $modsPath) {{
    Get-ChildItem -Path $modsPath -Filter "*.jar" -ErrorAction SilentlyContinue | ForEach-Object {{
        Move-Item -Path $_.FullName -Destination $oldmodsPath -Force
    }}
}}
(New-Object System.Net.WebClient).DownloadFile("http://$ServerIP:$Port/mods_latest.zip", $zipPath)
Expand-Archive -Path $zipPath -DestinationPath $modsPath -Force
Remove-Item -Path $zipPath -Force
$count = (Get-ChildItem -Path $modsPath -Filter "*.jar" | Measure-Object).Count
Write-Host "Installed $count mods" -ForegroundColor Green
'''
    
    # Bash script for Linux/Mac
    bash = f'''#!/bin/bash
SERVER_IP="${{1:-localhost}}"
PORT="${{2:-{http_port}}}"
[[ "$OSTYPE" == "darwin"* ]] && MC_DIR="$HOME/Library/Application Support/minecraft" || MC_DIR="$HOME/.minecraft"
MODS="$MC_DIR/mods"
OLD="$MC_DIR/oldmods"
ZIP="/tmp/mods_latest.zip"
mkdir -p "$OLD" "$MODS"
ls "$MODS"/*.jar 2>/dev/null && mv "$MODS"/*.jar "$OLD/" 2>/dev/null || true
echo "Downloading mods..."
curl -L -o "$ZIP" "http://$SERVER_IP:$PORT/mods_latest.zip" || exit 1
unzip -q "$ZIP" -d "$MODS"
rm "$ZIP"
echo "Installed $(ls -1 "$MODS"/*.jar 2>/dev/null | wc -l) mods"
'''
    
    with open(os.path.join(mods_dir, "install-mods.ps1"), "w") as f:
        f.write(ps)
    
    bash_path = os.path.join(mods_dir, "install-mods.sh")
    with open(bash_path, "w") as f:
        f.write(bash)
    os.chmod(bash_path, 0o755)
    
    log_event("SCRIPTS", f"Generated install-mods.ps1 and install-mods.sh (port={http_port})")

def create_mod_zip(mods_dir):
    """Create mods_latest.zip with all mods (root + clientonly) in flat structure"""
    import shutil
    import zipfile
    
    clientonly_dir = os.path.join(mods_dir, "clientonly")
    zip_path = os.path.join(mods_dir, "mods_latest.zip")
    
    try:
        # Collect all jar files with root taking precedence
        mods_to_zip = {}
        
        # First, add all jar files from clientonly directory
        if os.path.exists(clientonly_dir):
            for filename in os.listdir(clientonly_dir):
                if filename.endswith('.jar'):
                    file_path = os.path.join(clientonly_dir, filename)
                    if os.path.isfile(file_path):
                        mods_to_zip[filename] = file_path
        
        # Then, add/override with jar files from root (root takes precedence)
        for filename in os.listdir(mods_dir):
            if filename.endswith('.jar'):
                file_path = os.path.join(mods_dir, filename)
                if os.path.isfile(file_path):
                    mods_to_zip[filename] = file_path
        
        # Create zip with all collected mods (no duplicates)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename, file_path in sorted(mods_to_zip.items()):
                zf.write(file_path, arcname=filename)
        
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        mod_count = len(mods_to_zip)
        log_event("MOD_ZIP", f"Created mods_latest.zip ({mod_count} mods, {size_mb:.2f} MB)")
        
    except Exception as e:
        log_event("MOD_ZIP_ERROR", f"Failed to create ZIP: {e}")

class SecureHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler with security checks"""
    last_request_time = 0
    
    def do_GET(self):
        cfg = json.load(open(CONFIG))
        
        # Rate limiting
        current_time = time.time()
        if current_time - SecureHTTPHandler.last_request_time < cfg["rate_limit_seconds"]:
            self.send_error(429)
            return
        SecureHTTPHandler.last_request_time = current_time
        
        # File validation
        file_name = Path(self.path.lstrip("/")).name
        if not file_name or file_name.startswith("."):
            self.send_error(403)
            return
        
        # Extension whitelist
        allowed = [".jar", ".zip", ".ps1", ".sh"]
        if not any(file_name.endswith(ext) for ext in allowed):
            self.send_error(403)
            return
        
        # File size limit
        target_path = Path(cfg["mods_dir"]) / file_name
        if target_path.exists():
            size_mb = target_path.stat().st_size / (1024 * 1024)
            if size_mb > cfg["max_download_mb"]:
                self.send_error(413)
                return
        
        # Serve file
        if target_path.exists():
            self.path = str(target_path)
            return SimpleHTTPRequestHandler.do_GET(self)
        
        self.send_error(404)
    
    def log_message(self, format, *args):
        log_event("HTTP", format % args)

def backup_world(cfg):
    """Backup world directory"""
    world_dir = os.path.join(CWD, "world")
    backup_dir = os.path.join(CWD, "backups")
    
    if not os.path.exists(world_dir):
        return False
    
    os.makedirs(backup_dir, exist_ok=True)
    backup_name = f"world_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    log_event("BACKUP_START", backup_name)
    
    # Disable autosave and flush
    run(f"tmux send-keys -t MC 'save-off' Enter")
    run(f"tmux send-keys -t MC 'save-all flush' Enter")
    time.sleep(5)
    
    # Backup
    result = run(f"rsync -a {world_dir}/ {os.path.join(backup_dir, backup_name)}/")
    
    # Re-enable autosave
    run(f"tmux send-keys -t MC 'save-on' Enter")
    
    if result.returncode == 0:
        log_event("BACKUP_COMPLETE", backup_name)
        # Cleanup old backups (>7 days)
        cutoff = datetime.now() - timedelta(days=7)
        for backup in os.listdir(backup_dir):
            path = os.path.join(backup_dir, backup)
            if os.path.isdir(path) and datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                import shutil
                shutil.rmtree(path)
                log_event("BACKUP_CLEANUP", f"Removed {backup}")
        return True
    else:
        log_event("BACKUP_FAIL", result.stderr)
        return False

def backup_scheduler(cfg):
    """Schedule daily backup at 4 AM"""
    while True:
        now = datetime.now()
        target = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now.hour >= 4:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        log_event("BACKUP_SCHEDULER", f"Next backup in {wait/3600:.1f} hours")
        time.sleep(wait)
        backup_world(cfg)

def http_server(port, mods_dir):
    """Start HTTP server for mods and dashboard on a single port.
    
    Uses Flask to serve both the dashboard UI and mod download endpoints
    on the configured http_port (default 8000).
    """
    
    if FLASK_AVAILABLE:
        def run_flask_app():
            try:
                import sys as _sys
                _sys.path.insert(0, CWD)
                
                from flask import Flask, render_template, jsonify, request, send_file
                
                app = Flask(__name__, template_folder=CWD, static_folder=os.path.join(CWD, "static"))
                app.secret_key = os.urandom(24)
                
                def load_cfg():
                    if os.path.exists(CONFIG):
                        with open(CONFIG) as f:
                            return json.load(f)
                    return {}
                
                def save_cfg(c):
                    with open(CONFIG, "w") as f:
                        json.dump(c, f, indent=2)
                
                def run_cmd(cmd):
                    try:
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                        return {"success": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
                    except Exception as e:
                        return {"success": False, "error": str(e)}
                
                def get_server_status():
                    running = run_cmd("tmux list-sessions 2>/dev/null | grep -c MC").get("stdout", "").strip() == "1"
                    c = load_cfg()
                    loader = c.get("loader", "unknown")
                    mc_ver = c.get("mc_version", "unknown")
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    mod_count = len([f for f in os.listdir(mods_dir_path) if f.endswith(".jar")]) if os.path.exists(mods_dir_path) else 0
                    
                    return {
                        "running": running,
                        "loader": loader,
                        "mc_version": mc_ver,
                        "mod_count": mod_count,
                        "player_count": 0,
                        "rcon_enabled": c.get("rcon_pass") is not None,
                        "uptime": "N/A"
                    }
                
                def get_mod_list():
                    c = load_cfg()
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    mods = []
                    if os.path.exists(mods_dir_path):
                        for filename in sorted(os.listdir(mods_dir_path)):
                            if filename.endswith(".jar"):
                                path = os.path.join(mods_dir_path, filename)
                                size = os.path.getsize(path)
                                mods.append({"name": filename, "size": size, "size_mb": round(size / (1024*1024), 2)})
                    return sorted(mods, key=lambda x: x["name"])
                
                @app.route("/")
                def dashboard():
                    return render_template("dashboard.html")
                
                @app.route("/api/status")
                def api_status():
                    return jsonify(get_server_status())
                
                @app.route("/api/config")
                def api_config():
                    c = load_cfg()
                    c["rcon_pass"] = "***"
                    return jsonify(c)
                
                @app.route("/api/config", methods=["POST"])
                def api_config_update():
                    try:
                        data = request.json
                        c = load_cfg()
                        allowed = ["ferium_update_interval_hours", "ferium_weekly_update_day", "ferium_weekly_update_hour", "mc_version"]
                        for field in allowed:
                            if field in data:
                                c[field] = data[field]
                        save_cfg(c)
                        return jsonify({"success": True, "message": "Config updated"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/mods")
                def api_mods():
                    return jsonify(get_mod_list())
                
                @app.route("/api/mods/<mod_name>", methods=["DELETE"])
                def api_remove_mod(mod_name):
                    try:
                        c = load_cfg()
                        mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                        mod_path = os.path.join(mods_dir_path, mod_name)
                        if not os.path.abspath(mod_path).startswith(os.path.abspath(mods_dir_path)):
                            return jsonify({"success": False, "error": "Invalid path"}), 400
                        if os.path.exists(mod_path) and mod_path.endswith(".jar"):
                            os.remove(mod_path)
                            return jsonify({"success": True, "message": f"Removed {mod_name}"})
                        return jsonify({"success": False, "error": "Mod not found"}), 404
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/download/<mod_name>")
                def api_download_mod(mod_name):
                    """Download a mod JAR file"""
                    try:
                        c = load_cfg()
                        mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                        mod_path = os.path.join(mods_dir_path, mod_name)
                        if not os.path.abspath(mod_path).startswith(os.path.abspath(mods_dir_path)):
                            return jsonify({"success": False, "error": "Invalid path"}), 400
                        if os.path.exists(mod_path) and mod_path.endswith(".jar"):
                            return send_file(mod_path, as_attachment=True)
                        return jsonify({"success": False, "error": "Mod not found"}), 404
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/download/<filename>")
                def download_file(filename):
                    """Serve mod/zip/script files for client download"""
                    c = load_cfg()
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    allowed_ext = [".jar", ".zip", ".ps1", ".sh"]
                    if not any(filename.endswith(ext) for ext in allowed_ext):
                        return jsonify({"error": "File type not allowed"}), 403
                    file_path = os.path.join(mods_dir_path, filename)
                    if not os.path.abspath(file_path).startswith(os.path.abspath(mods_dir_path)):
                        return jsonify({"error": "Invalid path"}), 400
                    if os.path.exists(file_path):
                        return send_file(file_path, as_attachment=True)
                    return jsonify({"error": "File not found"}), 404
                
                @app.route("/api/mod-lists")
                def api_mod_lists():
                    """Return curated mod lists from cache, with installed status for each mod"""
                    c = load_cfg()
                    loader = c.get("loader", "neoforge")
                    mc_ver = c.get("mc_version", "1.21.11")
                    m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                    cache_file = os.path.join(CWD, f"curator_cache_{mc_ver}_{loader}.json")
                    
                    # Build set of installed mod filenames for matching
                    installed_jars = set()
                    installed_slugs = set()
                    if os.path.exists(m_dir):
                        for fn in os.listdir(m_dir):
                            if fn.endswith('.jar') and os.path.isfile(os.path.join(m_dir, fn)):
                                installed_jars.add(fn.lower())
                                # Normalize for fuzzy matching
                                installed_slugs.add(re.sub(r'[^a-z0-9]', '', fn.lower().split('.jar')[0]))
                    
                    def _mark_installed(mod):
                        """Add 'installed' flag to a mod dict"""
                        name = mod.get("name", "")
                        slug = mod.get("slug", "")
                        mod_id = mod.get("id", "")
                        # Check by slug, name, or id match against installed filenames
                        for check in [name, slug, mod_id]:
                            if check:
                                norm = re.sub(r'[^a-z0-9]', '', check.lower())
                                if norm and any(norm in ij for ij in installed_slugs):
                                    mod["installed"] = True
                                    return mod
                        mod["installed"] = False
                        return mod
                    
                    if os.path.exists(cache_file):
                        try:
                            with open(cache_file) as f:
                                raw = json.load(f)
                            if isinstance(raw, dict):
                                first_val = next(iter(raw.values()), None) if raw else None
                                if isinstance(first_val, dict) and "name" in first_val:
                                    mods = sorted(raw.values(), key=lambda m: m.get("downloads", 0), reverse=True)
                                    mods = [_mark_installed(m) for m in mods]
                                    return jsonify({loader: mods})
                                elif isinstance(first_val, list):
                                    # {loader: [list]} format — mark each
                                    for ldr in raw:
                                        if isinstance(raw[ldr], list):
                                            raw[ldr] = [_mark_installed(m) for m in raw[ldr]]
                                    return jsonify(raw)
                                else:
                                    return jsonify(raw)
                            elif isinstance(raw, list):
                                raw = [_mark_installed(m) for m in raw]
                                return jsonify({loader: raw})
                            else:
                                return jsonify(raw)
                        except Exception:
                            pass
                    
                    return jsonify({"error": "No cached mod lists. Run: python3 run.py curator"}), 404
                
                @app.route("/api/install-mods", methods=["POST"])
                def api_install_mods():
                    """Install selected mods from curated list (supports both Modrinth + CurseForge)"""
                    try:
                        data = request.json
                        selected = data.get("selected", [])
                        if not selected:
                            return jsonify({"success": False, "error": "No mods selected"}), 400
                        
                        c = load_cfg()
                        mc_ver = c.get("mc_version", "1.21.11")
                        loader = c.get("loader", "neoforge")
                        m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        os.makedirs(m_dir, exist_ok=True)
                        
                        # Load the full curator cache to get mod details (source, slug, file_id, etc.)
                        cache_file = os.path.join(CWD, f"curator_cache_{mc_ver}_{loader}.json")
                        cached_mods = {}
                        if os.path.exists(cache_file):
                            try:
                                with open(cache_file) as f:
                                    raw = json.load(f)
                                if isinstance(raw, dict):
                                    cached_mods = raw
                            except:
                                pass
                        
                        downloaded = 0
                        skipped = 0
                        failed = []
                        for mod_id in selected:
                            try:
                                # Look up full mod data from cache
                                mod_data = cached_mods.get(mod_id, {"id": mod_id, "name": mod_id})
                                source = mod_data.get("source", "modrinth")
                                
                                if source == "curseforge":
                                    result = download_mod_from_curseforge(mod_data, m_dir, mc_ver, loader)
                                    if result == "exists":
                                        skipped += 1
                                    elif result:
                                        downloaded += 1
                                    else:
                                        failed.append(mod_id)
                                else:
                                    # Default: Modrinth
                                    result = download_mod_from_modrinth(mod_data, m_dir, mc_ver, loader)
                                    if result == "exists":
                                        skipped += 1
                                    elif result:
                                        downloaded += 1
                                    else:
                                        failed.append(mod_id)
                            except Exception as e:
                                failed.append(mod_id)
                        
                        # Regenerate zip + install scripts so clients get the updated pack
                        if downloaded > 0:
                            try:
                                sort_mods_by_type(m_dir)
                                create_install_scripts(m_dir, c)
                                create_mod_zip(m_dir)
                            except Exception as e:
                                log_event("API", f"Post-install regeneration error: {e}")
                        
                        return jsonify({
                            "success": True,
                            "downloaded": downloaded,
                            "skipped": skipped,
                            "failed": failed,
                            "message": f"Downloaded {downloaded}, skipped {skipped} already installed, {len(failed)} failed"
                        })
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/logs")
                def api_logs():
                    lines_param = request.args.get("lines", 50, type=int)
                    if os.path.exists(LOG_FILE):
                        try:
                            with open(LOG_FILE) as f:
                                return jsonify({"logs": f.readlines()[-min(lines_param, 500):]})
                        except:
                            pass
                    return jsonify({"logs": []})
                
                @app.route("/api/server/start", methods=["POST"])
                def api_server_start():
                    try:
                        run_cmd(f"cd {CWD} && python3 run.py run &")
                        return jsonify({"success": True, "message": "Server starting..."})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/server/stop", methods=["POST"])
                def api_server_stop():
                    try:
                        c = load_cfg()
                        if c.get("rcon_pass"):
                            if send_rcon_command(c, "stop"):
                                return jsonify({"success": True, "message": "Stop command sent via RCON"})
                            # Fallback: send stop via tmux if RCON fails
                            run_cmd("tmux send-keys -t MC 'stop' Enter")
                            return jsonify({"success": True, "message": "Stop command sent via tmux (RCON failed)"})
                        # No RCON configured, use tmux
                        run_cmd("tmux send-keys -t MC 'stop' Enter")
                        return jsonify({"success": True, "message": "Stop command sent via tmux"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/mods/upgrade", methods=["POST"])
                def api_upgrade_mods():
                    try:
                        result = run_cmd("/home/services/.local/bin/ferium upgrade")
                        if result["success"]:
                            return jsonify({"success": True, "message": "Mods upgraded"})
                        return jsonify({"success": False, "error": result["stderr"]}), 400
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                flask_port = int(port)
                log_event("HTTP_SERVER", f"Starting dashboard + mod server on port {flask_port}")
                app.run(host="0.0.0.0", port=flask_port, debug=False, use_reloader=False)
            except Exception as e:
                log_event("HTTP_SERVER_ERROR", str(e))
        
        run_flask_app()
    else:
        # Fallback: simple HTTP file server if Flask not available
        os.chdir(mods_dir)
        mod_server = HTTPServer(("0.0.0.0", int(port)), SecureHTTPHandler)
        log_event("HTTP_SERVER", f"Mod file server (no Flask) on port {port}")
        mod_server.serve_forever()

def _get_neoforge_version():
    """Get NeoForge version from installed libraries (legacy helper, prefer loader class)"""
    lib_path = os.path.join(CWD, "libraries/net/neoforged/neoforge")
    if os.path.exists(lib_path):
        versions = [d for d in os.listdir(lib_path) if os.path.isdir(os.path.join(lib_path, d))]
        if versions:
            return sorted(versions)[-1]
    return "21.11.38-beta"  # Fallback

def _read_recent_log(lines=200):
    """Read the last N lines from the server log file"""
    try:
        if not os.path.exists(LOG_FILE):
            return ""
        with open(LOG_FILE, "r") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception:
        return ""

def _quarantine_mod(mods_dir, mod_id_or_slug, reason="unknown"):
    """Move a mod to quarantine directory. Searches by mod_id/slug in filenames.
    Returns the filename that was quarantined, or None."""
    import shutil
    quarantine_dir = os.path.join(mods_dir, "quarantine")
    os.makedirs(quarantine_dir, exist_ok=True)
    
    slug_lower = mod_id_or_slug.lower().replace('-', '').replace('_', '').replace(' ', '')
    
    for fn in os.listdir(mods_dir):
        if not fn.endswith('.jar') or not os.path.isfile(os.path.join(mods_dir, fn)):
            continue
        fn_norm = fn.lower().replace('-', '').replace('_', '').replace(' ', '')
        if slug_lower in fn_norm:
            src = os.path.join(mods_dir, fn)
            dst = os.path.join(quarantine_dir, fn)
            try:
                shutil.move(src, dst)
                log_event("QUARANTINE", f"Quarantined {fn} -> quarantine/ (reason: {reason})")
                
                # Write reason to a sidecar file
                reason_file = os.path.join(quarantine_dir, f"{fn}.reason.txt")
                with open(reason_file, "w") as rf:
                    rf.write(f"Quarantined: {datetime.now().isoformat()}\n")
                    rf.write(f"Reason: {reason}\n")
                    rf.write(f"Mod ID/slug: {mod_id_or_slug}\n")
                
                return fn
            except Exception as e:
                log_event("QUARANTINE", f"Failed to quarantine {fn}: {e}")
                return None
    
    log_event("QUARANTINE", f"Could not find JAR matching '{mod_id_or_slug}' to quarantine")
    return None


def _search_and_download_dep(dep_name, mods_dir, mc_version, loader_name):
    """Search both Modrinth and CurseForge for a missing dependency and download it.
    Returns True if successfully downloaded, False otherwise."""
    
    # 1. Try Modrinth first
    try:
        dep_query = url_quote(dep_name)
        search_url = f"https://api.modrinth.com/v2/search?query={dep_query}&facets=[[\"versions:{mc_version}\"],[\"categories:{loader_name}\"],[\"project_type:mod\"]]&limit=5"
        req = urllib.request.Request(search_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read().decode())
        
        hits = results.get("hits", [])
        if hits:
            # Pick best match (exact slug match first, then first result)
            best = None
            for h in hits:
                if h.get("slug", "").lower() == dep_name.lower():
                    best = h
                    break
            if not best:
                best = hits[0]
            
            mod_data = {"id": best["project_id"], "name": best.get("title", dep_name), "slug": best.get("slug", dep_name)}
            result = download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader_name)
            if result:
                log_event("SELF_HEAL", f"Downloaded {mod_data['name']} from Modrinth")
                return True
    except Exception as e:
        log_event("SELF_HEAL", f"Modrinth search failed for {dep_name}: {e}")
    
    # 2. Try CurseForge scraper (check curator cache for CF mods)
    try:
        cache_file = os.path.join(CWD, f"curator_cache_{mc_version}_{loader_name}.json")
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                cached = json.load(f)
            # Search cache for a mod matching the dep name
            dep_norm = dep_name.lower().replace('-', '').replace('_', '').replace(' ', '')
            for mod_id, mod_data in cached.items():
                if not isinstance(mod_data, dict):
                    continue
                mod_norm = mod_data.get("name", "").lower().replace('-', '').replace('_', '').replace(' ', '')
                slug_norm = mod_data.get("slug", "").lower().replace('-', '').replace('_', '')
                if dep_norm == mod_norm or dep_norm == slug_norm or dep_norm in mod_norm:
                    if mod_data.get("source") == "curseforge":
                        result = download_mod_from_curseforge(mod_data, mods_dir, mc_version, loader_name)
                        if result and result != False:
                            log_event("SELF_HEAL", f"Downloaded {mod_data['name']} from CurseForge cache")
                            return True
    except Exception as e:
        log_event("SELF_HEAL", f"CurseForge cache search failed for {dep_name}: {e}")
    
    log_event("SELF_HEAL", f"Could not find {dep_name} on either Modrinth or CurseForge for MC {mc_version}")
    return False


def _try_self_heal(loader_instance, crash_info, cfg, crash_history):
    """Attempt to fix a crash by fetching missing deps or quarantining bad mods.
    
    Args:
        loader_instance: loader class instance
        crash_info: dict from detect_crash_reason()
        cfg: server config
        crash_history: dict tracking {mod_id: crash_count} across restarts
    
    Returns: 'fixed', 'quarantined', or False
    """
    crash_type = crash_info.get("type", "unknown")
    culprit = crash_info.get("culprit")
    mc_version = cfg.get("mc_version", "1.21.11")
    loader_name = cfg.get("loader", "neoforge")
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    
    if crash_type == "missing_dep":
        dep_name = crash_info.get("dep", "")
        if not dep_name or dep_name == "unknown":
            log_event("SELF_HEAL", "Missing dependency detected but name unknown, cannot auto-fix")
            return False
        
        log_event("SELF_HEAL", f"Missing dependency: {dep_name}" + (f" (required by {culprit})" if culprit else ""))
        
        # Check if we've already tried to fetch this dep before (dep loop)
        dep_key = f"dep_{dep_name}"
        crash_history[dep_key] = crash_history.get(dep_key, 0) + 1
        
        if crash_history[dep_key] > 2:
            # We've tried fetching this dep twice and it still crashes
            # Quarantine the culprit mod (the one requiring the dep)
            if culprit:
                log_event("SELF_HEAL", f"Dep {dep_name} fetched {crash_history[dep_key]} times but still crashing. Quarantining {culprit}")
                quarantined = _quarantine_mod(mods_dir, culprit, f"Repeatedly requires unfetchable dep: {dep_name}")
                if quarantined:
                    return "quarantined"
            log_event("SELF_HEAL", f"Cannot resolve dep {dep_name} after {crash_history[dep_key]} attempts")
            return False
        
        # Try to download the missing dependency
        if _search_and_download_dep(dep_name, mods_dir, mc_version, loader_name):
            return "fixed"
        
        # Could not find the dep — quarantine the culprit if known
        if culprit:
            log_event("SELF_HEAL", f"Could not find dep {dep_name}. Quarantining {culprit}")
            quarantined = _quarantine_mod(mods_dir, culprit, f"Missing dep '{dep_name}' not available for MC {mc_version}")
            if quarantined:
                return "quarantined"
        
        return False
    
    elif crash_type == "mod_error":
        if culprit:
            # Track crash count for this mod
            crash_history[culprit] = crash_history.get(culprit, 0) + 1
            log_event("SELF_HEAL", f"Mod error from {culprit} (crash #{crash_history[culprit]})")
            
            if crash_history[culprit] >= 2:
                log_event("SELF_HEAL", f"Quarantining {culprit} after {crash_history[culprit]} crashes")
                quarantined = _quarantine_mod(mods_dir, culprit, f"Caused {crash_history[culprit]} crashes")
                if quarantined:
                    return "quarantined"
            return False
        else:
            log_event("SELF_HEAL", f"Mod error detected but cannot identify culprit mod")
            return False
    
    elif crash_type == "version_mismatch":
        if culprit:
            log_event("SELF_HEAL", f"Version mismatch involving {culprit}. Quarantining (no version fallback — strict MC version matching)")
            quarantined = _quarantine_mod(mods_dir, culprit, f"Version mismatch — no compatible build for MC {mc_version}")
            if quarantined:
                return "quarantined"
        else:
            log_event("SELF_HEAL", f"Version mismatch detected but cannot identify culprit")
        return False
    
    else:
        log_event("SELF_HEAL", f"Unknown crash type, no auto-fix available")
        return False

def _preflight_dep_check(cfg):
    """Proactive pre-flight: scan installed mods, resolve deps, download missing ones BEFORE launch.
    Returns number of deps fetched."""
    mc_version = cfg.get("mc_version", "1.21.11")
    loader_name = cfg.get("loader", "neoforge")
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    
    if not os.path.exists(mods_dir):
        return 0
    
    # Load curator cache to find Modrinth project IDs for installed mods
    cache_file = os.path.join(CWD, f"curator_cache_{mc_version}_{loader_name}.json")
    cached_mods = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cached_mods = json.load(f)
        except:
            pass
    
    # Build map of installed filenames (normalized) for quick lookup
    installed_files = set()
    for fn in os.listdir(mods_dir):
        if fn.endswith('.jar') and os.path.isfile(os.path.join(mods_dir, fn)):
            installed_files.add(fn.lower())
    
    if not installed_files:
        return 0
    
    log_event("PREFLIGHT", f"Checking dependencies for {len(installed_files)} installed mods...")
    
    fetched = 0
    checked = 0
    
    # For each cached mod that we have installed, check its deps
    for mod_id, mod_data in cached_mods.items():
        if not isinstance(mod_data, dict):
            continue
        
        source = mod_data.get("source", "modrinth")
        
        if source == "curseforge":
            # Check CurseForge deps from scraped data
            for dep in mod_data.get("deps_required", []) + mod_data.get("cf_deps_required", []):
                dep_slug = dep.get("slug", "")
                if dep_slug and not _mod_jar_exists(mods_dir, mod_slug=dep_slug):
                    log_event("PREFLIGHT", f"Missing CF dep: {dep.get('name', dep_slug)}")
                    # Try to find it in cache and download
                    for cid, cdata in cached_mods.items():
                        if isinstance(cdata, dict) and cdata.get("slug") == dep_slug:
                            result = download_mod_from_curseforge(cdata, mods_dir, mc_version, loader_name)
                            if result and result != False:
                                fetched += 1
                            break
        else:
            # Check Modrinth deps via API
            if mod_data.get("id") and not mod_data.get("id", "").startswith("cf_"):
                try:
                    deps = get_mod_version_dependencies(mod_data["id"], mc_version, loader_name)
                    for dep in deps:
                        if dep.get("dependency_type") == "required":
                            dep_id = dep.get("project_id")
                            if dep_id and not _mod_jar_exists(mods_dir, mod_slug=dep_id):
                                # Check if the dep exists in our mods dir by any other name
                                log_event("PREFLIGHT", f"Checking required dep {dep_id} for {mod_data.get('name', mod_id)}")
                                if _search_and_download_dep(dep_id, mods_dir, mc_version, loader_name):
                                    fetched += 1
                except Exception as e:
                    pass  # Non-fatal — preflight is best-effort
        
        checked += 1
        if checked >= 50:  # Don't spend forever on preflight
            break
    
    if fetched > 0:
        log_event("PREFLIGHT", f"Pre-flight fetched {fetched} missing dependencies")
    else:
        log_event("PREFLIGHT", "All dependencies satisfied")
    
    return fetched


def run_server(cfg):
    """Start Minecraft server in tmux with crash detection, self-healing, and quarantine.
    
    Uses loader abstraction classes for:
    - build_java_command() — loader-specific JVM args
    - detect_crash_reason() — parse crash logs (now with culprit extraction)
    
    Pipeline:
    1. Pre-flight dep check (proactive — fetch missing deps before launch)
    2. Start server
    3. Monitor tmux session
    4. If session dies, read crash log
    5. If crash: try self-heal (fetch dep / quarantine bad mod)
    6. Restart (up to MAX_RESTART_ATTEMPTS)
    
    Quarantine: mods/quarantine/ — bad mods moved there with reason files.
    No version fallback — strict MC version matching only.
    """
    MAX_RESTART_ATTEMPTS = 5
    RESTART_COOLDOWN = 15  # seconds between restart attempts
    MONITOR_TIMEOUT = 3600 * 6  # 6 hours — kill zombie tmux if no activity
    
    loader_name = cfg.get("loader", "neoforge").lower()
    mc_version = cfg.get("mc_version", "1.21.11")
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    
    # Get loader instance
    try:
        loader_instance = get_loader(cfg)
    except ValueError as e:
        log_event("SERVER_ERROR", str(e))
        return False
    
    # Build Java command from the loader class
    java_cmd_parts = loader_instance.build_java_command()
    java_cmd = " ".join(java_cmd_parts)
    
    log_event("SERVER_START", f"Starting {loader_instance.get_loader_display_name()} server (MC {mc_version})")
    log_event("SERVER_START", f"Java command: {java_cmd}")
    
    # ---- PRE-FLIGHT: check deps before launching ----
    try:
        preflight_fetched = _preflight_dep_check(cfg)
        if preflight_fetched > 0:
            log_event("SERVER_START", f"Pre-flight fetched {preflight_fetched} missing deps")
    except Exception as e:
        log_event("SERVER_START", f"Pre-flight check failed (non-fatal): {e}")
    
    # Ensure quarantine dir exists
    os.makedirs(os.path.join(mods_dir, "quarantine"), exist_ok=True)
    
    restart_count = 0
    crash_history = {}  # Track {mod_id: crash_count} across restarts
    
    while restart_count <= MAX_RESTART_ATTEMPTS:
        # Check if tmux session already exists (leftover from previous run)
        existing = run("tmux has-session -t MC 2>/dev/null")
        if existing.returncode == 0:
            log_event("SERVER_START", "Existing tmux session 'MC' found, killing it first")
            run("tmux kill-session -t MC 2>/dev/null")
            time.sleep(2)
        
        # Record log position before start so we can read just the new output
        log_size_before = 0
        try:
            if os.path.exists(LOG_FILE):
                log_size_before = os.path.getsize(LOG_FILE)
        except Exception:
            pass
        
        # Launch in tmux
        tmux_cmd = f"cd '{CWD}' && stdbuf -oL -eL {java_cmd}"
        result = run(f"tmux new-session -d -s MC \"{tmux_cmd}\"")
        if result.returncode != 0:
            log_event("SERVER_ERROR", f"Failed to start tmux session: {result.stderr}")
            return False
        
        run(f"tmux pipe-pane -o -t MC 'cat >> {LOG_FILE}'")
        
        if restart_count == 0:
            log_event("SERVER_RUNNING", f"Server started in tmux session 'MC'")
        else:
            log_event("SERVER_RUNNING", f"Server restarted (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})")
        
        # Monitor loop — wait for server to stop (with timeout)
        monitor_start = time.time()
        while True:
            check = run("tmux has-session -t MC 2>/dev/null")
            if check.returncode != 0:
                break
            if time.time() - monitor_start > MONITOR_TIMEOUT:
                log_event("SERVER_TIMEOUT", f"Server tmux session alive for >{MONITOR_TIMEOUT}s without crash — assuming hung, killing")
                run("tmux kill-session -t MC 2>/dev/null")
                break
            time.sleep(5)
        
        log_event("SERVER_STOPPED", "Server process ended, analyzing...")
        time.sleep(2)  # Let log flush
        
        # Read log output since we started
        new_log = ""
        try:
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "r") as f:
                    f.seek(log_size_before)
                    new_log = f.read()
        except Exception:
            new_log = _read_recent_log(300)
        
        # Check for clean shutdown (not a crash)
        if "Stopping the server" in new_log or "Server stopped" in new_log:
            log_event("SERVER_STOPPED", "Clean shutdown detected, not restarting")
            return True
        
        # Analyze crash
        crash_info = loader_instance.detect_crash_reason(new_log)
        crash_type = crash_info.get("type", "unknown")
        culprit = crash_info.get("culprit")
        log_event("CRASH_DETECT", f"Crash type: {crash_type}" + (f", culprit: {culprit}" if culprit else ""))
        if crash_info.get("message"):
            log_event("CRASH_DETECT", f"Details: {crash_info['message'][:200]}")
        
        # Attempt self-healing
        if restart_count < MAX_RESTART_ATTEMPTS:
            heal_result = _try_self_heal(loader_instance, crash_info, cfg, crash_history)
            
            if heal_result == "fixed":
                restart_count += 1
                log_event("SELF_HEAL", f"Fix applied, restarting in {RESTART_COOLDOWN}s...")
                time.sleep(RESTART_COOLDOWN)
                continue
            elif heal_result == "quarantined":
                restart_count += 1
                log_event("SELF_HEAL", f"Bad mod quarantined, restarting in {RESTART_COOLDOWN}s...")
                time.sleep(RESTART_COOLDOWN)
                continue
            elif crash_type == "unknown":
                # Unknown crash — still restart, but track it
                restart_count += 1
                crash_history["_unknown"] = crash_history.get("_unknown", 0) + 1
                if crash_history["_unknown"] >= 3:
                    log_event("SELF_HEAL", "Too many unknown crashes. Server will not restart.")
                    return False
                log_event("SELF_HEAL", f"Unknown crash, restarting in {RESTART_COOLDOWN}s (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})")
                time.sleep(RESTART_COOLDOWN)
                continue
            else:
                # Known crash type but can't auto-fix (no culprit to quarantine, dep not found)
                restart_count += 1
                log_event("SELF_HEAL", f"Cannot auto-fix, restarting anyway (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})")
                time.sleep(RESTART_COOLDOWN)
                continue
        else:
            log_event("SELF_HEAL", f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached. Server will not restart.")
            return False
    
    return False

def send_server_command(cmd):
    """Send command to tmux MC session"""
    # Escape quotes and special chars
    cmd_safe = cmd.replace("'", "'\\''")
    result = run(f"tmux send-keys -t MC '{cmd_safe}' Enter")
    return result.returncode == 0

def send_chat_message(msg):
    """Send chat message via 'say' command"""
    msg_safe = msg.replace("'", "'\\''")
    return send_server_command(f"say {msg_safe}")

def send_rcon_command(cfg, cmd):
    """Send command via RCON using the Source RCON protocol.
    Tries configured host first, then falls back to server-ip from server.properties."""
    try:
        import socket
        import struct
        
        hosts_to_try = [cfg.get("rcon_host", "localhost")]
        # Add server-ip from server.properties as fallback
        props = parse_props()
        server_ip = props.get("server-ip", "")
        if server_ip and server_ip not in hosts_to_try:
            hosts_to_try.append(server_ip)
        if "localhost" not in hosts_to_try:
            hosts_to_try.append("localhost")
        
        port = int(cfg.get("rcon_port", 25575))
        password = cfg.get("rcon_pass", "changeme")
        
        def _make_packet(request_id, packet_type, payload):
            """Build a Source RCON packet: length(4) + request_id(4) + type(4) + payload + \x00\x00"""
            payload_bytes = payload.encode("utf-8") + b"\x00\x00"
            length = 4 + 4 + len(payload_bytes)  # request_id + type + payload
            return struct.pack("<iii", length, request_id, packet_type) + payload_bytes
        
        def _read_packet(sock):
            """Read a Source RCON response packet"""
            raw_len = sock.recv(4)
            if len(raw_len) < 4:
                return None, None, None
            length = struct.unpack("<i", raw_len)[0]
            data = b""
            while len(data) < length:
                chunk = sock.recv(length - len(data))
                if not chunk:
                    break
                data += chunk
            if len(data) < 10:
                return None, None, None
            request_id, packet_type = struct.unpack("<ii", data[:8])
            payload = data[8:-2].decode("utf-8", errors="replace")  # strip 2 null bytes
            return request_id, packet_type, payload
        
        sock = None
        last_error = None
        connected_host = None
        for host in hosts_to_try:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((host, port))
                connected_host = host
                break
            except Exception as e:
                last_error = e
                try:
                    sock.close()
                except:
                    pass
                sock = None
        
        if sock is None:
            log_event("RCON_ERROR", f"Could not connect to any host: {hosts_to_try} - {last_error}")
            return False
        
        # Login (type 3)
        sock.sendall(_make_packet(1, 3, password))
        req_id, _, _ = _read_packet(sock)
        if req_id == -1 or req_id is None:
            log_event("RCON_ERROR", f"Authentication failed on {connected_host}")
            sock.close()
            return False
        
        # Send command (type 2)
        sock.sendall(_make_packet(2, 2, cmd))
        _, _, response = _read_packet(sock)
        
        sock.close()
        log_event("RCON", f"Command sent: {cmd}" + (f" -> {response}" if response else ""))
        return True
    except Exception as e:
        log_event("RCON_ERROR", str(e))
        return False

def show_mod_list_on_join(player, cfg):
    """Display mod list to player on join"""
    loader = cfg.get("loader", "neoforge")
    mod_lists = cfg.get("mod_lists", {})
    mods = mod_lists.get(loader, [])
    
    if not mods:
        send_chat_message(f"Welcome {player}! Mod list not available yet.")
        return
    
    send_chat_message("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    send_chat_message(f"📦 {loader.upper()} MOD LIST - Top {len(mods)}")
    send_chat_message("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    for idx, mod in enumerate(mods[:20], 1):
        name = mod.get("name", "Unknown")[:35]
        downloads = mod.get("downloads", 0)
        send_chat_message(f"  {idx:2}. {name} ({downloads/1e6:.1f}M)")
    
    if len(mods) > 20:
        send_chat_message(f"  ... and {len(mods) - 20} more mods")
    
    send_chat_message("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    send_chat_message("Type: download all | download 1-10 | download 1,5,15")
    send_chat_message("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

def handle_mod_download_command(player, command, cfg):
    """Parse mod download command from player chat"""
    import threading
    
    loader = cfg.get("loader", "neoforge")
    mod_lists = cfg.get("mod_lists", {})
    mods = mod_lists.get(loader, [])
    
    if not mods:
        send_chat_message(f"{player}: No mods available!")
        return
    
    cmd_lower = command.lower().strip()
    selected_mods = []
    
    if cmd_lower == "download all":
        selected_mods = list(range(len(mods)))
    elif "download" in cmd_lower:
        try:
            parts = cmd_lower.split("download", 1)[1].strip()
            
            if "-" in parts:
                start, end = parts.split("-", 1)
                start_idx = int(start.strip()) - 1
                end_idx = int(end.strip())
                if 0 <= start_idx < len(mods) and 1 <= end_idx <= len(mods):
                    selected_mods = list(range(start_idx, end_idx))
            elif "," in parts:
                indices = [int(x.strip()) - 1 for x in parts.split(",")]
                for idx in indices:
                    if 0 <= idx < len(mods):
                        selected_mods.append(idx)
            else:
                idx = int(parts.strip()) - 1
                if 0 <= idx < len(mods):
                    selected_mods = [idx]
            
            if not selected_mods:
                send_chat_message(f"{player}: Invalid selection!")
                return
        
        except ValueError:
            send_chat_message(f"{player}: Invalid format!")
            return
    
    if selected_mods:
        threading.Thread(target=download_selected_mods, args=(selected_mods, mods, cfg, player), daemon=True).start()

def download_selected_mods(selected_indices, mod_list, cfg, player):
    """Download selected mods in background"""
    mc_version = cfg.get("mc_version", "1.21.11")
    loader = cfg.get("loader", "neoforge")
    mods_dir = cfg.get("mods_dir", "mods")
    
    downloaded = 0
    
    for idx in selected_indices:
        if 0 <= idx < len(mod_list):
            mod = mod_list[idx]
            mod_id = mod.get("id")
            mod_name = mod.get("name")
            
            try:
                result = download_mod_from_modrinth(
                    {"project_id": mod_id, "title": mod_name},
                    mods_dir,
                    mc_version,
                    loader
                )
                if result:
                    downloaded += 1
                    log_event("MOD_DOWNLOAD", f"Downloaded {mod_name}")
            except Exception as e:
                log_event("MOD_DOWNLOAD_ERROR", f"Error: {str(e)}")
    
    if downloaded > 0:
        send_chat_message(f"✓ Downloaded {downloaded} mod(s)! Restarting server...")
        restart_server_for_mods(cfg)
    else:
        send_chat_message(f"✗ Failed to download mods!")

def restart_server_for_mods(cfg):
    """Restart MC server after mods downloaded.
    Sends 'stop' command and waits for clean shutdown.
    systemd will auto-restart the server (Restart=always),
    which re-runs run.py run and starts the MC server again."""
    time.sleep(2)
    send_server_command("stop")
    log_event("SERVER_RESTART", "Server stopping for mod update (systemd will auto-restart)...")
    # Wait for tmux session to die (server stopping)
    for _ in range(30):
        check = run("tmux has-session -t MC 2>/dev/null")
        if check.returncode != 0:
            log_event("SERVER_RESTART", "Server stopped. systemd will restart it.")
            return True
        time.sleep(1)
    log_event("SERVER_RESTART", "Server didn't stop within 30s, forcing kill")
    run("tmux kill-session -t MC 2>/dev/null")
    return True

class EventHook:
    """Base class for event handlers"""
    def __init__(self, name):
        self.name = name
        self.last_triggered = {}
    
    def should_trigger(self, event_data):
        """Override to detect event"""
        raise NotImplementedError
    
    def on_trigger(self, event_data, cfg):
        """Override to handle event"""
        raise NotImplementedError
    
    def debounce_check(self, key, seconds=5):
        """Prevent duplicate triggers within time window"""
        now = time.time()
        if key in self.last_triggered:
            if now - self.last_triggered[key] < seconds:
                return False
        self.last_triggered[key] = now
        return True

class PlayerJoinHook(EventHook):
    """Trigger on player join event - show mod list options"""
    def __init__(self):
        super().__init__("PlayerJoin")
    
    def should_trigger(self, event_data):
        return "joined the game" in event_data.get("raw_line", "")
    
    def on_trigger(self, event_data, cfg):
        player = event_data.get("player", "Unknown")
        if self.debounce_check(player, seconds=30):
            show_mod_list_on_join(player, cfg)
            log_event("HOOK_PLAYER_JOIN", f"Triggered for {player}")
            return True
        return False

class PlayerDeathHook(EventHook):
    """Trigger on player death event"""
    def __init__(self):
        super().__init__("PlayerDeath")
    
    def should_trigger(self, event_data):
        line = event_data.get("raw_line", "")
        return any(x in line for x in [" died ", " was slain ", " suffocated ", " drowned "])
    
    def on_trigger(self, event_data, cfg):
        if self.debounce_check("death", seconds=5):
            send_chat_message("RIP! Better luck next time.")
            log_event("HOOK_PLAYER_DEATH", event_data.get("raw_line", ""))
            return True
        return False

class ChatPatternHook(EventHook):
    """Trigger on chat pattern match"""
    def __init__(self, pattern, response):
        super().__init__(f"ChatPattern:{pattern}")
        self.pattern = pattern.lower()
        self.response = response
    
    def should_trigger(self, event_data):
        return self.pattern in event_data.get("raw_line", "").lower()
    
    def on_trigger(self, event_data, cfg):
        if self.debounce_check(self.pattern, seconds=10):
            send_chat_message(self.response)
            log_event("HOOK_CHAT_PATTERN", f"{self.pattern} -> {self.response}")
            return True
        return False

class ModDownloadHook(EventHook):
    """Trigger on player mod download command"""
    def __init__(self):
        super().__init__("ModDownload")
    
    def should_trigger(self, event_data):
        msg = event_data.get("message") or ""
        return msg.lower().startswith("download ")
    
    def on_trigger(self, event_data, cfg):
        player = event_data.get("player", "Unknown")
        msg = (event_data.get("message") or "").lower().strip()
        
        if self.debounce_check(f"download_{player}", seconds=5):
            handle_mod_download_command(player, msg, cfg)
            log_event("HOOK_MOD_DOWNLOAD", f"Command from {player}: {msg}")
            return True
        return False


def parse_log_line(line):
    """Parse server log line and extract event data"""
    import re
    
    event_data = {
        "raw_line": line,
        "timestamp": None,
        "player": None,
        "event_type": None,
        "message": None
    }
    
    # Parse timestamp [HH:MM:SS]
    ts_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
    if ts_match:
        event_data["timestamp"] = ts_match.group(1)
    
    # Detect player join
    join_match = re.search(r'(\w+) joined the game', line)
    if join_match:
        event_data["player"] = join_match.group(1)
        event_data["event_type"] = "PLAYER_JOIN"
        return event_data
    
    # Detect player death
    death_match = re.search(r'(\w+)(?:\s+)(?:died|was slain|suffocated|drowned|fell)', line)
    if death_match:
        event_data["player"] = death_match.group(1)
        event_data["event_type"] = "PLAYER_DEATH"
        return event_data
    
    # Detect player chat
    chat_match = re.search(r'<(\w+)>\s+(.+)', line)
    if chat_match:
        event_data["player"] = chat_match.group(1)
        event_data["message"] = chat_match.group(2)
        event_data["event_type"] = "PLAYER_CHAT"
        return event_data
    
    return event_data

def remote_event_monitor(cfg):
    """Monitor live.log and trigger hooks based on events"""
    hooks = [
        PlayerJoinHook(),
        PlayerDeathHook(),
        ModDownloadHook(),
        ChatPatternHook("!help", "Available commands: !help, !status, !tps"),
        ChatPatternHook("!status", "Server is running. Check Discord for more info."),
        ChatPatternHook("!tps", "Current TPS: ??? (use /forge tps for details)"),
    ]
    
    log_event("EVENT_MONITOR", "Remote event monitoring started")
    
    # Track last seen position
    last_pos = 0
    
    while True:
        try:
            if not os.path.exists(LOG_FILE):
                time.sleep(5)
                continue
            
            with open(LOG_FILE, 'r') as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                last_pos = f.tell()
            
            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                
                # Parse the line
                event_data = parse_log_line(line)
                
                # Check all hooks
                for hook in hooks:
                    if hook.should_trigger(event_data):
                        try:
                            hook.on_trigger(event_data, cfg)
                        except Exception as e:
                            log_event("HOOK_ERROR", f"{hook.name}: {e}")
            
            time.sleep(1)
        except Exception as e:
            log_event("EVENT_MONITOR_ERROR", str(e))
            time.sleep(5)

def monitor_players(cfg):
    """
    Monitor server events and trigger hooks.
    This replaces the old static join broadcast with a dynamic event system.
    """
    remote_event_monitor(cfg)

# ============================================================================
# CURSEFORGE MOD SCRAPER (Playwright stealth browser — API key is useless)
# ============================================================================

# CurseForge gameVersionTypeId mapping for mod loaders
CF_LOADER_IDS = {
    "neoforge": 6,
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
}

def _parse_cf_download_count(text):
    """Parse CurseForge download count strings like '315.0M', '539.8K', '1.2B' to int"""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if text.upper().endswith(suffix):
            try:
                return int(float(text[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(float(text))
    except ValueError:
        return 0

def _cf_search_url(mc_version, loader, page=1, page_size=50):
    """Build CurseForge search URL with loader filter, version, and pagination.
    
    Uses the search endpoint which supports pageSize=50 and gameVersionTypeId
    for proper loader filtering (NeoForge=6, Forge=1, Fabric=4, Quilt=5).
    """
    loader_id = CF_LOADER_IDS.get(loader.lower(), 6)
    base = "https://www.curseforge.com/minecraft/search"
    return (f"{base}?page={page}&pageSize={page_size}&sortBy=total+downloads"
            f"&version={mc_version}&gameVersionTypeId={loader_id}")

def _scrape_cf_page(page_obj):
    """Extract mod data from a loaded CurseForge search page using DOM selectors.
    
    Returns list of dicts: {name, slug, description, downloads, file_id, download_href, author, source}
    """
    mods = []
    cards = page_obj.query_selector_all("div.project-card")
    
    for card in cards:
        try:
            mod = {}
            
            name_el = card.query_selector("a.name span.ellipsis")
            if not name_el:
                name_el = card.query_selector("a.name")
            mod["name"] = name_el.inner_text().strip() if name_el else ""
            
            slug_el = card.query_selector("a.overlay-link")
            href = slug_el.get_attribute("href") if slug_el else ""
            slug_match = re.search(r'/minecraft/mc-mods/([^/?]+)', href) if href else None
            mod["slug"] = slug_match.group(1) if slug_match else ""
            
            desc_el = card.query_selector("p.description")
            mod["description"] = desc_el.inner_text().strip() if desc_el else ""
            
            dl_el = card.query_selector("li.detail-downloads")
            dl_text = dl_el.inner_text().strip() if dl_el else "0"
            dl_num = re.sub(r'\s*(downloads?|total)\s*', '', dl_text, flags=re.IGNORECASE).strip()
            mod["downloads"] = _parse_cf_download_count(dl_num)
            mod["downloads_raw"] = dl_text
            
            dl_cta = card.query_selector("a.download-cta")
            dl_href = dl_cta.get_attribute("href") if dl_cta else ""
            file_match = re.search(r'/download/(\d+)', dl_href) if dl_href else None
            mod["file_id"] = file_match.group(1) if file_match else ""
            mod["download_href"] = dl_href or ""
            
            author_el = card.query_selector("span.author-name")
            mod["author"] = author_el.inner_text().strip() if author_el else ""
            
            mod["source"] = "curseforge"
            
            if mod["name"] and mod["slug"]:
                mods.append(mod)
        except Exception as e:
            log.warning(f"CurseForge scraper: error parsing card: {e}")
            continue
    
    return mods

def _scrape_cf_dependencies(page_obj, slug):
    """Scrape dependency info from a mod's relations/dependencies page.
    
    Navigates to /minecraft/mc-mods/<slug>/relations/dependencies and extracts
    required and optional dependencies from a.related-project-card elements.
    
    Returns dict: {"required": [{name, slug, type}], "optional": [{name, slug, type}]}
    """
    url = f"https://www.curseforge.com/minecraft/mc-mods/{slug}/relations/dependencies"
    deps = {"required": [], "optional": []}
    
    try:
        page_obj.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(6)
        
        cards = page_obj.query_selector_all("a.related-project-card")
        for card in cards:
            try:
                name_el = card.query_selector("h5")
                type_el = card.query_selector("span.type")
                href = card.get_attribute("href") or ""
                
                dep_name = name_el.inner_text().strip() if name_el else ""
                dep_type = type_el.inner_text().strip() if type_el else ""
                dep_slug_match = re.search(r'/minecraft/mc-mods/([^/?]+)', href)
                dep_slug = dep_slug_match.group(1) if dep_slug_match else ""
                
                if not dep_name:
                    continue
                
                dep_info = {"name": dep_name, "slug": dep_slug, "type": dep_type}
                
                if "required" in dep_type.lower():
                    deps["required"].append(dep_info)
                elif "optional" in dep_type.lower():
                    deps["optional"].append(dep_info)
            except:
                continue
    except Exception as e:
        log.warning(f"CurseForge: error scraping deps for {slug}: {e}")
    
    return deps

def _get_cf_mod_id_from_download_page(page_obj, slug, file_id):
    """Navigate to a CurseForge download page and extract the numeric mod ID.
    
    The download page HTML contains a 'try again' link with the API URL:
    https://www.curseforge.com/api/v1/mods/<numericModId>/files/<fileId>/download
    """
    url = f"https://www.curseforge.com/minecraft/mc-mods/{slug}/download/{file_id}"
    try:
        page_obj.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        html = page_obj.content()
        match = re.search(r'/api/v1/mods/(\d+)/files/\d+/download', html)
        if match:
            return match.group(1)
    except Exception as e:
        log.warning(f"CurseForge scraper: error getting mod ID for {slug}: {e}")
    return None

def fetch_curseforge_mods_scraper(mc_version, loader, limit=100, scrape_deps=True):
    """
    Scrape CurseForge search pages using Playwright stealth headless browser.
    
    Uses the search URL with pageSize=50, gameVersionTypeId for loader filtering,
    sorted by total downloads. Paginates to collect up to `limit` mods.
    
    When scrape_deps=True, also visits each mod's /relations/dependencies page
    to collect required + optional dependencies.
    
    Results are cached to disk (6h TTL).
    
    Args:
        mc_version: e.g. "1.21.1"
        loader: e.g. "neoforge"
        limit: max mods to collect (default 100)
        scrape_deps: whether to scrape dependency pages (default True)
    
    Returns:
        List of mod dicts with {name, slug, description, downloads, file_id,
        download_href, author, source, deps_required, deps_optional}
    """
    if not PLAYWRIGHT_AVAILABLE:
        log.error("Playwright not installed — cannot scrape CurseForge. "
                  "Install: pip3 install --break-system-packages playwright playwright-stealth && "
                  "python3 -m playwright install chromium")
        return []
    
    # Check cache first (6 hour TTL)
    cache_file = os.path.join(CWD, f"curseforge_cache_{mc_version}_{loader}.json")
    if os.path.exists(cache_file):
        try:
            cache_age = time.time() - os.path.getmtime(cache_file)
            if cache_age < 6 * 3600:
                with open(cache_file) as f:
                    cached = json.load(f)
                if cached:
                    log.info(f"CurseForge: loaded {len(cached)} mods from cache ({cache_age/3600:.1f}h old)")
                    return cached[:limit]
        except Exception as e:
            log.warning(f"CurseForge: cache read error: {e}")
    
    log.info(f"CurseForge: scraping top {limit} mods for MC {mc_version} ({loader})...")
    
    all_mods = []
    page_size = 50
    pages_needed = (limit + page_size - 1) // page_size
    
    try:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(
                user_agent=random.choice(CF_USER_AGENTS),
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()
            
            # ---- Phase 1: Scrape search pages ----
            for page_num in range(1, pages_needed + 1):
                if len(all_mods) >= limit:
                    break
                
                url = _cf_search_url(mc_version, loader, page=page_num, page_size=page_size)
                log.info(f"CurseForge: scraping page {page_num}/{pages_needed} ({page_size}/page)")
                
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(6)
                    
                    title = page.title()
                    if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking"]):
                        log.warning(f"CurseForge: Cloudflare challenge on page {page_num}, waiting 15s...")
                        time.sleep(15)
                        title = page.title()
                        if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking"]):
                            log.error(f"CurseForge: Cloudflare challenge NOT resolved, aborting")
                            break
                    
                    page_mods = _scrape_cf_page(page)
                    
                    if not page_mods:
                        log.warning(f"CurseForge: no mods on page {page_num}, stopping")
                        break
                    
                    all_mods.extend(page_mods)
                    log.info(f"CurseForge: page {page_num} -> {len(page_mods)} mods (total: {len(all_mods)})")
                    
                    if page_num < pages_needed:
                        time.sleep(random.uniform(2, 4))
                
                except PlaywrightTimeout:
                    log.warning(f"CurseForge: timeout on page {page_num}")
                    continue
                except Exception as e:
                    log.error(f"CurseForge: error on page {page_num}: {e}")
                    if page_num == 1:
                        break
                    continue
            
            all_mods = all_mods[:limit]
            
            # ---- Phase 2: Scrape dependencies for each mod ----
            if scrape_deps and all_mods:
                log.info(f"CurseForge: scraping dependencies for {len(all_mods)} mods...")
                for i, mod in enumerate(all_mods):
                    slug = mod.get("slug", "")
                    if not slug:
                        continue
                    try:
                        deps = _scrape_cf_dependencies(page, slug)
                        mod["deps_required"] = deps.get("required", [])
                        mod["deps_optional"] = deps.get("optional", [])
                        if deps["required"] or deps["optional"]:
                            log.info(f"  [{i+1}/{len(all_mods)}] {mod['name']}: "
                                     f"{len(deps['required'])} req, {len(deps['optional'])} opt deps")
                        if (i + 1) % 10 == 0:
                            log.info(f"  ... {i+1}/{len(all_mods)} dep pages scraped")
                        time.sleep(random.uniform(1, 2))
                    except Exception as e:
                        log.warning(f"  deps error for {slug}: {e}")
                        mod["deps_required"] = []
                        mod["deps_optional"] = []
            
            context.close()
            browser.close()
    
    except Exception as e:
        log.error(f"CurseForge scraper failed: {e}")
        return []
    
    # Cache results
    if all_mods:
        try:
            with open(cache_file, "w") as f:
                json.dump(all_mods, f, indent=2)
            log.info(f"CurseForge: cached {len(all_mods)} mods to {cache_file}")
        except Exception as e:
            log.warning(f"CurseForge: cache write error: {e}")
    
    return all_mods

def download_mod_from_curseforge(mod_info, mods_dir, mc_version, loader):
    """
    Download a mod JAR from CurseForge using the CDN URL pattern.
    
    Download chain:
    1. API URL: /api/v1/mods/<modId>/files/<fileId>/download
    2. Redirects to edge.forgecdn.net -> mediafilez.forgecdn.net
    
    Returns: 'downloaded', 'exists', or False
    Falls back to Playwright to extract numeric modId if not available.
    """
    mod_name = mod_info.get("name", "unknown")
    slug = mod_info.get("slug", "")
    file_id = mod_info.get("file_id", "")
    mod_id = mod_info.get("mod_id", "")
    
    if not file_id:
        log.warning(f"CurseForge download: no file_id for {mod_name}")
        return False
    
    # Check if we already have this mod by slug match before even hitting the API
    existing = _mod_jar_exists(mods_dir, mod_slug=slug)
    if existing:
        log.info(f"CurseForge: {mod_name} already installed as {existing}, skipping")
        return "exists"
    
    # If we have the numeric mod_id, use the direct API download URL
    if mod_id:
        api_url = f"https://www.curseforge.com/api/v1/mods/{mod_id}/files/{file_id}/download"
        try:
            req = urllib.request.Request(api_url, headers={
                "User-Agent": random.choice(CF_USER_AGENTS)
            })
            with urllib.request.urlopen(req, timeout=60) as response:
                final_url = response.url
                filename = os.path.basename(final_url.split("?")[0])
                if not filename.endswith(".jar"):
                    filename = f"{slug}-{file_id}.jar"
                
                file_path = os.path.join(mods_dir, filename)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    log.info(f"CurseForge: {filename} already exists, skipping")
                    return "exists"
                
                data = response.read()
                with open(file_path, "wb") as f:
                    f.write(data)
                
                log.info(f"CurseForge: downloaded {filename} ({len(data)/1024:.0f} KB)")
                return "downloaded"
        except Exception as e:
            log.warning(f"CurseForge: API download failed for {mod_name}: {e}")
    
    # Fallback: use Playwright to get numeric modId from download page
    if PLAYWRIGHT_AVAILABLE and slug and len(file_id) >= 5:
        try:
            with Stealth().use_sync(sync_playwright()) as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
                )
                context = browser.new_context(
                    user_agent=random.choice(CF_USER_AGENTS),
                    viewport={"width": 1920, "height": 1080}
                )
                pg = context.new_page()
                numeric_id = _get_cf_mod_id_from_download_page(pg, slug, file_id)
                context.close()
                browser.close()
                
                if numeric_id:
                    mod_info_with_id = dict(mod_info, mod_id=numeric_id)
                    return download_mod_from_curseforge(mod_info_with_id, mods_dir, mc_version, loader)
        except Exception as e:
            log.warning(f"CurseForge: Playwright fallback failed for {mod_name}: {e}")
    
    log.error(f"CurseForge: could not download {mod_name} (slug={slug}, file_id={file_id})")
    return False


def fetch_modrinth_mods(mc_version, loader, limit=100, offset=0, categories=None):
    """
    Fetch top downloaded mods from Modrinth for given MC version + loader
    
    Args:
        mc_version: e.g. "1.21.11"
        loader: e.g. "neoforge"
        limit: max # of mods to fetch per request (default 100)
        offset: pagination offset (default 0)
        categories: list of content categories to include (None = all)
    
    Returns:
        List of mod dictionaries, sorted by downloads (highest first)
    """
    from urllib.parse import quote
    base_url = "https://api.modrinth.com/v2"
    
    loader_query = loader.lower()
    
    # Build facets for search
    # Modrinth facet syntax: [["A"],["B"]] = A AND B; [["A","B"]] = A OR B
    # We want: version AND loader (AND category if specified)
    facets_parts = [
        f'["versions:{mc_version}"]',
        f'["categories:{loader_query}"]',
        '["project_type:mod"]'
    ]
    
    # Add category filters if specified
    if categories:
        for cat in categories:
            facets_parts.append(f'["categories:{cat}"]')
    
    facets = "[" + ",".join(facets_parts) + "]"
    facets_encoded = quote(facets)
    
    # Query: sort by downloads (highest first)
    url = f"{base_url}/search?query=&facets={facets_encoded}&limit={limit}&offset={offset}&index=downloads"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            return data.get("hits", [])
    except Exception as e:
        log_event("CURATOR", f"Error fetching mods: {e}")
        return []

def get_mod_dependencies_modrinth(mod_id):
    """Fetch dependencies for a specific mod from Modrinth"""
    base_url = "https://api.modrinth.com/v2"
    url = f"{base_url}/project/{mod_id}"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        log_event("CURATOR", f"Error fetching mod {mod_id}: {e}")
        return None

def get_mod_version_dependencies(mod_id, mc_version, loader):
    """Get dependencies from latest version matching MC version and loader"""
    from urllib.parse import quote
    base_url = "https://api.modrinth.com/v2"
    loader_lower = loader.lower()
    
    try:
        # Try with both game version and loader filters
        url = f'{base_url}/project/{mod_id}/version?loaders=["{loader_lower}"]&game_versions=["{mc_version}"]&limit=5'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            versions = json.loads(response.read().decode())
            if versions:
                return versions[0].get("dependencies", [])
        
        # Fallback: try just the game version
        url = f'{base_url}/project/{mod_id}/version?game_versions=["{mc_version}"]&limit=5'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            versions = json.loads(response.read().decode())
            if versions:
                return versions[0].get("dependencies", [])
        
        # Last fallback: get latest versions and check for exact MC version match
        url = f'{base_url}/project/{mod_id}/version?limit=10'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            versions = json.loads(response.read().decode())
            # Find a recent version that has exact mc_version match
            for v in versions:
                if mc_version in v.get("game_versions", []):
                    return v.get("dependencies", [])
            # Do NOT fall back to wrong MC version — strict matching only
    except Exception as e:
        log_event("DEPS", f"Error fetching deps for {mod_id}: {e}")
    
    return []

def is_library(mod_name, required_dep=False):
    """
    Check if mod is a library/API/dependency (not a user-facing gameplay mod)
    
    ONLY user-facing mods are shown. Dependencies are fetched on-demand.
    
    Args:
        mod_name: name of the mod
        required_dep: if True, don't filter (required deps override library status)
    
    Returns:
        True if should be filtered (is a library/API), False if user-facing
    """
    if not mod_name:
        return True  # Filter out mods with no name
    
    # Required dependencies bypass the library filter — they must be installed
    if required_dep:
        return False
    
    name_lower = mod_name.lower()
    
    # Exact name matches for known libraries/APIs/dependencies
    lib_exact = {
        "fabric api", "fabric-api", "fabric loader", "fabric-loader",
        "fabric language kotlin", "fabric language scala",
        "collective", "konkrete", "balm", "terrablender",
        "searchables", "curios api", "malilib", "malllib",
        "owo-lib", "oωo (owo-lib)", "text placeholder api",
        "playeranimator", "placeholder api",
        "geckolib", "architectury api", "architectury",
        "cloth config", "cloth-config",
        "ferrite core", "ferritecore",
        "yacl", "yet another config lib",
        "puzzles lib", "forge config api port",
        "creative core", "creativecore", "libipn",
        "resourceful lib", "resourceful config",
        "supermartijn642's config lib", "supermartijn642's core lib",
        "fzzy config", "midnight lib", "midnightlib",
        "kotlin for forge", "kotlinforforge",
        "sinytra connector", "forgified fabric api",
        "connector extras", "mod menu", "modmenu",
        "iceberg", "prism lib", "prismlib",
        "lithostitched", "neoforge", "forge",
        "indium", "quilted fabric api",
        "cardinal components api", "trinkets",
        "completeconfig", "complete config",
        "parchment", "mixinextras",
        "connector", "panorama api",
    }
    
    if name_lower.strip() in lib_exact:
        return True
    
    # Substring patterns that indicate a library/API
    lib_patterns = [
        " api",       # "Curios API", "Fabric API", etc.
        " lib",       # "Puzzles Lib", "Prism Lib"
        "lib ",       # "lib " prefix
        "config lib", # Config libraries
        "core lib",   # Core libraries
        "language kotlin",
        "language scala",
        "placeholder api",
    ]
    
    for pattern in lib_patterns:
        if pattern in name_lower:
            return True
    
    # Suffix patterns
    if name_lower.endswith(" api") or name_lower.endswith("-api"):
        return True
    if name_lower.endswith(" lib") or name_lower.endswith("-lib"):
        return True
    if name_lower.endswith("lib") and len(name_lower) > 5:
        # Catch "geckolib", "malilib" but not short words
        if name_lower not in {"toolib"}:  # whitelist real mods ending in lib
            return True
    
    return False  # User-facing mod

def resolve_mod_dependencies_modrinth(mod_id, mc_version, loader, resolved=None, optional_deps=None, depth=0, max_depth=3):
    """
    Recursively resolve mod dependencies from Modrinth
    
    Tracks required vs optional separately. Only fetches required deps automatically.
    Returns (resolved, optional_deps) tuple so callers always get both.
    """
    if resolved is None:
        resolved = {"required": {}, "optional": {}}
    if optional_deps is None:
        optional_deps = {}
    
    if depth > max_depth or mod_id in resolved.get("required", {}):
        return resolved, optional_deps
    
    deps = get_mod_version_dependencies(mod_id, mc_version, loader)
    
    for dep in deps:
        dep_type = dep.get("dependency_type", "required")
        dep_mod_id = dep.get("project_id")
        
        if not dep_mod_id:
            continue
        
        if dep_type == "required":
            # Track required dependency
            if dep_mod_id not in resolved["required"]:
                resolved["required"][dep_mod_id] = {
                    "id": dep_mod_id,
                    "depth": depth + 1,
                    "type": "required"
                }
                # Recursively resolve dependencies of this dependency
                resolve_mod_dependencies_modrinth(dep_mod_id, mc_version, loader, resolved, optional_deps, depth + 1, max_depth)
        
        elif dep_type == "optional":
            # Track optional dependency (don't auto-fetch, but log for audit)
            if dep_mod_id not in optional_deps:
                optional_deps[dep_mod_id] = {
                    "id": dep_mod_id,
                    "requested_by": [mod_id],
                    "type": "optional"
                }
            else:
                # Track that multiple mods have this optional dep
                if mod_id not in optional_deps[dep_mod_id].get("requested_by", []):
                    optional_deps[dep_mod_id]["requested_by"].append(mod_id)
    
    return resolved, optional_deps

def curate_mod_list(mods, mc_version, loader, include_required_deps=True, optional_dep_audit=None):
    """
    Curate mod list:
    1. Filter out libraries
    2. Fetch required dependencies (auto-include even if not in top list)
    3. Track optional dependencies for audit
    4. Remove duplicates
    5. Sort by download count
    
    Returns:
        (curated_mods_dict, optional_deps_audit_dict, required_deps_count)
    """
    curated = {}
    all_required_deps = {}
    all_optional_deps = {}
    
    log_event("CURATOR", f"Curating {len(mods)} mods from Modrinth...")
    
    # Add all top mods
    for mod in mods:
        mod_id = mod.get("project_id")
        mod_name = mod.get("title")
        download_count = mod.get("downloads", 0)
        
        if is_library(mod_name, required_dep=False):
            log_event("CURATOR", f"Skipping library: {mod_name}")
            continue
        
        curated[mod_id] = {
            "id": mod_id,
            "name": mod_name,
            "downloads": download_count,
            "description": mod.get("description", "")[:100],
            "url": f"https://modrinth.com/mod/{mod_id}",
            "dependencies": {"required": [], "optional": []},
            "source": "top_downloaded"
        }
        
        # Resolve dependencies
        if include_required_deps:
            deps_result, opt_deps = resolve_mod_dependencies_modrinth(mod_id, mc_version, loader)
            curated[mod_id]["dependencies"]["required"] = list(deps_result["required"].keys())
            all_required_deps.update(deps_result["required"])
            all_optional_deps.update(opt_deps)
    
    # Auto-fetch required dependencies that aren't already in curated list
    if include_required_deps:
        for dep_id, dep_info in all_required_deps.items():
            if dep_id not in curated:
                try:
                    mod_data = get_mod_dependencies_modrinth(dep_id)
                    if mod_data:
                        dep_name = mod_data.get("title")
                        # Don't filter required deps even if they look like libraries
                        curated[dep_id] = {
                            "id": dep_id,
                            "name": dep_name,
                            "downloads": mod_data.get("downloads", 0),
                            "description": mod_data.get("description", "")[:100],
                            "url": f"https://modrinth.com/mod/{dep_id}",
                            "dependencies": {"required": [], "optional": []},
                            "source": "required_dependency"
                        }
                        log_event("CURATOR", f"Auto-added required dep: {dep_name}")
                except Exception as e:
                    log_event("CURATOR", f"Error fetching required dep {dep_id}: {e}")
    
    # Sort by download count
    sorted_mods = sorted(curated.items(), key=lambda x: x[1]["downloads"], reverse=True)
    
    log_event("CURATOR", f"Curated list: {len(sorted_mods)} mods ({len(all_required_deps)} required deps, {len(all_optional_deps)} optional deps)")
    
    return dict(sorted_mods), all_optional_deps, len(all_required_deps)

def save_curator_cache(mods_dict, optional_deps, mc_version, loader):
    """Cache curated mod list and optional dependencies audit for quick access"""
    cache_file = os.path.join(CWD, f"curator_cache_{mc_version}_{loader}.json")
    audit_file = os.path.join(CWD, f"curator_optional_audit_{mc_version}_{loader}.json")
    
    try:
        with open(cache_file, "w") as f:
            json.dump(mods_dict, f, indent=2)
        log_event("CURATOR", f"Cached {len(mods_dict)} mods to {cache_file}")
        
        # Save optional deps audit
        if optional_deps:
            with open(audit_file, "w") as f:
                json.dump(optional_deps, f, indent=2)
            log_event("CURATOR", f"Saved optional deps audit to {audit_file}")
    except Exception as e:
        log_event("CURATOR", f"Error saving cache: {e}")

def load_curator_cache(mc_version, loader):
    """Load cached mod list and optional deps audit"""
    cache_file = os.path.join(CWD, f"curator_cache_{mc_version}_{loader}.json")
    audit_file = os.path.join(CWD, f"curator_optional_audit_{mc_version}_{loader}.json")
    
    mods_data = None
    optional_data = None
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                mods_data = json.load(f)
        except Exception as e:
            log_event("CURATOR", f"Error loading cache: {e}")
    
    if os.path.exists(audit_file):
        try:
            with open(audit_file) as f:
                optional_data = json.load(f)
        except Exception as e:
            log_event("CURATOR", f"Error loading optional audit: {e}")
    
    return mods_data, optional_data

def print_optional_deps_audit(optional_deps, installed_mods):
    """
    Print audit report of optional dependencies
    Shows which mods have optional deps that we already have
    """
    if not optional_deps:
        print("\n✓ No optional dependencies to audit")
        return
    
    print("\n" + "="*70)
    print("OPTIONAL DEPENDENCY AUDIT")
    print("="*70 + "\n")
    
    print("Shows which mods request optional deps we may have installed:\n")
    
    for opt_mod_id, opt_info in sorted(optional_deps.items(), key=lambda x: len(x[1].get("requested_by", [])), reverse=True):
        requesters = opt_info.get("requested_by", [])
        is_installed = "✓" if opt_mod_id in installed_mods else "✗"
        print(f"{is_installed} {opt_mod_id}")
        print(f"   Requested by {len(requesters)} mod(s)")
        
        # Get names of mods requesting this optional dep
        for req_id in requesters[:3]:  # Show first 3
            req_mod = installed_mods.get(req_id, {})
            if req_mod:
                print(f"   - {req_mod.get('name', req_id)}")
        if len(requesters) > 3:
            print(f"   ... and {len(requesters) - 3} more")
        print()

def display_mod_menu(mods_dict, start=0, per_page=10):
    """Display paginated mod menu"""
    sorted_mods = list(mods_dict.items())
    total = len(sorted_mods)
    pages = (total + per_page - 1) // per_page
    current_page = start // per_page
    
    page_mods = sorted_mods[start:start+per_page]
    
    print(f"\n{'='*70}")
    print(f"Available Mods - Page {current_page + 1}/{pages} (Total: {total})")
    print(f"{'='*70}")
    
    for idx, (mod_id, mod_data) in enumerate(page_mods, start=start+1):
        source_marker = ""
        if mod_data.get("source") == "required_dependency":
            source_marker = " [AUTO-REQUIRED]"
        
        req_deps = len(mod_data.get('dependencies', {}).get('required', []))
        opt_deps = len(mod_data.get('dependencies', {}).get('optional', []))
        
        deps_str = ""
        if req_deps > 0:
            deps_str += f" [{req_deps} req"
        if opt_deps > 0:
            if deps_str:
                deps_str += f", {opt_deps} opt]"
            else:
                deps_str = f" [{opt_deps} opt]"
        elif deps_str:
            deps_str += "]"
        
        print(f"{idx}. {mod_data['name']}{source_marker}{deps_str}")
        print(f"   Downloads: {mod_data['downloads']:,} | {mod_data['description']}")
    
    print(f"\nCommands: [n] next page, [p] previous page, [select N] add mod N, [q] quit")
    return current_page, pages

def rcon_interactive_mod_menu(cfg, mods_dict):
    """Interactive RCON-based mod selection menu"""
    selected = []
    start = 0
    per_page = 10
    
    while True:
        current_page, total_pages = display_mod_menu(mods_dict, start, per_page)
        
        user_input = input("\n> ").strip().lower()
        
        if user_input == "q":
            break
        elif user_input == "n" and current_page < total_pages - 1:
            start += per_page
        elif user_input == "p" and current_page > 0:
            start -= per_page
        elif user_input.startswith("select "):
            try:
                mod_idx = int(user_input.split()[1]) - 1
                sorted_mods = list(mods_dict.items())
                if 0 <= mod_idx < len(sorted_mods):
                    mod_id, mod_data = sorted_mods[mod_idx]
                    selected.append(mod_data)
                    print(f"✓ Selected: {mod_data['name']}")
                    send_rcon_command(cfg, f"say ✓ Admin selected mod: {mod_data['name']}")
            except (ValueError, IndexError):
                print("Invalid selection")
        else:
            print("Invalid command")
    
    return selected

def _get_installed_mod_slugs(mods_dir):
    """Build a dict of normalized mod name -> (filename, file_size) for installed mods.
    Used to detect if we already have a mod installed."""
    installed = {}
    if not os.path.exists(mods_dir):
        return installed
    for fn in os.listdir(mods_dir):
        if fn.endswith('.jar') and os.path.isfile(os.path.join(mods_dir, fn)):
            # Normalize: lowercase, strip version-like suffixes for fuzzy matching
            norm = re.sub(r'[^a-z0-9]', '', fn.lower().split('.jar')[0])
            installed[norm] = fn
            # Also store the raw filename for exact match
            installed[fn] = fn
    return installed


def _mod_jar_exists(mods_dir, filename=None, mod_slug=None):
    """Check if a mod JAR already exists in the mods directory.
    Checks by exact filename first, then by slug/name prefix match."""
    if not os.path.exists(mods_dir):
        return None
    
    # Exact filename match
    if filename:
        path = os.path.join(mods_dir, filename)
        if os.path.exists(path) and os.path.isfile(path):
            return filename
    
    # Fuzzy match: look for JARs whose name contains the mod slug
    if mod_slug:
        slug_lower = mod_slug.lower().replace('-', '').replace('_', '').replace(' ', '')
        for fn in os.listdir(mods_dir):
            if not fn.endswith('.jar') or not os.path.isfile(os.path.join(mods_dir, fn)):
                continue
            fn_norm = fn.lower().replace('-', '').replace('_', '').replace(' ', '')
            if slug_lower in fn_norm:
                return fn
    
    return None


def download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader):
    """Download mod JAR from Modrinth.
    
    - Strict MC version matching only (no adjacent version fallback)
    - Checks if mod already exists (by filename) and skips if so
    - Returns: 'downloaded', 'exists', or False
    """
    mod_name = mod_data.get("name", "unknown")
    mod_id = mod_data.get("id")
    mod_slug = mod_data.get("slug", mod_name)
    
    if not mod_id:
        log_event("CURATOR", f"No mod ID for {mod_name}, skipping")
        return False
    
    base_url = "https://api.modrinth.com/v2"
    loader_lower = loader.lower()
    
    # Try with both game version and loader filters (most specific)
    versions = None
    for attempt_url in [
        f'{base_url}/project/{mod_id}/version?loaders=["{loader_lower}"]&game_versions=["{mc_version}"]&limit=5',
        f'{base_url}/project/{mod_id}/version?game_versions=["{mc_version}"]&limit=5',
    ]:
        try:
            req = urllib.request.Request(attempt_url, headers={"User-Agent": "NeoRunner/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                if result:
                    # Verify the version actually matches our exact MC version
                    for v in result:
                        if mc_version in v.get("game_versions", []):
                            versions = [v]
                            break
                    if versions:
                        break
        except Exception as e:
            log_event("CURATOR", f"API request failed for {mod_name}: {e}")
    
    # Last resort: broad fetch, strict filter
    if not versions:
        try:
            url = f'{base_url}/project/{mod_id}/version?limit=20'
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                all_versions = json.loads(response.read().decode())
                # Exact MC version + correct loader
                for v in all_versions:
                    if mc_version in v.get("game_versions", []) and loader_lower in v.get("loaders", []):
                        versions = [v]
                        break
                # Exact MC version, any loader (last resort)
                if not versions:
                    for v in all_versions:
                        if mc_version in v.get("game_versions", []):
                            versions = [v]
                            break
                # Do NOT fall back to wrong MC version — strict matching only
        except Exception as e:
            log_event("CURATOR", f"Broad version fetch failed for {mod_name}: {e}")
    
    if not versions:
        log_event("CURATOR", f"No version of {mod_name} found for MC {mc_version}")
        return False
    
    files = versions[0].get("files", [])
    if not files:
        log_event("CURATOR", f"No files found for {mod_name}")
        return False
    
    # Get primary file (prefer primary=True, else first)
    file_info = files[0]
    for fi in files:
        if fi.get("primary", False):
            file_info = fi
            break
    
    download_url = file_info.get("url")
    file_name = file_info.get("filename")
    
    if not download_url or not file_name:
        log_event("CURATOR", f"No download URL/filename for {mod_name}")
        return False
    
    # Check if this exact file already exists
    file_path = os.path.join(mods_dir, file_name)
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        log_event("CURATOR", f"Already have {file_name}, skipping")
        return "exists"
    
    # Check if an older version of this mod exists (by slug/name match)
    existing = _mod_jar_exists(mods_dir, mod_slug=mod_slug)
    if existing and existing != file_name:
        # Newer version available — remove old, download new
        old_path = os.path.join(mods_dir, existing)
        try:
            os.remove(old_path)
            log_event("CURATOR", f"Removed old version: {existing}")
        except Exception as e:
            log_event("CURATOR", f"Failed to remove old {existing}: {e}")
    
    # Download with proper timeout
    log_event("CURATOR", f"Downloading {file_name}...")
    try:
        req = urllib.request.Request(download_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
            with open(file_path, "wb") as f:
                f.write(data)
        log_event("CURATOR", f"Downloaded {file_name} ({len(data)/1024:.0f} KB)")
        return "downloaded"
    except Exception as e:
        log_event("CURATOR", f"Download failed for {mod_name}: {e}")
        # Clean up partial file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        return False

def generate_mod_lists_for_loaders(mc_version, limit=100, loaders=None):
    """
    Generate and cache dual-source mod lists for specified loaders.
    Fetches from Modrinth API + CurseForge scraper, deduplicates, saves curator cache.
    Returns dict keyed by loader name, each containing list of mods.
    """
    if loaders is None:
        loaders = ["neoforge"]
    mod_lists = {}
    
    for loader in loaders:
        print(f"\nGenerating {loader.upper()} mod list (up to {limit} per source, dual-source)...")
        
        # ---- SOURCE 1: MODRINTH ----
        scan_limit = min(limit * 5, 500)
        modrinth_raw = []
        for offset in range(0, scan_limit, 100):
            batch_limit = min(100, scan_limit - offset)
            mods = fetch_modrinth_mods(mc_version, loader, limit=batch_limit, offset=offset)
            if mods:
                modrinth_raw.extend(mods)
            else:
                break
        
        modrinth_mods = {}
        for mod in modrinth_raw:
            if len(modrinth_mods) >= limit:
                break
            mod_id = mod.get("project_id")
            mod_name = mod.get("title")
            if not is_library(mod_name):
                modrinth_mods[mod_id] = {
                    "id": mod_id,
                    "name": mod_name,
                    "downloads": mod.get("downloads", 0),
                    "description": mod.get("description", "No description"),
                    "source": "modrinth"
                }
        
        print(f"  Modrinth: {len(modrinth_mods)} user-facing mods")
        
        # ---- SOURCE 2: CURSEFORGE SCRAPER ----
        cf_mods = {}
        try:
            cf_raw = fetch_curseforge_mods_scraper(mc_version, loader, limit=limit, scrape_deps=True)
            for mod in cf_raw:
                mod_name = mod.get("name", "")
                slug = mod.get("slug", "")
                if slug and not is_library(mod_name):
                    cf_mods[f"cf_{slug}"] = {
                        "id": f"cf_{slug}",
                        "name": mod_name,
                        "slug": slug,
                        "downloads": mod.get("downloads", 0),
                        "description": mod.get("description", "No description"),
                        "file_id": mod.get("file_id", ""),
                        "download_href": mod.get("download_href", ""),
                        "author": mod.get("author", ""),
                        "source": "curseforge",
                        "deps_required": mod.get("deps_required", []),
                        "deps_optional": mod.get("deps_optional", []),
                    }
            print(f"  CurseForge: {len(cf_mods)} user-facing mods")
        except Exception as e:
            log_event("BOOT", f"CurseForge scraper failed (non-fatal): {e}")
            print(f"  CurseForge: scraper failed ({e}), continuing with Modrinth only")
        
        # ---- DEDUPLICATION ----
        def _normalize_name(name):
            return re.sub(r'[^a-z0-9]', '', name.lower())
        
        modrinth_name_map = {}
        for mod_id, mod_data in modrinth_mods.items():
            modrinth_name_map[_normalize_name(mod_data["name"])] = mod_id
        
        merged = dict(modrinth_mods)
        cf_dupes = 0
        cf_unique = 0
        for cf_key, cf_mod in cf_mods.items():
            norm = _normalize_name(cf_mod["name"])
            if norm in modrinth_name_map:
                mr_key = modrinth_name_map[norm]
                if mr_key in merged:
                    merged[mr_key]["also_on"] = "curseforge"
                    merged[mr_key]["cf_slug"] = cf_mod.get("slug", "")
                    merged[mr_key]["cf_file_id"] = cf_mod.get("file_id", "")
                    merged[mr_key]["cf_deps_required"] = cf_mod.get("deps_required", [])
                    merged[mr_key]["cf_deps_optional"] = cf_mod.get("deps_optional", [])
                cf_dupes += 1
            else:
                merged[cf_key] = cf_mod
                cf_unique += 1
        
        print(f"  Dedup: {cf_dupes} shared, {cf_unique} CF-only added -> {len(merged)} unique mods")
        
        # Save curator cache (this is what the dashboard API reads)
        save_curator_cache(merged, {}, mc_version, loader)
        
        # Also return as a flat list for in-memory use
        mod_lists[loader] = sorted(merged.values(), key=lambda m: m.get("downloads", 0), reverse=True)
        print(f"  {len(mod_lists[loader])} {loader} mods ready")
    
    return mod_lists

def curator_command(cfg, limit=None, show_optional_audit=False):
    """
    Main curator command - dual-source smart dependency management
    
    Flow:
    1. Fetch top N mods from BOTH Modrinth API AND CurseForge web scraper
    2. Filter OUT all libs/APIs
    3. Deduplicate by normalized mod name (prefer Modrinth for downloads, keep both sources)
    4. Merge into unified list sorted by downloads
    5. Save curator cache so dashboard/API can access the full list
    6. When called interactively: show list, user picks, download mods + required deps
    7. Auto-fetch CurseForge required deps (from scraped dep data)
    8. Flag optional dep interoperability: if 2+ selected mods share an optional dep, notify user
    
    Args:
        cfg: configuration dict
        limit: max USER-FACING mods to fetch PER SOURCE (default 100, None = use config)
        show_optional_audit: show optional deps audit report after download
    """
    mc_version = cfg.get("mc_version", "1.21.11")
    loader = cfg.get("loader", "neoforge")
    if limit is None:
        limit = cfg.get("curator_limit", 100)
    
    print(f"\n{'='*70}")
    print(f"MOD CURATOR - {loader.upper()} {mc_version} (DUAL SOURCE)")
    print(f"{'='*70}\n")
    
    # ---- SOURCE 1: MODRINTH API ----
    print(f"[1/2] Fetching top {limit} mods from Modrinth API...")
    scan_limit = min(limit * 5, 500)
    
    modrinth_raw = []
    for offset in range(0, scan_limit, 100):
        batch_limit = min(100, scan_limit - offset)
        mods = fetch_modrinth_mods(mc_version, loader, limit=batch_limit, offset=offset)
        if mods:
            modrinth_raw.extend(mods)
        else:
            break
    
    # Filter Modrinth to user-facing only
    modrinth_mods = {}
    for mod in modrinth_raw:
        if len(modrinth_mods) >= limit:
            break
        mod_id = mod.get("project_id")
        mod_name = mod.get("title")
        if not is_library(mod_name):
            modrinth_mods[mod_id] = {
                "id": mod_id,
                "name": mod_name,
                "downloads": mod.get("downloads", 0),
                "description": mod.get("description", "No description"),
                "source": "modrinth"
            }
    
    print(f"  Modrinth: {len(modrinth_mods)} user-facing mods (scanned {len(modrinth_raw)} total)")
    
    # ---- SOURCE 2: CURSEFORGE SCRAPER ----
    print(f"\n[2/2] Fetching top {limit} mods from CurseForge (web scraper)...")
    cf_raw = fetch_curseforge_mods_scraper(mc_version, loader, limit=limit, scrape_deps=True)
    
    # Build a slug -> raw CF mod lookup (for dep resolution later)
    cf_raw_by_slug = {}
    for mod in cf_raw:
        s = mod.get("slug", "")
        if s:
            cf_raw_by_slug[s] = mod
    
    # Filter CurseForge to user-facing only, preserving dep data
    cf_mods = {}
    for mod in cf_raw:
        mod_name = mod.get("name", "")
        if not is_library(mod_name):
            slug = mod.get("slug", "")
            if slug:
                cf_mods[f"cf_{slug}"] = {
                    "id": f"cf_{slug}",
                    "name": mod_name,
                    "slug": slug,
                    "downloads": mod.get("downloads", 0),
                    "description": mod.get("description", "No description"),
                    "file_id": mod.get("file_id", ""),
                    "download_href": mod.get("download_href", ""),
                    "author": mod.get("author", ""),
                    "source": "curseforge",
                    "deps_required": mod.get("deps_required", []),
                    "deps_optional": mod.get("deps_optional", []),
                }
    
    print(f"  CurseForge: {len(cf_mods)} user-facing mods (scraped {len(cf_raw)} total)")
    
    # ---- DEDUPLICATION ----
    def _normalize_name(name):
        """Normalize mod name for dedup comparison: lowercase, strip non-alphanum"""
        return re.sub(r'[^a-z0-9]', '', name.lower())
    
    # Build name -> key mapping for Modrinth mods
    modrinth_name_map = {}
    for mod_id, mod_data in modrinth_mods.items():
        norm = _normalize_name(mod_data["name"])
        modrinth_name_map[norm] = mod_id
    
    # Merge: start with all Modrinth mods, add CurseForge-only mods
    merged_mods = dict(modrinth_mods)
    cf_dupes = 0
    cf_unique = 0
    
    for cf_key, cf_mod in cf_mods.items():
        norm = _normalize_name(cf_mod["name"])
        if norm in modrinth_name_map:
            # Duplicate — keep Modrinth entry, annotate with CF info
            mr_key = modrinth_name_map[norm]
            if mr_key in merged_mods:
                merged_mods[mr_key]["also_on"] = "curseforge"
                merged_mods[mr_key]["cf_slug"] = cf_mod.get("slug", "")
                merged_mods[mr_key]["cf_file_id"] = cf_mod.get("file_id", "")
                # Carry over CF dep data to the merged entry
                merged_mods[mr_key]["cf_deps_required"] = cf_mod.get("deps_required", [])
                merged_mods[mr_key]["cf_deps_optional"] = cf_mod.get("deps_optional", [])
            cf_dupes += 1
        else:
            # CurseForge-only mod — add to merged list
            merged_mods[cf_key] = cf_mod
            cf_unique += 1
    
    print(f"\n  Deduplication: {cf_dupes} shared mods, {cf_unique} CurseForge-only mods added")
    print(f"  Total unique mods: {len(merged_mods)}")
    
    # ---- SORT & CACHE ----
    user_facing_mods = merged_mods
    sorted_mods = sorted(user_facing_mods.items(), key=lambda x: x[1]['downloads'], reverse=True)
    
    # Save curator cache so dashboard/API can access the full list
    save_curator_cache(user_facing_mods, {}, mc_version, loader)
    
    print(f"\n{'='*70}")
    print(f"  Found {len(user_facing_mods)} unique user-facing mods from both sources")
    print(f"{'='*70}\n")
    
    # ---- DISPLAY ----
    print(f"{'='*70}")
    print("AVAILABLE MODS FOR SELECTION")
    print(f"{'='*70}\n")
    
    for idx, (mod_id, mod_data) in enumerate(sorted_mods, 1):
        src_tag = mod_data.get("source", "?")[0].upper()  # M or C
        also = "+" if mod_data.get("also_on") else " "
        print(f"{idx:3}. [{src_tag}{also}] {mod_data['name']:<46} ({mod_data['downloads']:>12,})")
    
    print(f"\n{len(user_facing_mods)} total mods available  [M]=Modrinth [C]=CurseForge [+]=both sources")
    
    # ---- SELECTION ----
    print(f"\n{'='*70}")
    print("SELECT MODS TO DOWNLOAD")
    print(f"{'='*70}\n")
    
    try:
        response = input("Download all mods? [y/n/custom]: ").strip().lower()
    except EOFError:
        print("(Skipping interactive selection when running as service)")
        return
    
    selected_mods_list = []
    
    if response == "y":
        selected_mods_list = list(user_facing_mods.values())
        print(f"\nSelected all {len(selected_mods_list)} mods")
    elif response == "custom":
        print("\nEnter mod numbers to select (comma-separated, e.g. 1,5,10 or 1-10):")
        try:
            selection_input = input("Mods to download: ").strip()
            selected_indices = []
            for part in selection_input.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = map(int, part.split("-"))
                    selected_indices.extend(range(start - 1, end))
                else:
                    selected_indices.append(int(part) - 1)
            for idx in sorted(set(selected_indices)):
                if 0 <= idx < len(sorted_mods):
                    selected_mods_list.append(sorted_mods[idx][1])
            print(f"\nSelected {len(selected_mods_list)} mods")
        except ValueError:
            print("Invalid selection format")
            return
    else:
        print("Cancelled")
        return
    
    if not selected_mods_list:
        print("No mods selected")
        return
    
    # ---- DEPENDENCY RESOLUTION ----
    print(f"\n{'='*70}")
    print("RESOLVING DEPENDENCIES")
    print(f"{'='*70}\n")
    
    mods_dir = cfg.get("mods_dir", "mods")
    os.makedirs(mods_dir, exist_ok=True)
    
    modrinth_selected = [m for m in selected_mods_list if m.get("source") == "modrinth"]
    curseforge_selected = [m for m in selected_mods_list if m.get("source") == "curseforge"]
    
    # -- Modrinth: resolve deps via API --
    modrinth_req_deps = set()
    modrinth_opt_deps = {}  # dep_mod_id -> {id, requested_by: [mod_names]}
    
    if modrinth_selected:
        print(f"Resolving dependencies for {len(modrinth_selected)} Modrinth mods...")
        for mod in modrinth_selected:
            try:
                opt_deps_collector = {}
                deps, opt_collected = resolve_mod_dependencies_modrinth(mod['id'], mc_version, loader, optional_deps=opt_deps_collector)
                modrinth_req_deps.update(deps.get("required", {}).keys())
                # Collect optional deps with requester names
                for opt_id, opt_info in opt_deps_collector.items():
                    if opt_id not in modrinth_opt_deps:
                        modrinth_opt_deps[opt_id] = {"id": opt_id, "requested_by": [mod.get("name", mod["id"])]}
                    else:
                        name = mod.get("name", mod["id"])
                        if name not in modrinth_opt_deps[opt_id]["requested_by"]:
                            modrinth_opt_deps[opt_id]["requested_by"].append(name)
            except Exception as e:
                log.warning(f"Modrinth dep resolution failed for {mod.get('name','?')}: {e}")
        print(f"  Modrinth: {len(modrinth_req_deps)} required deps, {len(modrinth_opt_deps)} optional deps")
    
    # -- CurseForge: resolve deps from scraped data --
    cf_req_dep_slugs = set()   # slugs of required deps to download
    cf_opt_deps = {}           # slug -> {name, slug, requested_by: [mod_names]}
    
    if curseforge_selected:
        print(f"Resolving dependencies for {len(curseforge_selected)} CurseForge mods...")
        for mod in curseforge_selected:
            mod_name = mod.get("name", "?")
            for dep in mod.get("deps_required", []):
                dep_slug = dep.get("slug", "")
                if dep_slug and not is_library(dep.get("name", ""), required_dep=True):
                    cf_req_dep_slugs.add(dep_slug)
            for dep in mod.get("deps_optional", []):
                dep_slug = dep.get("slug", "")
                dep_name = dep.get("name", dep_slug)
                if dep_slug:
                    if dep_slug not in cf_opt_deps:
                        cf_opt_deps[dep_slug] = {"name": dep_name, "slug": dep_slug, "requested_by": [mod_name]}
                    else:
                        if mod_name not in cf_opt_deps[dep_slug]["requested_by"]:
                            cf_opt_deps[dep_slug]["requested_by"].append(mod_name)
        # Also check merged Modrinth mods that had CF dep data (duplicates)
        for mod in modrinth_selected:
            mod_name = mod.get("name", "?")
            for dep in mod.get("cf_deps_required", []):
                dep_slug = dep.get("slug", "")
                if dep_slug and not is_library(dep.get("name", ""), required_dep=True):
                    cf_req_dep_slugs.add(dep_slug)
            for dep in mod.get("cf_deps_optional", []):
                dep_slug = dep.get("slug", "")
                dep_name = dep.get("name", dep_slug)
                if dep_slug:
                    if dep_slug not in cf_opt_deps:
                        cf_opt_deps[dep_slug] = {"name": dep_name, "slug": dep_slug, "requested_by": [mod_name]}
                    else:
                        if mod_name not in cf_opt_deps[dep_slug]["requested_by"]:
                            cf_opt_deps[dep_slug]["requested_by"].append(mod_name)
        print(f"  CurseForge: {len(cf_req_dep_slugs)} required deps, {len(cf_opt_deps)} optional deps")
    
    # ---- OPTIONAL DEP INTEROPERABILITY REPORT ----
    # Merge optional deps from both sources, flag when 2+ selected mods share one
    interop_flags = []
    
    # Build a selected mod name set for cross-reference
    selected_names_norm = set(_normalize_name(m.get("name", "")) for m in selected_mods_list)
    
    # Check Modrinth optional deps shared by 2+ mods
    for opt_id, opt_info in modrinth_opt_deps.items():
        if len(opt_info["requested_by"]) >= 2:
            interop_flags.append({
                "dep_id": opt_id,
                "dep_name": opt_id,  # Modrinth uses project IDs
                "source": "modrinth",
                "requested_by": opt_info["requested_by"],
            })
    
    # Check CurseForge optional deps shared by 2+ mods
    for slug, opt_info in cf_opt_deps.items():
        if len(opt_info["requested_by"]) >= 2:
            interop_flags.append({
                "dep_id": slug,
                "dep_name": opt_info["name"],
                "source": "curseforge",
                "requested_by": opt_info["requested_by"],
            })
    
    if interop_flags:
        print(f"\n{'='*70}")
        print("OPTIONAL DEPENDENCY INTEROPERABILITY")
        print(f"{'='*70}")
        print(f"\n{len(interop_flags)} optional deps are shared by 2+ of your selected mods.")
        print("Installing these can improve compatibility between the mods that use them:\n")
        for flag in interop_flags:
            requesters = ", ".join(flag["requested_by"][:5])
            if len(flag["requested_by"]) > 5:
                requesters += f" (+{len(flag['requested_by'])-5} more)"
            src = flag["source"][0].upper()
            print(f"  [{src}] {flag['dep_name']}")
            print(f"      Shared by: {requesters}\n")
    
    # ---- DOWNLOAD MODS ----
    print(f"\n{'='*70}")
    print("DOWNLOADING MODS & DEPENDENCIES")
    print(f"{'='*70}\n")
    
    downloaded_mods = []
    skipped_mods = []
    deps_downloaded = 0
    deps_skipped = 0
    
    # Download Modrinth mods
    if modrinth_selected:
        print(f"Downloading {len(modrinth_selected)} Modrinth mods:")
        for mod in modrinth_selected:
            result = download_mod_from_modrinth(mod, mods_dir, mc_version, loader)
            if result == "exists":
                skipped_mods.append(f"[M] {mod['name']}")
                print(f"  SKIP [M] {mod['name']} (already installed)")
            elif result:
                downloaded_mods.append(f"[M] {mod['name']}")
                print(f"  OK [M] {mod['name']}")
            else:
                print(f"  FAIL [M] {mod['name']}")
    
    # Download CurseForge mods
    if curseforge_selected:
        print(f"\nDownloading {len(curseforge_selected)} CurseForge mods:")
        for mod in curseforge_selected:
            result = download_mod_from_curseforge(mod, mods_dir, mc_version, loader)
            if result == "exists":
                skipped_mods.append(f"[C] {mod['name']}")
                print(f"  SKIP [C] {mod['name']} (already installed)")
            elif result:
                downloaded_mods.append(f"[C] {mod['name']}")
                print(f"  OK [C] {mod['name']}")
            else:
                print(f"  FAIL [C] {mod['name']}")
    
    # Download Modrinth required dependencies
    if modrinth_req_deps:
        print(f"\nDownloading {len(modrinth_req_deps)} Modrinth required dependencies:")
        for dep_mod_id in modrinth_req_deps:
            try:
                dep_info = {"id": dep_mod_id, "name": dep_mod_id}
                result = download_mod_from_modrinth(dep_info, mods_dir, mc_version, loader)
                if result == "exists":
                    deps_skipped += 1
                    print(f"  SKIP [dep] {dep_mod_id} (already installed)")
                elif result:
                    deps_downloaded += 1
                    print(f"  OK [dep] {dep_mod_id}")
            except Exception as e:
                log.warning(f"  FAIL [dep] {dep_mod_id}: {e}")
    
    # Download CurseForge required dependencies
    if cf_req_dep_slugs:
        print(f"\nDownloading {len(cf_req_dep_slugs)} CurseForge required dependencies:")
        for dep_slug in cf_req_dep_slugs:
            # Look up dep info from the raw CF data (may have been scraped)
            dep_mod = cf_raw_by_slug.get(dep_slug)
            if dep_mod:
                dep_info = {
                    "name": dep_mod.get("name", dep_slug),
                    "slug": dep_slug,
                    "file_id": dep_mod.get("file_id", ""),
                    "source": "curseforge",
                }
                result = download_mod_from_curseforge(dep_info, mods_dir, mc_version, loader)
                if result == "exists":
                    deps_skipped += 1
                    print(f"  SKIP [dep] {dep_slug} (already installed)")
                elif result:
                    deps_downloaded += 1
                    print(f"  OK [dep] {dep_slug}")
                else:
                    print(f"  FAIL [dep] {dep_slug} (download failed)")
            else:
                # Dep wasn't in our scraped list — log it, can't auto-download without file_id
                print(f"  SKIP [dep] {dep_slug} (not in scraped data, install manually from CurseForge)")
    
    # ---- SUMMARY ----
    print(f"\n{'='*70}")
    print(f"DOWNLOAD COMPLETE")
    print(f"{'='*70}")
    print(f"  Modrinth mods:    {len(modrinth_selected)} selected")
    print(f"  CurseForge mods:  {len(curseforge_selected)} selected")
    print(f"  Downloaded:       {len(downloaded_mods)} mods + {deps_downloaded} deps")
    print(f"  Skipped:          {len(skipped_mods)} mods + {deps_skipped} deps (already installed)")
    if interop_flags:
        print(f"  Interop flags:    {len(interop_flags)} optional deps shared by 2+ mods")
    print()
    
    # Optional audit report
    if show_optional_audit and (modrinth_opt_deps or cf_opt_deps):
        print(f"{'='*70}")
        print("OPTIONAL DEPENDENCY AUDIT (FULL)")
        print(f"{'='*70}\n")
        print("Modrinth optional deps:")
        for opt_id, info in sorted(modrinth_opt_deps.items(), key=lambda x: len(x[1]["requested_by"]), reverse=True):
            count = len(info["requested_by"])
            tag = " ** INTEROP" if count >= 2 else ""
            print(f"  {opt_id} (requested by {count} mod{'s' if count != 1 else ''}){tag}")
        print("\nCurseForge optional deps:")
        for slug, info in sorted(cf_opt_deps.items(), key=lambda x: len(x[1]["requested_by"]), reverse=True):
            count = len(info["requested_by"])
            tag = " ** INTEROP" if count >= 2 else ""
            print(f"  {info['name']} [{slug}] (requested by {count} mod{'s' if count != 1 else ''}){tag}")
        print()
    
    # Save optional deps audit for API/dashboard access
    combined_opt_audit = {}
    for opt_id, info in modrinth_opt_deps.items():
        combined_opt_audit[f"mr_{opt_id}"] = {"name": opt_id, "source": "modrinth", "requested_by": info["requested_by"]}
    for slug, info in cf_opt_deps.items():
        combined_opt_audit[f"cf_{slug}"] = {"name": info["name"], "source": "curseforge", "requested_by": info["requested_by"]}
    save_curator_cache(user_facing_mods, combined_opt_audit, mc_version, loader)
    
    # Regenerate mod ZIP + install scripts
    print("Updating mod distribution package...")
    sort_mods_by_type(mods_dir)
    create_install_scripts(mods_dir, cfg)
    create_mod_zip(mods_dir)
    print("Done - ready for distribution on port 8000\n")

def create_systemd_service(cfg):
    """Generate systemd service file for auto-start"""
    loader = cfg.get("loader", "neoforge")
    mc_ver = cfg.get("mc_version", "1.21.11")
    python_bin = sys.executable or "/usr/bin/python3"
    service_content = f"""[Unit]
Description=Minecraft {loader} {mc_ver} Server (NeoRunner)
After=network.target

[Service]
Type=simple
User={os.getenv('USER')}
WorkingDirectory={CWD}
ExecStart={python_bin} {os.path.abspath(__file__)} run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    service_path = os.path.join(CWD, "mcserver.service")
    with open(service_path, "w") as f:
        f.write(service_content)
    log_event("SYSTEMD", f"Created {service_path}")
    print(f"\nTo install systemd service:")
    print(f"  sudo mv {service_path} /etc/systemd/system/")
    print(f"  sudo systemctl daemon-reload")
    print(f"  sudo systemctl enable mcserver")
    print(f"  sudo systemctl start mcserver\n")

def init_ferium_scheduler(cfg):
    """Initialize ferium background scheduler for mod updates"""
    try:
        manager = FeriumManager(cwd=CWD)
        if cfg.get("ferium_enable_scheduler", True):
            log_event("FERIUM_SETUP", "Initializing mod update scheduler...")
            
            # Get scheduler parameters from config
            update_interval = cfg.get("ferium_update_interval_hours", 4)
            weekly_day = cfg.get("ferium_weekly_update_day", "mon")
            weekly_hour = cfg.get("ferium_weekly_update_hour", 2)
            
            success = manager.start_scheduler(
                update_interval_hours=update_interval,
                weekly_update_day=weekly_day,
                weekly_update_hour=weekly_hour
            )
            if success:
                log_event("FERIUM_SETUP", f"Scheduler started ({update_interval}h updates, weekly on {weekly_day} at {weekly_hour}:00)")
                return manager
            else:
                log_event("FERIUM_WARN", "Scheduler failed to start")
                return None
        return None
    except Exception as e:
        log_event("FERIUM_ERROR", f"Failed to initialize ferium: {e}")
        return None

def main():
    ensure_deps()
    cfg = get_config()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "curator":
            # Parse curator-specific arguments
            curator_limit = None
            show_optional_audit = True
            
            # Parse remaining arguments
            i = 2
            while i < len(sys.argv):
                arg = sys.argv[i]
                if arg == "--limit" and i + 1 < len(sys.argv):
                    try:
                        curator_limit = int(sys.argv[i + 1])
                        i += 2
                    except ValueError:
                        print(f"[ERROR] --limit requires an integer value")
                        sys.exit(1)
                elif arg == "--no-audit":
                    show_optional_audit = False
                    i += 1
                elif arg == "--help" or arg == "-h":
                    print("\nMod Curator - Discover and curate mods for your server\n")
                    print("Usage: python3 run.py curator [options]\n")
                    print("Options:")
                    print("  --limit N              Fetch top N mods (default: from config)")
                    print("  --no-audit             Skip optional dependencies audit report")
                    print("  --help, -h             Show this help message\n")
                    return
                else:
                    print(f"[ERROR] Unknown curator option: {arg}")
                    print("Use 'python3 run.py curator --help' for usage information")
                    sys.exit(1)
                i += 1
            
            # Launch mod curator with parsed arguments
            curator_command(cfg, limit=curator_limit, show_optional_audit=show_optional_audit)
            return
        elif cmd == "run":
            print("[BOOT] Starting server automation...")
            
            # Check if server is already initialized (skip regeneration)
            initialized_marker = os.path.join(CWD, ".initialized")
            is_initialized = os.path.exists(initialized_marker)
            
            if is_initialized:
                log_event("BOOT", "Server already initialized, skipping regeneration")
            else:
                # First-time setup: generate systemd service and install scripts
                create_systemd_service(cfg)
            
            # Check if first run and offer curator
            first_run_marker = os.path.join(CWD, ".curator_first_run")
            if not os.path.exists(first_run_marker) and cfg.get("run_curator_on_startup", False):
                # Only prompt if running interactively (not in systemd)
                if sys.stdin.isatty():
                    print("\n" + "="*70)
                    print("FIRST RUN: MOD CURATOR SETUP")
                    print("="*70)
                    print("\nWould you like to discover and add the top 100 mods")
                    print(f"for {cfg['loader']} {cfg['mc_version']} right now?")
                    print("\nThis will fetch mods from Modrinth and let you select")
                    print("which ones to add to your server.\n")
                    
                    response = input("Run mod curator now? [y/n]: ").strip().lower()
                    if response == "y":
                        print("\nLaunching curator...")
                        curator_command(cfg)
                        print("\nCurator complete! Starting server...\n")
                else:
                    # Running as systemd service - skip interactive prompt
                    log_event("BOOT", "Skipping interactive curator setup (running as service)")
                
                # Mark that we've run curator setup
                with open(first_run_marker, "w") as f:
                    f.write("first run complete")
                log_event("BOOT", "Marked curator first-run complete")
            
            # Check if modloader is properly configured
            loader_choice = cfg.get("loader", "neoforge")
            print(f"\n[BOOT] Checking modloader: {loader_choice}")
            if not download_loader(loader_choice):
                print("[ERROR] Modloader configuration invalid or missing")
                print(f"For {loader_choice}, ensure libraries are installed correctly")
                sys.exit(1)
            
            # Setup mods
            print("[BOOT] Sorting mods by type (client/server/both)...")
            sort_mods_by_type(cfg["mods_dir"])
            
            # Always regenerate install scripts (pick up port/IP changes)
            create_install_scripts(cfg["mods_dir"], cfg)
            create_mod_zip(cfg["mods_dir"])
            
            if not is_initialized:
                # Write initialized marker
                with open(initialized_marker, "w") as f:
                    f.write(f"initialized at {datetime.now().isoformat()}")
                log_event("BOOT", "First-time initialization complete, marker written")
            
            # Generate mod lists for the active loader at startup
            loader = cfg.get("loader", "neoforge")
            mc_version = cfg.get("mc_version", "1.21.11")
            curator_limit = cfg.get("curator_limit", 100)
            print(f"\n[BOOT] Generating mod list for {loader}...")
            try:
                mod_lists = generate_mod_lists_for_loaders(mc_version, limit=curator_limit, loaders=[loader])
                cfg["mod_lists"] = mod_lists
                log_event("BOOT", f"Mod list generated for {loader}")
            except Exception as e:
                log_event("ERROR", f"Failed to generate mod lists: {e}")
            
            # Start services
            threading.Thread(target=http_server, args=(cfg["http_port"], cfg["mods_dir"]), daemon=True).start()
            threading.Thread(target=backup_scheduler, args=(cfg,), daemon=True).start()
            threading.Thread(target=monitor_players, args=(cfg,), daemon=True).start()
            
            # Initialize ferium scheduler for automatic mod updates
            ferium_mgr = init_ferium_scheduler(cfg)
            
            # Start server with crash detection
            run_server(cfg)
            
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                log_event("SHUTDOWN", "Server stopping")
                run("tmux send-keys -t MC 'stop' Enter")
                time.sleep(10)
    else:
        # Show client instructions
        props = parse_props()
        server_ip = props.get("server-ip", "YOURSERVER")
        server_port = props.get("server-port", "25565")
        
        print(f"\n{'='*50}")
        print(f"Server IP: {server_ip}:{server_port}")
        print(f"Mod HTTP: http://{server_ip}:{cfg['http_port']}")
        print(f"\nClient Installation:")
        print(f"\n  Windows (PowerShell):")
        print(f"    powershell -ExecutionPolicy Bypass -File install-mods.ps1 -ServerIP {server_ip} -Port {cfg['http_port']}")
        print(f"\n  Linux/Mac (Bash):")
        print(f"    bash install-mods.sh {server_ip} {cfg['http_port']}")
        print(f"\n  Direct ZIP:")
        print(f"    http://{server_ip}:{cfg['http_port']}/mods_latest.zip")
        print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
