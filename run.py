#!/usr/bin/env python3
"""
Minecraft Modded Server - HTTP Mod Distribution via RCON
- Hosts mods on HTTP (with security checks)
- Auto-generates install scripts for Windows/Linux/Mac
- Daily world backups
- RCON messaging on player join
- Crash detection & auto-restart
"""

import os, json, subprocess, sys, time, threading, logging, hashlib, urllib.request, urllib.error
from http.server import SimpleHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

CONFIG = "config.json"
CWD = os.getcwd()

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
    """Download modloader server if not present"""
    import urllib.request
    
    if os.path.exists("server.jar") or os.path.exists("*.jar"):
        return True
    
    log_event("LOADER", f"Downloading {loader} server...")
    
    try:
        if loader == "fabric":
            # Fabric latest
            meta = json.loads(urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/loader").read())
            latest = meta[0]["version"]
            url = f"https://meta.fabricmc.net/v2/versions/loader/{latest}/server/jar"
            urllib.request.urlretrieve(url, "fabric-server.jar")
            log_event("LOADER", "Fabric server downloaded")
            
        elif loader == "forge":
            # Forge 1.21 latest
            try:
                data = json.loads(urllib.request.urlopen("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json").read())
                latest = data["promos"]["1.21-latest"]
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/1.21-{latest}/forge-1.21-{latest}-installer.jar"
                urllib.request.urlretrieve(url, "forge-installer.jar")
                subprocess.run("java -jar forge-installer.jar --installServer", shell=True)
                log_event("LOADER", "Forge server downloaded and installed")
            except:
                log_event("LOADER_ERROR", "Could not download Forge, try manual installation")
                return False
        else:
            log_event("LOADER_ERROR", "Download NeoForge from https://neoforged.net")
            return False
        
        return True
    except Exception as e:
        log_event("LOADER_ERROR", str(e))
        return False

def get_config():
    """Load config, prompt if needed"""
    if not os.path.exists(CONFIG):
        props = parse_props()
        
        cfg = {
            "server_jar": input("Server jar [server.jar]: ").strip() or "server.jar",
            "rcon_pass": input("RCON password [changeme]: ").strip() or "changeme",
            "rcon_port": input("RCON port [25575]: ").strip() or "25575",
            "rcon_host": "localhost",
            "http_port": input("HTTP mod port [8000]: ").strip() or "8000",
            "mods_dir": input("Mods folder [mods]: ").strip() or "mods",
            "clientonly_dir": "clientonly",
            "mc_version": input("Minecraft version [1.21.11]: ").strip() or "1.21.11",
            "loader": input("Modloader (fabric/forge/neoforge) [neoforge]: ").strip() or "neoforge",
            "max_download_mb": 600,
            "rate_limit_seconds": 2,
            "run_curator_on_startup": True,
            "curator_limit": 100,
            "curator_show_optional_audit": True,
            "curator_max_depth": 3
        }
        json.dump(cfg, open(CONFIG, "w"), indent=2)
        
        # API key setup for mod sources
        print("\n" + "="*70)
        print("MOD CURATOR SETUP")
        print("="*70)
        print("\nMod curator can fetch from Modrinth (no key needed) or CurseForge (requires key).")
        print("CurseForge API key available? Get one free from: https://console.curseforge.com/\n")
        
        api_key = input("CurseForge API key (optional, press Enter to skip): ").strip()
        if api_key:
            api_key_file = os.path.join(CWD, "curseforgeAPIkey")
            with open(api_key_file, "w") as f:
                f.write(api_key)
            log_event("SETUP", f"Saved CurseForge API key to {api_key_file}")
            print(f"✓ CurseForge API key saved - will use CurseForge for mod discovery")
        else:
            print("✓ Skipped - mod curator will use Modrinth's public API (no key needed)")
        
        # Enable RCON in server.properties
        props_path = os.path.join(CWD, "server.properties")
        if os.path.exists(props_path):
            txt = open(props_path).read()
            if "enable-rcon" not in txt:
                txt += "\nenable-rcon=true\n"
            else:
                txt = txt.replace("enable-rcon=false", "enable-rcon=true")
            open(props_path, "w").write(txt)
        
        print("\n" + "="*70)
        print("✓ CONFIGURATION SAVED")
        print("="*70 + "\n")
    
    # Load config and add missing defaults
    cfg = json.load(open(CONFIG))
    
    # Ensure curator settings exist (for backwards compatibility)
    if "curator_limit" not in cfg:
        cfg["curator_limit"] = 100
    if "curator_show_optional_audit" not in cfg:
        cfg["curator_show_optional_audit"] = True
    if "curator_max_depth" not in cfg:
        cfg["curator_max_depth"] = 3
    
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

def create_install_scripts(mods_dir):
    """Generate client install scripts"""
    os.makedirs(mods_dir, exist_ok=True)
    
    # PowerShell script for Windows
    ps = '''# Minecraft Mod Installer (Windows)
param([string]$ServerIP="localhost", [int]$Port=8000)
$modsPath = "$env:APPDATA\\.minecraft\\mods"
$oldmodsPath = "$env:APPDATA\\.minecraft\\oldmods"
$zipPath = "$env:TEMP\\mods_latest.zip"

Write-Host "Downloading mods..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $oldmodsPath -Force | Out-Null
if (Test-Path $modsPath) {
    Get-ChildItem -Path $modsPath -Filter "*.jar" -ErrorAction SilentlyContinue | ForEach-Object {
        Move-Item -Path $_.FullName -Destination $oldmodsPath -Force
    }
}
(New-Object System.Net.WebClient).DownloadFile("http://$ServerIP:$Port/mods_latest.zip", $zipPath)
Expand-Archive -Path $zipPath -DestinationPath $modsPath -Force
Remove-Item -Path $zipPath -Force
$count = (Get-ChildItem -Path $modsPath -Filter "*.jar" | Measure-Object).Count
Write-Host "✓ Installed $count mods" -ForegroundColor Green
'''
    
    # Bash script for Linux/Mac
    bash = '''#!/bin/bash
SERVER_IP="${1:-localhost}"
PORT="${2:-8000}"
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
echo "✓ Installed $(ls -1 "$MODS"/*.jar 2>/dev/null | wc -l) mods"
'''
    
    with open(os.path.join(mods_dir, "install-mods.ps1"), "w") as f:
        f.write(ps)
    
    bash_path = os.path.join(mods_dir, "install-mods.sh")
    with open(bash_path, "w") as f:
        f.write(bash)
    os.chmod(bash_path, 0o755)
    
    log_event("SCRIPTS", "Generated install-mods.ps1 and install-mods.sh")

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
    """Start HTTP server for mods"""
    os.chdir(mods_dir)
    server = HTTPServer(("0.0.0.0", int(port)), SecureHTTPHandler)
    log_event("HTTP_SERVER", f"Starting on port {port}")
    server.serve_forever()

def run_server(cfg):
    """Start Minecraft server in tmux"""
    log_event("SERVER_START", "Starting server")
    
    result = run(f"cd {CWD} && tmux new-session -d -s MC 'java -jar {cfg['server_jar']} nogui'")
    if result.returncode != 0:
        log_event("SERVER_ERROR", result.stderr)
        return False
    
    run(f"tmux pipe-pane -o -t MC 'cat >> {LOG_FILE}'")
    log_event("SERVER_RUNNING", "Server started in tmux session 'MC'")
    
    # Keep running until server stops (systemd will restart if needed)
    while True:
        result = run("tmux has-session -t MC 2>/dev/null")
        if result.returncode != 0:
            log_event("SERVER_STOPPED", "Server process ended")
            break
        time.sleep(5)
    
    return True

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
    """Trigger on player join event"""
    def __init__(self):
        super().__init__("PlayerJoin")
    
    def should_trigger(self, event_data):
        return "joined the game" in event_data.get("raw_line", "")
    
    def on_trigger(self, event_data, cfg):
        player = event_data.get("player", "Unknown")
        if self.debounce_check(player, seconds=30):
            msg = f"Welcome {player}! Mods: http://localhost:{cfg.get('http_port', 8000)}/mods_latest.zip"
            send_chat_message(msg)
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


def fetch_modrinth_mods(mc_version, loader, limit=100, categories=None):
    """
    Fetch top downloaded mods from Modrinth for given MC version + loader
    
    Args:
        mc_version: e.g. "1.21.11"
        loader: e.g. "neoforge"
        limit: max # of mods to fetch (configurable, default 100)
        categories: list of content categories to include (None = all except libraries)
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
    
    # Query: sort by downloads
    url = f"{base_url}/search?query=&facets={facets_encoded}&limit={limit}&offset=0&index=downloads"
    
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
    
    Args:
        mod_name: name of the mod
        required_dep: if True, don't filter (required deps override library status)
    
    Returns:
        True if should be filtered (is a library), False if user-facing
    """
    if required_dep:
        # Don't filter required dependencies
        return False
    
    lib_keywords = [
        "lib", "library", "api", "core", "base",
        "framework", "utils", "utility", "helper",
        "compat", "compatibility", "config", "registrar"
    ]
    name_lower = mod_name.lower()
    return any(lib in name_lower for lib in lib_keywords)

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

def curator_command(cfg, limit=None, show_optional_audit=True):
    """
    Main curator command - fetches and presents mods via RCON
    
    Args:
        cfg: configuration dict
        limit: max mods to fetch (default 100, None = use config)
        show_optional_audit: show optional deps audit report
    """
    mc_version = cfg.get("mc_version", "1.21.11")
    loader = cfg.get("loader", "neoforge")
    if limit is None:
        limit = cfg.get("curator_limit", 100)
    
    print(f"\nFetching top {limit} mods for {loader} {mc_version}...")
    
    # Try cache first
    curated, optional_deps = load_curator_cache(mc_version, loader)
    
    if not curated:
        mods = fetch_modrinth_mods(mc_version, loader, limit=limit)
        if not mods:
            print("Error: Could not fetch mods from Modrinth")
            return
        
        curated, optional_deps, req_deps_count = curate_mod_list(mods, mc_version, loader)
        save_curator_cache(curated, optional_deps, mc_version, loader)
        print(f"✓ Fetched {len(curated)} mods ({req_deps_count} auto-required deps)")
    
    # Show optional dependencies audit if requested
    if show_optional_audit and optional_deps:
        print_optional_deps_audit(optional_deps, curated)
    
    # Launch interactive menu
    try:
        send_rcon_command(cfg, "say Mod selection menu opened! Check console.")
    except:
        pass  # RCON may not be available
    
    selected_mods = rcon_interactive_mod_menu(cfg, curated)
    
    if selected_mods:
        print(f"\nDownloading {len(selected_mods)} selected mods...")
        mods_dir = cfg.get("mods_dir", "mods")
        
        downloaded_count = 0
        for mod in selected_mods:
            if download_mod_from_modrinth(mod, mods_dir, mc_version, loader):
                downloaded_count += 1
                try:
                    send_rcon_command(cfg, f"say Downloaded: {mod['name']}")
                except:
                    pass
        
        print(f"\n✓ Downloaded {downloaded_count}/{len(selected_mods)} mods")
        
        # Regenerate mod ZIP
        print("\nRegenerating mod ZIP...")
        sort_mods_by_type(mods_dir)
        create_mod_zip(mods_dir)
        
        try:
            send_rcon_command(cfg, "say Mods updated! Restart client to download latest.")
        except:
            pass
    
    print("\nCurator complete!")

def create_systemd_service(cfg):
    """Generate systemd service file for auto-start"""
    service_content = f"""[Unit]
Description=Minecraft Server
After=network.target

[Service]
Type=simple
User={os.getenv('USER')}
WorkingDirectory={CWD}
ExecStart=/usr/bin/python3 {os.path.basename(__file__)} run
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
            
            # Create systemd service file
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
                        print("\n✓ Curator complete! Starting server...\n")
                else:
                    # Running as systemd service - skip interactive prompt
                    log_event("BOOT", "Skipping interactive curator setup (running as service)")
                
                # Mark that we've run curator setup
                with open(first_run_marker, "w") as f:
                    f.write("first run complete")
                log_event("BOOT", "Marked curator first-run complete")
            
            # Check if server jar exists, download if needed
            if not os.path.exists(cfg["server_jar"]):
                print(f"\n[BOOT] Server jar not found: {cfg['server_jar']}")
                loader_choice = cfg.get("loader", "neoforge")
                print(f"[BOOT] Using loader: {loader_choice}")
                if not download_loader(loader_choice):
                    print("[ERROR] Could not obtain server jar")
                    sys.exit(1)
            
            # Setup mods
            print("[BOOT] Sorting mods by type (client/server/both)...")
            sort_mods_by_type(cfg["mods_dir"])
            
            create_install_scripts(cfg["mods_dir"])
            create_mod_zip(cfg["mods_dir"])
            
            # Start services
            threading.Thread(target=http_server, args=(cfg["http_port"], cfg["mods_dir"]), daemon=True).start()
            threading.Thread(target=backup_scheduler, args=(cfg,), daemon=True).start()
            threading.Thread(target=monitor_players, args=(cfg,), daemon=True).start()
            
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
