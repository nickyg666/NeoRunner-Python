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
from urllib.parse import urljoin
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
                    """Return curated mod lists from cache, normalized to a list"""
                    c = load_cfg()
                    loader = c.get("loader", "neoforge")
                    mc_ver = c.get("mc_version", "1.21.11")
                    cache_file = os.path.join(CWD, f"curator_cache_{mc_ver}_{loader}.json")
                    
                    if os.path.exists(cache_file):
                        try:
                            with open(cache_file) as f:
                                raw = json.load(f)
                            # Normalize: cache may be {id: {id,name,...}} or {loader: [list]}
                            if isinstance(raw, dict):
                                # Check if values are mod objects (have 'name' key)
                                first_val = next(iter(raw.values()), None) if raw else None
                                if isinstance(first_val, dict) and "name" in first_val:
                                    # Flat dict of {mod_id: mod_obj} -> convert to list
                                    mods = sorted(raw.values(), key=lambda m: m.get("downloads", 0), reverse=True)
                                    return jsonify({loader: mods})
                                elif isinstance(first_val, list):
                                    # Already {loader: [list]} format
                                    return jsonify(raw)
                                else:
                                    return jsonify(raw)
                            elif isinstance(raw, list):
                                return jsonify({loader: raw})
                            else:
                                return jsonify(raw)
                        except Exception:
                            pass
                    
                    return jsonify({"error": "No cached mod lists. Run: python3 run.py curator"}), 404
                
                @app.route("/api/install-mods", methods=["POST"])
                def api_install_mods():
                    """Install selected mods from curated list"""
                    try:
                        data = request.json
                        selected = data.get("selected", [])
                        if not selected:
                            return jsonify({"success": False, "error": "No mods selected"}), 400
                        
                        c = load_cfg()
                        mc_ver = c.get("mc_version", "1.21.11")
                        loader = c.get("loader", "neoforge")
                        m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        
                        downloaded = 0
                        failed = []
                        for mod_id in selected:
                            try:
                                mod_data = {"id": mod_id, "name": mod_id}
                                if download_mod_from_modrinth(mod_data, m_dir, mc_ver, loader):
                                    downloaded += 1
                                else:
                                    failed.append(mod_id)
                            except Exception as e:
                                failed.append(mod_id)
                        
                        return jsonify({
                            "success": True,
                            "downloaded": downloaded,
                            "failed": failed,
                            "message": f"Downloaded {downloaded}/{len(selected)} mods"
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
                            run_cmd(f"echo 'stop' | nc localhost {c.get('rcon_port', 25575)} 2>/dev/null")
                            return jsonify({"success": True, "message": "Stop command sent"})
                        return jsonify({"success": False, "error": "RCON not configured"}), 400
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

def _try_self_heal(loader_instance, crash_info, cfg):
    """Attempt to fix a crash by fetching missing dependency from Modrinth.
    Returns True if a fix was applied and a restart should be attempted."""
    crash_type = crash_info.get("type", "unknown")
    
    if crash_type == "missing_dep":
        dep_name = crash_info.get("dep", "")
        if not dep_name or dep_name == "unknown":
            log_event("SELF_HEAL", "Missing dependency detected but name unknown, cannot auto-fix")
            return False
        
        log_event("SELF_HEAL", f"Attempting to fetch missing dependency: {dep_name}")
        mc_version = cfg.get("mc_version", "1.21.11")
        loader_name = cfg.get("loader", "neoforge")
        mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
        
        # Search Modrinth for the mod by name
        try:
            search_url = f"https://api.modrinth.com/v2/search?query={dep_name}&facets=[[\"versions:{mc_version}\"],[\"categories:{loader_name}\"]]]&limit=5"
            req = urllib.request.Request(search_url, headers={"User-Agent": "NeoRunner/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                results = json.loads(resp.read().decode())
            
            hits = results.get("hits", [])
            if not hits:
                log_event("SELF_HEAL", f"No Modrinth results for '{dep_name}'")
                return False
            
            # Pick best match (exact slug match first, then first result)
            best = None
            for h in hits:
                if h.get("slug", "").lower() == dep_name.lower():
                    best = h
                    break
            if not best:
                best = hits[0]
            
            mod_data = {"id": best["project_id"], "name": best.get("title", dep_name)}
            if download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader_name):
                log_event("SELF_HEAL", f"Successfully downloaded {mod_data['name']} - will restart")
                return True
            else:
                log_event("SELF_HEAL", f"Failed to download {dep_name}")
                return False
        except Exception as e:
            log_event("SELF_HEAL", f"Error searching Modrinth for {dep_name}: {e}")
            return False
    
    elif crash_type == "mod_error":
        log_event("SELF_HEAL", f"Mod error detected: {crash_info.get('message', '')[:100]}")
        log_event("SELF_HEAL", "Cannot auto-fix mod errors. Check logs and remove the broken mod.")
        return False
    
    elif crash_type == "version_mismatch":
        log_event("SELF_HEAL", f"Version mismatch: {crash_info.get('message', '')[:100]}")
        log_event("SELF_HEAL", "Cannot auto-fix version mismatches. Check mod compatibility.")
        return False
    
    else:
        log_event("SELF_HEAL", f"Unknown crash type, no auto-fix available")
        return False

def run_server(cfg):
    """Start Minecraft server in tmux with crash detection and self-healing.
    
    Uses loader abstraction classes for:
    - build_java_command() — loader-specific JVM args
    - detect_crash_reason() — parse crash logs
    
    Self-healing loop:
    1. Start server
    2. Monitor tmux session
    3. If session dies, read crash log
    4. If crash is a missing dep, try to fetch it from Modrinth
    5. Restart (up to MAX_RESTART_ATTEMPTS)
    """
    MAX_RESTART_ATTEMPTS = 3
    RESTART_COOLDOWN = 30  # seconds between restart attempts
    
    loader_name = cfg.get("loader", "neoforge").lower()
    mc_version = cfg.get("mc_version", "1.21.11")
    
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
    
    restart_count = 0
    
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
        # Use stdbuf to disable buffering so pipe-pane gets output immediately
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
        
        # Monitor loop — wait for server to stop
        while True:
            check = run("tmux has-session -t MC 2>/dev/null")
            if check.returncode != 0:
                break
            time.sleep(5)
        
        log_event("SERVER_STOPPED", "Server process ended, analyzing crash...")
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
        log_event("CRASH_DETECT", f"Crash type: {crash_type}")
        if crash_info.get("message"):
            log_event("CRASH_DETECT", f"Details: {crash_info['message'][:200]}")
        
        # Attempt self-healing
        if restart_count < MAX_RESTART_ATTEMPTS:
            healed = _try_self_heal(loader_instance, crash_info, cfg)
            if healed:
                restart_count += 1
                log_event("SELF_HEAL", f"Fix applied, restarting in {RESTART_COOLDOWN}s...")
                time.sleep(RESTART_COOLDOWN)
                continue
            elif crash_type == "unknown":
                # Unknown crash — still restart, but don't try to fix
                restart_count += 1
                log_event("SELF_HEAL", f"Unknown crash, restarting in {RESTART_COOLDOWN}s (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})")
                time.sleep(RESTART_COOLDOWN)
                continue
            else:
                # Known crash type but can't auto-fix
                log_event("SELF_HEAL", "Cannot auto-fix this crash type. Server will not restart.")
                return False
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
    """Send command via RCON (if mcrcon available)"""
    try:
        import socket
        host = cfg.get("rcon_host", "localhost")
        port = int(cfg.get("rcon_port", 25575))
        password = cfg.get("rcon_pass", "changeme")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        
        # Send login
        login_payload = f"\x00\x00\x00\x00\x03\x00\x00\x00" + password.encode()
        sock.send(login_payload)
        
        # Send command
        cmd_payload = f"\x00\x00\x00\x00\x02{cmd}".encode()
        sock.send(cmd_payload)
        
        sock.close()
        log_event("RCON", f"Command sent: {cmd}")
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
    """Restart MC server after mods downloaded"""
    time.sleep(2)
    send_server_command("stop")
    log_event("SERVER_RESTART", "Server stopping for mod update...")
    time.sleep(15)

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
# CURSEFORGE MOD CURATOR SYSTEM (using Modrinth API for better public access)
# ============================================================================

def get_curseforge_key():
    """Read CurseForge API key from disk (optional - can fallback to Modrinth if not available)"""
    key_file = os.path.join(CWD, "curseforgeAPIkey")
    if os.path.exists(key_file):
        return open(key_file).read().strip()
    return None

def fetch_curseforge_mods(mc_version, loader, limit=100, categories=None):
    """
    Fetch top downloaded mods from CurseForge for given MC version + loader
    Uses official CurseForge REST API (https://docs.curseforge.com/rest-api)
    
    Args:
        mc_version: e.g. "1.21.11"
        loader: e.g. "neoforge" 
        limit: max # of mods to fetch (configurable, default 100, max 50 per request)
        categories: list of category ids to include (optional)
        
    Returns:
        List of mod objects from CurseForge API
    """
    api_key = get_curseforge_key()
    if not api_key:
        log_event("CURATOR", "No CurseForge API key found, skipping CurseForge")
        return []
    
    base_url = "https://api.curseforge.com/v1/mods/search"
    
    # CurseForge Game ID for Minecraft
    game_id = 432
    
    # Map loader names to CurseForge ModLoaderType IDs (from official docs)
    loader_map = {
        "forge": 1,
        "cauldron": 2,
        "liteloader": 3,
        "fabric": 4,
        "quilt": 5,
        "neoforge": 6,
    }
    
    loader_id = loader_map.get(loader.lower())
    if not loader_id:
        log_event("CURATOR", f"Unknown loader for CurseForge: {loader}")
        return []
    
    # CurseForge has a max page size of 50, so we'll need multiple requests if limit > 50
    all_mods = []
    page_size = min(limit, 50)
    pages_needed = (limit + page_size - 1) // page_size
    
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json"
    }
    
    for page in range(pages_needed):
        index = page * page_size
        
        params = {
            "gameId": game_id,
            "gameVersion": mc_version,
            "modLoaderType": loader_id,
            "sortField": 0,  # 0 = Featured, 1 = Popularity, 2 = LastUpdated, 3 = Name, 4 = Author, 5 = TotalDownloads, 6 = Category, 7 = GameVersion
            "sortOrder": "desc",
            "pageSize": page_size,
            "index": index
        }
        
        try:
            # Build query string
            query_parts = [f"{k}={v}" for k, v in params.items()]
            url = f"{base_url}?{'&'.join(query_parts)}"
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                mods = data.get("data", [])
                all_mods.extend(mods)
                
                # Check if we got fewer results than requested (end of list)
                if len(mods) < page_size:
                    break
        except Exception as e:
            log_event("CURATOR", f"Error fetching CurseForge mods (page {page}): {e}")
            if page == 0:  # First page failed
                return []
            else:
                break  # Continue with what we have
    
    return all_mods[:limit]

def get_mod_dependencies_curseforge(mod_id):
    """Fetch dependencies for a specific mod from CurseForge"""
    api_key = get_curseforge_key()
    if not api_key:
        return None
    
    base_url = f"https://api.curseforge.com/v1/mods/{mod_id}"
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json"
    }
    
    try:
        req = urllib.request.Request(base_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            return data.get("data", {})
    except Exception as e:
        log_event("CURATOR", f"Error fetching CurseForge mod {mod_id}: {e}")
        return None


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
    facets = f'[["game_versions:{mc_version}","mrpack_loaders:{loader_query}"'
    
    # Add category filters if specified
    if categories:
        for cat in categories:
            facets += f'","categories:{cat}'
    
    facets += ']]'
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
        
        # Last fallback: get latest versions and check
        url = f'{base_url}/project/{mod_id}/version?limit=10'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            versions = json.loads(response.read().decode())
            # Find a recent version that has mc_version
            for v in versions:
                if mc_version in v.get("game_versions", []):
                    return v.get("dependencies", [])
            # If none match, just return from first version
            if versions:
                return versions[0].get("dependencies", [])
    except Exception as e:
        pass
    
    return []

def is_library(mod_name, required_dep=False):
    """
    Check if mod is a library (not a user-facing mod)
    
    ONLY user-facing mods are shown. Dependencies are fetched on-demand.
    Fabric API/Loader are allowed if explicitly required.
    
    Args:
        mod_name: name of the mod
        required_dep: if True, don't filter (required deps override library status)
    
    Returns:
        True if should be filtered (is a library), False if user-facing
    """
    if not mod_name:
        return True  # Filter out mods with no name
    
    name_lower = mod_name.lower()
    
    # Always allow Fabric core loaders/APIs
    fabric_whitelist = ["fabric api", "fabric-api", "fabric loader", "fabric-loader"]
    for allowed in fabric_whitelist:
        if allowed in name_lower:
            return False  # Don't filter - this is allowed
    
    # Specific libraries to filter out (from our identified list)
    # These are known dependency-only mods
    lib_name_patterns = [
        "cloth config",
        "ferrite",
        "yacl", "yet another config",
        "architectury",
        "geckolib",
        "puzzles lib",
        "forge config api",
        "creative",  # CreativeCore
        "libipn",
        "resourceful",
        "supermartijn", # Config libs
        "fzzy config",
        "midnight",  # MidnightLib
        "kotlin for forge",
        "lib ",  # "lib " prefix
        " lib",  # " lib" suffix
    ]
    
    for pattern in lib_name_patterns:
        if pattern in name_lower:
            return True  # This is a library
    
    return False  # User-facing mod

def resolve_mod_dependencies_modrinth(mod_id, mc_version, loader, resolved=None, optional_deps=None, depth=0, max_depth=3):
    """
    Recursively resolve mod dependencies from Modrinth
    
    Tracks required vs optional separately. Only fetches required deps automatically.
    """
    if resolved is None:
        resolved = {"required": {}, "optional": {}}
    if optional_deps is None:
        optional_deps = {}
    
    if depth > max_depth or mod_id in resolved.get("required", {}):
        return resolved
    
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
    
    return resolved

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
            deps_result = resolve_mod_dependencies_modrinth(mod_id, mc_version, loader)
            curated[mod_id]["dependencies"]["required"] = list(deps_result["required"].keys())
            all_required_deps.update(deps_result["required"])
            all_optional_deps.update(deps_result.get("optional", {}))
    
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

def download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader):
    """Download mod JAR from Modrinth"""
    mod_name = mod_data.get("name")
    mod_id = mod_data.get("id")
    
    try:
        # Get latest file for this mod
        base_url = "https://api.modrinth.com/v2"
        loader_lower = loader.lower()
        
        # Try with both game version and loader filters
        url = f'{base_url}/project/{mod_id}/version?loaders=["{loader_lower}"]&game_versions=["{mc_version}"]&limit=5'
        req = urllib.request.Request(url)
        
        versions = []
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                versions = json.loads(response.read().decode())
        except:
            pass
        
        # Fallback: try just game version
        if not versions:
            url = f'{base_url}/project/{mod_id}/version?game_versions=["{mc_version}"]&limit=5'
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    versions = json.loads(response.read().decode())
            except:
                pass
        
        # Last fallback: get latest versions and pick first with matching MC
        if not versions:
            url = f'{base_url}/project/{mod_id}/version?limit=10'
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as response:
                all_versions = json.loads(response.read().decode())
                for v in all_versions:
                    if mc_version in v.get("game_versions", []):
                        versions = [v]
                        break
                if not versions and all_versions:
                    versions = [all_versions[0]]
        
        if not versions:
            log_event("CURATOR", f"No versions found for {mod_name}")
            return False
        
        files = versions[0].get("files", [])
        if not files:
            log_event("CURATOR", f"No files found for {mod_name}")
            return False
        
        # Get primary file (first)
        file_info = files[0]
        download_url = file_info.get("url")
        file_name = file_info.get("filename")
        
        if not download_url:
            log_event("CURATOR", f"No download URL for {mod_name}")
            return False
        
        file_path = os.path.join(mods_dir, file_name)
        log_event("CURATOR", f"Downloading {file_name}...")
        
        urllib.request.urlretrieve(download_url, file_path)
        log_event("CURATOR", f"Downloaded {file_name}")
        return True
    except Exception as e:
        log_event("CURATOR", f"Error downloading {mod_name}: {e}")
        return False

def generate_mod_lists_for_loaders(mc_version, limit=100, loaders=None):
    """
    Generate and cache mod lists for specified loaders (or just the active one).
    Returns dict keyed by loader name, each containing list of mods.
    """
    if loaders is None:
        loaders = ["neoforge"]
    mod_lists = {}
    
    for loader in loaders:
        print(f"\nGenerating {loader.upper()} mod list ({limit} mods)...")
        
        # Fetch more than limit to account for libs filtered out
        scan_limit = min(limit * 5, 500)
        all_mods = []
        
        # Fetch in batches
        for offset in range(0, scan_limit, 100):
            batch_limit = min(100, scan_limit - offset)
            mods = fetch_modrinth_mods(mc_version, loader, limit=batch_limit, offset=offset)
            if mods:
                all_mods.extend(mods)
            else:
                break
        
        # Filter to user-facing only
        user_facing = []
        for mod in all_mods:
            if len(user_facing) >= limit:
                break
            
            mod_id = mod.get("project_id")
            mod_name = mod.get("title")
            if not is_library(mod_name):
                user_facing.append({
                    "id": mod_id,
                    "name": mod_name,
                    "downloads": mod.get("downloads", 0)
                })
        
        mod_lists[loader] = user_facing
        print(f"  {len(user_facing)} {loader} mods ready")
    
    return mod_lists

def curator_command(cfg, limit=None, show_optional_audit=False):
    """
    Main curator command - smart dependency management
    
    Flow:
    1. Fetch top N mods (scans deeper to find N user-facing after filtering libs)
    2. Filter OUT all libs/APIs (except Fabric API/Loader)
    3. Show user-facing mods list for selection
    4. User picks which mods they want
    5. System auto-downloads selected mods + their required dependencies
    6. Dependencies fetched silently in background
    
    Args:
        cfg: configuration dict
        limit: max USER-FACING mods to fetch (default 100, None = use config)
        show_optional_audit: show optional deps audit report (disabled by default)
    """
    mc_version = cfg.get("mc_version", "1.21.11")
    loader = cfg.get("loader", "neoforge")
    if limit is None:
        limit = cfg.get("curator_limit", 100)
    
    print(f"\n{'='*70}")
    print(f"MOD CURATOR - {loader.upper()} {mc_version}")
    print(f"{'='*70}\n")
    
    # Fetch more than limit to account for libs we filter out
    # Scan up to 5x the limit to find enough user-facing mods
    scan_limit = min(limit * 5, 500)
    print(f"Scanning top {scan_limit} mods to find {limit} user-facing mods...")
    
    # Fetch in batches (API limit is 100 per request)
    all_mods = []
    for offset in range(0, scan_limit, 100):
        batch_limit = min(100, scan_limit - offset)
        mods = fetch_modrinth_mods(mc_version, loader, limit=batch_limit, offset=offset)
        if mods:
            all_mods.extend(mods)
        else:
            break
    
    if not all_mods:
        print("Error: Could not fetch mods from Modrinth")
        return
    
    # Filter to ONLY user-facing mods (NO libs/APIs)
    # Stop once we have enough
    user_facing_mods = {}
    for mod in all_mods:
        if len(user_facing_mods) >= limit:
            break
        
        mod_id = mod.get("project_id")
        mod_name = mod.get("title")
        if not is_library(mod_name):
            user_facing_mods[mod_id] = {
                "id": mod_id,
                "name": mod_name,
                "downloads": mod.get("downloads", 0),
                "description": mod.get("description", "No description")
            }
    
    print(f"\n✓ Found {len(user_facing_mods)} user-facing mods (scanned {len(all_mods)} total)\n")
    
    # Display the list informally
    print(f"{'='*70}")
    print("AVAILABLE MODS FOR SELECTION")
    print(f"{'='*70}\n")
    
    sorted_mods = sorted(user_facing_mods.items(), key=lambda x: x[1]['downloads'], reverse=True)
    for idx, (mod_id, mod_data) in enumerate(sorted_mods, 1):
        print(f"{idx:3}. {mod_data['name']:<50} ({mod_data['downloads']:>12,})")
    
    print(f"\n{len(user_facing_mods)} total mods available for selection")
    
    # Ask user if they want all or custom selection
    print(f"\n{'='*70}")
    print("SELECT MODS TO DOWNLOAD")
    print(f"{'='*70}\n")
    
    try:
        response = input("Download all mods? [y/n/custom]: ").strip().lower()
    except EOFError:
        # Running in systemd - skip and exit
        print("(Skipping interactive selection when running as service)")
        return
    
    selected_mods_list = []
    
    if response == "y":
        # Select all
        selected_mods_list = list(user_facing_mods.values())
        print(f"\n✓ Selected all {len(selected_mods_list)} mods")
    
    elif response == "custom":
        # Custom selection
        print("\nEnter mod numbers to select (comma-separated, e.g. 1,5,10 or 1-10):")
        try:
            selection_input = input("Mods to download: ").strip()
            selected_indices = []
            
            # Parse range and individual numbers
            for part in selection_input.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = map(int, part.split("-"))
                    selected_indices.extend(range(start-1, end))
                else:
                    selected_indices.append(int(part) - 1)
            
            for idx in sorted(set(selected_indices)):
                if 0 <= idx < len(sorted_mods):
                    selected_mods_list.append(sorted_mods[idx][1])
            
            print(f"\n✓ Selected {len(selected_mods_list)} mods")
        except ValueError:
            print("Invalid selection format")
            return
    else:
        print("Cancelled")
        return
    
    if not selected_mods_list:
        print("No mods selected")
        return
    
    # Now download selected mods + their dependencies
    print(f"\n{'='*70}")
    print("DOWNLOADING MODS & DEPENDENCIES")
    print(f"{'='*70}\n")
    
    mods_dir = cfg.get("mods_dir", "mods")
    os.makedirs(mods_dir, exist_ok=True)
    
    # Track what we download
    downloaded_mods = []
    all_deps_to_download = set()
    
    # Resolve dependencies for all selected mods
    print("Resolving dependencies...")
    for mod in selected_mods_list:
        deps = resolve_mod_dependencies_modrinth(mod['id'], mc_version, loader)
        all_deps_to_download.update(deps.get("required", {}).keys())
    
    print(f"  -> Found {len(all_deps_to_download)} required dependencies\n")
    
    # Download selected mods
    print("Downloading selected mods:")
    for mod in selected_mods_list:
        if download_mod_from_modrinth(mod, mods_dir, mc_version, loader):
            downloaded_mods.append(mod['name'])
            print(f"  ✓ {mod['name']}")
        else:
            print(f"  ✗ {mod['name']} (failed)")
    
    # Download dependencies silently in background
    print("\nDownloading dependencies (background):")
    deps_downloaded = 0
    for dep_mod_id in all_deps_to_download:
        # Fetch minimal info about the dependency
        try:
            dep_info = {"id": dep_mod_id, "name": dep_mod_id}
            if download_mod_from_modrinth(dep_info, mods_dir, mc_version, loader):
                deps_downloaded += 1
                print(f"  ✓ {dep_mod_id}")
        except:
            pass
    
    print(f"\n{'='*70}")
    print(f"DOWNLOAD COMPLETE")
    print(f"{'='*70}")
    print(f"  Mods: {len(downloaded_mods)} downloaded")
    print(f"  Dependencies: {deps_downloaded} downloaded")
    print(f"  Total: {len(downloaded_mods) + deps_downloaded} files\n")
    
    # Regenerate mod ZIP
    print("Updating mod distribution package...")
    sort_mods_by_type(mods_dir)
    create_mod_zip(mods_dir)
    print("✓ Ready for distribution on port 8000\n")

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
            
            if not is_initialized:
                create_install_scripts(cfg["mods_dir"], cfg)
                create_mod_zip(cfg["mods_dir"])
                
                # Write initialized marker
                with open(initialized_marker, "w") as f:
                    f.write(f"initialized at {datetime.now().isoformat()}")
                log_event("BOOT", "First-time initialization complete, marker written")
            else:
                # Still recreate mod zip on every boot (mods may have changed)
                create_mod_zip(cfg["mods_dir"])
            
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
