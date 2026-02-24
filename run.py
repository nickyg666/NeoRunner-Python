#!/usr/bin/env python3
"""
NeoRunner - Minecraft Modded Server Manager
Single-file entry point: download this file, run it, everything auto-installs.

- Hosts mods on HTTP (with security checks)
- Auto-generates install scripts for Windows/Linux/Mac
- Daily world backups
- RCON messaging on player join
- Crash detection & auto-restart
- Full-featured hosting dashboard for server management
"""

# ══════════════════════════════════════════════════════════════════════════════
# SELF-BOOTSTRAP — auto-install dependencies if missing
# ══════════════════════════════════════════════════════════════════════════════
import subprocess, sys, os

def _ensure_deps():
    """Auto-install required Python packages if they're missing."""
    required = {
        "flask": "flask",
        "requests": "requests",
        "playwright": "playwright",
        "playwright_stealth": "playwright-stealth",
        "apscheduler": "apscheduler",
        "tomli": "tomli",
    }
    missing = []
    for import_name, pip_name in required.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)
    
    if missing:
        print(f"[NeoRunner] Auto-installing missing dependencies: {', '.join(missing)}")
        # Try without --break-system-packages first (older pip), then with it (newer pip)
        pip_base = [sys.executable, "-m", "pip", "install", "--quiet"]
        tried = False
        for flags in [[], ["--break-system-packages"]]:
            pip_cmd = pip_base + flags + missing
            try:
                subprocess.check_call(pip_cmd)
                print(f"[NeoRunner] Installed: {', '.join(missing)}")
                tried = True
                break
            except subprocess.CalledProcessError:
                continue
        if not tried:
            print(f"[NeoRunner] WARNING: pip install failed. Try manually:")
            print(f"           pip install {' '.join(missing)}")
    
    # Ensure Playwright browsers are installed
    try:
        import playwright
        # Check if chromium is available by looking for the browser path
        from playwright._impl._driver import compute_driver_executable
        if not os.path.exists(os.path.join(os.path.dirname(compute_driver_executable()), 
                                            ".local-browsers")):
            raise FileNotFoundError
    except Exception:
        print("[NeoRunner] Installing Playwright Chromium browser...")
        try:
            subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"],
                                  timeout=300)
            print("[NeoRunner] Playwright Chromium installed.")
        except Exception as e:
            print(f"[NeoRunner] WARNING: Playwright browser install failed: {e}")
            print("           CurseForge scraping will be unavailable.")

_ensure_deps()
# ══════════════════════════════════════════════════════════════════════════════

import json, time, threading, logging, hashlib, urllib.request, urllib.error, socket
from http.server import SimpleHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, quote as url_quote
from ferium_manager import FeriumManager, setup_ferium_wizard

# Loader abstraction classes
from loaders.neoforge import NeoForgeLoader
from loaders.forge import ForgeLoader
from loaders.fabric import FabricLoader

try:
    import tomllib
except ImportError:
    import tomli as tomllib

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
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
]

CF_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 2560, "height": 1440},
    {"width": 1280, "height": 720},
]

CF_LOCALES = ["en-US", "en-GB", "en-CA", "en-AU"]

CF_TIMEZONES = ["America/New_York", "America/Los_Angeles", "America/Chicago", "Europe/London", "Europe/Berlin"]

_last_cf_request_time = 0

def _cf_rate_limit():
    """Random delay between CurseForge requests to appear human-like."""
    global _last_cf_request_time
    now = time.time()
    elapsed = now - _last_cf_request_time
    delay = random.uniform(1.5, 5.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_cf_request_time = time.time()

def _get_cf_headers():
    """Get randomized headers for CurseForge requests."""
    return {
        "User-Agent": random.choice(CF_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
import re
import random

def _get_cwd():
    """Determine the working directory dynamically."""
    env_cwd = os.environ.get("NEORUNNER_HOME")
    if env_cwd:
        return env_cwd
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()

CWD = _get_cwd()
CONFIG = os.path.join(CWD, "config.json")

# Setup logging to file and console
LOG_FILE = os.path.join(CWD, "live.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]  # Systemd captures stdout to live.log
)
log = logging.getLogger(__name__)

# In-memory event store for dashboard (survives until process restart)
_server_events = []
_SERVER_EVENT_TYPES = {
    "CRASH_DETECT", "SELF_HEAL", "QUARANTINE", "SERVER_RESTART",
    "SERVER_STOPPED", "SERVER_RUNNING", "SERVER_START", "SERVER_ERROR",
    "SERVER_TIMEOUT", "PREFLIGHT", "MOD_INSTALL"
}
_MAX_EVENTS = 200

def log_event(event_type, msg):
    """Log with event type tag. Captures crash/heal/quarantine events for dashboard."""
    log.info(f"[{event_type}] {msg}")
    if event_type in _SERVER_EVENT_TYPES:
        from datetime import datetime
        _server_events.append({
            "type": event_type,
            "message": msg,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        # Trim to max
        while len(_server_events) > _MAX_EVENTS:
            _server_events.pop(0)

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

def install_neoforge(mc_version):
    """Download and install NeoForge server for the given MC version."""
    log_event("LOADER_INSTALL", f"Installing NeoForge for MC {mc_version}...")
    
    neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
    if os.path.exists(neoforge_dir):
        log_event("LOADER_INSTALL", "NeoForge already installed")
        return True
    
    # NeoForge version schema: MC 1.21.11 -> NeoForge 21.11.xx-beta
    mc_parts = mc_version.split(".")
    if len(mc_parts) >= 3:
        major = mc_parts[1] if len(mc_parts) > 1 else "21"
        minor = mc_parts[2] if len(mc_parts) > 2 else "1"
        prefix = f"{major}.{minor}"
    else:
        prefix = "21.11"
    
    # Fetch latest version from Maven
    neo_version = None
    try:
        versions_url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        req = urllib.request.Request(versions_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            versions_data = json.loads(resp.read().decode())
            versions = versions_data.get("versions", [])
            matching = [v for v in versions if v.startswith(prefix)]
            if matching:
                neo_version = matching[-1]
    except Exception as e:
        log_event("LOADER_INSTALL", f"Version lookup failed: {e}")
    
    if not neo_version:
        log_event("LOADER_INSTALL_ERROR", f"No NeoForge version found for MC {mc_version}")
        return False
    
    installer_jar = f"neoforge-{neo_version}-installer.jar"
    installer_url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{neo_version}/{installer_jar}"
    installer_path = os.path.join(CWD, installer_jar)
    
    try:
        log_event("LOADER_INSTALL", f"Downloading NeoForge {neo_version}...")
        req = urllib.request.Request(installer_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
            if len(data) < 10000:
                log_event("LOADER_INSTALL_ERROR", "Download too small, likely 404")
                return False
            with open(installer_path, "wb") as f:
                f.write(data)
        
        log_event("LOADER_INSTALL", "Running installer (this takes a minute)...")
        result = subprocess.run(
            ["java", "-jar", installer_jar, "--installServer"],
            cwd=CWD, capture_output=True, text=True, timeout=600
        )
        
        os.remove(installer_path)
        
        if os.path.exists(neoforge_dir):
            log_event("LOADER_INSTALL", f"NeoForge {neo_version} installed")
            return True
        else:
            log_event("LOADER_INSTALL_ERROR", f"Install failed: {result.stderr[:500]}")
            return False
    except Exception as e:
        log_event("LOADER_INSTALL_ERROR", f"Failed: {e}")
        if os.path.exists(installer_path):
            os.remove(installer_path)
        return False

def install_fabric(mc_version):
    """Download and install Fabric server for the given MC version."""
    log_event("LOADER_INSTALL", f"Installing Fabric for MC {mc_version}...")
    
    fabric_jar = os.path.join(CWD, "fabric-server-launch.jar")
    if os.path.exists(fabric_jar):
        log_event("LOADER_INSTALL", "Fabric already installed")
        return True
    
    # Check if MC version is supported by Fabric
    try:
        versions_url = "https://meta.fabricmc.net/v2/versions/game"
        req = urllib.request.Request(versions_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            games = json.loads(resp.read().decode())
            stable_versions = [g["version"] for g in games if g.get("stable")]
            if mc_version not in stable_versions:
                log_event("LOADER_INSTALL_ERROR", f"MC {mc_version} not supported by Fabric")
                return False
    except Exception as e:
        log_event("LOADER_INSTALL", f"Could not verify MC version: {e}")
    
    # Get latest Fabric loader version
    loader_version = None
    try:
        loader_url = "https://meta.fabricmc.net/v2/versions/loader"
        req = urllib.request.Request(loader_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            loaders = json.loads(resp.read().decode())
            if loaders:
                loader_version = loaders[0]["version"]
    except Exception as e:
        log_event("LOADER_INSTALL", f"Could not get loader version: {e}")
    
    if not loader_version:
        loader_version = "0.18.4"  # Fallback
    
    # Download Fabric installer and run it
    installer_url = "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.0.1/fabric-installer-1.0.1.jar"
    installer_path = os.path.join(CWD, "fabric-installer.jar")
    
    try:
        log_event("LOADER_INSTALL", f"Downloading Fabric installer...")
        req = urllib.request.Request(installer_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(installer_path, "wb") as f:
                f.write(resp.read())
        
        log_event("LOADER_INSTALL", "Running Fabric installer...")
        result = subprocess.run(
            ["java", "-jar", "fabric-installer.jar", "server", "-mcversion", mc_version, 
             "-loader", loader_version, "-dir", "."],
            cwd=CWD, capture_output=True, text=True, timeout=300
        )
        
        os.remove(installer_path)
        
        if os.path.exists(fabric_jar):
            log_event("LOADER_INSTALL", f"Fabric {loader_version} installed for MC {mc_version}")
            return True
        else:
            log_event("LOADER_INSTALL_ERROR", f"Install failed: {result.stderr[:500]}")
            return False
    except Exception as e:
        log_event("LOADER_INSTALL_ERROR", f"Failed: {e}")
        if os.path.exists(installer_path):
            os.remove(installer_path)
        return False

def install_forge(mc_version):
    """Download and install Forge server for the given MC version."""
    log_event("LOADER_INSTALL", f"Installing Forge for MC {mc_version}...")
    
    forge_dir = os.path.join(CWD, "libraries", "net", "minecraftforge", "forge")
    if os.path.exists(forge_dir):
        log_event("LOADER_INSTALL", "Forge already installed")
        return True
    
    # Get Forge version for this MC version
    forge_version = None
    try:
        promo_url = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
        req = urllib.request.Request(promo_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            promos = json.loads(resp.read().decode()).get("promos", {})
            # Try recommended first, then latest
            key = f"{mc_version}-recommended"
            if key in promos:
                forge_version = promos[key]
            else:
                key = f"{mc_version}-latest"
                if key in promos:
                    forge_version = promos[key]
    except Exception as e:
        log_event("LOADER_INSTALL", f"Could not get Forge version: {e}")
    
    if not forge_version:
        log_event("LOADER_INSTALL_ERROR", f"No Forge version found for MC {mc_version}")
        log_event("LOADER_INSTALL_ERROR", "Forge may not support this MC version yet")
        return False
    
    installer_jar = f"forge-{mc_version}-{forge_version}-installer.jar"
    installer_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc_version}-{forge_version}/{installer_jar}"
    installer_path = os.path.join(CWD, installer_jar)
    
    try:
        log_event("LOADER_INSTALL", f"Downloading Forge {mc_version}-{forge_version}...")
        req = urllib.request.Request(installer_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
            if len(data) < 10000:
                log_event("LOADER_INSTALL_ERROR", "Download too small, likely 404")
                return False
            with open(installer_path, "wb") as f:
                f.write(data)
        
        log_event("LOADER_INSTALL", "Running installer (this takes a minute)...")
        result = subprocess.run(
            ["java", "-jar", installer_jar, "--installServer"],
            cwd=CWD, capture_output=True, text=True, timeout=600
        )
        
        os.remove(installer_path)
        
        if os.path.exists(forge_dir):
            log_event("LOADER_INSTALL", f"Forge {forge_version} installed")
            return True
        else:
            log_event("LOADER_INSTALL_ERROR", f"Install failed: {result.stderr[:500]}")
            return False
    except Exception as e:
        log_event("LOADER_INSTALL_ERROR", f"Failed: {e}")
        if os.path.exists(installer_path):
            os.remove(installer_path)
        return False

def ensure_loader_installed(loader, mc_version):
    """Ensure the specified loader is installed, downloading if necessary."""
    loader = loader.lower()
    
    if loader == "neoforge":
        neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
        if os.path.exists(neoforge_dir):
            return True
        return install_neoforge(mc_version)
    
    elif loader == "fabric":
        if os.path.exists(os.path.join(CWD, "fabric-server-launch.jar")):
            return True
        return install_fabric(mc_version)
    
    elif loader == "forge":
        if os.path.exists(os.path.join(CWD, "libraries", "net", "minecraftforge")):
            return True
        return install_forge(mc_version)
    
    else:
        log_event("LOADER_ERROR", f"Unknown loader: {loader}")
        return False

def download_loader(loader):
    """Verify modloader is available and return True if ready to use."""
    loader = loader.lower()
    
    if loader == "neoforge":
        neoforge_dir = os.path.join(CWD, "libraries", "net", "neoforged", "neoforge")
        if os.path.exists(neoforge_dir):
            log_event("LOADER", f"{loader} server environment ready (using @args files)")
            return True
        else:
            log_event("LOADER_ERROR", f"{loader} libraries not found at {neoforge_dir}")
            return False
    
    elif loader == "fabric":
        if os.path.exists(os.path.join(CWD, "fabric-server-launch.jar")):
            log_event("LOADER", f"{loader} server JAR found")
            return True
        else:
            log_event("LOADER_ERROR", f"{loader} server JAR not found")
            return False
    
    elif loader == "forge":
        if os.path.exists(os.path.join(CWD, "libraries", "net", "minecraftforge")):
            log_event("LOADER", f"{loader} libraries found")
            return True
        else:
            log_event("LOADER_ERROR", f"{loader} libraries not found")
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
        "mc_version": mc_version or props.get("mc-version", "1.21.1"),
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
            "mc_version": input("Minecraft version [1.21.1]: ").strip() or "1.21.1",
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
        "curator_sort": "downloads",
        "ferium_profile": f"{cfg.get('loader', 'neoforge')}-{cfg.get('mc_version', '1.21.11')}",
        "ferium_enable_scheduler": True,
        "ferium_update_interval_hours": 4,
        "ferium_weekly_update_day": "mon",
        "ferium_weekly_update_hour": 2,
        "curseforge_method": "modrinth_only",
        "http_port": "8000",
        "loader": "neoforge",
        "mc_version": "1.21.11",
        # Hostname / network
        "hostname": "",  # public-facing hostname/IP; empty = auto-detect from server.properties
        # Broadcast / tellraw
        "broadcast_enabled": True,  # master toggle for all tellraw broadcasts
        "broadcast_auto_on_install": True,  # auto-broadcast after /api/install-mods
        # Nag screens
        "nag_show_mod_list_on_join": True,  # show mod list tellraw when player joins
        "nag_first_visit_modal": True,  # auto-open mod selector on first dashboard visit
        # MOTD
        "motd_show_download_url": False,  # embed download URL in server MOTD
        # Install scripts
        "install_script_types": "all",  # which scripts to generate: "all", "bat", "ps1", "sh"
        # Java memory
        "xmx": "6G",  # max heap size
        "xms": "4G",  # initial heap size
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

def _parse_mod_manifest(jar_path):
    """Extract structured manifest data from a mod JAR.
    
    Reads neoforge.mods.toml, mods.toml, and/or fabric.mod.json and returns a dict:
    {
        "mod_id": str or None,
        "display_name": str or None,
        "loader": "neoforge" | "forge" | "fabric" | None,
        "loader_version_range": str or None,       # e.g. "[21.11.0-beta,)"
        "mc_version_range": str or None,            # e.g. "[1.21.11,1.22)"
        "side": "client" | "server" | "both" | None,  # from deps or environment
        "display_test": str or None,                # IGNORE_ALL_VERSION, NONE, etc.
        "environment": str or None,                 # fabric: "client", "server", "*"
        "has_neoforge_toml": bool,
        "has_fabric_json": bool,
    }
    """
    import zipfile
    
    result = {
        "mod_id": None, "display_name": None,
        "loader": None, "loader_version_range": None,
        "mc_version_range": None, "side": None,
        "display_test": None, "environment": None,
        "has_neoforge_toml": False, "has_fabric_json": False,
    }
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            names = zf.namelist()
            
            # ── NeoForge / Forge TOML manifest ──
            toml_file = None
            if 'META-INF/neoforge.mods.toml' in names:
                toml_file = 'META-INF/neoforge.mods.toml'
                result["has_neoforge_toml"] = True
            elif 'META-INF/mods.toml' in names:
                toml_file = 'META-INF/mods.toml'
            
            if toml_file:
                try:
                    raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                    # tomllib requires bytes
                    toml_data = tomllib.loads(raw)
                    
                    # Extract mod ID and display name from [[mods]] table
                    mods_list = toml_data.get("mods", [])
                    if mods_list and isinstance(mods_list, list):
                        first_mod = mods_list[0]
                        result["mod_id"] = first_mod.get("modId")
                        result["display_name"] = first_mod.get("displayName")
                        # displayTest: IGNORE_ALL_VERSION, NONE, etc.
                        result["display_test"] = first_mod.get("displayTest")
                    
                    # Determine loader from modLoader field
                    mod_loader = toml_data.get("modLoader", "")
                    result["loader_version_range"] = toml_data.get("loaderVersion")
                    
                    # Parse [[dependencies.<modid>]] for loader, MC version, and side
                    mod_id = result["mod_id"]
                    deps = {}
                    # Dependencies can be under "dependencies" as a dict of lists
                    all_deps = toml_data.get("dependencies", {})
                    if isinstance(all_deps, dict):
                        # dependencies.modid = [{...}, {...}]
                        for dep_mod_id, dep_list in all_deps.items():
                            if isinstance(dep_list, list):
                                deps[dep_mod_id] = dep_list
                    
                    # Find deps for our mod
                    mod_deps = deps.get(mod_id, []) if mod_id else []
                    
                    # Collect side info and version ranges from deps
                    sides_found = []
                    for dep in mod_deps:
                        if not isinstance(dep, dict):
                            continue
                        dep_id = dep.get("modId", "").lower()
                        side = dep.get("side", "BOTH").upper()
                        
                        if dep_id in ("neoforge", "forge"):
                            result["loader"] = dep_id
                            result["loader_version_range"] = dep.get("versionRange", result["loader_version_range"])
                            sides_found.append(side)
                        elif dep_id == "minecraft":
                            result["mc_version_range"] = dep.get("versionRange")
                            sides_found.append(side)
                        else:
                            sides_found.append(side)
                    
                    # If no loader detected from deps, infer from TOML file name
                    # ONLY set loader if we're certain. If a mod doesn't explicitly
                    # require neoforge/forge in deps, it might be cross-compatible.
                    if not result["loader"]:
                        if result["has_neoforge_toml"]:
                            result["loader"] = "neoforge"
                        # Don't default to "forge" for mods.toml - let it pass
                        # as loader=None (cross-compatible) unless deps say otherwise
                    
                    # Determine overall side: if ALL deps are CLIENT, mod is client-only
                    if sides_found:
                        if all(s == "CLIENT" for s in sides_found):
                            result["side"] = "client"
                        elif all(s == "SERVER" for s in sides_found):
                            result["side"] = "server"
                        else:
                            result["side"] = "both"
                    
                except Exception:
                    pass
            
            # ── Fabric mod.json ──
            if 'fabric.mod.json' in names:
                result["has_fabric_json"] = True
                try:
                    fabric_raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                    fabric_data = json.loads(fabric_raw)
                    
                    result["environment"] = fabric_data.get("environment", "*")
                    
                    if not result["mod_id"]:
                        result["mod_id"] = fabric_data.get("id")
                    if not result["display_name"]:
                        result["display_name"] = fabric_data.get("name")
                    
                    # Fabric environment: "client", "server", "*" (both)
                    if result["environment"] == "client" and not result["side"]:
                        result["side"] = "client"
                    
                    # Extract MC version from depends
                    fabric_deps = fabric_data.get("depends", {})
                    if isinstance(fabric_deps, dict):
                        mc_dep = fabric_deps.get("minecraft")
                        if mc_dep and not result["mc_version_range"]:
                            result["mc_version_range"] = mc_dep
                        
                        if not result["loader"]:
                            if "fabricloader" in fabric_deps:
                                result["loader"] = "fabric"
                            elif "quilt_loader" in fabric_deps:
                                result["loader"] = "quilt"
                    
                except Exception:
                    pass
    
    except Exception:
        pass
    
    return result


def classify_mod(jar_path):
    """
    Detect if a mod is client-only, server-only, or both.
    Uses proper manifest parsing of neoforge.mods.toml / fabric.mod.json.
    
    STRICT: Only classify as "client" if EXPLICITLY marked client-side.
    If in doubt, return "both" to keep mod in root mods/ folder.
    
    Returns: "client", "server", or "both"
    """
    manifest = _parse_mod_manifest(jar_path)
    
    # 1. Explicit side from manifest dependencies (most reliable)
    #    If ALL deps have side="CLIENT", the mod is client-only.
    if manifest["side"] == "client":
        return "client"
    if manifest["side"] == "server":
        return "server"
    
    # 2. Fabric environment: "client" (explicit)
    if manifest.get("environment") == "client":
        return "client"
    
    # 3. Default to "both" — if not EXPLICITLY marked client, keep in root mods/
    #    Do NOT use displayTest or other heuristics to guess client-only
    return "both"

def sort_mods_by_type(mods_dir):
    """
    Scan mods directory and move client-only mods to clientonly folder.
    Also deduplicates: if a JAR exists in both mods/ and clientonly/, remove the
    root copy (clientonly is the correct home for client mods).
    Returns count of mods moved.
    """
    import shutil
    
    clientonly_dir = os.path.join(mods_dir, "clientonly")
    os.makedirs(clientonly_dir, exist_ok=True)
    
    moved_count = 0
    dedup_count = 0
    
    # Phase 1: Deduplicate — if same filename exists in both root and clientonly, remove from root
    clientonly_files = set()
    if os.path.exists(clientonly_dir):
        clientonly_files = {f for f in os.listdir(clientonly_dir) if f.endswith('.jar')}
    
    for filename in list(os.listdir(mods_dir)):
        if not filename.endswith('.jar'):
            continue
        jar_path = os.path.join(mods_dir, filename)
        if not os.path.isfile(jar_path):
            continue
        if filename in clientonly_files:
            try:
                os.remove(jar_path)
                log_event("MOD_SORT", f"Dedup: removed {filename} from root (already in clientonly/)")
                dedup_count += 1
            except Exception as e:
                log_event("MOD_SORT_ERROR", f"Failed to dedup {filename}: {e}")
    
    # Phase 2: Classify remaining root mods and move client-only ones
    for filename in list(os.listdir(mods_dir)):
        if not filename.endswith('.jar'):
            continue
        
        jar_path = os.path.join(mods_dir, filename)
        if not os.path.isfile(jar_path):
            continue
        
        mod_type = classify_mod(jar_path)
        
        if mod_type == "client":
            dest = os.path.join(clientonly_dir, filename)
            try:
                if not os.path.exists(dest):
                    shutil.move(jar_path, dest)
                    log_event("MOD_SORT", f"Moved {filename} to clientonly/ (manifest says client-only)")
                    moved_count += 1
                else:
                    # Already in clientonly, remove the root copy
                    os.remove(jar_path)
                    log_event("MOD_SORT", f"Dedup: removed {filename} from root (already in clientonly/)")
                    dedup_count += 1
            except Exception as e:
                log_event("MOD_SORT_ERROR", f"Failed to move {filename}: {e}")
    
    if moved_count > 0 or dedup_count > 0:
        log_event("MOD_SORT", f"Sorted {moved_count} client-only mods, deduplicated {dedup_count}")
    
    return moved_count


def _parse_version_range(version_range):
    """Parse a Maven-style version range like '[1.21.11,1.22)' or '[21.0.0-beta,)'.
    
    Returns (lower, upper, lower_inclusive, upper_inclusive) or None if unparseable.
    Lower/upper are version strings (or None for open-ended).
    """
    if not version_range or not isinstance(version_range, str):
        return None
    
    vr = version_range.strip()
    if not vr:
        return None
    
    # Handle wildcard
    if vr == "*":
        return (None, None, True, True)
    
    # Handle simple version (no brackets) like ">=1.21.11"
    if vr[0] not in ('[', '('):
        # Treat as exact or minimum version
        return (vr, None, True, True)
    
    lower_inc = vr[0] == '['
    upper_inc = vr[-1] == ']' if vr[-1] in (']', ')') else True
    
    inner = vr[1:-1] if len(vr) > 2 else ""
    
    if ',' in inner:
        parts = inner.split(',', 1)
        lower = parts[0].strip() or None
        upper = parts[1].strip() or None
    else:
        # Single value like "[1.21.11]" means exact match
        lower = inner.strip() or None
        upper = inner.strip() or None
        lower_inc = True
        upper_inc = True
    
    return (lower, upper, lower_inc, upper_inc)


def _version_tuple(version_str):
    """Convert version string to comparable tuple.
    Handles: '1.21.11', '21.11.0-beta', '21.0.110-beta', etc.
    Beta/alpha suffixes sort lower than release.
    """
    if not version_str:
        return (0,)
    
    # Strip common suffixes for comparison
    clean = version_str.strip().lower()
    is_prerelease = False
    for suffix in ('-beta', '-alpha', '-rc', '-snapshot', '+beta', '.beta'):
        if suffix in clean:
            clean = clean.split(suffix)[0]
            is_prerelease = True
    
    parts = []
    for p in clean.split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            # Non-numeric part, try to extract leading digits
            import re
            m = re.match(r'(\d+)', p)
            if m:
                parts.append(int(m.group(1)))
            else:
                parts.append(0)
    
    # Append prerelease indicator (0 = prerelease, 1 = release)
    parts.append(0 if is_prerelease else 1)
    
    return tuple(parts)


def _version_in_range(version, version_range):
    """Check if a version string falls within a version range.
    
    Supports NeoForge/Maven-style ranges:
    - "[1.0,)" means 1.0 or higher
    - "[1.0,2.0)" means 1.0 inclusive to 2.0 exclusive
    - "[1.0]" means exactly 1.0
    """
    import re
    
    def parse_ver(v):
        """Parse version string into tuple of integers"""
        v = v.strip()  # Strip whitespace
        parts = re.findall(r'\d+', v)
        return tuple(int(p) for p in parts) if parts else (0,)
    
    # Clean up version string
    version = version.strip().strip('"\'')
    
    # Handle simple version requirements
    if not version_range or version_range == "*" or version_range == "":
        return True
    
    # Parse range notation - strip spaces from captured groups
    range_match = re.match(r'^([\[\(])\s*([^,]*?)\s*,\s*([^,\]\)]*?)\s*([\]\)])$', version_range)
    if not range_match:
        # Single version requirement
        return parse_ver(version) >= parse_ver(version_range.strip("[]() "))
    
    left_bracket, left_ver, right_ver, right_bracket = range_match.groups()
    
    v = parse_ver(version)
    left = parse_ver(left_ver) if left_ver else None
    right = parse_ver(right_ver) if right_ver else None
    
    # Check left bound
    if left:
        if left_bracket == '[':
            if v < left:
                return False
        else:  # '('
            if v <= left:
                return False
    
    # Check right bound
    if right:
        if right_bracket == ']':
            if v > right:
                return False
        else:  # ')'
            if v >= right:
                return False
    
    return True


def _get_java_version():
    """Get current Java major version"""
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=5)
        # Parse version from output like "openjdk version "21.0.10"
        for line in (result.stderr + result.stdout).split('\n'):
            if 'version' in line:
                match = re.search(r'"(\d+)', line)
                if match:
                    return match.group(1)
                # Handle old format "1.8.0"
                match = re.search(r'"1\.(\d+)', line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "21"


def _check_jdk_upgrade_available():
    """Check if a newer JDK is available in system repos"""
    available = []
    
    try:
        # Check apt for available JDK versions
        result = subprocess.run(
            ["apt-cache", "search", "openjdk-.*-jdk", "temurin-.*-jdk"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split('\n'):
            if 'jdk' in line.lower() and ('openjdk' in line.lower() or 'temurin' in line.lower()):
                # Extract version number
                match = re.search(r'(\d+)-jdk', line)
                if match:
                    version = int(match.group(1))
                    if version >= 21:  # Only care about Java 21+
                        available.append({
                            "version": str(version),
                            "package": line.split()[0] if line.split() else "",
                            "description": line
                        })
    except Exception:
        pass
    
    # Also check for Eclipse Temurin (Adoptium)
    try:
        result = subprocess.run(
            ["apt-cache", "search", "temurin"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split('\n'):
            match = re.search(r'temurin-(\d+)-jdk', line)
            if match:
                version = int(match.group(1))
                if version >= 21:
                    pkg = f"temurin-{version}-jdk"
                    if not any(a.get("package") == pkg for a in available):
                        available.append({
                            "version": str(version),
                            "package": pkg,
                            "description": f"Eclipse Temurin JDK {version}"
                        })
    except Exception:
        pass
    
    # Sort by version descending
    available.sort(key=lambda x: int(x["version"]), reverse=True)
    return available[:5]  # Top 5


def _install_jdk(package_name):
    """Install a JDK package"""
    try:
        result = subprocess.run(
            ["sudo", "apt-get", "install", "-y", package_name],
            capture_output=True, text=True, timeout=120
        )
        return result.returncode == 0
    except Exception as e:
        log_event("JDK_UPGRADE", f"Failed to install {package_name}: {e}")
        return False


def _set_default_java(version):
    """Set default Java version using update-alternatives"""
    try:
        # Find all java alternatives and pick the right one
        result = subprocess.run(
            ["update-alternatives", "--list", "java"],
            capture_output=True, text=True, timeout=10
        )
        for path in result.stdout.split('\n'):
            if f"java-{version}-" in path or f"temurin-{version}" in path:
                subprocess.run(
                    ["sudo", "update-alternatives", "--set", "java", path],
                    capture_output=True, timeout=10
                )
                return True
    except Exception:
        pass
    return False


def preflight_mod_compatibility_check(mods_dir, cfg):
    """Validate all mods in mods_dir against the configured loader and MC version.
    
    Checks:
    1. Loader compatibility: mod declares a loader dep (neoforge/forge/fabric) that
       doesn't match config.json loader. If no loader dep, skip (it's fine).
    2. MC version compatibility: mod's minecraft version range doesn't include our version.
       If no MC version range, skip.
    3. Client-only mods still in root: flag but don't block (sort_mods_by_type handles moves).
    
    Returns dict with:
        "compatible": list of (filename, mod_id) tuples
        "incompatible": list of (filename, mod_id, reason) tuples  
        "quarantined": list of filenames moved to quarantine
        "warnings": list of warning strings
    """
    server_loader = cfg.get("loader", "neoforge").lower()
    server_mc_version = cfg.get("mc_version", "1.21.11")
    quarantine_dir = os.path.join(mods_dir, "quarantine")
    os.makedirs(quarantine_dir, exist_ok=True)
    
    # Loader family mapping: neoforge and forge are NOT compatible with each other
    # despite sharing the javafml modLoader. They use different APIs.
    LOADER_COMPAT = {
        "neoforge": {"neoforge"},
        "forge": {"forge"},
        "fabric": {"fabric", "quilt"},
    }
    
    compatible_loaders = LOADER_COMPAT.get(server_loader, {server_loader})
    
    results = {
        "compatible": [],
        "incompatible": [],
        "quarantined": [],
        "warnings": [],
    }
    
    for filename in sorted(os.listdir(mods_dir)):
        if not filename.endswith('.jar'):
            continue
        jar_path = os.path.join(mods_dir, filename)
        if not os.path.isfile(jar_path):
            continue
        
        manifest = _parse_mod_manifest(jar_path)
        mod_id = manifest.get("mod_id") or filename
        display = manifest.get("display_name") or mod_id
        
        # ── Check 1: Loader compatibility ──
        mod_loader = manifest.get("loader")
        if mod_loader and mod_loader.lower() not in compatible_loaders:
            reason = f"Wrong loader: mod requires {mod_loader}, server runs {server_loader}"
            results["incompatible"].append((filename, mod_id, reason))
            
            # Quarantine wrong-loader mods
            dest = os.path.join(quarantine_dir, filename)
            reason_file = os.path.join(quarantine_dir, f"{filename}.reason.txt")
            try:
                import shutil
                shutil.move(jar_path, dest)
                with open(reason_file, "w") as f:
                    from datetime import datetime
                    f.write(f"Quarantined: {datetime.now().isoformat()}\n")
                    f.write(f"Reason: {reason}\n")
                    f.write(f"Mod ID: {mod_id}\n")
                    f.write(f"Display Name: {display}\n")
                results["quarantined"].append(filename)
                log_event("COMPAT_CHECK", f"QUARANTINED {filename}: {reason}")
            except Exception as e:
                log_event("COMPAT_CHECK", f"Failed to quarantine {filename}: {e}")
            continue
        
        # ── Check 2: MC version compatibility ──
        mc_range = manifest.get("mc_version_range")
        if mc_range:
            version_ok = _version_in_range(server_mc_version, mc_range)
            if version_ok is False:
                reason = f"MC version mismatch: mod requires {mc_range}, server runs {server_mc_version}"
                results["incompatible"].append((filename, mod_id, reason))
                
                # Quarantine version-mismatched mods
                dest = os.path.join(quarantine_dir, filename)
                reason_file = os.path.join(quarantine_dir, f"{filename}.reason.txt")
                try:
                    import shutil
                    shutil.move(jar_path, dest)
                    with open(reason_file, "w") as f:
                        from datetime import datetime
                        f.write(f"Quarantined: {datetime.now().isoformat()}\n")
                        f.write(f"Reason: {reason}\n")
                        f.write(f"Mod ID: {mod_id}\n")
                        f.write(f"Display Name: {display}\n")
                    results["quarantined"].append(filename)
                    log_event("COMPAT_CHECK", f"QUARANTINED {filename}: {reason}")
                except Exception as e:
                    log_event("COMPAT_CHECK", f"Failed to quarantine {filename}: {e}")
                continue
        
        # Mod passed all checks
        results["compatible"].append((filename, mod_id))
    
    # Summary log
    total = len(results["compatible"]) + len(results["incompatible"])
    if results["incompatible"]:
        log_event("COMPAT_CHECK", 
                  f"Compatibility check: {len(results['compatible'])}/{total} mods OK, "
                  f"{len(results['incompatible'])} incompatible ({len(results['quarantined'])} quarantined)")
        for fn, mid, reason in results["incompatible"]:
            log_event("COMPAT_CHECK", f"  FAIL: {fn} — {reason}")
    else:
        log_event("COMPAT_CHECK", f"All {total} mods compatible with {server_loader} {server_mc_version}")
    
    return results

# ══════════════════════════════════════════════════════════════════════════════
# INSTALLED MOD DETECTION — Smart matching with token extraction + fuzzy match
# ══════════════════════════════════════════════════════════════════════════════

# Known abbreviations/aliases used by mod authors in JAR filenames
# Maps alias -> canonical form (both directions are checked)
MOD_ALIASES = {
    "mcw": "macaws",
    "macaws": "mcw",
    "etf": "entitytexturefeatures",
    "emf": "entitymodelfeatures",
    "yacl": "yetanotherconfiglib",
    "ctov": "choicetheorems",
    "jei": "justenoughitems",
    "jeb": "justenoughbreeding",
    "rei": "roughlyenoughitems",
}

def _extract_mod_token(filename):
    """Extract a clean mod-name token from a JAR filename by stripping version/loader/mc noise.
    
    e.g. 'mcw-bridges-3.1.2-mc1.21.11neoforge.jar' -> 'mcwbridges'
         'entity_texture_features_1.21.11-neoforge-7.0.8.jar' -> 'entitytexturefeatures'
    """
    base = filename.lower().replace('.jar', '')
    # Strip loader names
    base = re.sub(r'neoforge|forge|fabric|quilt', '', base)
    # Strip MC version patterns: 1.21.11, mc1.21.11, 1.21.x, mc1.21
    base = re.sub(r'mc?[\._\-]?1[\._]\d+[\._x]?\d*', '', base)
    # Strip version numbers like 3.1.2, v2.14.10, +1.21.11, -beta1
    base = re.sub(r'[+\-_.]?v?\d+[\._]\d+[\._]?\d*[\._]?\d*', '', base)
    # Strip leftover single digits and noise
    base = re.sub(r'[^a-z]', '', base)
    return base.strip()

def build_installed_index(mods_dir):
    """Scan mods/ and mods/clientonly/ and build a set of normalized mod tokens.
    
    Returns (installed_tokens, installed_jars) where:
    - installed_tokens: set of cleaned mod name strings for fuzzy matching
    - installed_jars: set of raw lowercased filenames for exact matching
    """
    from difflib import SequenceMatcher
    installed_tokens = set()
    installed_jars = set()
    
    scan_dirs = [mods_dir]
    clientonly = os.path.join(mods_dir, "clientonly")
    if os.path.isdir(clientonly):
        scan_dirs.append(clientonly)
    
    for d in scan_dirs:
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith('.jar') and os.path.isfile(os.path.join(d, fn)):
                installed_jars.add(fn.lower())
                token = _extract_mod_token(fn)
                if token:
                    installed_tokens.add(token)
    
    return installed_tokens, installed_jars

def check_installed(name, slug, installed_tokens, threshold=0.82, exact=False):
    """Check if a mod (by name and/or slug) matches any installed JAR token.
    
    Uses three strategies in order:
    1. Exact substring match (either direction) against tokens - but NOT short common words
    2. Alias expansion (e.g. 'macaws-bridges' -> also check 'mcw' + 'bridges')  
    3. Fuzzy SequenceMatcher above threshold
    
    If exact=True, only allow EXACT token matches (for dependency resolution).
    
    Returns True if the mod appears to be installed.
    """
    from difflib import SequenceMatcher
    
    # Common words that should NOT trigger substring matches
    COMMON_WORDS = {"biomes", "world", "armor", "tools", "food", "storage", "inventory", 
                    "chest", "block", "item", "entity", "mob", "particle", "render", 
                    "client", "server", "config", "api", "lib", "core", "util", "helper",
                    "better", "simple", "advanced", "extra", "more", "ultimate", "ultimate"}
    
    checks = []
    for raw in [name, slug]:
        if raw:
            norm = re.sub(r'[^a-z0-9]', '', raw.lower())
            if norm and norm not in COMMON_WORDS:
                checks.append(norm)
    
    if not checks:
        return False
    
    for norm in checks:
        # For exact mode (dependency resolution), require EXACT token match
        if exact:
            for token in installed_tokens:
                if norm == token:
                    return True
            continue
        
        # Strategy 1: substring match (bidirectional) - but skip if norm is a common word
        for token in installed_tokens:
            # Require EXACT match or a true prefix/suffix (not just substring in middle)
            # This prevents "biomesoplenty" matching "mcwbiomesoplenty"
            if norm == token:
                return True
            # Allow prefix/suffix matches only if significantly different (addon pattern)
            if len(norm) >= 5 and (token.startswith(norm) or token.endswith(norm)) and len(token) - len(norm) < 4:
                return True
        
        # Strategy 2: alias expansion
        for alias, canonical in MOD_ALIASES.items():
            if norm.startswith(alias):
                expanded = canonical + norm[len(alias):]
                for token in installed_tokens:
                    if len(expanded) >= 5 and (expanded in token or token in expanded):
                        return True
            if norm.startswith(canonical):
                expanded = alias + norm[len(canonical):]
                for token in installed_tokens:
                    if len(expanded) >= 5 and (expanded in token or token in expanded):
                        return True
    
    # In exact mode, we've already checked all tokens - no match found
    if exact:
        return False
    
    # Strategy 3: fuzzy match with SequenceMatcher (higher threshold for short names)
    for norm in checks:
        for token in installed_tokens:
            required_ratio = 0.90 if len(norm) < 8 else threshold
            if SequenceMatcher(None, norm, token).ratio() >= required_ratio:
                return True
    
    return False

def get_server_hostname(cfg):
    """Resolve the public-facing hostname/IP for the server.
    
    Priority: cfg['hostname'] > cloud metadata > local IP > server.properties > hostname
    """
    # 1. Explicit config override
    hostname = cfg.get("hostname", "")
    if hostname:
        return hostname
    
    # 2. Try cloud metadata services for public IP
    metadata_endpoints = [
        ("EC2", "http://169.254.169.254/latest/meta-data/public-ipv4", {}),
        ("GCP", "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip", {"Metadata-Flavor": "Google"}),
        ("Azure", "http://169.254.254.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text", {"Metadata": "true"}),
    ]
    
    for cloud_name, url, headers in metadata_endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/1.0", **headers})
            with urllib.request.urlopen(req, timeout=2) as resp:
                ip = resp.read().decode().strip()
                if ip and ip != "" and not ip.startswith("127."):
                    log_event("NETWORK", f"Detected {cloud_name} public IP: {ip}")
                    return ip
        except Exception:
            pass
    
    # 3. Try hostname -I to get local IPs (pick first non-localhost)
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ips = result.stdout.strip().split()
            for ip in ips:
                if not ip.startswith("127.") and not ip.startswith("::") and "." in ip:
                    return ip.split("/")[0]
    except Exception:
        pass
    
    # 4. Try ip addr show as fallback
    try:
        result = subprocess.run(["ip", "addr", "show"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            import re as _re
            matches = _re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", result.stdout)
            for ip in matches:
                if not ip.startswith("127."):
                    return ip
    except Exception:
        pass
    
    # 5. Try server.properties
    props = parse_props()
    server_ip = props.get("server-ip", "")
    if server_ip and server_ip != "0.0.0.0" and not server_ip.startswith("127."):
        return server_ip
    
    # 6. Try system hostname
    try:
        return socket.gethostname()
    except Exception:
        pass
    
    # 7. Last resort
    return "YOUR_SERVER_IP"

def create_install_scripts(mods_dir, cfg=None):
    """Generate client install scripts (.ps1, .sh).
    
    PowerShell uses only built-ins available in Windows 10 21H2 (PowerShell 5.1).
    Scripts are generated on-demand via Flask routes, not stored on disk.
    """
    os.makedirs(mods_dir, exist_ok=True)
    http_port = int(cfg.get("http_port", 8000)) if cfg else 8000
    server_ip = get_server_hostname(cfg) if cfg else "localhost"
    
    # Store config for dynamic script generation
    script_config = {
        "server_ip": server_ip,
        "http_port": http_port,
    }
    script_config_path = os.path.join(mods_dir, ".script_config.json")
    with open(script_config_path, "w") as f:
        json.dump(script_config, f)
    
    log_event("SCRIPTS", f"Script config saved (ip={server_ip}, port={http_port}) - scripts generated on-demand")

def create_mod_zip(mods_dir):
    """Create mods_latest.zip with all mods (root + clientonly) in flat structure.
    Also creates mods_manifest.json with filenames and sizes for client-side diff sync."""
    import shutil
    import zipfile
    import hashlib
    
    clientonly_dir = os.path.join(mods_dir, "clientonly")
    zip_path = os.path.join(mods_dir, "mods_latest.zip")
    manifest_path = os.path.join(mods_dir, "mods_manifest.json")
    
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
        
        # Create manifest JSON with sizes for diff sync
        mods_list = []
        total_size = 0
        for filename, file_path in sorted(mods_to_zip.items()):
            size = os.path.getsize(file_path)
            total_size += size
            mods_list.append({
                "name": filename,
                "size": size
            })
        
        manifest = {
            "version": "2.0",
            "created": datetime.now().isoformat(),
            "mod_count": len(mods_to_zip),
            "total_size": total_size,
            "mods": mods_list
        }
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        mod_count = len(mods_to_zip)
        log_event("MOD_ZIP", f"Created mods_latest.zip ({mod_count} mods, {size_mb:.2f} MB) + manifest v2")
        
    except Exception as e:
        log_event("MOD_ZIP_ERROR", f"Failed to create ZIP: {e}")

class SecureHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler with security checks and individual mod downloads"""
    last_request_time = 0
    
    def do_GET(self):
        cfg = json.load(open(CONFIG))
        
        # Rate limiting
        current_time = time.time()
        if current_time - SecureHTTPHandler.last_request_time < cfg["rate_limit_seconds"]:
            self.send_error(429)
            return
        SecureHTTPHandler.last_request_time = current_time
        
        # Handle /download/mods/{filename} for individual mod downloads
        if self.path.startswith("/download/mods/"):
            filename = self.path[len("/download/mods/"):].split("?")[0]
            if not filename or filename.startswith(".") or not filename.endswith(".jar"):
                self.send_error(403)
                return
            
            mods_dir = Path(cfg["mods_dir"])
            clientonly_dir = mods_dir / "clientonly"
            
            # Check root first, then clientonly
            file_path = mods_dir / filename
            if not file_path.exists():
                file_path = clientonly_dir / filename
            
            if not file_path.exists():
                self.send_error(404, f"Mod not found: {filename}")
                return
            
            # File size limit
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb > cfg.get("max_download_mb", 600):
                self.send_error(413)
                return
            
            # Serve the file
            self.send_response(200)
            self.send_header("Content-Type", "application/java-archive")
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
            log_event("HTTP_DOWNLOAD", f"Served individual mod: {filename}")
            return
        
        # Handle /download/manifest for manifest.json
        if self.path.startswith("/download/manifest") or self.path == "/download/mods_manifest.json":
            manifest_path = Path(cfg["mods_dir"]) / "mods_manifest.json"
            if not manifest_path.exists():
                self.send_error(404, "Manifest not found")
                return
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(manifest_path.stat().st_size))
            self.end_headers()
            with open(manifest_path, "rb") as f:
                self.wfile.write(f.read())
            return
        
        # File validation for other requests
        file_name = Path(self.path.lstrip("/")).name
        if not file_name or file_name.startswith("."):
            self.send_error(403)
            return
        
        # Extension whitelist
        allowed = [".jar", ".zip", ".ps1", ".sh", ".json"]
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
                
                from flask import Flask, render_template, jsonify, request, send_file, Response
                
                app = Flask(__name__, template_folder=CWD, static_folder=os.path.join(CWD, "static"))
                app.secret_key = os.urandom(24)
                
                def load_cfg():
                    if os.path.exists(CONFIG):
                        with open(CONFIG) as f:
                            c = json.load(f)
                    else:
                        c = {}
                    # Apply runtime defaults for any missing keys
                    runtime_defaults = {
                        "hostname": "",
                        "broadcast_enabled": True,
                        "broadcast_auto_on_install": True,
                        "nag_show_mod_list_on_join": True,
                        "nag_first_visit_modal": True,
                        "motd_show_download_url": False,
                        "install_script_types": "all",
                        "curator_sort": "downloads",
                        "curator_limit": 100,
                    }
                    for k, v in runtime_defaults.items():
                        if k not in c:
                            c[k] = v
                    return c
                
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
                    uid = os.getuid()
                    tmux_socket = f"/tmp/tmux-{uid}/default"
                    running = run_cmd(f"tmux -S {tmux_socket} list-sessions 2>/dev/null | grep -c MC").get("stdout", "").strip() == "1"
                    if not running:
                        java_check = run_cmd("ps aux | grep -v grep | grep -v pgrep | grep -c 'java.*nogui' || true")
                        running = java_check.get("stdout", "").strip() != "0"
                    c = load_cfg()
                    loader = c.get("loader", "unknown")
                    mc_ver = c.get("mc_version", "unknown")
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    mod_count = len([f for f in os.listdir(mods_dir_path) if f.endswith(".jar")]) if os.path.exists(mods_dir_path) else 0
                    
                    props = parse_props()
                    
                    return {
                        "running": running,
                        "loader": loader,
                        "mc_version": mc_ver,
                        "mod_count": mod_count,
                        "player_count": 0,
                        "rcon_enabled": c.get("rcon_pass") is not None,
                        "uptime": "N/A",
                        "server_port": props.get("server-port", c.get("server_port", "25565")),
                        "query_port": props.get("query.port", "25565"),
                        "rcon_port": props.get("rcon.port", "25575"),
                    }
                
                def get_mod_list():
                    """Return sorted list of all mods (server + clientonly)."""
                    c = load_cfg()
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    clientonly_path = os.path.join(mods_dir_path, "clientonly")
                    mods = []
                    
                    # Server mods
                    if os.path.exists(mods_dir_path):
                        for filename in os.listdir(mods_dir_path):
                            if filename.endswith(".jar"):
                                path = os.path.join(mods_dir_path, filename)
                                size = os.path.getsize(path)
                                mods.append({
                                    "name": filename,
                                    "size": size,
                                    "size_mb": round(size / (1024*1024), 2),
                                    "source": "server"
                                })
                    
                    # Client-only mods
                    if os.path.exists(clientonly_path):
                        for filename in os.listdir(clientonly_path):
                            if filename.endswith(".jar"):
                                path = os.path.join(clientonly_path, filename)
                                size = os.path.getsize(path)
                                mods.append({
                                    "name": filename,
                                    "size": size,
                                    "size_mb": round(size / (1024*1024), 2),
                                    "source": "clientonly"
                                })
                    
                    # Sort A-Z by name
                    return sorted(mods, key=lambda x: x["name"].lower())
                
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
                    props = parse_props()
                    c["server_port"] = props.get("server-port", c.get("server_port", "25565"))
                    c["query_port"] = props.get("query.port", "25565")
                    c["rcon_port"] = props.get("rcon.port", "25575")
                    return jsonify(c)
                
                @app.route("/api/config", methods=["POST"])
                def api_config_update():
                    try:
                        data = request.json
                        c = load_cfg()
                        allowed = [
                            "ferium_update_interval_hours", "ferium_weekly_update_day",
                            "ferium_weekly_update_hour", "mc_version",
                            "hostname", "curator_sort", "curator_limit",
                            "broadcast_enabled", "broadcast_auto_on_install",
                            "nag_show_mod_list_on_join", "nag_first_visit_modal",
                            "motd_show_download_url", "install_script_types",
                        ]
                        for field in allowed:
                            if field in data:
                                c[field] = data[field]
                        save_cfg(c)
                        return jsonify({"success": True, "message": "Config updated"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/java")
                def api_java_status():
                    """Get current Java version and available upgrades"""
                    current = _get_java_version()
                    available = _check_jdk_upgrade_available()
                    
                    # Find mods quarantined for Java version mismatch
                    c = load_cfg()
                    mods_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                    quarantine_dir = os.path.join(mods_dir, "quarantine")
                    java_quarantined = []
                    
                    if os.path.isdir(quarantine_dir):
                        for fn in os.listdir(quarantine_dir):
                            if fn.endswith('.jar'):
                                reason_file = os.path.join(quarantine_dir, f"{fn}.reason.txt")
                                if os.path.exists(reason_file):
                                    with open(reason_file) as rf:
                                        reason = rf.read()
                                    if "Requires Java" in reason and "server has Java" in reason:
                                        # Extract required version
                                        match = re.search(r'Requires Java (\d+)', reason)
                                        required = match.group(1) if match else "unknown"
                                        java_quarantined.append({
                                            "name": fn,
                                            "required_java": required,
                                            "reason": reason.split('\n')[1] if '\n' in reason else reason
                                        })
                    
                    return jsonify({
                        "current_version": current,
                        "available_upgrades": available,
                        "quarantined_mods": java_quarantined
                    })
                
                @app.route("/api/java/upgrade", methods=["POST"])
                def api_java_upgrade():
                    """Install a JDK upgrade"""
                    data = request.json or {}
                    package = data.get("package")
                    
                    if not package:
                        return jsonify({"success": False, "error": "No package specified"}), 400
                    
                    # Verify it's a valid JDK package
                    if not re.match(r'^(openjdk|temurin)-\d+-jdk', package):
                        return jsonify({"success": False, "error": "Invalid package name"}), 400
                    
                    # Install
                    log_event("JDK_UPGRADE", f"Installing {package}...")
                    if _install_jdk(package):
                        # Extract version and set as default
                        match = re.search(r'(\d+)-jdk', package)
                        if match:
                            version = match.group(1)
                            _set_default_java(version)
                        
                        log_event("JDK_UPGRADE", f"Successfully installed {package}")
                        return jsonify({
                            "success": True, 
                            "message": f"Installed {package}. Restart server to apply."
                        })
                    else:
                        return jsonify({"success": False, "error": "Installation failed"}), 500
                
                @app.route("/api/java/unquarantine", methods=["POST"])
                def api_java_unquarantine():
                    """Move Java-incompatible mods back from quarantine"""
                    c = load_cfg()
                    mods_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                    quarantine_dir = os.path.join(mods_dir, "quarantine")
                    
                    if not os.path.isdir(quarantine_dir):
                        return jsonify({"success": True, "restored": 0})
                    
                    restored = []
                    for fn in os.listdir(quarantine_dir):
                        if fn.endswith('.jar'):
                            reason_file = os.path.join(quarantine_dir, f"{fn}.reason.txt")
                            if os.path.exists(reason_file):
                                with open(reason_file) as rf:
                                    reason = rf.read()
                                if "Requires Java" in reason and "server has Java" in reason:
                                    # Move back
                                    import shutil
                                    src = os.path.join(quarantine_dir, fn)
                                    dst = os.path.join(mods_dir, fn)
                                    shutil.move(src, dst)
                                    os.remove(reason_file)
                                    restored.append(fn)
                    
                    if restored:
                        log_event("JDK_UPGRADE", f"Restored {len(restored)} mods after Java upgrade")
                        # Regenerate zip
                        create_mod_zip(mods_dir)
                    
                    return jsonify({"success": True, "restored": len(restored), "mods": restored})
                
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
                
                @app.route("/api/mods/<mod_name>/quarantine", methods=["POST"])
                def api_quarantine_mod(mod_name):
                    """Manually quarantine a mod (server or clientonly)"""
                    try:
                        c = load_cfg()
                        mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                        quarantine_dir = os.path.join(mods_dir_path, "quarantine")
                        clientonly_dir = os.path.join(mods_dir_path, "clientonly")
                        
                        # Check root mods folder first
                        mod_path = os.path.join(mods_dir_path, mod_name)
                        source = "server"
                        
                        # If not in root, check clientonly
                        if not os.path.exists(mod_path):
                            mod_path = os.path.join(clientonly_dir, mod_name)
                            source = "clientonly"
                        
                        if not os.path.exists(mod_path):
                            return jsonify({"success": False, "error": "Mod not found"}), 404
                        
                        if not mod_path.endswith(".jar"):
                            return jsonify({"success": False, "error": "Not a JAR file"}), 400
                        
                        # Ensure quarantine dir exists
                        os.makedirs(quarantine_dir, exist_ok=True)
                        
                        # Move to quarantine
                        dest = os.path.join(quarantine_dir, mod_name)
                        import shutil
                        shutil.move(mod_path, dest)
                        
                        # Write reason file
                        reason_file = dest + ".reason.txt"
                        from datetime import datetime
                        with open(reason_file, "w") as f:
                            f.write(f"Quarantined: {datetime.now().isoformat()}\n")
                            f.write(f"Reason: Manually quarantined via dashboard\n")
                            f.write(f"Mod ID: {mod_name}\n")
                            f.write(f"Display Name: {mod_name}\n")
                            f.write(f"Source: {source}\n")
                        
                        log_event("MANUAL_QUARANTINE", f"Manually quarantined {mod_name} (from {source})")
                        
                        # Regenerate zip
                        create_mod_zip(mods_dir_path)
                        
                        return jsonify({
                            "success": True, 
                            "message": f"Quarantined {mod_name}",
                            "source": source
                        })
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
                    allowed_ext = [".jar", ".zip", ".ps1", ".sh", ".bat", ".json"]
                    if not any(filename.endswith(ext) for ext in allowed_ext):
                        return jsonify({"error": "File type not allowed"}), 403
                    file_path = os.path.join(mods_dir_path, filename)
                    if not os.path.abspath(file_path).startswith(os.path.abspath(mods_dir_path)):
                        return jsonify({"error": "Invalid path"}), 400
                    if os.path.exists(file_path):
                        return send_file(file_path, as_attachment=True)
                    return jsonify({"error": "File not found"}), 404
                
                @app.route("/download/manifest")
                def download_manifest():
                    """Serve mods_manifest.json"""
                    c = load_cfg()
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    manifest_path = os.path.join(mods_dir_path, "mods_manifest.json")
                    if os.path.exists(manifest_path):
                        return send_file(manifest_path, mimetype="application/json")
                    return jsonify({"error": "Manifest not found"}), 404
                
                @app.route("/download/mods/<filename>")
                def download_mod(filename):
                    """Serve individual mod JAR for diff-based syncing"""
                    c = load_cfg()
                    mods_dir_path = os.path.join(CWD, c.get("mods_dir", "mods"))
                    if not filename.endswith(".jar"):
                        return jsonify({"error": "Only .jar files"}), 403
                    
                    # Check root first, then clientonly
                    file_path = os.path.join(mods_dir_path, filename)
                    if not os.path.exists(file_path):
                        file_path = os.path.join(mods_dir_path, "clientonly", filename)
                    
                    if os.path.exists(file_path):
                        return send_file(file_path, as_attachment=True)
                    return jsonify({"error": "Mod not found"}), 404
                
                @app.route("/download/install-mods.<ext>")
                def download_script(ext):
                    """Generate and serve install scripts on-the-fly"""
                    c = load_cfg()
                    http_port = int(c.get("http_port", 8000))
                    server_ip = get_server_hostname(c)
                    
                    if ext == "bat":
                        # Minimal wrapper - bypasses execution policy
                        script = f'''@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'http://{server_ip}:{http_port}/download/install-mods.ps1' -OutFile '%TEMP%\\install-mods.ps1'; PowerShell -NoProfile -ExecutionPolicy Bypass -File '%TEMP%\\install-mods.ps1'"
'''
                        return Response(script, mimetype="application/bat", headers={"Content-Disposition": "attachment; filename=install-mods.bat"})
                    
                    elif ext == "ps1":
                        script = f'''# Minecraft Mod Installer
# Compatible with PowerShell 5.1 (Windows 10 21H2)

$modsPath = "$env:APPDATA\\.minecraft\\mods"
$oldPath = "$env:APPDATA\\.minecraft\\oldmods"
$baseUrl = "http://{server_ip}:{http_port}"

Write-Host "============================================"
Write-Host "   Minecraft Mod Installer"
Write-Host "   Server: {server_ip}:{http_port}"
Write-Host "============================================"

New-Item -ItemType Directory -Path $modsPath,$oldPath -Force | Out-Null

Write-Host "Fetching mod list..."
try {{ $man = Invoke-RestMethod "$baseUrl/download/manifest" -UseBasicParsing }}
catch {{ Write-Host "ERROR: Cannot connect to server" -Fore Red; Read-Host "Press Enter"; exit 1 }}

$srv = @($man.mods.name)
$loc = @(Get-ChildItem $modsPath *.jar -ErrorAction SilentlyContinue).Name
$dl = @($srv | ?{{$_ -notin $loc}})
$ar = @($loc | ?{{$_ -notin $srv}})

Write-Host "Server: $($srv.Count) Local: $($loc.Count)"
Write-Host "Download: $($dl.Count) Archive: $($ar.Count)"

foreach ($f in $ar) {{
    $p = Join-Path $modsPath $f
    if (Test-Path $p) {{ Write-Host " Archiving $f"; mv $p $oldPath -Force }}
}}

$n = 0
foreach ($f in $dl) {{
    Write-Host " Downloading $f..." -NoNewline
    try {{ Invoke-WebRequest "$baseUrl/download/mods/$f" -OutFile "$modsPath\\$f" -UseBasicParsing; Write-Host " OK" -Fore Green; $n++ }}
    catch {{ Write-Host " FAIL" -Fore Red }}
}}

Write-Host "============================================"
Write-Host "SUCCESS: $((Get-ChildItem $modsPath *.jar).Count) mods ($n new)" -Fore Green
Write-Host "============================================"
Read-Host "Press Enter"
'''
                        return Response(script, mimetype="text/plain", headers={"Content-Disposition": "attachment; filename=install-mods.ps1"})
                    
                    elif ext == "sh":
                        script = f'''#!/bin/bash
MC="$HOME/.minecraft"
[[ "$OSTYPE" == "darwin"* ]] && MC="$HOME/Library/Application Support/minecraft"
MODS="$MC/mods"
OLD="$MC/oldmods"
URL="http://{server_ip}:{http_port}/download/mods_latest.zip"

echo "============================================"
echo "   Minecraft Mod Installer"
echo "   Server: {server_ip}:{http_port}"
echo "============================================"

mkdir -p "$MODS" "$OLD"
echo "Downloading mods..."
curl -fL -o /tmp/mods.zip "$URL" || {{ echo "ERROR: Download failed"; exit 1; }}

echo "Archiving old mods..."
mv "$MODS"/*.jar "$OLD/" 2>/dev/null || true

echo "Extracting mods..."
unzip -o /tmp/mods.zip -d "$MODS" 2>/dev/null || python3 -c "import zipfile; zipfile.ZipFile('/tmp/mods.zip').extractall('$MODS')"
rm -f /tmp/mods.zip

echo "============================================"
echo "SUCCESS: $(ls $MODS/*.jar 2>/dev/null | wc -l) mods installed!"
echo "============================================"
'''
                        return Response(script, mimetype="text/plain", headers={"Content-Disposition": "attachment; filename=install-mods.sh"})
                    
                    return jsonify({"error": "Unknown script type. Use .ps1 or .sh"}), 404
                
                @app.route("/api/mod-lists")
                def api_mod_lists():
                    """Return curated mod lists from cache, with installed status for each mod"""
                    c = load_cfg()
                    loader = c.get("loader", "neoforge")
                    mc_ver = c.get("mc_version", "1.21.11")
                    m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                    cache_file = os.path.join(CWD, f"curator_cache_{mc_ver}_{loader}.json")
                    
                    # Build installed index (scans mods/ AND mods/clientonly/)
                    installed_tokens, installed_jars = build_installed_index(m_dir)
                    
                    def _mark_installed(mod):
                        """Add 'installed' flag to a mod dict using smart matching"""
                        name = mod.get("name", "")
                        slug = mod.get("slug", "")
                        mod["installed"] = check_installed(name, slug, installed_tokens)
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
                                # Look up full mod data from cache; if not cached (e.g. from
                                # modpack conversion), treat as Modrinth project ID
                                mod_data = cached_mods.get(mod_id)
                                if not mod_data:
                                    mod_data = {"id": mod_id, "name": mod_id, "source": "modrinth"}
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
                        broadcast_sent = False
                        if downloaded > 0:
                            try:
                                sort_mods_by_type(m_dir)
                                create_install_scripts(m_dir, c)
                                create_mod_zip(m_dir)
                            except Exception as e:
                                log_event("API", f"Post-install regeneration error: {e}")
                            # Auto-broadcast to online players (if enabled in config)
                            try:
                                if c.get("broadcast_enabled", True) and c.get("broadcast_auto_on_install", True):
                                    total_mods = len([f for f in os.listdir(m_dir) if f.endswith(".jar")])
                                    broadcast_sent = broadcast_mod_update(c, mod_count=total_mods)
                            except Exception as e:
                                log_event("API", f"Post-install broadcast error: {e}")
                            
                            # Auto-restart server so new mods are loaded
                            # Run in background thread so the API response returns immediately
                            def _deferred_restart(config):
                                try:
                                    time.sleep(3)  # Brief delay for zip/scripts to finish
                                    log_event("API", "Auto-restarting server to load new mods...")
                                    restart_server_for_mods(config)
                                except Exception as e:
                                    log_event("API", f"Auto-restart failed: {e}")
                            
                            restart_thread = threading.Thread(target=_deferred_restart, args=(c,), daemon=True)
                            restart_thread.start()
                        
                        return jsonify({
                            "success": True,
                            "downloaded": downloaded,
                            "skipped": skipped,
                            "failed": failed,
                            "broadcast": broadcast_sent,
                            "restarting": downloaded > 0,
                            "message": f"Downloaded {downloaded}, skipped {skipped} already installed, {len(failed)} failed" + (". Server restarting to load new mods..." if downloaded > 0 else "")
                        })
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/convert-modpack", methods=["POST"])
                def api_convert_modpack():
                    """Modpack Conversion: accept a list of JAR filenames from another modpack
                    (e.g. client's 1.21.4 Fabric mods folder), search Modrinth for each mod,
                    and check if a version exists for the server's MC version + loader.
                    
                    Request body: {"filenames": ["mod1-1.21.4.jar", "mod2-fabric-1.21.4.jar", ...],
                                   "source_loader": "fabric",    // optional, for display
                                   "source_version": "1.21.4"}   // optional, for display
                    
                    Returns: {"results": [...], "summary": {...}}
                    """
                    try:
                        data = request.json
                        filenames = data.get("filenames", [])
                        source_loader = data.get("source_loader", "unknown")
                        source_version = data.get("source_version", "unknown")
                        
                        if not filenames:
                            return jsonify({"success": False, "error": "No filenames provided"}), 400
                        
                        c = load_cfg()
                        mc_ver = c.get("mc_version", "1.21.11")
                        loader = c.get("loader", "neoforge")
                        m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        
                        # Build installed index for checking what's already on the server
                        installed_tokens, installed_jars = build_installed_index(m_dir)
                        
                        from urllib.parse import quote
                        base_url = "https://api.modrinth.com/v2"
                        loader_lower = loader.lower()
                        
                        results = []
                        for fn in filenames:
                            if not fn.endswith('.jar'):
                                continue
                            
                            token = _extract_mod_token(fn)
                            if not token or len(token) < 2:
                                results.append({
                                    "filename": fn,
                                    "status": "unparseable",
                                    "message": "Could not extract mod name from filename"
                                })
                                continue
                            
                            # Check if already installed on the server
                            if check_installed(token, token, installed_tokens):
                                results.append({
                                    "filename": fn,
                                    "token": token,
                                    "status": "already_installed",
                                    "message": f"Already installed on server"
                                })
                                continue
                            
                            # Search Modrinth for this mod name
                            # Use a broader search query derived from the token
                            search_query = re.sub(r'([a-z])([A-Z])', r'\1 \2', token)  # camelCase split
                            # Also try the raw filename (minus version/loader noise) as search query
                            readable_name = re.sub(r'[-_.]', ' ', fn.replace('.jar', ''))
                            readable_name = re.sub(r'\b(neoforge|forge|fabric|quilt)\b', '', readable_name, flags=re.I)
                            readable_name = re.sub(r'\b\d+\.\d+[\.\d]*\b', '', readable_name)
                            readable_name = re.sub(r'\s+', ' ', readable_name).strip()
                            
                            found = False
                            for query in [readable_name, token]:
                                if found:
                                    break
                                # Search with server's MC version + loader facets
                                facets = f'[["versions:{mc_ver}"],["categories:{loader_lower}"],["project_type:mod"]]'
                                facets_enc = quote(facets)
                                search_url = f"{base_url}/search?query={quote(query)}&facets={facets_enc}&limit=5"
                                
                                try:
                                    req = urllib.request.Request(search_url, headers={"User-Agent": "NeoRunner/1.0"})
                                    with urllib.request.urlopen(req, timeout=15) as resp:
                                        search_data = json.loads(resp.read().decode())
                                        hits = search_data.get("hits", [])
                                        
                                        if hits:
                                            # Try to find a good match by comparing tokens
                                            best_hit = None
                                            best_score = 0
                                            from difflib import SequenceMatcher
                                            for hit in hits:
                                                hit_slug = re.sub(r'[^a-z0-9]', '', hit.get("slug", "").lower())
                                                hit_title = re.sub(r'[^a-z0-9]', '', hit.get("title", "").lower())
                                                score_slug = SequenceMatcher(None, token, hit_slug).ratio()
                                                score_title = SequenceMatcher(None, token, hit_title).ratio()
                                                score = max(score_slug, score_title)
                                                if score > best_score:
                                                    best_score = score
                                                    best_hit = hit
                                            
                                            # Accept if score is reasonable (>0.5) or it's the only result
                                            if best_hit and (best_score > 0.5 or len(hits) == 1):
                                                results.append({
                                                    "filename": fn,
                                                    "token": token,
                                                    "status": "found",
                                                    "match_score": round(best_score, 2),
                                                    "mod_id": best_hit.get("project_id"),
                                                    "name": best_hit.get("title"),
                                                    "slug": best_hit.get("slug"),
                                                    "description": best_hit.get("description", ""),
                                                    "downloads": best_hit.get("downloads", 0),
                                                    "icon_url": best_hit.get("icon_url", ""),
                                                    "message": f"Found on Modrinth for {mc_ver} ({loader})"
                                                })
                                                found = True
                                except Exception as e:
                                    log_event("CONVERT", f"Search failed for '{query}': {e}")
                            
                            if not found:
                                # Try a broader search WITHOUT mc version/loader facets
                                # to tell the user the mod exists but not for their version
                                exists_anywhere = False
                                try:
                                    broad_facets = '[["project_type:mod"]]'
                                    broad_url = f"{base_url}/search?query={quote(readable_name)}&facets={quote(broad_facets)}&limit=3"
                                    req = urllib.request.Request(broad_url, headers={"User-Agent": "NeoRunner/1.0"})
                                    with urllib.request.urlopen(req, timeout=10) as resp:
                                        broad_data = json.loads(resp.read().decode())
                                        broad_hits = broad_data.get("hits", [])
                                        if broad_hits:
                                            from difflib import SequenceMatcher
                                            bh = broad_hits[0]
                                            bh_slug = re.sub(r'[^a-z0-9]', '', bh.get("slug", "").lower())
                                            if SequenceMatcher(None, token, bh_slug).ratio() > 0.5:
                                                exists_anywhere = True
                                                results.append({
                                                    "filename": fn,
                                                    "token": token,
                                                    "status": "not_available",
                                                    "name": bh.get("title"),
                                                    "slug": bh.get("slug"),
                                                    "message": f"Exists on Modrinth but NOT available for {mc_ver} ({loader})"
                                                })
                                except Exception:
                                    pass
                                
                                if not exists_anywhere:
                                    results.append({
                                        "filename": fn,
                                        "token": token,
                                        "status": "not_found",
                                        "message": "Not found on Modrinth"
                                    })
                            
                            # Rate-limit to avoid hammering the API
                            time.sleep(0.3)
                        
                        # Summary
                        found_count = sum(1 for r in results if r["status"] == "found")
                        installed_count = sum(1 for r in results if r["status"] == "already_installed")
                        not_avail_count = sum(1 for r in results if r["status"] == "not_available")
                        not_found_count = sum(1 for r in results if r["status"] == "not_found")
                        unparseable_count = sum(1 for r in results if r["status"] == "unparseable")
                        
                        return jsonify({
                            "success": True,
                            "source": {"loader": source_loader, "version": source_version},
                            "target": {"loader": loader, "version": mc_ver},
                            "results": results,
                            "summary": {
                                "total": len(results),
                                "found": found_count,
                                "already_installed": installed_count,
                                "not_available": not_avail_count,
                                "not_found": not_found_count,
                                "unparseable": unparseable_count
                            }
                        })
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/broadcast", methods=["POST"])
                def api_broadcast():
                    """Send mod update notification to all online players via RCON tellraw"""
                    try:
                        c = load_cfg()
                        if not c.get("broadcast_enabled", True):
                            return jsonify({"success": False, "error": "Broadcasts are disabled in config"}), 403
                        m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        mod_count = len([f for f in os.listdir(m_dir) if f.endswith(".jar")]) if os.path.isdir(m_dir) else 0
                        ok = broadcast_mod_update(c, mod_count=mod_count)
                        if ok:
                            return jsonify({"success": True, "message": f"Broadcast sent to all players ({mod_count} mods)"})
                        return jsonify({"success": False, "error": "RCON failed — is the server running with RCON enabled?"}), 500
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
                    """Start the MC server - resets restart counter and removes stopped flag."""
                    try:
                        uid = os.getuid()
                        tmux_socket = f"/tmp/tmux-{uid}/default"
                        
                        # Check if MC is already running
                        check = run_cmd(f"tmux -S {tmux_socket} has-session -t MC 2>/dev/null")
                        if check.get("success"):
                            return jsonify({"success": True, "message": "Server already running"})
                        
                        # Remove stopped flag
                        stopped_flag = os.path.join(CWD, ".mc_stopped")
                        if os.path.exists(stopped_flag):
                            os.remove(stopped_flag)
                        
                        # Reset restart counter by creating reset flag
                        reset_flag = os.path.join(CWD, ".mc_reset_counter")
                        with open(reset_flag, "w") as f:
                            f.write(str(time.time()))
                        
                        log_event("SERVER_START", "Start command - reset restart counter, removed stopped flag")
                        
                        # Restart service to re-enter monitoring loop with fresh counter
                        run_cmd("systemctl --user restart mcserver")
                        return jsonify({"success": True, "message": "Starting server (restart counter reset)..."})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/server/stop", methods=["POST"])
                def api_server_stop():
                    """Stop the MC server (tmux session only, keep Flask running)."""
                    try:
                        uid = os.getuid()
                        tmux_socket = f"/tmp/tmux-{uid}/default"
                        
                        # Send stop command to MC
                        run_cmd(f"tmux -S {tmux_socket} send-keys -t MC 'stop' Enter 2>/dev/null")
                        time.sleep(3)
                        
                        # Kill tmux session if still alive
                        run_cmd(f"tmux -S {tmux_socket} kill-session -t MC 2>/dev/null || true")
                        
                        # Create flag to prevent auto-restart
                        with open(os.path.join(CWD, ".mc_stopped"), "w") as f:
                            f.write(str(time.time()))
                        
                        log_event("SERVER_STOP", "MC server stopped via dashboard")
                        return jsonify({"success": True, "message": "Server stopped"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/server/restart", methods=["POST"])
                def api_server_restart():
                    """Restart MC server: stop then start."""
                    try:
                        uid = os.getuid()
                        tmux_socket = f"/tmp/tmux-{uid}/default"
                        
                        # Create flag first to prevent clean-shutdown exit
                        stopped_flag = os.path.join(CWD, ".mc_stopped")
                        
                        # Stop MC
                        run_cmd(f"tmux -S {tmux_socket} send-keys -t MC 'stop' Enter 2>/dev/null")
                        time.sleep(3)
                        run_cmd(f"tmux -S {tmux_socket} kill-session -t MC 2>/dev/null || true")
                        
                        # Remove flag to trigger restart in run loop
                        if os.path.exists(stopped_flag):
                            os.remove(stopped_flag)
                        
                        log_event("SERVER_RESTART", "MC server restart via dashboard")
                        return jsonify({"success": True, "message": "Restarting..."})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/mods/upgrade", methods=["POST"])
                def api_upgrade_mods():
                    try:
                        ferium_bin = os.path.join(CWD, ".local/bin/ferium")
                        result = run_cmd(f"{ferium_bin} upgrade")
                        if result["success"]:
                            return jsonify({"success": True, "message": "Mods upgraded"})
                        return jsonify({"success": False, "error": result["stderr"]}), 400
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                # ---- Quarantine API ----
                @app.route("/api/quarantine")
                def api_quarantine():
                    """List all quarantined mods with their reasons"""
                    try:
                        c = load_cfg()
                        q_dir = os.path.join(CWD, c.get("mods_dir", "mods"), "quarantine")
                        if not os.path.isdir(q_dir):
                            return jsonify({"mods": []})
                        mods = []
                        for fn in sorted(os.listdir(q_dir)):
                            if not fn.endswith(".jar"):
                                continue
                            reason_file = os.path.join(q_dir, f"{fn}.reason.txt")
                            reason = ""
                            date = ""
                            mod_id = ""
                            if os.path.exists(reason_file):
                                try:
                                    with open(reason_file) as rf:
                                        for line in rf:
                                            if line.startswith("Reason:"):
                                                reason = line.split(":", 1)[1].strip()
                                            elif line.startswith("Quarantined:"):
                                                date = line.split(":", 1)[1].strip()
                                            elif line.startswith("Mod ID"):
                                                mod_id = line.split(":", 1)[1].strip()
                                except Exception:
                                    pass
                            size_mb = round(os.path.getsize(os.path.join(q_dir, fn)) / (1024*1024), 2)
                            mods.append({
                                "filename": fn,
                                "reason": reason,
                                "date": date,
                                "mod_id": mod_id,
                                "size_mb": size_mb
                            })
                        return jsonify({"mods": mods})
                    except Exception as e:
                        return jsonify({"mods": [], "error": str(e)}), 500
                
                @app.route("/api/quarantine/restore", methods=["POST"])
                def api_quarantine_restore():
                    """Restore a quarantined mod back to the mods folder"""
                    try:
                        import shutil
                        data = request.json
                        filename = data.get("filename", "")
                        restart = data.get("restart", True)  # Auto-restart by default
                        if not filename or not filename.endswith(".jar"):
                            return jsonify({"success": False, "error": "Invalid filename"}), 400
                        c = load_cfg()
                        m_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        q_dir = os.path.join(m_dir, "quarantine")
                        src = os.path.join(q_dir, filename)
                        dst = os.path.join(m_dir, filename)
                        if not os.path.exists(src):
                            return jsonify({"success": False, "error": "File not found in quarantine"}), 404
                        shutil.move(src, dst)
                        # Remove reason sidecar
                        reason_file = os.path.join(q_dir, f"{filename}.reason.txt")
                        if os.path.exists(reason_file):
                            os.remove(reason_file)
                        log_event("QUARANTINE", f"Restored {filename} from quarantine")
                        
                        # Restart server if requested
                        if restart:
                            uid = os.getuid()
                            tmux_socket = f"/tmp/tmux-{uid}/default"
                            run_cmd(f"tmux -S {tmux_socket} send-keys -t MC 'stop' Enter 2>/dev/null")
                            import time
                            time.sleep(3)
                            run_cmd(f"tmux -S {tmux_socket} kill-session -t MC 2>/dev/null || true")
                            # Restart via user systemd
                            env = os.environ.copy()
                            env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
                            subprocess.run(["systemctl", "--user", "restart", "mcserver"], env=env, capture_output=True)
                            log_event("QUARANTINE", f"Server restart triggered after restoring {filename}")
                        
                        return jsonify({"success": True, "message": f"Restored {filename}", "restarted": restart})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/quarantine/delete", methods=["POST"])
                def api_quarantine_delete():
                    """Permanently delete a quarantined mod"""
                    try:
                        data = request.json
                        filename = data.get("filename", "")
                        if not filename or not filename.endswith(".jar"):
                            return jsonify({"success": False, "error": "Invalid filename"}), 400
                        c = load_cfg()
                        q_dir = os.path.join(CWD, c.get("mods_dir", "mods"), "quarantine")
                        jar_path = os.path.join(q_dir, filename)
                        reason_path = os.path.join(q_dir, f"{filename}.reason.txt")
                        if not os.path.exists(jar_path):
                            return jsonify({"success": False, "error": "File not found in quarantine"}), 404
                        os.remove(jar_path)
                        if os.path.exists(reason_path):
                            os.remove(reason_path)
                        log_event("QUARANTINE", f"Deleted {filename} from quarantine")
                        return jsonify({"success": True, "message": f"Deleted {filename}"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                # ---- New Quarantine API ----
                @app.route("/api/quarantine/client-mods", methods=["POST"])
                def api_quarantine_client_mods():
                    """Move all client-only mods from root to clientonly/ directory"""
                    try:
                        c = load_cfg()
                        mods_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        clientonly_dir = os.path.join(mods_dir, "clientonly")
                        
                        # Find all client-only mods in root
                        client_mods = []
                        for fn in os.listdir(mods_dir):
                            if not fn.endswith(".jar"):
                                continue
                            jar_path = os.path.join(mods_dir, fn)
                            if _is_client_only_mod(jar_path):
                                client_mods.append(fn)
                        
                        # Move them to clientonly/
                        os.makedirs(clientonly_dir, exist_ok=True)
                        moved_count = 0
                        for mod in client_mods:
                            src = os.path.join(mods_dir, mod)
                            dst = os.path.join(clientonly_dir, mod)
                            if not os.path.exists(dst):
                                shutil.move(src, dst)
                                moved_count += 1
                                log_event("SELF_HEAL", f"Moved client-only mod {mod} -> clientonly/")
                        
                        return jsonify({"success": True, "message": f"Moved {moved_count} client-only mods to clientonly/", "moved": moved_count})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/quarantine/all", methods=["POST"])
                def api_quarantine_all():
                    """Quarantine all mods that cause crashes (client-only, dependency conflicts, etc.)"""
                    try:
                        c = load_cfg()
                        mods_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        quarantine_dir = os.path.join(mods_dir, "quarantine")
                        
                        # Get all mods that need quarantining
                        mods_to_quarantine = _get_problematic_mods(mods_dir)
                        
                        # Quarantine them
                        quarantined_count = 0
                        for mod in mods_to_quarantine:
                            if _quarantine_mod(mods_dir, mod["id"], mod["reason"]):
                                quarantined_count += 1
                        
                        return jsonify({"success": True, "message": f"Quarantined {quarantined_count} problematic mods", "quarantined": quarantined_count})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/quarantine/mods", methods=["POST"])
                def api_quarantine_mods():
                    """Quarantine specific mods by ID"""
                    try:
                        data = request.json
                        mod_ids = data.get("mod_ids", [])
                        if not mod_ids:
                            return jsonify({"success": False, "error": "No mod IDs provided"}), 400
                        
                        c = load_cfg()
                        mods_dir = os.path.join(CWD, c.get("mods_dir", "mods"))
                        
                        quarantined_count = 0
                        for mod_id in mod_ids:
                            if _quarantine_mod(mods_dir, mod_id, "User-requested quarantine"):
                                quarantined_count += 1
                        
                        return jsonify({"success": True, "message": f"Quarantined {quarantined_count} mods", "quarantined": quarantined_count})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                # ---- Blacklist API ----
                @app.route("/api/blacklist")
                def api_blacklist():
                    """Get current blacklist and whitelist"""
                    try:
                        c = load_cfg()
                        blacklist = c.get("blacklist", [])
                        whitelist = c.get("whitelist", [])
                        user_blacklist = c.get("user_blacklist", [])
                        user_whitelist = c.get("user_whitelist", [])
                        
                        return jsonify({
                            "blacklist": blacklist,
                            "whitelist": whitelist,
                            "user_blacklist": user_blacklist,
                            "user_whitelist": user_whitelist
                        })
                    except Exception as e:
                        return jsonify({"blacklist": [], "whitelist": [], "error": str(e)}), 500
                
                @app.route("/api/blacklist/add", methods=["POST"])
                def api_blacklist_add():
                    """Add a mod to blacklist"""
                    try:
                        data = request.json
                        mod_id = data.get("mod_id", "").strip().lower()
                        if not mod_id:
                            return jsonify({"success": False, "error": "No mod ID provided"}), 400
                        
                        c = load_cfg()
                        user_blacklist = c.get("user_blacklist", [])
                        
                        # Add to user_blacklist if not already present
                        if mod_id not in user_blacklist:
                            user_blacklist.append(mod_id)
                            c["user_blacklist"] = user_blacklist
                            save_cfg(c)
                            log_event("BLACKLIST", f"Added {mod_id} to user blacklist")
                        
                        return jsonify({"success": True, "message": f"Added {mod_id} to blacklist"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/blacklist/remove", methods=["POST"])
                def api_blacklist_remove():
                    """Remove a mod from blacklist"""
                    try:
                        data = request.json
                        mod_id = data.get("mod_id", "").strip().lower()
                        if not mod_id:
                            return jsonify({"success": False, "error": "No mod ID provided"}), 400
                        
                        c = load_cfg()
                        user_blacklist = c.get("user_blacklist", [])
                        
                        # Remove from user_blacklist if present
                        if mod_id in user_blacklist:
                            user_blacklist.remove(mod_id)
                            c["user_blacklist"] = user_blacklist
                            save_cfg(c)
                            log_event("BLACKLIST", f"Removed {mod_id} from user blacklist")
                        
                        return jsonify({"success": True, "message": f"Removed {mod_id} from blacklist"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/blacklist/patterns/add", methods=["POST"])
                def api_blacklist_pattern_add():
                    """Add a regex pattern to blacklist"""
                    try:
                        data = request.json
                        pattern = data.get("pattern", "").strip()
                        if not pattern:
                            return jsonify({"success": False, "error": "No pattern provided"}), 400
                        
                        # Validate regex pattern
                        try:
                            re.compile(pattern)
                        except re.error as e:
                            return jsonify({"success": False, "error": f"Invalid regex pattern: {e}"}), 400
                        
                        c = load_cfg()
                        blacklist_patterns = c.get("blacklist_patterns", [])
                        
                        # Add pattern if not already present
                        if pattern not in blacklist_patterns:
                            blacklist_patterns.append(pattern)
                            c["blacklist_patterns"] = blacklist_patterns
                            save_cfg(c)
                            log_event("BLACKLIST", f"Added pattern {pattern} to blacklist")
                        
                        return jsonify({"success": True, "message": f"Added pattern {pattern} to blacklist"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/blacklist/patterns/remove", methods=["POST"])
                def api_blacklist_pattern_remove():
                    """Remove a regex pattern from blacklist"""
                    try:
                        data = request.json
                        pattern = data.get("pattern", "").strip()
                        if not pattern:
                            return jsonify({"success": False, "error": "No pattern provided"}), 400
                        
                        c = load_cfg()
                        blacklist_patterns = c.get("blacklist_patterns", [])
                        
                        # Remove pattern if present
                        if pattern in blacklist_patterns:
                            blacklist_patterns.remove(pattern)
                            c["blacklist_patterns"] = blacklist_patterns
                            save_cfg(c)
                            log_event("BLACKLIST", f"Removed pattern {pattern} from blacklist")
                        
                        return jsonify({"success": True, "message": f"Removed pattern {pattern} from blacklist"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 400
                
                @app.route("/api/blacklist/check", methods=["POST"])
                def api_blacklist_check():
                    """Check if a mod ID matches any blacklist patterns"""
                    try:
                        data = request.json
                        mod_id = data.get("mod_id", "").strip().lower()
                        if not mod_id:
                            return jsonify({"success": False, "error": "No mod ID provided"}), 400
                        
                        c = load_cfg()
                        blacklist = c.get("blacklist", [])
                        user_blacklist = c.get("user_blacklist", [])
                        whitelist = c.get("whitelist", [])
                        user_whitelist = c.get("user_whitelist", [])
                        blacklist_patterns = c.get("blacklist_patterns", [])
                        
                        # Check if mod is explicitly whitelisted
                        if mod_id in whitelist or mod_id in user_whitelist:
                            return jsonify({"success": True, "blacklisted": False, "reason": "Whitelisted"})
                        
                        # Check if mod is explicitly blacklisted
                        if mod_id in blacklist or mod_id in user_blacklist:
                            return jsonify({"success": True, "blacklisted": True, "reason": "Explicitly blacklisted"})
                        
                        # Check if mod matches any blacklist patterns
                        for pattern in blacklist_patterns:
                            if re.search(pattern, mod_id):
                                return jsonify({"success": True, "blacklisted": True, "reason": f"Matches pattern: {pattern}", "pattern": pattern})
                        
                        # Check MC version compatibility - only allow exact matches
                        current_mc_version = c.get("mc_version", "1.21.11")
                        if _is_version_incompatible(mod_id, current_mc_version):
                            return jsonify({"success": True, "blacklisted": True, "reason": f"Version incompatible - requires exact MC version {current_mc_version}", "required_version": current_mc_version})
                        
                        return jsonify({"success": True, "blacklisted": False, "reason": "Not blacklisted"})
                    except Exception as e:
                        return jsonify({"success": False, "error": str(e)}), 500
                
                def _is_version_incompatible(mod_id, current_mc_version):
                    """Check if mod ID indicates incompatible MC version"""
                    # Extract version patterns from mod ID
                    version_patterns = [
                        r"-\d+\.\d+(?:\.\d+)?",  # -1.21.11, -1.21.1
                        r"_\d+\.\d+(?:\.\d+)?",  # _1.21.11, _1.21.1
                        r"\d+\.\d+(?:\.\d+)?-",  # 1.21.11-, 1.21.1-
                        r"mc\d+\.\d+(?:\.\d+)?",  # mc1.21.11, mc1.21.1
                        r"minecraft\d+\.\d+(?:\.\d+)?",  # minecraft1.21.11, minecraft1.21.1
                    ]
                    
                    # Check for exact version match first
                    exact_pattern = rf"-\d+\.\d+\.\d+"  # -1.21.11
                    if re.search(exact_pattern, mod_id):
                        # Check if exact version matches current MC version
                        match = re.search(r"-(\d+\.\d+\.\d+)", mod_id)
                        if match:
                            mod_version = match.group(1)
                            # Only allow exact match
                            if mod_version != current_mc_version:
                                return True  # Incompatible version
                    
                    # Check for partial version patterns that would be incompatible
                    for pattern in version_patterns:
                        if re.search(pattern, mod_id):
                            # Extract the version number
                            match = re.search(r"(\d+\.\d+(?:\.\d+)?)", mod_id)
                            if match:
                                mod_version = match.group(1)
                                # Block if it's a partial version that doesn't match exactly
                                if mod_version != current_mc_version:
                                    return True  # Incompatible version
                    
                    return False
                
                # ---- Server Events API ----
                @app.route("/api/server-events")
                def api_server_events():
                    """Return server events (crash, heal, quarantine) for dashboard timeline"""
                    return jsonify({"events": _server_events})
                
                @app.route("/api/server-events/clear", methods=["POST"])
                def api_server_events_clear():
                    """Clear the in-memory event store"""
                    _server_events.clear()
                    return jsonify({"success": True})
                
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
                
                # Write reason to a sidecar file with original folder
                reason_file = os.path.join(quarantine_dir, f"{fn}.reason.txt")
                with open(reason_file, "w") as rf:
                    rf.write(f"Quarantined: {datetime.now().isoformat()}\n")
                    rf.write(f"Reason: {reason}\n")
                    rf.write(f"Mod ID/slug: {mod_id_or_slug}\n")
                    rf.write(f"OriginalFolder: mods\n")
                
                return fn
            except Exception as e:
                log_event("QUARANTINE", f"Failed to quarantine {fn}: {e}")
                return None
    
    log_event("QUARANTINE", f"Could not find JAR matching '{mod_id_or_slug}' to quarantine")
    return None


def _quarantine_dependent_mods(mods_dir, quarantined_mod_id):
    """Find and quarantine all mods that depend on the given mod_id.
    
    When a mod is quarantined, any mods that list it as a dependency
    should also be quarantined since they won't work without it.
    """
    import shutil
    
    if not quarantined_mod_id:
        return []
    
    quarantine_dir = os.path.join(mods_dir, "quarantine")
    os.makedirs(quarantine_dir, exist_ok=True)
    
    quarantined_deps = []
    target_lower = quarantined_mod_id.lower()
    
    # Scan all JARs for dependencies on the quarantined mod
    for fn in os.listdir(mods_dir):
        if not fn.endswith('.jar'):
            continue
        jar_path = os.path.join(mods_dir, fn)
        if not os.path.isfile(jar_path):
            continue
        
        manifest = _parse_mod_manifest(jar_path)
        mod_id = manifest.get("mod_id", "")
        deps = manifest.get("dependencies", {})
        
        # Check if this mod depends on the quarantined mod
        for dep_id in deps.keys():
            if dep_id.lower() == target_lower:
                # Quarantine this dependent mod
                dst = os.path.join(quarantine_dir, fn)
                try:
                    shutil.move(jar_path, dst)
                    reason_file = os.path.join(quarantine_dir, f"{fn}.reason.txt")
                    with open(reason_file, "w") as rf:
                        rf.write(f"Quarantined: {datetime.now().isoformat()}\n")
                        rf.write(f"Reason: Depends on quarantined mod '{quarantined_mod_id}'\n")
                        rf.write(f"Mod ID: {mod_id}\n")
                        rf.write(f"OriginalFolder: mods\n")
                    log_event("QUARANTINE", f"Quarantined {fn} (depends on {quarantined_mod_id})")
                    quarantined_deps.append((fn, mod_id))
                except Exception as e:
                    log_event("QUARANTINE", f"Failed to quarantine dependent {fn}: {e}")
                break
    
    return quarantined_deps


def _search_curseforge_live(dep_name, mods_dir, mc_version, loader_name):
    """Search CurseForge live for a dependency and download it.
    
    Uses Playwright stealth browser to search CurseForge, find a matching mod,
    and download the appropriate file for the given MC version + loader.
    
    Returns True if successfully downloaded, False otherwise.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return False
    
    _cf_rate_limit()
    
    loader_id = CF_LOADER_IDS.get(loader_name.lower(), 6)
    dep_norm = re.sub(r'[^a-z0-9]', '', dep_name.lower())
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    
    try:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--no-first-run",
                    "--disable-extensions",
                    "--mute-audio",
                ]
            )
            context = browser.new_context(
                user_agent=ua,
                viewport=viewport,
                locale=locale,
                color_scheme="dark" if random.random() > 0.5 else "light",
            )
            page = context.new_page()
            
            # Visit homepage first to establish cookies
            page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.0, 3.5))
            
            search_url = f"https://www.curseforge.com/minecraft/search?search={dep_name}&version={mc_version}&gameVersionTypeId={loader_id}"
            log_event("SELF_HEAL", f"CurseForge search URL: {search_url}")
            
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(random.uniform(3.0, 5.0))
                
                title = page.title()
                if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking"]):
                    log_event("SELF_HEAL", "CurseForge: Cloudflare challenge, waiting...")
                    time.sleep(random.uniform(8.0, 15.0))
                    page.wait_for_load_state("networkidle", timeout=45000)
                
                cards = page.query_selector_all("div.project-card")
                if not cards:
                    log_event("SELF_HEAL", f"CurseForge: no results for '{dep_name}'")
                    context.close()
                    browser.close()
                    return False
                
                best_match = None
                best_score = 0
                
                for card in cards[:10]:
                    try:
                        name_el = card.query_selector("a.name span.ellipsis")
                        if not name_el:
                            name_el = card.query_selector("a.name")
                        card_name = name_el.inner_text().strip() if name_el else ""
                        
                        slug_el = card.query_selector("a.overlay-link")
                        href = slug_el.get_attribute("href") if slug_el else ""
                        slug_match = re.search(r'/minecraft/mc-mods/([^/?]+)', href) if href else None
                        card_slug = slug_match.group(1) if slug_match else ""
                        
                        if not card_name or not card_slug:
                            continue
                        
                        card_norm = re.sub(r'[^a-z0-9]', '', card_name.lower())
                        slug_norm = re.sub(r'[^a-z0-9]', '', card_slug.lower())
                        
                        score = 0
                        if dep_norm == card_norm or dep_norm == slug_norm:
                            score = 100
                        elif dep_norm in card_norm or dep_norm in slug_norm:
                            score = 75
                        elif card_norm in dep_norm or slug_norm in dep_norm:
                            score = 50
                        
                        if score > best_score:
                            best_score = score
                            dl_cta = card.query_selector("a.download-cta")
                            dl_href = dl_cta.get_attribute("href") if dl_cta else ""
                            file_match = re.search(r'/download/(\d+)', dl_href) if dl_href else None
                            
                            best_match = {
                                "name": card_name,
                                "slug": card_slug,
                                "file_id": file_match.group(1) if file_match else "",
                                "download_href": dl_href,
                            }
                    except Exception:
                        continue
                
                context.close()
                browser.close()
                
                if best_match and best_score >= 50:
                    log_event("SELF_HEAL", f"CurseForge found '{best_match['name']}' (score={best_score}) for dep '{dep_name}'")
                    mod_info = {
                        "name": best_match["name"],
                        "slug": best_match["slug"],
                        "file_id": best_match["file_id"],
                    }
                    result = download_mod_from_curseforge(mod_info, mods_dir, mc_version, loader_name)
                    if result and result != False:
                        log_event("SELF_HEAL", f"Downloaded {best_match['name']} from CurseForge live search")
                        return True
                else:
                    log_event("SELF_HEAL", f"CurseForge: no good match for '{dep_name}' (best score={best_score})")
                    
            except PlaywrightTimeout:
                log_event("SELF_HEAL", f"CurseForge search timeout for '{dep_name}'")
            except Exception as e:
                log_event("SELF_HEAL", f"CurseForge search error for '{dep_name}': {e}")
            
            try:
                context.close()
                browser.close()
            except:
                pass
            
            return False
    except Exception as e:
        log_event("SELF_HEAL", f"CurseForge live search failed: {e}")
        return False


def _search_and_download_dep(dep_name, mods_dir, mc_version, loader_name):
    """Search Modrinth (with fuzzy matching) and CurseForge for a missing dependency and download it.
    
    Handles the common case where a mod's manifest modId differs from its Modrinth slug:
      - modId "supermartijn642corelib" -> slug "supermartijn642s-core-lib"
      - modId "biomeswevegone" -> slug "oh-the-biomes-weve-gone"
    
    Strategy:
      1. Try exact modId search on Modrinth
      2. Try with dashes/underscores inserted (fuzzy slug variations)
      3. Try Modrinth project lookup by modId directly (some mods use modId as project ID)
      4. Fall back to CurseForge curator cache
    
    Returns True if successfully downloaded, False otherwise."""
    from urllib.parse import quote as _url_quote
    
    def _modrinth_search(query, project_types=None):
        """Search Modrinth for mods AND libraries. Returns list of hits."""
        if project_types is None:
            project_types = ["mod", "modlibrary"]  # Search both mods and libraries
        
        all_hits = []
        for ptype in project_types:
            try:
                facets = f'[["versions:{mc_version}"],["categories:{loader_name}"],["project_type:{ptype}"]]'
                search_url = f"https://api.modrinth.com/v2/search?query={_url_quote(query)}&facets={_url_quote(facets)}&limit=10"
                req = urllib.request.Request(search_url, headers={"User-Agent": "NeoRunner/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    results = json.loads(resp.read().decode())
                all_hits.extend(results.get("hits", []))
            except Exception:
                continue
        return all_hits
    
    def _try_download_hit(hit):
        """Try downloading a Modrinth search hit. Returns True on success."""
        mod_data = {"id": hit["project_id"], "name": hit.get("title", dep_name), "slug": hit.get("slug", dep_name)}
        result = download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader_name)
        if result:
            log_event("SELF_HEAL", f"Downloaded {mod_data['name']} from Modrinth")
            return True
        return False
    
    def _pick_best_hit(hits, search_term):
        """Pick the best Modrinth hit by matching slug/title against the search term."""
        if not hits:
            return None
        search_norm = re.sub(r'[^a-z0-9]', '', search_term.lower())
        # Priority 1: exact slug match
        for h in hits:
            if h.get("slug", "").lower() == search_term.lower():
                return h
        # Priority 2: slug contains the search term (normalized)
        for h in hits:
            slug_norm = re.sub(r'[^a-z0-9]', '', h.get("slug", "").lower())
            if search_norm in slug_norm or slug_norm in search_norm:
                return h
        # Priority 3: title contains the search term
        for h in hits:
            title_norm = re.sub(r'[^a-z0-9]', '', h.get("title", "").lower())
            if search_norm in title_norm or title_norm in search_norm:
                return h
        # Fallback: first result
        return hits[0]
    
    # 1. Try exact modId as search query
    hits = _modrinth_search(dep_name)
    if hits:
        best = _pick_best_hit(hits, dep_name)
        if best and _try_download_hit(best):
            return True
    
    # 2. Generate slug variations and try each
    #    "supermartijn642corelib" -> "supermartijn642-core-lib", "supermartijn642s-core-lib"
    #    "biomeswevegone" -> "biomes-weve-gone", "oh-the-biomes-weve-gone"
    slug_variations = _generate_slug_variations(dep_name)
    for variant in slug_variations:
        if variant.lower() == dep_name.lower():
            continue  # Already tried
        hits = _modrinth_search(variant)
        if hits:
            best = _pick_best_hit(hits, dep_name)
            if best and _try_download_hit(best):
                return True
    
    # 3. Try direct project lookup by slug (Modrinth API)
    for slug_try in [dep_name] + slug_variations[:3]:
        try:
            url = f"https://api.modrinth.com/v2/project/{_url_quote(slug_try)}"
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                proj = json.loads(resp.read().decode())
            if proj.get("id"):
                mod_data = {"id": proj["id"], "name": proj.get("title", dep_name), "slug": proj.get("slug", dep_name)}
                result = download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader_name)
                if result:
                    log_event("SELF_HEAL", f"Downloaded {mod_data['name']} from Modrinth (direct lookup)")
                    return True
        except Exception:
            pass
    
    # 4. Try CurseForge curator cache first
    try:
        cache_file = os.path.join(CWD, f"curator_cache_{mc_version}_{loader_name}.json")
        if os.path.exists(cache_file):
            with open(cache_file) as f:
                cached = json.load(f)
            dep_norm = re.sub(r'[^a-z0-9]', '', dep_name.lower())
            for mod_id, mod_data in cached.items():
                if not isinstance(mod_data, dict):
                    continue
                mod_norm = re.sub(r'[^a-z0-9]', '', mod_data.get("name", "").lower())
                slug_norm = re.sub(r'[^a-z0-9]', '', mod_data.get("slug", "").lower())
                if dep_norm == mod_norm or dep_norm == slug_norm or dep_norm in mod_norm or dep_norm in slug_norm:
                    if mod_data.get("source") == "curseforge":
                        result = download_mod_from_curseforge(mod_data, mods_dir, mc_version, loader_name)
                        if result and result != False:
                            log_event("SELF_HEAL", f"Downloaded {mod_data['name']} from CurseForge cache")
                            return True
    except Exception as e:
        log_event("SELF_HEAL", f"CurseForge cache search failed for {dep_name}: {e}")
    
    # 5. Try LIVE CurseForge search via scraper
    if PLAYWRIGHT_AVAILABLE:
        log_event("SELF_HEAL", f"Searching CurseForge live for: {dep_name}")
        try:
            cf_result = _search_curseforge_live(dep_name, mods_dir, mc_version, loader_name)
            if cf_result:
                return True
        except Exception as e:
            log_event("SELF_HEAL", f"CurseForge live search failed for {dep_name}: {e}")
    
    log_event("SELF_HEAL", f"Could not find {dep_name} on either Modrinth or CurseForge for MC {mc_version}")
    return False


def _generate_slug_variations(mod_id):
    """Generate plausible Modrinth slug variations from a TOML modId.
    
    Mod manifest modIds are often camelCase or concatenated (e.g. 'supermartijn642corelib',
    'biomeswevegone') but Modrinth slugs use dashes ('supermartijn642s-core-lib',
    'oh-the-biomes-weve-gone'). This generates likely slug forms.
    
    Returns a list of slug variations to try.
    """
    variations = set()
    name = mod_id.lower().strip()
    
    # 1. Insert dashes at camelCase boundaries: "coreLib" -> "core-lib"
    dashed = re.sub(r'([a-z])([A-Z])', r'\1-\2', mod_id).lower()
    if dashed != name:
        variations.add(dashed)
    
    # 2. Insert dashes between word boundaries in concatenated strings
    #    "supermartijn642corelib" -> try splitting at common word boundaries
    #    Use a simple heuristic: split at transitions from digits to letters
    digit_split = re.sub(r'(\d)([a-z])', r'\1-\2', name)
    if digit_split != name:
        variations.add(digit_split)
    
    # 3. Add "s" after common author prefixes (supermartijn642 -> supermartijn642s)
    m = re.match(r'^([a-z]+\d+)(.*)', name)
    if m:
        prefix, rest = m.groups()
        variations.add(f"{prefix}s-{rest}" if rest else name)
        # Also try with dashes in the rest
        rest_dashed = re.sub(r'([a-z]{3,})', lambda x: x.group(), rest)
        if rest:
            variations.add(f"{prefix}s-{'-'.join(_split_words(rest))}")
            variations.add(f"{prefix}-{'-'.join(_split_words(rest))}")
    
    # 4. Split into natural English words
    words = _split_words(name)
    if len(words) > 1:
        variations.add('-'.join(words))
        # Try with common prefixes: "oh-the-", etc.
        variations.add('oh-the-' + '-'.join(words))
    
    # 5. Replace underscores with dashes
    if '_' in name:
        variations.add(name.replace('_', '-'))
    
    # Remove the original and empty strings
    variations.discard(name)
    variations.discard('')
    
    return list(variations)


def _split_words(s):
    """Split a concatenated lowercase string into likely English words.
    Uses a greedy approach with a dictionary of common mod-related words."""
    _WORDS = {
        'the', 'of', 'and', 'for', 'with', 'oh', 'weve', 'gone', 'wee', 'all',
        'biomes', 'biome', 'trees', 'tree', 'mods', 'mod', 'core', 'lib', 'library',
        'config', 'api', 'forge', 'fabric', 'neo', 'craft', 'mine', 'server', 'client',
        'world', 'extra', 'plus', 'super', 'mega', 'mini', 'max', 'pro', 'lite',
        'addons', 'addon', 'patch', 'fix', 'pack', 'packed', 'up', 'down',
        'connected', 'glass', 'lanterns', 'additional', 'farming', 'blockheads',
        'corgi', 'martijn', 'resourceful', 'creative', 'enchantment', 'description',
        'descriptions', 'enchanted', 'ench', 'desc', 'prickle', 'sodium', 'lithium',
        'iris', 'jade', 'curios', 'balm', 'framework', 'fusion', 'konkrete',
        'puzzles', 'searchables', 'controlling', 'configured', 'collective',
    }
    result = []
    i = 0
    while i < len(s):
        # Try longest match first
        best = None
        for length in range(min(12, len(s) - i), 1, -1):
            candidate = s[i:i+length]
            if candidate in _WORDS:
                best = candidate
                break
        if best:
            result.append(best)
            i += len(best)
        else:
            # No dictionary match — consume one character and append to last word or start new
            if result:
                result[-1] += s[i]
            else:
                result.append(s[i])
            i += 1
    return result


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
    
    if crash_type == "benign_mixin_warning":
        log_event("SELF_HEAL", f"Benign mixin warning detected - NOT a crash: {crash_info.get('message', '')[:200]}")
        return "ignored"
    
    if crash_type == "missing_dep":
        dep_name = crash_info.get("dep", "")
        if not dep_name or dep_name == "unknown":
            log_event("SELF_HEAL", "Missing dependency detected but name unknown, cannot auto-fix")
            return False
        
        log_event("SELF_HEAL", f"Missing dependency: {dep_name}" + (f" (required by {culprit})" if culprit else ""))
        
        # First check if dependency is already installed (jar filename contains dep_name)
        dep_norm = re.sub(r'[^a-z0-9]', '', dep_name.lower())
        already_installed = False
        if os.path.isdir(mods_dir):
            for fname in os.listdir(mods_dir):
                if fname.endswith('.jar'):
                    file_norm = re.sub(r'[^a-z0-9]', '', fname.lower())
                    if dep_norm in file_norm or file_norm.startswith(dep_norm):
                        already_installed = True
                        log_event("SELF_HEAL", f"Dependency {dep_name} already installed as {fname} - version mismatch or mod ID issue")
                        break
        
        if already_installed:
            if culprit:
                log_event("SELF_HEAL", f"Quarantining {culprit} - dep {dep_name} present but incompatible")
                quarantined = _quarantine_mod(mods_dir, culprit, f"Incompatible with installed {dep_name}")
                if quarantined:
                    return "quarantined"
            return False
        
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
    
    elif crash_type == "mod_conflict":
        # Two or more mods are incompatible — quarantine the most recently installed one
        culprits = crash_info.get("culprits", [])
        conflict_type = crash_info.get("conflict_type", "unknown")
        log_event("SELF_HEAL", f"Mod conflict ({conflict_type}) involving: {', '.join(culprits) if culprits else 'unknown mods'}")
        
        if culprit:
            crash_history[culprit] = crash_history.get(culprit, 0) + 1
            log_event("SELF_HEAL", f"Quarantining {culprit} (conflict type: {conflict_type})")
            quarantined = _quarantine_mod(mods_dir, culprit, f"Mod conflict ({conflict_type}) with other installed mods")
            if quarantined:
                return "quarantined"
        
        # If primary culprit couldn't be quarantined, try the last one in the list
        for c in reversed(culprits):
            if c and c != culprit:
                log_event("SELF_HEAL", f"Trying to quarantine alternate conflict mod: {c}")
                quarantined = _quarantine_mod(mods_dir, c, f"Mod conflict ({conflict_type})")
                if quarantined:
                    return "quarantined"
        
        log_event("SELF_HEAL", "Cannot identify which mod to quarantine for conflict")
        return False
    
    elif crash_type == "mod_error":
        if culprit:
            # Client-only mod crash — move to clientonly/ instead of quarantining
            subtype = crash_info.get("subtype", "")
            bad_file = crash_info.get("bad_file")
            culprits = crash_info.get("culprits", [culprit]) if crash_info.get("culprits") else [culprit]
            
            if subtype == "client_only" and bad_file:
                import shutil
                jar_path = os.path.join(mods_dir, bad_file)
                clientonly_dir = os.path.join(mods_dir, "clientonly")
                quarantine_dir = os.path.join(mods_dir, "quarantine")
                
                # Check if already in clientonly (crashed from there)
                clientonly_jar = os.path.join(clientonly_dir, bad_file)
                if os.path.exists(clientonly_jar):
                    # Mod is in clientonly/ but still causing crash - quarantine it
                    os.makedirs(quarantine_dir, exist_ok=True)
                    dst = os.path.join(quarantine_dir, bad_file)
                    shutil.move(clientonly_jar, dst)
                    reason_file = os.path.join(quarantine_dir, f"{bad_file}.reason.txt")
                    with open(reason_file, "w") as rf:
                        rf.write(f"Quarantined: {datetime.now().isoformat()}\n")
                        rf.write(f"Reason: Client-only mixin crash - mod still crashed from clientonly/\n")
                        rf.write(f"Mod ID: {culprit}\n")
                        rf.write(f"OriginalFolder: clientonly\n")
                    log_event("QUARANTINE", f"Quarantined {bad_file} (client-only mixin crash from clientonly/)")
                    
                    # Also quarantine mods that depend on this one
                    _quarantine_dependent_mods(mods_dir, culprit)
                    return "quarantined"
                
                if os.path.exists(jar_path):
                    os.makedirs(clientonly_dir, exist_ok=True)
                    dst = os.path.join(clientonly_dir, bad_file)
                    if not os.path.exists(dst):
                        shutil.move(jar_path, dst)
                        log_event("SELF_HEAL", f"Moved client-only mod {bad_file} -> clientonly/")
                        
                        # Move client-only dependencies to clientonly/ directory
                        if crash_info.get("dependencies"):
                            for dep in crash_info["dependencies"]:
                                _move_clientonly_dependency(mods_dir, dep, clientonly_dir)
                    else:
                        os.remove(jar_path)
                        log_event("SELF_HEAL", f"Removed duplicate client-only mod {bad_file} from mods/ (already in clientonly/)")
                    return "fixed"
                
                # If bad_file not found, quarantine by mod ID
                quarantined = _quarantine_mod(mods_dir, culprit, f"Client-only mod — crashes server (mixin error)")
                if quarantined:
                    _quarantine_dependent_mods(mods_dir, culprit)
                    return "quarantined"
                return False
            
            # If it's a corrupt/invalid JAR, quarantine immediately by exact filename
            if bad_file:
                import shutil
                jar_path = os.path.join(mods_dir, bad_file)
                if os.path.exists(jar_path):
                    quarantine_dir = os.path.join(mods_dir, "quarantine")
                    os.makedirs(quarantine_dir, exist_ok=True)
                    dst = os.path.join(quarantine_dir, bad_file)
                    shutil.move(jar_path, dst)
                    reason_file = os.path.join(quarantine_dir, f"{bad_file}.reason.txt")
                    with open(reason_file, "w") as rf:
                        rf.write(f"Quarantined: {datetime.now().isoformat()}\n")
                        rf.write(f"Reason: Invalid JAR file (corrupt download / HTML error page)\n")
                        rf.write(f"Mod ID/slug: {culprit}\n")
                        rf.write(f"OriginalFolder: mods\n")
                    log_event("QUARANTINE", f"Quarantined invalid JAR {bad_file} -> quarantine/")
                    return "quarantined"
            
            # Track crash count for this mod
            crash_history[culprit] = crash_history.get(culprit, 0) + 1
            log_event("SELF_HEAL", f"Mod error from {culprit} (crash #{crash_history[culprit]})")
            
            # For mixin-related errors, quarantine immediately (after 1 crash)
            max_crashes = cfg.get("max_crashes_before_quarantine", 2)
            if crash_history[culprit] >= max_crashes:
                log_event("SELF_HEAL", f"Quarantining {culprit} after {crash_history[culprit]} crashes")
                quarantined = _quarantine_mod(mods_dir, culprit, f"Caused {crash_history[culprit]} crashes")
                if quarantined:
                    _quarantine_dependent_mods(mods_dir, culprit)
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
    """Proactive pre-flight: scan ALL installed mod JARs' manifests for required deps,
    check if they're installed, and auto-fetch missing ones from Modrinth.
    
    This is the REAL dependency resolver — it reads each JAR's neoforge.mods.toml
    directly rather than relying on the curator cache (which only knows about mods
    it has seen before).
    
    Also scans mods/clientonly/ for deps needed on the client side.
    
    Handles:
    - Standard manifest deps (modId in [[dependencies.modid]])
    - Transitive deps (dep A requires dep B which requires dep C)
    - modId-to-slug mismatches (via _search_and_download_dep fuzzy search)
    - Re-downloading wrongly-quarantined deps that are now available
    - Optional dep interop alerts when 2+ mods share the same optional dep
    
    Returns dict with:
        - fetched: number of deps fetched
        - optional_interop: list of {dep_id, requested_by} for shared optional deps"""
    import zipfile
    
    mc_version = cfg.get("mc_version", "1.21.11")
    loader_name = cfg.get("loader", "neoforge")
    mods_dir = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    clientonly_dir = os.path.join(mods_dir, "clientonly")
    quarantine_dir = os.path.join(mods_dir, "quarantine")
    
    result = {"fetched": 0, "optional_interop": [], "quarantined": []}
    
    if not os.path.exists(mods_dir):
        return result
    
    # ── Phase 0: Build index of all installed mod IDs ──
    # Map modId -> jar filename for everything in mods/ and mods/clientonly/
    # Also track JiJ-provided mod IDs (embedded in JARs via META-INF/jarjar/)
    installed_mod_ids = {}  # modId -> [jar_filename, ...]
    jij_provided = set()    # modIds provided via Jar-in-Jar (don't need fetching)
    dirs_to_scan = [mods_dir]
    if os.path.isdir(clientonly_dir):
        dirs_to_scan.append(clientonly_dir)
    
    for scan_dir in dirs_to_scan:
        for fn in os.listdir(scan_dir):
            if not fn.endswith('.jar') or not os.path.isfile(os.path.join(scan_dir, fn)):
                continue
            jar_path = os.path.join(scan_dir, fn)
            try:
                with zipfile.ZipFile(jar_path, 'r') as zf:
                    # Index the mod's own ID(s)
                    names = zf.namelist()
                    toml_file = None
                    if 'META-INF/neoforge.mods.toml' in names:
                        toml_file = 'META-INF/neoforge.mods.toml'
                    elif 'META-INF/mods.toml' in names:
                        toml_file = 'META-INF/mods.toml'
                    if toml_file:
                        raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                        toml_data = tomllib.loads(raw)
                        for mod_entry in toml_data.get("mods", []):
                            mid = mod_entry.get("modId", "").lower()
                            if mid:
                                installed_mod_ids.setdefault(mid, []).append(fn)
                    
                    # Scan JiJ metadata — embedded JARs provide modIds that don't
                    # need to be fetched separately.  NeoForge extracts these at load time.
                    if 'META-INF/jarjar/metadata.json' in names:
                        try:
                            jij_raw = zf.read('META-INF/jarjar/metadata.json').decode('utf-8', errors='ignore')
                            jij_data = json.loads(jij_raw)
                            for jij_entry in jij_data.get("jars", []):
                                jij_path = jij_entry.get("path", "")
                                # Read the nested JAR's manifest to get its modId
                                if jij_path and jij_path in names:
                                    try:
                                        nested_data = zf.read(jij_path)
                                        import io
                                        with zipfile.ZipFile(io.BytesIO(nested_data), 'r') as nested_zf:
                                            nested_names = nested_zf.namelist()
                                            nested_toml = None
                                            if 'META-INF/neoforge.mods.toml' in nested_names:
                                                nested_toml = 'META-INF/neoforge.mods.toml'
                                            elif 'META-INF/mods.toml' in nested_names:
                                                nested_toml = 'META-INF/mods.toml'
                                            if nested_toml:
                                                nraw = nested_zf.read(nested_toml).decode('utf-8', errors='ignore')
                                                ndata = tomllib.loads(nraw)
                                                for nmod in ndata.get("mods", []):
                                                    nmid = nmod.get("modId", "").lower()
                                                    if nmid:
                                                        jij_provided.add(nmid)
                                                        installed_mod_ids.setdefault(nmid, []).append(f"JiJ:{fn}")
                                    except Exception:
                                        pass
                                # Fallback: infer modId from JiJ artifact name
                                artifact = jij_entry.get("identifier", {}).get("artifact", "")
                                if artifact:
                                    # "lambdynlights-runtime-neoforge" -> try "lambdynlights_runtime"
                                    # Strip loader suffixes and convert dashes to underscores
                                    art_clean = artifact.lower()
                                    for suffix in ["-neoforge", "-forge", "-fabric", "-quilt"]:
                                        art_clean = art_clean.removesuffix(suffix)
                                    art_id = art_clean.replace("-", "_")
                                    jij_provided.add(art_id)
                                    installed_mod_ids.setdefault(art_id, []).append(f"JiJ:{fn}")
                        except Exception:
                            pass
            except Exception:
                continue
    
    # Always-present mods that don't need fetching (provided by loader/game itself)
    BUILTIN_MODS = {
        "neoforge", "forge", "minecraft", "java", "fml", "fabricloader", 
        "quilt_loader", "javafml", "lowcodefml", "mixin", "mixinextras",
    }
    
    # Known language providers (mods that provide language runtime support)
    # These are declared via modLoader field, NOT in [[dependencies]]
    KNOWN_LANGUAGE_PROVIDERS = {
        "kotori_scala": "scalable-cats-force",      # Scala language provider
        "kotlinforforge": "kotlinforforge",          # Kotlin language provider
        "kotlin": "kotlinforforge",                  # Alternate Kotlin provider ID
        "scalacats": "scalable-cats-force",          # Alternate Scala provider
        "scala": "scalable-cats-force",              # Alternate Scala provider
    }
    
    # Java class file version mapping
    # Used to detect mods compiled for newer Java than server is running
    JAVA_CLASS_VERSIONS = {
        52: "8", 53: "9", 54: "10", 55: "11", 56: "12", 57: "13", 58: "14",
        59: "15", 60: "16", 61: "17", 62: "18", 63: "19", 64: "20",
        65: "21", 66: "22", 67: "23", 68: "24", 69: "25",
    }
    
    # Loader-incompatible deps - skip these to avoid downloading wrong mods
    # NeoForge/Forge server should not try to fetch Fabric deps, and vice versa
    # Using pattern matching to catch all fabric-* variants
    def _is_loader_incompatible(dep_id, loader_name):
        dep_lower = dep_id.lower()
        if loader_name in ("neoforge", "forge"):
            # Skip any fabric-related dep
            if dep_lower.startswith("fabric") or "fabric" in dep_lower:
                return True
            if dep_lower in ("quilt_loader", "quiltloader"):
                return True
        elif loader_name == "fabric":
            # Skip forge/neoforge deps
            if dep_lower in ("neoforge", "forge", "fml", "javafml"):
                return True
        return False
    
    incompatible_deps = set()  # Will be checked dynamically
    
    log_event("PREFLIGHT", f"Scanning {len(installed_mod_ids)} installed mods for missing dependencies ({len(jij_provided)} JiJ-provided)...")
    
    # ── Phase 1: Extract all required AND optional deps from all installed JARs ──
    # {dep_modId: set of jar filenames that require it}
    # Only process [[dependencies.X]] sections where X is a mod declared in the
    # same JAR.  This avoids phantom deps (e.g. xaerominimap.jar declaring deps
    # for xaerobetterpvp which isn't installed).
    required_deps = {}  
    optional_deps = {}  # {dep_modId: set of jar filenames that optionally want it}
    
    for scan_dir in dirs_to_scan:
        for fn in os.listdir(scan_dir):
            if not fn.endswith('.jar') or not os.path.isfile(os.path.join(scan_dir, fn)):
                continue
            jar_path = os.path.join(scan_dir, fn)
            try:
                with zipfile.ZipFile(jar_path, 'r') as zf:
                    names = zf.namelist()
                    toml_file = None
                    if 'META-INF/neoforge.mods.toml' in names:
                        toml_file = 'META-INF/neoforge.mods.toml'
                    elif 'META-INF/mods.toml' in names:
                        toml_file = 'META-INF/mods.toml'
                    
                    if toml_file:
                        raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                        toml_data = tomllib.loads(raw)
                        
                        # Check for language provider declaration (modLoader field)
                        # This is NOT a normal dependency - it's declared at the top of the file
                        # Example: modLoader = "kotori_scala" (needs Scala runtime)
                        mod_loader = toml_data.get("modLoader", "").lower()
                        if mod_loader and mod_loader not in ("javafml", "lowcodefml", "java"):
                            # This mod needs a language provider
                            if mod_loader in KNOWN_LANGUAGE_PROVIDERS:
                                provider_slug = KNOWN_LANGUAGE_PROVIDERS[mod_loader]
                                required_deps.setdefault(provider_slug, set()).add(fn)
                                log_event("PREFLIGHT", f"Language provider detected: {fn} needs '{mod_loader}' -> will fetch '{provider_slug}'")
                            else:
                                # Unknown language provider - log warning
                                log_event("PREFLIGHT", f"WARNING: Unknown language provider '{mod_loader}' required by {fn}")
                                required_deps.setdefault(mod_loader, set()).add(fn)
                        
                        # Collect ALL mod IDs declared in this JAR (not just the first)
                        mods_list = toml_data.get("mods", [])
                        jar_mod_ids = set()
                        for mod_entry in mods_list:
                            mid = mod_entry.get("modId", "").lower()
                            if mid:
                                jar_mod_ids.add(mid)
                        
                        # Only process [[dependencies.X]] where X is in jar_mod_ids
                        all_deps = toml_data.get("dependencies", {})
                        if isinstance(all_deps, dict):
                            for dep_parent, dep_list in all_deps.items():
                                # Skip dep sections for mods not declared in THIS jar
                                if dep_parent.lower() not in jar_mod_ids:
                                    continue
                                if not isinstance(dep_list, list):
                                    continue
                                for dep in dep_list:
                                    if not isinstance(dep, dict):
                                        continue
                                    dep_type = dep.get("type", "required").lower()
                                    dep_mod_id = dep.get("modId", "").lower()
                                    if not dep_mod_id or dep_mod_id in BUILTIN_MODS or dep_mod_id in jar_mod_ids:
                                        continue
                                    
                                    if dep_type == "required":
                                        required_deps.setdefault(dep_mod_id, set()).add(fn)
                                    elif dep_type == "optional":
                                        optional_deps.setdefault(dep_mod_id, set()).add(fn)
                    
                    # Also check fabric.mod.json
                    if 'fabric.mod.json' in names:
                        fabric_raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                        fabric_data = json.loads(fabric_raw)
                        for dep_id, dep_ver in fabric_data.get("depends", {}).items():
                            dep_id_lower = dep_id.lower()
                            # Skip builtin AND loader-incompatible deps
                            if dep_id_lower in BUILTIN_MODS or _is_loader_incompatible(dep_id_lower, loader_name):
                                continue
                            required_deps.setdefault(dep_id_lower, set()).add(fn)
            except Exception:
                continue
    
    # ── Phase 2: Check which deps are missing ──
    missing = {}  # dep_modId -> set of jar filenames that need it
    for dep_id, requesters in required_deps.items():
        # Skip builtin mods
        if dep_id in BUILTIN_MODS:
            continue
        # Skip loader-incompatible deps (e.g., fabric-api on neoforge server)
        if _is_loader_incompatible(dep_id, loader_name):
            continue
        if dep_id not in installed_mod_ids:
            missing[dep_id] = requesters
    
    # ── Phase 2.4: Check Java class file versions ──
    # Detect mods compiled for newer Java than server is running
    java_version = _get_java_version()
    java_major = int(java_version.split('.')[0]) if java_version else 21
    max_class_version = java_major + 44  # Java 8 = 52, Java 21 = 65, Java 22 = 66
    
    java_incompatible = []  # Mods that need newer Java
    
    for scan_dir in dirs_to_scan:
        for fn in os.listdir(scan_dir):
            if not fn.endswith('.jar') or not os.path.isfile(os.path.join(scan_dir, fn)):
                continue
            jar_path = os.path.join(scan_dir, fn)
            try:
                with zipfile.ZipFile(jar_path, 'r') as zf:
                    # Check a few class files for version
                    for entry in zf.namelist():
                        if entry.endswith('.class'):
                            data = zf.read(entry)
                            if len(data) >= 8:
                                # Class file version is bytes 6-7 (big-endian)
                                minor = (data[4] << 8) | data[5]
                                major = (data[6] << 8) | data[7]
                                if major > max_class_version:
                                    needed_java = JAVA_CLASS_VERSIONS.get(major, f"unknown({major})")
                                    java_incompatible.append((fn, needed_java))
                                    log_event("PREFLIGHT", f"Java version mismatch: {fn} needs Java {needed_java} (server has Java {java_version})")
                                break  # Only check first class file
            except Exception:
                continue
    
    # Quarantine mods that need newer Java
    java_quarantined_count = 0
    java_needed_versions = {}  # {version: count}
    
    for fn, needed_java in java_incompatible:
        quarantined = _quarantine_mod(mods_dir, fn, f"Requires Java {needed_java} (server has Java {java_version})")
        if quarantined:
            result["quarantined"].append(fn)
            java_quarantined_count += 1
            java_needed_versions[needed_java] = java_needed_versions.get(needed_java, 0) + 1
    
    # Auto-upgrade JDK if 90%+ of mods need the same newer version
    total_mods = len(installed_mod_ids)
    if java_quarantined_count > 0 and total_mods > 0:
        # Find the most common needed version
        most_common_version = max(java_needed_versions.items(), key=lambda x: x[1]) if java_needed_versions else (None, 0)
        needed_ver, needed_count = most_common_version
        
        if needed_ver:
            percentage = (needed_count / total_mods) * 100
            if percentage >= 90:
                log_event("PREFLIGHT", f"AUTO_JDK_UPGRADE: {percentage:.0f}% of mods need Java {needed_ver}, auto-upgrading...")
                
                # Find package for this version
                available_jdks = _check_jdk_upgrade_available()
                matching_jdk = next((j for j in available_jdks if j["version"] == needed_ver), None)
                
                if matching_jdk:
                    if _install_jdk(matching_jdk["package"]):
                        _set_default_java(needed_ver)
                        log_event("PREFLIGHT", f"Auto-installed {matching_jdk['package']} and set as default")
                        
                        # Unquarantine all Java-incompatible mods
                        import shutil
                        for fn, _ in java_incompatible:
                            src = os.path.join(quarantine_dir, fn)
                            dst = os.path.join(mods_dir, fn)
                            reason_file = f"{src}.reason.txt"
                            try:
                                shutil.move(src, dst)
                                if os.path.exists(reason_file):
                                    os.remove(reason_file)
                            except:
                                pass
                        log_event("PREFLIGHT", f"Restored {java_quarantined_count} mods after auto JDK upgrade")
                    else:
                        log_event("PREFLIGHT", f"Failed to auto-install JDK {needed_ver}")
    
    # ── Phase 2.5: Re-evaluate quarantined mods ──
    # Mods quarantined for "missing dep" or "Mod conflict (mixin)" may be safe to
    # restore now.  For "missing dep" reasons, check if the dep is now installed
    # or about to be fetched.  For mixin conflicts that were likely false positives
    # (e.g. caused by a client-only mod crash), restore them since we need them.
    import shutil
    if os.path.isdir(quarantine_dir):
        for qfn in list(os.listdir(quarantine_dir)):
            if not qfn.endswith('.jar'):
                continue
            reason_file = os.path.join(quarantine_dir, f"{qfn}.reason.txt")
            reason_text = ""
            if os.path.exists(reason_file):
                try:
                    with open(reason_file) as rf:
                        reason_text = rf.read()
                except Exception:
                    pass
            
            # Skip mods quarantined for client-only crashes — those are correctly quarantined
            if "client-only" in reason_text.lower() or "noclassdeffounderror" in reason_text.lower():
                continue
            # Skip corrupt JARs
            if "corrupt" in reason_text.lower() or "invalid jar" in reason_text.lower() or "not a jar" in reason_text.lower():
                continue
            
            qjar = os.path.join(quarantine_dir, qfn)
            qmanifest = _parse_mod_manifest(qjar)
            q_mod_id = qmanifest.get("mod_id", "").lower() if qmanifest else ""
            
            if not q_mod_id:
                continue
            
            # Check if any installed mod needs this quarantined mod as a dep,
            # OR if it was quarantined for a missing dep that's now available
            needed_as_dep = q_mod_id in required_deps or q_mod_id in missing
            
            dep_now_available = False
            if "missing dep" in reason_text.lower():
                # Extract the dep name from the reason text
                import re as _re
                dep_match = _re.search(r"missing dep '(\w+)'", reason_text.lower())
                if dep_match:
                    needed_dep = dep_match.group(1)
                    dep_now_available = (needed_dep in installed_mod_ids 
                                        or needed_dep in missing)  # will be fetched
            
            if needed_as_dep or dep_now_available:
                dst = os.path.join(mods_dir, qfn)
                try:
                    shutil.move(qjar, dst)
                    if os.path.exists(reason_file):
                        os.remove(reason_file)
                    log_event("PREFLIGHT", f"Restored {qfn} from quarantine (reason was: {reason_text.split(chr(10))[1].strip() if chr(10) in reason_text else 'unknown'})")
                    installed_mod_ids.setdefault(q_mod_id, []).append(qfn)
                    # Remove from missing if it was there
                    if q_mod_id in missing:
                        del missing[q_mod_id]
                except Exception as e:
                    log_event("PREFLIGHT", f"Failed to restore {qfn}: {e}")
    
    # Re-check missing after quarantine restoration
    missing = {dep_id: req for dep_id, req in missing.items() if dep_id not in installed_mod_ids}
    
    if not missing:
        log_event("PREFLIGHT", "All dependencies satisfied (some restored from quarantine)")
    
    log_event("PREFLIGHT", f"Found {len(missing)} missing dependencies:")
    for dep_id, requesters in missing.items():
        req_str = ', '.join(sorted(requesters)[:3])
        log_event("PREFLIGHT", f"  {dep_id} (required by: {req_str})")
    
    # ── Phase 3: Try to fetch missing deps ──
    fetched = 0
    fetch_failed = {}  # dep_id -> reason
    
    # Process deps in multiple rounds to handle transitive deps
    MAX_ROUNDS = 3
    for round_num in range(MAX_ROUNDS):
        if not missing:
            break
        
        round_fetched = 0
        still_missing = {}
        
        for dep_id, requesters in missing.items():
            # Check quarantine one more time (for transitive deps found in later rounds)
            restored = False
            if os.path.isdir(quarantine_dir):
                for qfn in list(os.listdir(quarantine_dir)):
                    if not qfn.endswith('.jar'):
                        continue
                    qjar = os.path.join(quarantine_dir, qfn)
                    if not os.path.isfile(qjar):
                        continue
                    qmanifest = _parse_mod_manifest(qjar)
                    q_mod = (qmanifest.get("mod_id") or "") if qmanifest else ""
                    if q_mod.lower() == dep_id:
                        dst = os.path.join(mods_dir, qfn)
                        try:
                            shutil.move(qjar, dst)
                            reason_file = os.path.join(quarantine_dir, f"{qfn}.reason.txt")
                            if os.path.exists(reason_file):
                                os.remove(reason_file)
                            log_event("PREFLIGHT", f"Restored {qfn} from quarantine (required by {', '.join(sorted(requesters)[:2])})")
                            installed_mod_ids.setdefault(dep_id, []).append(qfn)
                            fetched += 1
                            round_fetched += 1
                            restored = True
                        except Exception:
                            pass
                        break
            
            if restored:
                continue
            
            # Try to download from Modrinth/CurseForge
            log_event("PREFLIGHT", f"Fetching missing dep: {dep_id}")
            if _search_and_download_dep(dep_id, mods_dir, mc_version, loader_name):
                fetched += 1
                round_fetched += 1
                installed_mod_ids.setdefault(dep_id, []).append(f"<fetched:{dep_id}>")
            else:
                still_missing[dep_id] = requesters
                fetch_failed[dep_id] = requesters
        
        missing = still_missing
        
        if round_fetched == 0:
            break  # No progress, stop
        
        # Re-scan newly downloaded/restored JARs for THEIR deps (transitive resolution)
        if round_num < MAX_ROUNDS - 1 and round_fetched > 0:
            new_missing = {}
            for fn in os.listdir(mods_dir):
                if not fn.endswith('.jar') or not os.path.isfile(os.path.join(mods_dir, fn)):
                    continue
                jar_path = os.path.join(mods_dir, fn)
                try:
                    with zipfile.ZipFile(jar_path, 'r') as zf:
                        names = zf.namelist()
                        toml_file = None
                        if 'META-INF/neoforge.mods.toml' in names:
                            toml_file = 'META-INF/neoforge.mods.toml'
                        elif 'META-INF/mods.toml' in names:
                            toml_file = 'META-INF/mods.toml'
                        if toml_file:
                            raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                            toml_data = tomllib.loads(raw)
                            # Get this JAR's own mod IDs
                            jar_mod_ids = set()
                            for mod_entry in toml_data.get("mods", []):
                                mid = mod_entry.get("modId", "").lower()
                                if mid:
                                    jar_mod_ids.add(mid)
                            all_deps = toml_data.get("dependencies", {})
                            if isinstance(all_deps, dict):
                                for dep_parent, dep_list in all_deps.items():
                                    if dep_parent.lower() not in jar_mod_ids:
                                        continue
                                    if not isinstance(dep_list, list):
                                        continue
                                    for dep in dep_list:
                                        if not isinstance(dep, dict):
                                            continue
                                        dep_type = dep.get("type", "required").lower()
                                        dep_mod_id = dep.get("modId", "").lower()
                                        if (dep_type == "required" and dep_mod_id not in BUILTIN_MODS
                                                and dep_mod_id not in jar_mod_ids):
                                            if dep_mod_id not in installed_mod_ids and dep_mod_id not in missing:
                                                new_missing.setdefault(dep_mod_id, set()).add(fn)
                except Exception:
                    continue
            if new_missing:
                log_event("PREFLIGHT", f"Round {round_num + 2}: found {len(new_missing)} transitive deps to resolve")
                missing = new_missing
    
    # ── Phase 4: Quarantine mods with unresolvable dependencies (chain rollback) ──
    if fetch_failed:
        log_event("PREFLIGHT", f"{len(fetch_failed)} dependencies could not be found - rolling back dependency chains:")
        
        # Build reverse dependency map: mod -> what deps it needs
        mod_to_deps = {}
        for dep_id, requesters in required_deps.items():
            for req in requesters:
                mod_to_deps.setdefault(req, set()).add(dep_id)
        
        # For each failed dep, find the full chain and quarantine all affected mods
        for dep_id, requesters in fetch_failed.items():
            req_list = sorted(requesters)[:5]
            
            # Find root cause - why is this dep unavailable?
            dep_reason = f"Not available for MC {mc_version}/{loader_name}"
            
            # Check if it's a version-specific issue
            dep_lower = dep_id.lower()
            if dep_lower in ["create", "create-fabric", "createforge"]:
                dep_reason = f"Create mod only supports MC 1.18.2, 1.19.2, 1.20.1, 1.21.1 - not {mc_version}"
            elif dep_lower in ["easy_npc"]:
                dep_reason = f"Easy NPC not updated for MC {mc_version}"
            elif dep_lower.startswith("ftb"):
                dep_reason = f"FTB mods may not support MC {mc_version} yet"
            
            log_event("PREFLIGHT", f"  Missing: {dep_id} - {dep_reason}")
            log_event("PREFLIGHT", f"    Needed by: {', '.join(req_list)}")
            
            # Quarantine all mods that directly need this dep
            for requester in requesters:
                if requester.startswith("<"):
                    continue
                if not requester.endswith(".jar"):
                    requester = requester + ".jar" if not requester.endswith(".jar") else requester
                
                # Check if file exists before quarantining
                requester_path = os.path.join(mods_dir, requester)
                if not os.path.exists(requester_path):
                    # Try to find it by partial name
                    for fn in os.listdir(mods_dir):
                        if fn.lower().startswith(dep_id.replace("_", "").replace("-", "")[:8]) and fn.endswith(".jar"):
                            requester_path = os.path.join(mods_dir, fn)
                            requester = fn
                            break
                
                if os.path.exists(requester_path):
                    # Build chain explanation
                    chain_reason = f"Requires '{dep_id}' which is unavailable ({dep_reason})"
                    quarantined = _quarantine_mod(mods_dir, requester, chain_reason)
                    if quarantined:
                        log_event("PREFLIGHT", f"    Quarantined {requester}")
                        result["quarantined"].append(requester)
    
    if fetched > 0:
        log_event("PREFLIGHT", f"Pre-flight fetched/restored {fetched} dependencies")
    
    # ── Phase 5: Optional dependency interop alerts ──
    # Report when 2+ mods share the same optional dep (installing it improves compatibility)
    for dep_id, requesters in optional_deps.items():
        if len(requesters) >= 2 and dep_id not in installed_mod_ids:
            req_list = sorted(requesters)[:5]
            result["optional_interop"].append({
                "dep_id": dep_id,
                "requested_by": req_list,
                "count": len(requesters)
            })
            log_event("PREFLIGHT", f"OPTIONAL INTEROP: {dep_id} wanted by {len(requesters)} mods: {', '.join(req_list)}")
    
    if result["optional_interop"]:
        log_event("PREFLIGHT", f"Found {len(result['optional_interop'])} shared optional dependencies - installing these may improve mod compatibility")
    
    result["fetched"] = fetched
    return result


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
    MAX_RESTART_ATTEMPTS = cfg.get("max_restart_attempts", 25)
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
    
    # ---- PRE-LAUNCH: sort client-only mods, check compatibility ----
    try:
        sort_mods_by_type(mods_dir)
    except Exception as e:
        log_event("SERVER_START", f"Mod sort failed (non-fatal): {e}")
    
    try:
        compat = preflight_mod_compatibility_check(mods_dir, cfg)
        if compat["quarantined"]:
            log_event("SERVER_START", f"Quarantined {len(compat['quarantined'])} incompatible mod(s) before launch")
            # Regenerate mod ZIP since mods changed
            create_mod_zip(mods_dir)
    except Exception as e:
        log_event("SERVER_START", f"Compatibility check failed (non-fatal): {e}")
    
    # ---- PRE-FLIGHT: check deps before launching ----
    try:
        preflight_result = _preflight_dep_check(cfg)
        if preflight_result["fetched"] > 0:
            log_event("SERVER_START", f"Pre-flight fetched {preflight_result['fetched']} missing deps")
            # Regenerate mod ZIP since new mods were fetched
            create_mod_zip(mods_dir)
            create_install_scripts(mods_dir, cfg)
        if preflight_result["optional_interop"]:
            log_event("SERVER_START", f"OPTIONAL DEP INTEROP: {len(preflight_result['optional_interop'])} shared optional deps found (installing may improve compatibility)")
            for interop in preflight_result["optional_interop"][:5]:
                log_event("SERVER_START", f"  - {interop['dep_id']} (wanted by {interop['count']} mods)")
        if preflight_result.get("quarantined"):
            log_event("SERVER_START", f"Pre-flight quarantined {len(preflight_result['quarantined'])} mods with unresolvable deps")
    except Exception as e:
        log_event("SERVER_START", f"Pre-flight check failed (non-fatal): {e}")
    
    # Ensure quarantine dir exists
    os.makedirs(os.path.join(mods_dir, "quarantine"), exist_ok=True)
    
    restart_count = 0
    crash_history = {}  # Track {mod_id: crash_count} across restarts
    tmux_socket = f"/tmp/tmux-{os.getuid()}/default"
    stopped_flag = os.path.join(CWD, ".mc_stopped")
    reset_counter_flag = os.path.join(CWD, ".mc_reset_counter")
    
    while restart_count <= MAX_RESTART_ATTEMPTS:
        # Check for reset counter flag (from dashboard start button)
        if os.path.exists(reset_counter_flag):
            os.remove(reset_counter_flag)
            restart_count = 0
            crash_history = {}
            log_event("SERVER_START", "Restart counter reset via dashboard")
        
        # Check if MC was intentionally stopped via dashboard
        if os.path.exists(stopped_flag):
            log_event("SERVER_STOPPED", "MC was stopped via dashboard, waiting for start command...")
            # Wait for start command (flag to be removed) or service stop
            for _ in range(3600):  # Wait up to 1 hour
                if not os.path.exists(stopped_flag):
                    break
                time.sleep(1)
            else:
                log_event("SERVER_STOPPED", "No start command received for 1 hour, exiting")
                return True
            # Flag removed, continue to start MC
            log_event("SERVER_START", "Start command received, starting MC...")
        
        # Check if tmux session already exists (leftover from previous run)
        existing = run(f"tmux -S {tmux_socket} has-session -t MC 2>/dev/null")
        if existing.returncode == 0:
            log_event("SERVER_START", "Existing tmux session 'MC' found, killing it first")
            run(f"tmux -S {tmux_socket} kill-session -t MC 2>/dev/null")
            time.sleep(2)
        
        # Record log position before start so we can read just the new output
        log_size_before = 0
        try:
            if os.path.exists(LOG_FILE):
                log_size_before = os.path.getsize(LOG_FILE)
        except Exception:
            pass
        
        # Launch in tmux with shared socket for visibility
        socket_dir = f"/tmp/tmux-{os.getuid()}"
        os.makedirs(socket_dir, exist_ok=True)
        
        tmux_cmd = f"cd '{CWD}' && stdbuf -oL -eL {java_cmd}"
        result = run(f"tmux -S {tmux_socket} new-session -d -s MC \"{tmux_cmd}\"")
        if result.returncode != 0:
            log_event("SERVER_ERROR", f"Failed to start tmux session: {result.stderr}")
            return False
        
        # Make socket dir accessible (700 for security)
        try:
            os.chmod(socket_dir, 0o700)
            os.chmod(tmux_socket, 0o700)
        except Exception:
            pass
        
        run(f"tmux -S {tmux_socket} pipe-pane -o -t MC 'cat >> {LOG_FILE}'")
        
        if restart_count == 0:
            log_event("SERVER_RUNNING", f"Server started in tmux session 'MC'")
        else:
            log_event("SERVER_RUNNING", f"Server restarted (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})")
        
        # Monitor loop — wait for server to stop (with timeout)
        monitor_start = time.time()
        while True:
            check = run(f"tmux -S {tmux_socket} has-session -t MC 2>/dev/null")
            if check.returncode != 0:
                break
            if time.time() - monitor_start > MONITOR_TIMEOUT:
                log_event("SERVER_TIMEOUT", f"Server tmux session alive for >{MONITOR_TIMEOUT}s without crash — assuming hung, killing")
                run(f"tmux -S {tmux_socket} kill-session -t MC 2>/dev/null")
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
            # If stopped via dashboard, wait for start command instead of exiting
            if os.path.exists(stopped_flag):
                log_event("SERVER_STOPPED", "Clean shutdown via dashboard, waiting for start command...")
                for _ in range(3600):
                    if not os.path.exists(stopped_flag):
                        log_event("SERVER_START", "Start command received, restarting MC...")
                        break
                    time.sleep(1)
                else:
                    log_event("SERVER_STOPPED", "No start command for 1 hour, exiting")
                    return True
                continue  # Restart MC
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
    tmux_socket = f"/tmp/tmux-{os.getuid()}/default"
    cmd_safe = cmd.replace("'", "'\\''")
    result = run(f"tmux -S {tmux_socket} send-keys -t MC '{cmd_safe}' Enter")
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

def broadcast_mod_update(cfg, mod_count=None):
    """Send a clickable tellraw message to all online players with the mod installer link.
    
    Players click the gold link in chat -> Minecraft shows 'Open URL?' confirmation ->
    browser opens -> browser downloads install-mods.bat -> player double-clicks it -> done.
    """
    server_ip = get_server_hostname(cfg)
    http_port = int(cfg.get("http_port", 8000))
    
    bat_url = f"http://{server_ip}:{http_port}/download/install-mods.bat"
    
    # Build the tellraw JSON components
    # Line 1: Header
    header_cmd = 'tellraw @a ["",{"text":"=============================","color":"gold"}]'
    
    # Line 2: Update message
    if mod_count:
        update_text = f"Server mods updated! ({mod_count} mods)"
    else:
        update_text = "Server mods have been updated!"
    update_cmd = f'tellraw @a ["",{{"text":"  {update_text}","color":"yellow","bold":true}}]'
    
    # Line 3: Clickable download link
    link_cmd = (
        'tellraw @a ["",{"text":"  "},{"text":"[CLICK HERE TO UPDATE]",'
        '"color":"green","bold":true,"underlined":true,'
        f'"clickEvent":{{"action":"open_url","value":"{bat_url}"}},'
        '"hoverEvent":{"action":"show_text","value":"Download mod installer (.bat)"}'
        '}]'
    )
    
    # Line 4: Instructions
    instr_cmd = 'tellraw @a ["",{"text":"  Save the .bat file and double-click it!","color":"aqua"}]'
    
    # Line 5: Footer
    footer_cmd = 'tellraw @a ["",{"text":"=============================","color":"gold"}]'
    
    # Send all lines via RCON
    success = True
    for cmd in [header_cmd, update_cmd, link_cmd, instr_cmd, footer_cmd]:
        if not send_rcon_command(cfg, cmd):
            success = False
            break
    
    if success:
        log_event("BROADCAST", f"Mod update notification sent to all players (url={bat_url})")
    else:
        log_event("BROADCAST_ERROR", "Failed to send tellraw broadcast (RCON error)")
    
    return success

def show_mod_list_on_join(player, cfg):
    """Display mod list to player on join (respects nag_show_mod_list_on_join config)"""
    if not cfg.get("nag_show_mod_list_on_join", True):
        return
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
    """Trigger on player join event - show welcome message"""
    def __init__(self):
        super().__init__("PlayerJoin")
    
    def should_trigger(self, event_data):
        return "joined the game" in event_data.get("raw_line", "")
    
    def on_trigger(self, event_data, cfg):
        player = event_data.get("player", "Unknown")
        if self.debounce_check(player, seconds=30):
            send_chat_message(f"Welcome {player}! Type 'mods' to see available mods.")
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


class ModsCommandHook(EventHook):
    """Trigger when player types 'mods' to show the mod list"""
    def __init__(self):
        super().__init__("ModsCommand")
    
    def should_trigger(self, event_data):
        msg = event_data.get("message") or ""
        return msg.lower().strip() == "mods"
    
    def on_trigger(self, event_data, cfg):
        player = event_data.get("player", "Unknown")
        
        if self.debounce_check(f"mods_{player}", seconds=10):
            show_mod_list_on_join(player, cfg)
            log_event("HOOK_MODS_COMMAND", f"Player {player} requested mod list")
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
        ModsCommandHook(),
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

def _cf_search_url(mc_version, loader, page=1, page_size=50, sort="downloads"):
    """Build CurseForge search URL with loader filter, version, pagination, and sort.
    
    Uses the search endpoint which supports pageSize=50 and gameVersionTypeId
    for proper loader filtering (NeoForge=6, Forge=1, Fabric=4, Quilt=5).
    
    sort options: "downloads", "popularity", "updated", "name", "author", "created"
    """
    loader_id = CF_LOADER_IDS.get(loader.lower(), 6)
    sort_param = CF_SORT_OPTIONS.get(sort, "total+downloads")
    base = "https://www.curseforge.com/minecraft/search"
    return (f"{base}?page={page}&pageSize={page_size}&sortBy={sort_param}"
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
    
    Also attempts to extract file_id from download links if present.
    
    Returns dict: {"required": [{name, slug, type, file_id}], "optional": [{name, slug, type, file_id}]}
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
                
                dep_file_id = ""
                dl_link = card.query_selector("a[href*='/download/']")
                if dl_link:
                    dl_href = dl_link.get_attribute("href") or ""
                    file_match = re.search(r'/download/(\d+)', dl_href)
                    if file_match:
                        dep_file_id = file_match.group(1)
                
                dep_info = {"name": dep_name, "slug": dep_slug, "type": dep_type, "file_id": dep_file_id}
                
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

def fetch_curseforge_mods_scraper(mc_version, loader, limit=100, scrape_deps=True, sort="downloads"):
    """
    Scrape CurseForge search pages using Playwright stealth headless browser.
    
    Uses the search URL with pageSize=50, gameVersionTypeId for loader filtering.
    Paginates to collect up to `limit` mods.
    
    When scrape_deps=True, also visits each mod's /relations/dependencies page
    to collect required + optional dependencies.
    
    Results are cached to disk (6h TTL, keyed by sort).
    
    Args:
        mc_version: e.g. "1.21.1"
        loader: e.g. "neoforge"
        limit: max mods to collect (default 100)
        scrape_deps: whether to scrape dependency pages (default True)
        sort: sort method — "downloads", "popularity", "updated", "name", "author", "created"
    
    Returns:
        List of mod dicts with {name, slug, description, downloads, file_id,
        download_href, author, source, deps_required, deps_optional}
    """
    if not PLAYWRIGHT_AVAILABLE:
        log.error("Playwright not installed — cannot scrape CurseForge. "
                  "Install: pip3 install --break-system-packages playwright playwright-stealth && "
                  "python3 -m playwright install chromium")
        return []
    
    # Check cache first (6 hour TTL, keyed by sort)
    sort_suffix = f"_{sort}" if sort != "downloads" else ""
    cache_file = os.path.join(CWD, f"curseforge_cache_{mc_version}_{loader}{sort_suffix}.json")
    if os.path.exists(cache_file):
        try:
            cache_age = time.time() - os.path.getmtime(cache_file)
            if cache_age < 6 * 3600:
                with open(cache_file) as f:
                    cached = json.load(f)
                if cached:
                    log.info(f"CurseForge: loaded {len(cached)} mods from cache ({cache_age/3600:.1f}h old, sort={sort})")
                    return cached[:limit]
        except Exception as e:
            log.warning(f"CurseForge: cache read error: {e}")
    
    log.info(f"CurseForge: scraping top {limit} mods for MC {mc_version} ({loader}, sort={sort})...")
    
    all_mods = []
    page_size = 50
    pages_needed = (limit + page_size - 1) // page_size
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    timezone = random.choice(CF_TIMEZONES)
    
    try:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--disable-background-networking",
                    "--no-first-run",
                    "--disable-extensions",
                    "--disable-sync",
                    "--mute-audio",
                    "--disable-translate",
                    "--force-color-profile=srgb",
                ]
            )
            context = browser.new_context(
                user_agent=ua,
                viewport=viewport,
                locale=locale,
                timezone_id=timezone,
                color_scheme="dark" if random.random() > 0.5 else "light",
            )
            
            context.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": f"{locale},en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
            
            page = context.new_page()
            
            # First visit homepage to establish cookies
            page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.0, 4.0))
            
            # ---- Phase 1: Scrape search pages ----
            for page_num in range(1, pages_needed + 1):
                if len(all_mods) >= limit:
                    break
                
                _cf_rate_limit()
                url = _cf_search_url(mc_version, loader, page=page_num, page_size=page_size, sort=sort)
                log.info(f"CurseForge: scraping page {page_num}/{pages_needed} ({page_size}/page)")
                
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(random.uniform(3.0, 6.0))
                    
                    title = page.title()
                    if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking"]):
                        log.warning(f"CurseForge: Cloudflare challenge on page {page_num}, waiting...")
                        time.sleep(random.uniform(10.0, 20.0))
                        page.wait_for_load_state("networkidle", timeout=45000)
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
                        time.sleep(random.uniform(2.5, 5.0))
                
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
                    _cf_rate_limit()
                    try:
                        deps = _scrape_cf_dependencies(page, slug)
                        mod["deps_required"] = deps.get("required", [])
                        mod["deps_optional"] = deps.get("optional", [])
                        if deps["required"] or deps["optional"]:
                            log.info(f"  [{i+1}/{len(all_mods)}] {mod['name']}: "
                                     f"{len(deps['required'])} req, {len(deps['optional'])} opt deps")
                        if (i + 1) % 10 == 0:
                            log.info(f"  ... {i+1}/{len(all_mods)} dep pages scraped")
                        time.sleep(random.uniform(1.5, 3.5))
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

def _cf_download_jar(url, mods_dir, slug, file_id, mod_name, headers=None):
    """Helper: download a JAR from a CDN URL (no Cloudflare). Returns 'downloaded', 'exists', or False."""
    _cf_rate_limit()
    if headers is None:
        headers = _get_cf_headers()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as response:
            final_url = response.url
            filename = os.path.basename(final_url.split("?")[0])
            if not filename.endswith(".jar"):
                filename = f"{slug}-{file_id}.jar"
            
            file_path = os.path.join(mods_dir, filename)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                log.info(f"CurseForge: {filename} already exists, skipping")
                return "exists"
            
            data = response.read()
            if len(data) < 1000 or data[:2] != b'PK':
                return False
            with open(file_path, "wb") as f:
                f.write(data)
            log.info(f"CurseForge: downloaded {filename} ({len(data)/1024:.0f} KB)")
            return "downloaded"
    except Exception as e:
        log.warning(f"CurseForge: CDN download failed for {mod_name}: {e}")
        return False


def _cf_download_playwright(slug, file_id, mods_dir, mod_name, mc_version=None, loader=None):
    """Download a JAR using Playwright browser to defeat Cloudflare java challenge.
    
    Now navigates to the mod's files page to find the correct file for the target MC version and loader.
    
    Returns: 'downloaded', 'exists', or False
    """
    if not PLAYWRIGHT_AVAILABLE:
        log.warning(f"CurseForge: Playwright not available, cannot download {mod_name}")
        return False
    
    _cf_rate_limit()
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    timezone = random.choice(CF_TIMEZONES)
    
    try:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(
                headless=True, 
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--no-first-run",
                    "--disable-extensions",
                    "--mute-audio",
                ]
            )
            context = browser.new_context(
                user_agent=ua,
                viewport=viewport,
                locale=locale,
                timezone_id=timezone,
                color_scheme="dark" if random.random() > 0.5 else "light",
            )
            
            context.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": f"{locale},en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
            
            page = context.new_page()
            
            # Simulate human-like mouse movements
            page.mouse.move(random.randint(0, viewport["width"]), random.randint(0, viewport["height"]))
            
            # First visit homepage to establish cookies
            page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 2.5))
            
            # If we have mc_version and loader, go to files page to find correct file
            actual_file_id = file_id
            if mc_version and loader:
                loader_id = CF_LOADER_IDS.get(loader.lower(), 6)
                files_url = f"https://www.curseforge.com/minecraft/mc-mods/{slug}/files?version={mc_version}&gameVersionTypeId={loader_id}"
                log.info(f"CurseForge: finding correct file for {mod_name} (MC {mc_version}, {loader})")
                
                page.goto(files_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2.0, 3.5))
                
                # Wait for Cloudflare challenge
                title = page.title()
                if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking", "cloudflare"]):
                    log.info("CurseForge: Cloudflare challenge detected, waiting...")
                    time.sleep(random.uniform(5.0, 10.0))
                    page.wait_for_load_state("networkidle", timeout=45000)
                
                # Find the first file row with download link
                file_rows = page.query_selector_all("tr.project-file, tr.file-row, tbody tr")
                found_file_id = None
                for row in file_rows[:20]:
                    try:
                        # Look for download link in this row
                        dl_link = row.query_selector("a.download-cta, a[data-href*='download']")
                        if dl_link:
                            href = dl_link.get_attribute("href") or ""
                            match = re.search(r'/download/(\d+)', href)
                            if match:
                                found_file_id = match.group(1)
                                # Verify this file is for our version (check row text)
                                row_text = row.inner_text().lower()
                                if mc_version.lower() in row_text or not any(v in row_text for v in ["1.20", "1.19", "1.18"]):
                                    break
                                else:
                                    found_file_id = None
                    except:
                        continue
                
                if found_file_id:
                    actual_file_id = found_file_id
                    log.info(f"CurseForge: found file_id {actual_file_id} for MC {mc_version}")
                else:
                    log.warning(f"CurseForge: no file found for {mod_name} matching MC {mc_version}, {loader}")
            
            # Now download using the correct file_id
            url = f"https://www.curseforge.com/minecraft/mc-mods/{slug}/download/{actual_file_id}"
            log.info(f"CurseForge: fetching {mod_name} via Playwright (file_id={actual_file_id})")
            
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for Cloudflare challenge
            title = page.title()
            if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking", "cloudflare"]):
                log.info("CurseForge: Cloudflare challenge detected, waiting...")
                time.sleep(random.uniform(2.0, 4.0))
                page.wait_for_load_state("networkidle", timeout=60000)
                page.mouse.move(random.randint(100, 800), random.randint(100, 600))
                time.sleep(random.uniform(0.5, 1.5))
            
            time.sleep(random.uniform(1.5, 3.0))
            
            # Get final redirect URL (CDN link)
            final_url = page.url
            filename = os.path.basename(final_url.split("?")[0])
            if not filename.endswith(".jar"):
                filename = f"{slug}-{actual_file_id}.jar"
            
            file_path = os.path.join(mods_dir, filename)
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                log.info(f"CurseForge: {filename} already exists")
                context.close()
                browser.close()
                return "exists"
            
            # Download using browser cookies
            cookies = context.cookies()
            cookie_header = "; ".join(f"{c.get('name','')}={c.get('value','')}" for c in cookies if c.get('name') and c.get('value'))
            headers = _get_cf_headers()
            headers["Cookie"] = cookie_header
            headers["Referer"] = url
            
            req = urllib.request.Request(final_url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                if len(data) < 1000 or data[:2] != b'PK':
                    log.warning(f"CurseForge: invalid JAR from {final_url}")
                    context.close()
                    browser.close()
                    return False
                with open(file_path, "wb") as f:
                    f.write(data)
            
            log.info(f"CurseForge: downloaded {filename} ({os.path.getsize(file_path)/1024:.0f} KB)")
            context.close()
            browser.close()
            return "downloaded"
            
    except Exception as e:
        log.warning(f"CurseForge: Playwright download failed for {mod_name}: {e}")
        return False


def download_mod_from_curseforge(mod_info, mods_dir, mc_version, loader):
    """Download a mod JAR from CurseForge using Playwright to defeat Cloudflare.
    Returns: 'downloaded', 'exists', or False
    """
    mod_name = mod_info.get("name", "unknown")
    slug = mod_info.get("slug", "")
    file_id = str(mod_info.get("file_id", ""))
    
    if not slug:
        log.warning(f"CurseForge download: no slug for {mod_name}")
        return False
    
    # Check if already installed
    existing = _mod_jar_exists(mods_dir, mod_slug=slug)
    if existing:
        log.info(f"CurseForge: {mod_name} already installed as {existing}")
        return "exists"
    
    # Use Playwright to find and download the correct version
    return _cf_download_playwright(slug, file_id, mods_dir, mod_name, mc_version=mc_version, loader=loader)


MODRINTH_SORT_OPTIONS = {
    "downloads": "downloads",      # Total downloads (default)
    "relevance": "relevance",      # Modrinth relevance algorithm
    "follows": "follows",          # Most followed
    "newest": "newest",            # Newest first
    "updated": "updated",          # Recently updated
}

CF_SORT_OPTIONS = {
    "downloads": "total+downloads",    # Total downloads (default)
    "popularity": "popularity",        # CurseForge trending/popularity
    "updated": "last+updated",         # Recently updated
    "name": "name",                    # Alphabetical
    "author": "author",               # By author
    "created": "creation+date",        # Newest first
}

def fetch_modrinth_mods(mc_version, loader, limit=100, offset=0, categories=None, sort="downloads"):
    """
    Fetch mods from Modrinth for given MC version + loader
    
    Args:
        mc_version: e.g. "1.21.11"
        loader: e.g. "neoforge"
        limit: max # of mods to fetch per request (default 100)
        offset: pagination offset (default 0)
        categories: list of content categories to include (None = all)
        sort: sort index — "downloads", "relevance", "follows", "newest", "updated"
    
    Returns:
        List of mod dictionaries sorted by chosen index
    """
    from urllib.parse import quote
    base_url = "https://api.modrinth.com/v2"
    
    loader_query = loader.lower()
    index = MODRINTH_SORT_OPTIONS.get(sort, "downloads")
    
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
    
    url = f"{base_url}/search?query=&facets={facets_encoded}&limit={limit}&offset={offset}&index={index}"
    
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
    """Get dependencies from latest version matching MC version and loader.
    
    IMPORTANT: Fetches ALL versions without filter query params, then filters
    in Python. Modrinth's loaders/game_versions query params silently return
    empty results (known bug).
    """
    base_url = "https://api.modrinth.com/v2"
    loader_lower = loader.lower()
    
    try:
        # Fetch ALL versions — do NOT use loaders= or game_versions= params
        url = f'{base_url}/project/{mod_id}/version'
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            all_versions = json.loads(response.read().decode())
            
            # Priority 1: Exact MC version + exact loader
            for v in all_versions:
                if mc_version in v.get("game_versions", []) and loader_lower in [l.lower() for l in v.get("loaders", [])]:
                    return v.get("dependencies", [])
            
            # Priority 2: Exact MC version, any loader
            for v in all_versions:
                if mc_version in v.get("game_versions", []):
                    return v.get("dependencies", [])
            
            # Do NOT fall back to wrong MC version — strict matching only
    except Exception as e:
        log_event("DEPS", f"Error fetching deps for {mod_id}: {e}")
    
    return []

def is_library(mod_name, required_dep=False, mod_data=None):
    """
    Check if mod is a library/API/dependency (not a user-facing gameplay mod)
    
    ONLY user-facing mods are shown. Dependencies are fetched on-demand.
    
    Args:
        mod_name: name of the mod
        required_dep: if True, don't filter (required deps override library status)
        mod_data: optional dict with 'description', 'categories', 'project_type',
                  'slug' fields for deeper inspection
    
    Returns:
        True if should be filtered (is a library/API), False if user-facing
    """
    if not mod_name:
        return True  # Filter out mods with no name
    
    # Required dependencies bypass the library filter — they must be installed
    if required_dep:
        return False
    
    name_lower = mod_name.lower().strip()
    slug_lower = (mod_data.get("slug", "") if mod_data else "").lower().strip()
    
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
        # Additional known libraries that slip through pattern checks
        "glitchcore", "glitch core",
        "moonlight lib", "moonlight",
        "spectrelib", "spectre lib",
        "blueprint", "citadel",
        "flywheel", "caelus api",
        "bookshelf", "pollen",
        "structure gel api", "playeranimator",
        "cofh core", "cofhcore",
        "curios", "autoreglib",
        "mantle", "titanium",
        "l2library", "l2lib",
        "fusion (connected textures)",
        "shedaniel's cloth config",
        "neoforged", "lexforge",
        "kiwi", "u_team_core",
        "catalogue", "configured",
    }
    
    if name_lower in lib_exact:
        return True
    
    # Also check slug (catches cases like "glitchcore" slug with different display name)
    lib_slug_exact = {
        "glitchcore", "moonlight", "spectrelib", "cofhcore",
        "autoreglib", "mantle", "titanium", "citadel",
        "flywheel", "caelus", "bookshelf", "pollen",
        "blueprint", "kiwi", "u-team-core", "catalogue",
        "configured", "l2library",
    }
    if slug_lower in lib_slug_exact:
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
    if name_lower.endswith("core") and len(name_lower) > 6:
        # Catch "glitchcore", "cofhcore", "creativecore" etc.
        # Whitelist actual gameplay mods that happen to end in "core"
        core_whitelist = {"hardcore", "voidcore", "deepcore", "reactorcore"}
        if name_lower not in core_whitelist:
            return True
    
    # Check mod_data fields for deeper library detection
    if mod_data:
        # Modrinth project_type: "mod" vs explicit library markers
        categories = [c.lower() for c in mod_data.get("categories", [])]
        if "library" in categories or "utility" in categories:
            return True
        
        # Check Modrinth project_type field
        ptype = mod_data.get("project_type", "").lower()
        if ptype == "library":
            return True
        
        # Scan description for library indicators
        desc = (mod_data.get("description") or "").lower()
        lib_desc_phrases = [
            "library for",
            "a library",
            "an api for",
            "utility library",
            "core library",
            "dependency for",
            "required by other mods",
            "used as a dependency",
            "provides api",
            "provides an api",
            "shared code",
            "helper library",
            "framework for",
        ]
        for phrase in lib_desc_phrases:
            if phrase in desc:
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
        
        if is_library(mod_name, required_dep=False, mod_data=mod):
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


def _mod_jar_exists(mods_dir, filename=None, mod_slug=None, mod_name=None):
    """Check if a mod JAR already exists in the mods directory.
    Uses the same smart matching as installed detection (tokens + aliases + fuzzy).
    
    Checks by exact filename first, then by smart token matching.
    Returns the matching filename if found, else None.
    """
    if not os.path.exists(mods_dir):
        return None
    
    # Exact filename match
    if filename:
        path = os.path.join(mods_dir, filename)
        if os.path.exists(path) and os.path.isfile(path):
            return filename
    
    # Smart match using the installed detection system
    if mod_slug or mod_name:
        installed_tokens, installed_jars = build_installed_index(mods_dir)
        # Use exact=True for dependency resolution - don't let "biomesoplenty" match "mcwbiomesoplenty"
        if check_installed(mod_name or "", mod_slug or "", installed_tokens, exact=True):
            # Found a match — figure out which JAR it is for potential replacement
            search_norm = re.sub(r'[^a-z0-9]', '', (mod_slug or mod_name or "").lower())
            if search_norm:
                for fn in os.listdir(mods_dir):
                    if not fn.endswith('.jar') or not os.path.isfile(os.path.join(mods_dir, fn)):
                        continue
                    token = _extract_mod_token(fn)
                    if token and (search_norm in token or token in search_norm):
                        return fn
                # Check aliases too
                for alias, canonical in MOD_ALIASES.items():
                    if search_norm.startswith(alias):
                        alt = canonical + search_norm[len(alias):]
                        for fn in os.listdir(mods_dir):
                            if not fn.endswith('.jar'):
                                continue
                            token = _extract_mod_token(fn)
                            if token and (alt in token or token in alt):
                                return fn
            # We know it's installed but couldn't pinpoint the exact JAR — 
            # return a truthy sentinel so callers know it exists
            return "__installed__"
    
    return None


def download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader):
    """Download mod JAR from Modrinth.
    
    - Fetches ALL versions (no filter query params — Modrinth silently returns
      empty results when loaders/game_versions params are used)
    - Filters in Python for exact MC version + loader match
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
    
    # IMPORTANT: Do NOT use loaders= or game_versions= query params.
    # Modrinth's version endpoint silently returns empty results when these
    # filters are used (regardless of encoding). Instead, fetch ALL versions
    # and filter in Python.
    versions = None
    try:
        url = f'{base_url}/project/{mod_id}/version'
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            all_versions = json.loads(response.read().decode())
            
            # Priority 1: Exact MC version + exact loader match
            for v in all_versions:
                if mc_version in v.get("game_versions", []) and loader_lower in [l.lower() for l in v.get("loaders", [])]:
                    versions = [v]
                    break
            
            # Priority 2: Exact MC version, any loader (some mods only publish under generic name)
            if not versions:
                for v in all_versions:
                    if mc_version in v.get("game_versions", []):
                        versions = [v]
                        break
            
            # Do NOT fall back to wrong MC version — strict matching only
    except Exception as e:
        log_event("CURATOR", f"Version fetch failed for {mod_name}: {e}")
    
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
    existing = _mod_jar_exists(mods_dir, mod_slug=mod_slug, mod_name=mod_name)
    if existing and existing != file_name and existing != "__installed__":
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

def generate_mod_lists_for_loaders(mc_version, limit=100, loaders=None, sort="downloads"):
    """
    Generate and cache dual-source mod lists for specified loaders.
    Fetches from Modrinth API + CurseForge scraper, deduplicates, saves curator cache.
    
    Already-installed mods are EXCLUDED from the curated list and extras are fetched
    to fill the gaps, so the user always sees `limit` NEW mods to choose from.
    
    Args:
        mc_version: MC version string
        limit: target number of user-facing mods per source (default 100)
        loaders: list of loader names (default ["neoforge"])
        sort: sort method — "downloads", "relevance", "follows", "newest", "updated"
              (maps to Modrinth index and CurseForge sortBy)
    
    Returns dict keyed by loader name, each containing list of mods.
    """
    if loaders is None:
        loaders = ["neoforge"]
    mod_lists = {}
    
    for loader in loaders:
        print(f"\nGenerating {loader.upper()} mod list (up to {limit} per source, sort={sort})...")
        
        # Build installed mod index for exclusion (scans mods/ AND mods/clientonly/)
        mods_dir = os.path.join(CWD, "mods")
        installed_tokens, installed_jars = build_installed_index(mods_dir)
        
        def _is_installed(name, slug=""):
            """Check if a mod name/slug matches an installed JAR using smart matching"""
            return check_installed(name, slug, installed_tokens)
        
        # ---- SOURCE 1: MODRINTH ----
        # Over-fetch to account for installed mods being excluded
        scan_limit = min(limit * 7, 700)
        modrinth_raw = []
        for offset in range(0, scan_limit, 100):
            batch_limit = min(100, scan_limit - offset)
            mods = fetch_modrinth_mods(mc_version, loader, limit=batch_limit, offset=offset, sort=sort)
            if mods:
                modrinth_raw.extend(mods)
            else:
                break
        
        modrinth_mods = {}
        installed_skipped_mr = 0
        for mod in modrinth_raw:
            if len(modrinth_mods) >= limit:
                break
            mod_id = mod.get("project_id")
            mod_name = mod.get("title")
            mod_slug = mod.get("slug", "")
            if is_library(mod_name, mod_data=mod):
                continue
            if _is_installed(mod_name, mod_slug):
                installed_skipped_mr += 1
                continue
            modrinth_mods[mod_id] = {
                "id": mod_id,
                "name": mod_name,
                "downloads": mod.get("downloads", 0),
                "description": mod.get("description", "No description"),
                "source": "modrinth"
            }
        
        print(f"  Modrinth: {len(modrinth_mods)} new mods ({installed_skipped_mr} installed skipped)")
        
        # ---- SOURCE 2: CURSEFORGE SCRAPER ----
        cf_mods = {}
        installed_skipped_cf = 0
        try:
            # Over-fetch CF too — request extra to compensate for installed exclusions
            cf_fetch_limit = min(limit + installed_skipped_mr + 20, 200)
            cf_raw = fetch_curseforge_mods_scraper(mc_version, loader, limit=cf_fetch_limit, scrape_deps=True, sort=sort)
            for mod in cf_raw:
                if len(cf_mods) >= limit:
                    break
                mod_name = mod.get("name", "")
                slug = mod.get("slug", "")
                if not slug or is_library(mod_name, mod_data=mod):
                    continue
                if _is_installed(mod_name, slug):
                    installed_skipped_cf += 1
                    continue
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
            print(f"  CurseForge: {len(cf_mods)} new mods ({installed_skipped_cf} installed skipped)")
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
        
        print(f"  Dedup: {cf_dupes} shared, {cf_unique} CF-only added -> {len(merged)} unique NEW mods")
        total_skipped = installed_skipped_mr + installed_skipped_cf
        if total_skipped:
            print(f"  ({total_skipped} installed mods excluded: {installed_skipped_mr} MR + {installed_skipped_cf} CF)")
        
        # Save curator cache (this is what the dashboard API reads)
        save_curator_cache(merged, {}, mc_version, loader)
        
        # Also return as a flat list for in-memory use
        mod_lists[loader] = sorted(merged.values(), key=lambda m: m.get("downloads", 0), reverse=True)
        print(f"  {len(mod_lists[loader])} {loader} mods ready")
    
    return mod_lists

def curator_command(cfg, limit=None, show_optional_audit=False, sort="downloads"):
    """
    Main curator command - dual-source smart dependency management
    
    Flow:
    1. Fetch top N mods from BOTH Modrinth API AND CurseForge web scraper
    2. Filter OUT all libs/APIs and already-installed mods
    3. Over-fetch to fill gaps left by installed exclusions
    4. Deduplicate by normalized mod name (prefer Modrinth for downloads, keep both sources)
    5. Merge into unified list sorted by chosen sort
    6. Save curator cache so dashboard/API can access the full list
    7. When called interactively: show list, user picks, download mods + required deps
    8. Auto-fetch CurseForge required deps (from scraped dep data)
    9. Flag optional dep interoperability: if 2+ selected mods share an optional dep, notify user
    
    Args:
        cfg: configuration dict
        limit: max USER-FACING mods to fetch PER SOURCE (default 100, None = use config)
        show_optional_audit: show optional deps audit report after download
        sort: sort method — "downloads", "relevance", "follows", "newest", "updated", "popularity"
    """
    mc_version = cfg.get("mc_version", "1.21.11")
    loader = cfg.get("loader", "neoforge")
    if limit is None:
        limit = cfg.get("curator_limit", 100)
    
    sort_label = sort.upper()
    print(f"\n{'='*70}")
    print(f"MOD CURATOR - {loader.upper()} {mc_version} (DUAL SOURCE, sort={sort_label})")
    print(f"{'='*70}\n")
    
    # Build installed mod index for exclusion (scans mods/ AND mods/clientonly/)
    mods_dir_path = os.path.join(CWD, cfg.get("mods_dir", "mods"))
    installed_tokens, installed_jars = build_installed_index(mods_dir_path)
    
    def _is_installed(name, slug=""):
        return check_installed(name, slug, installed_tokens)
    
    installed_count = len(installed_tokens)
    print(f"  {installed_count} mods already installed (will be excluded from list)\n")
    
    # ---- SOURCE 1: MODRINTH API ----
    print(f"[1/2] Fetching top {limit} mods from Modrinth API (sort={sort_label})...")
    scan_limit = min(limit * 7, 700)
    
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
        if not is_library(mod_name, mod_data=mod):
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
        if not is_library(mod_name, mod_data=mod):
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
    """Generate systemd user service file for auto-start (no sudo needed)"""
    loader = cfg.get("loader", "neoforge")
    mc_ver = cfg.get("mc_version", "1.21.11")
    python_bin = sys.executable or "/usr/bin/python3"
    user = os.getenv("USER", "services")
    
    service_content = f"""[Unit]
Description=Minecraft {loader} {mc_ver} Server (NeoRunner)
After=network.target

[Service]
Type=simple
WorkingDirectory={CWD}
ExecStart={python_bin} {os.path.abspath(__file__)} run
Restart=always
RestartSec=10
StandardOutput=append:{CWD}/live.log
StandardError=append:{CWD}/live.log
Environment="NEORUNNER_HOME={CWD}"

[Install]
WantedBy=default.target
"""
    
    # Create user systemd directory
    systemd_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(systemd_dir, exist_ok=True)
    
    service_path = os.path.join(systemd_dir, "mcserver.service")
    with open(service_path, "w") as f:
        f.write(service_content)
    
    log_event("SYSTEMD", f"Created user service at {service_path}")
    
    # Enable lingering so service starts at boot without login
    try:
        subprocess.run(["loginctl", "enable-linger", user], capture_output=True)
    except Exception:
        pass
    
    # Reload and enable
    try:
        uid = os.getuid()
        run_dir = f"/run/user/{uid}"
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = run_dir
        subprocess.run(["systemctl", "--user", "daemon-reload"], env=env, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "mcserver"], env=env, capture_output=True)
    except Exception as e:
        log_event("SYSTEMD", f"Could not auto-enable service: {e}")
    
    print(f"\nUser service installed! Manage with:")
    print(f"  systemctl --user start mcserver")
    print(f"  systemctl --user stop mcserver")
    print(f"  systemctl --user restart mcserver")
    print(f"  systemctl --user status mcserver")

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
            run_neorunner(cfg)
    else:
        # No args = run (unified install + start)
        run_neorunner(cfg)

def run_neorunner(cfg):
    """Main entry point: install loader if needed, then run server."""
    print("\n" + "="*70)
    print("  NeoRunner - Minecraft Modded Server Manager")
    print("="*70 + "\n")
    
    # Check if server is already initialized
    initialized_marker = os.path.join(CWD, ".initialized")
    is_initialized = os.path.exists(initialized_marker)
    
    loader_choice = cfg.get("loader", "neoforge")
    mc_version = cfg.get("mc_version", "1.21.11")
    
    # ── STEP 1: Ensure loader is installed ──
    print(f"[BOOT] Checking modloader: {loader_choice}")
    if not download_loader(loader_choice):
        # Loader not found - need to install it
        if sys.stdin.isatty():
            print(f"\n[BOOT] {loader_choice.upper()} not installed. Installing now...")
        else:
            log_event("BOOT", f"{loader_choice} not installed, auto-installing...")
        
        if not ensure_loader_installed(loader_choice, mc_version):
            print(f"\n[ERROR] Failed to install {loader_choice}")
            print("Please install manually and try again.")
            sys.exit(1)
        
        # Verify installation
        if not download_loader(loader_choice):
            print(f"\n[ERROR] {loader_choice} installation failed")
            sys.exit(1)
        
        print(f"[BOOT] {loader_choice.upper()} installed successfully!\n")
    
    if not is_initialized:
        # First-time setup
        log_event("BOOT", "First-time initialization...")
        create_systemd_service(cfg)
    
    # ── STEP 2: Check for curator first run ──
    first_run_marker = os.path.join(CWD, ".curator_first_run")
    if not os.path.exists(first_run_marker) and cfg.get("run_curator_on_startup", False):
        if sys.stdin.isatty():
            print("\n" + "="*70)
            print("FIRST RUN: MOD CURATOR SETUP")
            print("="*70)
            print(f"\nWould you like to discover and add the top 100 mods")
            print(f"for {loader_choice} {mc_version} right now?")
            print("\nThis will fetch mods from Modrinth and let you select")
            print("which ones to add to your server.\n")
            
            response = input("Run mod curator now? [y/n]: ").strip().lower()
            if response == "y":
                print("\nLaunching curator...")
                curator_command(cfg)
                print("\nCurator complete! Starting server...\n")
        else:
            log_event("BOOT", "Skipping interactive curator setup (running as service)")
        
        with open(first_run_marker, "w") as f:
            f.write("first run complete")
    
    # ── STEP 3: Setup mods ──
    print("[BOOT] Sorting mods by type (client/server/both)...")
    sort_mods_by_type(cfg["mods_dir"])
    
    print("[BOOT] Checking mod compatibility (loader/version)...")
    compat = preflight_mod_compatibility_check(cfg["mods_dir"], cfg)
    if compat["quarantined"]:
        print(f"[BOOT] WARNING: {len(compat['quarantined'])} incompatible mod(s) quarantined")
    if compat["compatible"]:
        print(f"[BOOT] {len(compat['compatible'])} mods passed compatibility check")
    
    # Regenerate install scripts
    create_install_scripts(cfg["mods_dir"], cfg)
    create_mod_zip(cfg["mods_dir"])
    
    if not is_initialized:
        with open(initialized_marker, "w") as f:
            f.write(f"initialized at {datetime.now().isoformat()}")
        log_event("BOOT", "Initialization complete")
    
    # ── STEP 4: Generate mod lists (in background to not block server start) ──
    def _generate_mod_lists_async():
        try:
            mod_lists = generate_mod_lists_for_loaders(mc_version, limit=cfg.get("curator_limit", 100), loaders=[loader_choice])
            cfg["mod_lists"] = mod_lists
        except Exception as e:
            log_event("ERROR", f"Failed to generate mod lists: {e}")
    
    threading.Thread(target=_generate_mod_lists_async, daemon=True).start()
    
    # ── STEP 5: Start services ──
    print(f"\n[BOOT] Starting services...")
    print(f"  Dashboard: http://localhost:{cfg['http_port']}")
    print(f"  MC Server: starting in tmux session 'MC'\n")
    
    threading.Thread(target=http_server, args=(cfg["http_port"], cfg["mods_dir"]), daemon=True).start()
    threading.Thread(target=backup_scheduler, args=(cfg,), daemon=True).start()
    threading.Thread(target=monitor_players, args=(cfg,), daemon=True).start()
    
    ferium_mgr = init_ferium_scheduler(cfg)
    
    # Start Minecraft server
    run_server(cfg)
    
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log_event("SHUTDOWN", "Server stopping")
        run("tmux send-keys -t MC 'stop' Enter")
        time.sleep(10)

if __name__ == "__main__":
    main()

# Add this endpoint near the other mod API endpoints
