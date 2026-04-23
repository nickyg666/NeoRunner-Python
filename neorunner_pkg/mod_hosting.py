"""
Mod hosting server with HTTP endpoints for mod distribution.
Provides secure mod downloads with rate limiting and conditional zip creation.
"""

from __future__ import annotations

import os
import json
import time
import zipfile
import hashlib
import threading
import socket
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Dict, Any, Set
from datetime import datetime
from urllib.parse import quote as url_quote

from .config import load_cfg, ServerConfig
from .constants import CWD
from .log import log_event


def _is_private_ip(ip: str) -> bool:
    """Check if IP is private LAN address."""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        first = int(parts[0])
        second = int(parts[1])
        
        # 10.x.x.x
        if first == 10:
            return True
        # 172.16-31.x.x
        if first == 172 and 16 <= second <= 31:
            return True
        # 192.168.x.x
        if first == 192 and second == 168:
            return True
        # 127.x.x.x
        if first == 127:
            return True
        return False
    except:
        return False


def _get_local_ip() -> str:
    """Detect the local LAN IP address of this machine."""
    import subprocess
    
    # Known VPN/tunnel interface prefixes to avoid
    vpn_prefixes = ['as0t', 'wg', 'tun', 'tap', 'vpn', 'chi', 'utun', 'en0']
    
    try:
        result = subprocess.run(
            ["ip", "addr", "show"],
            capture_output=True, text=True, timeout=5
        )
        
        # Find all inet entries with their interface names
        lines = result.stdout.split('\n')
        lan_ips = []
        vpn_ips = []
        
        for line in lines:
            # Look for "inet X.X.X.X/X" followed by interface name
            if 'inet ' in line:
                parts = line.strip().split()
                try:
                    idx = parts.index('inet')
                    if idx + 1 < len(parts):
                        ip_cidr = parts[idx + 1]
                        ip = ip_cidr.split('/')[0]
                        
                        # Find interface name (usually at end of line after "scope")
                        iface = ''
                        for i, p in enumerate(parts):
                            if p in ['enp0s3', 'eth0', 'eth1', 'wlan0', 'eno1', 'en0', 'en1']:
                                iface = p
                                break
                            if 'scope' in p and i + 1 < len(parts):
                                # Next thing might be interface
                                pass
                        
                        # Also check end of line for interface
                        line_end = parts[-1] if parts else ''
                        if line_end not in ['lo', 'inet6'] and any(x in line_end for x in ['enp', 'eth', 'wlan', 'eno']):
                            iface = line_end
                        
                        if ip.startswith('127.'):
                            continue
                        
                        is_vpn = any(ip.startswith(prefix) for prefix in vpn_prefixes) or \
                                any(prefix in line for prefix in vpn_prefixes)
                        
                        if is_vpn:
                            vpn_ips.append(ip)
                        elif _is_private_ip(ip):
                            lan_ips.append(ip)
                except (ValueError, IndexError):
                    continue
        
        # Prefer LAN IPs (ethernet/wifi)
        if lan_ips:
            return lan_ips[0]
        
        # If no LAN, maybe VPN is only option
        if vpn_ips:
            return vpn_ips[0]
        
    except Exception:
        pass
    
    # Fallback: try connecting to typical gateways
    lan_gateways = ["192.168.1.1", "192.168.0.1", "10.0.0.1"]
    
    for gateway in lan_gateways:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((gateway, 53))
            ip = s.getsockname()[0]
            s.close()
            if _is_private_ip(ip):
                return ip
        except Exception:
            continue
    
    # Last resort: any IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_server_hostname(cfg: ServerConfig) -> str:
    """Get the server hostname/IP for client scripts."""
    if cfg.hostname:
        return cfg.hostname
    return _get_local_ip()


# Global state for download tracking
_last_request_time = 0
_download_lock = threading.Lock()
_zip_creation_lock = threading.Lock()
_last_zip_time: Optional[float] = None


class SecureHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler with security checks and individual mod downloads."""
    
    last_request_time = 0
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
    
    def do_GET(self):
        """Handle GET requests with security checks."""
        cfg = load_cfg()
        
        # Track downloads
        is_download = self.path.startswith("/download/mods") or self.path.endswith(".zip")
        
        # Rate limiting
        current_time = time.time()
        if current_time - SecureHTTPHandler.last_request_time < cfg.rate_limit_seconds:
            self.send_error(429, "Rate limited")
            return
        SecureHTTPHandler.last_request_time = current_time
        
        # Handle /download/mods/{filename} for individual mod downloads
        if self.path.startswith("/download/mods/"):
            self._handle_mod_download(cfg)
            return
        
        # Handle /download/manifest for manifest.json
        if self.path.startswith("/download/manifest") or self.path == "/download/mods_manifest.json":
            self._handle_manifest_download(cfg)
            return
        
        # Handle /download/all for full zip download
        if self.path.startswith("/download/all") or self.path == "/download/mods_latest.zip":
            self._handle_zip_download(cfg)
            return
        
        # Handle /client-status for client to report mod status
        if self.path.startswith("/client-status"):
            self._handle_client_status(cfg)
            return
        
        # Handle install scripts
        if self.path.startswith("/install") or self.path.startswith("/download/install"):
            log_event("DEBUG", f"Install script request: {self.path}")
            self._handle_install_script(cfg)
            return
        
        log_event("DEBUG", f"Unhandled path: {self.path}")
        
        # Default: serve static files
        super().do_GET()
    
    def do_POST(self):
        """Handle POST requests."""
        cfg = load_cfg()
        
        # Handle client status updates
        if self.path.startswith("/api/client-status"):
            self._handle_client_status_post(cfg)
            return
        
        # Handle custom zip request - client requests specific mods
        if self.path.startswith("/download/zip") or self.path.startswith("/api/download-zip"):
            self._handle_custom_zip_download(cfg)
            return
        
        # Default: method not allowed
        self.send_error(405, "Method not allowed")
    
    def _handle_custom_zip_download(self, cfg: ServerConfig):
        """Handle custom zip download - client requests specific mods."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_error(400, "No mod list provided")
            return
        
        try:
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            requested_mods = data.get("mods", [])
            
            if not requested_mods:
                self.send_error(400, "No mods specified")
                return
            
            mods_dir = Path(cfg.mods_dir)
            if not mods_dir.is_absolute():
                mods_dir = CWD / mods_dir
            clientonly_dir = Path(cfg.clientonly_dir)
            if not clientonly_dir.is_absolute():
                clientonly_dir = CWD / clientonly_dir
            
            # Build list of files to include
            mods_to_zip: Dict[str, Path] = {}
            missing = []
            
            for mod_name in requested_mods:
                # Check server mods dir first
                mod_path = mods_dir / mod_name
                if mod_path.exists():
                    mods_to_zip[mod_name] = mod_path
                elif clientonly_dir.exists():
                    # Check clientonly dir
                    mod_path = clientonly_dir / mod_name
                    if mod_path.exists():
                        mods_to_zip[mod_name] = mod_path
                    else:
                        missing.append(mod_name)
                else:
                    missing.append(mod_name)
            
            if not mods_to_zip:
                self.send_error(404, "None of the requested mods found")
                return
            
            # Create temporary zip in memory
            import io
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for filename, file_path in sorted(mods_to_zip.items()):
                    zf.write(file_path, arcname=filename)
            
            zip_data = zip_buffer.getvalue()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(zip_data)))
            self.send_header("Content-Disposition", 'attachment; filename="neorunner_mods.zip"')
            self.end_headers()
            self.wfile.write(zip_data)
            
            log_event("HTTP_DOWNLOAD", f"Served custom zip ({len(mods_to_zip)} mods)")
            
        except Exception as e:
            log_event("ERROR", f"Custom zip failed: {e}")
            self.send_error(500, str(e))
    
    def _handle_mod_download(self, cfg: ServerConfig):
        """Handle individual mod download requests."""
        filename = self.path[len("/download/mods/"):].split("?")[0]
        
        # Security check - reject server-only jars
        if not filename or filename.startswith(".") or not filename.endswith(".jar"):
            self.send_error(403, "Invalid filename")
            return
        
        # Don't serve .server.jar to clients - only for server
        if filename.endswith(".server.jar"):
            self.send_error(403, "Server-only mod not available for clients")
            return
        
        mods_dir = Path(cfg.mods_dir)
        if not mods_dir.is_absolute():
            mods_dir = CWD / mods_dir
        
        clientonly_dir = Path(cfg.clientonly_dir)
        if not clientonly_dir.is_absolute():
            clientonly_dir = CWD / clientonly_dir
        
        # Check root first, then clientonly
        file_path = mods_dir / filename
        if not file_path.exists():
            file_path = clientonly_dir / filename
        
        if not file_path.exists():
            self.send_error(404, f"Mod not found: {filename}")
            return
        
        # File size limit
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > cfg.max_download_mb:
            self.send_error(413, "File too large")
            return
        
        # Security: prevent path traversal
        if not str(file_path.resolve()).startswith(str(mods_dir.resolve())):
            self.send_error(403, "Invalid path")
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
    
    def _handle_manifest_download(self, cfg: ServerConfig):
        """Handle manifest.json download."""
        mods_dir = Path(cfg.mods_dir)
        if not mods_dir.is_absolute():
            mods_dir = CWD / mods_dir
        
        # Always update manifest to ensure it's fresh and includes client-only mods
        update_manifest(mods_dir, cfg)
        
        manifest_path = mods_dir / "manifest.json"
        
        if manifest_path.exists():
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with open(manifest_path, "rb") as f:
                self.wfile.write(f.read())
            log_event("HTTP_DOWNLOAD", "Served manifest.json")
        else:
            self.send_error(404, "Manifest not found")
    
    def _handle_zip_download(self, cfg: ServerConfig):
        """Handle full mods zip download."""
        mods_dir = Path(cfg.mods_dir)
        if not mods_dir.is_absolute():
            mods_dir = CWD / mods_dir
        
        zip_path = mods_dir / "mods_latest.zip"
        
        # Create zip if it doesn't exist
        if not zip_path.exists():
            create_mod_zip(mods_dir, cfg)
        
        if zip_path.exists():
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(zip_path.stat().st_size))
            self.send_header("Content-Disposition", 'attachment; filename="mods_latest.zip"')
            self.end_headers()
            with open(zip_path, "rb") as f:
                self.wfile.write(f.read())
            log_event("HTTP_DOWNLOAD", f"Served mods_latest.zip ({zip_path.stat().st_size / (1024*1024):.2f} MB)")
        else:
            self.send_error(404, "Zip not found")
    
    def _handle_client_status(self, cfg: ServerConfig):
        """Handle client status check (GET)."""
        # Return current server info
        response = {
            "status": "ok",
            "mc_version": cfg.mc_version,
            "loader": cfg.loader,
            "timestamp": time.time()
        }
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())
    
    def _handle_client_status_post(self, cfg: ServerConfig):
        """Handle client status update (POST)."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            try:
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))
                
                client_id = data.get("client_id", "unknown")
                correct_mods = data.get("correct_mods", 0)
                total_mods = data.get("total_mods", 0)
                
                log_event("CLIENT_STATUS", 
                    f"Client {client_id}: {correct_mods}/{total_mods} mods correct")
                
                # If client reports 0 correct mods, trigger zip creation
                if correct_mods == 0 and total_mods > 0:
                    log_event("CLIENT_STATUS", 
                        f"Client {client_id} needs full mod package")
                    
                    # Trigger conditional zip creation in background
                    mods_dir = Path(cfg.mods_dir)
                    if not mods_dir.is_absolute():
                        mods_dir = CWD / mods_dir
                    
                    thread = threading.Thread(
                        target=conditional_create_mod_zip,
                        args=(mods_dir,),
                        daemon=True
                    )
                    thread.start()
                
                # Send response
                response = {"success": True}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
                return
            except Exception as e:
                log_event("ERROR", f"Failed to process client status: {e}")
        
        self.send_error(400, "Invalid request")
    
    def _handle_install_script(self, cfg: ServerConfig):
        """Handle install script requests."""
        script_type = self.path.split("/")[-1] if "/" in self.path else "all"
        
        # /download/install-mods.bat - serve batch file
        if script_type == "install-mods.bat":
            bat_path = Path(__file__).parent / "mods" / "install-mods.bat"
            if bat_path.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="install-mods.bat"')
                self.end_headers()
                with open(bat_path, "rb") as f:
                    self.wfile.write(f.read())
                log_event("HTTP_DOWNLOAD", "Served install-mods.bat")
            else:
                self.send_error(404, "Bat script not found")
            return
        
        # /download/install serves PowerShell (for curl | iex)
        if script_type == "install" or script_type == "windows" or script_type == "install-mods.ps1":
            script = generate_powershell_script(cfg)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="install-mods.ps1"')
            self.end_headers()
            self.wfile.write(script.encode())
            log_event("HTTP_DOWNLOAD", "Served PowerShell install script")
            return
        
        elif script_type == "linux" or script_type == "install-mods.sh":
            script = generate_bash_script(cfg)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="install-mods.sh"')
            self.end_headers()
            self.wfile.write(script.encode())
            log_event("HTTP_DOWNLOAD", "Served Bash install script")
            return
         
        else:
            self.send_error(404, "Script type not found")


def update_manifest(mods_dir: Path, cfg: Optional[ServerConfig] = None) -> bool:
    """Update manifest.json with current mod list including client-only mods."""
    mods_dir = Path(mods_dir)
    if cfg is None:
        cfg = load_cfg()
    clientonly_dir = Path(cfg.clientonly_dir)
    if not clientonly_dir.is_absolute():
        clientonly_dir = CWD / clientonly_dir
    manifest_path = mods_dir / "manifest.json"
    
    try:
        mods: Dict[str, Path] = {}
        
        # Collect server mods (skip .server.jar)
        if mods_dir.exists():
            for f in os.listdir(mods_dir):
                if f.endswith('.jar') and not f.endswith('.server.jar'):
                    mods[f] = mods_dir / f
        
        # Add client-only mods with type indicator
        clientonly_mods = {}
        if clientonly_dir.exists():
            for f in os.listdir(clientonly_dir):
                if f.endswith('.jar') and not f.endswith('.server.jar'):
                    if f not in mods:
                        clientonly_mods[f] = clientonly_dir / f
        
        # Build manifest with type field (server vs clientonly)
        files = []
        for name in sorted(mods.keys()):
            files.append({"path": name, "type": "server"})
        for name in sorted(clientonly_mods.keys()):
            files.append({"path": name, "type": "clientonly"})
        
        manifest = {"files": files}
        
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        log_event("MANIFEST", f"Updated manifest.json ({len(mods)} server, {len(clientonly_mods)} clientonly)")
        return True
        
    except Exception as e:
        log_event("MANIFEST", f"Error updating manifest: {e}")
        return False


def create_mod_zip(mods_dir: Path, cfg: Optional[ServerConfig] = None) -> Optional[Path]:
    """
    Create mods_latest.zip with all mods + clientonly mods.
    Also updates manifest.json first.
    """
    with _zip_creation_lock:
        mods_dir = Path(mods_dir)
        if cfg is None:
            cfg = load_cfg()
        clientonly_dir = Path(cfg.clientonly_dir)
        if not clientonly_dir.is_absolute():
            clientonly_dir = CWD / clientonly_dir
        zip_path = mods_dir / "mods_latest.zip"
        
        try:
            # Always update manifest first
            update_manifest(mods_dir)
            
            mods_to_zip: Dict[str, Path] = {}
            
            # Collect server mods (skip .server.jar)
            if mods_dir.exists():
                for f in os.listdir(mods_dir):
                    if f.endswith('.jar') and not f.endswith('.server.jar'):
                        mods_to_zip[f] = mods_dir / f
            
            # Add client-only mods
            if clientonly_dir.exists():
                for f in os.listdir(clientonly_dir):
                    if f.endswith('.jar') and not f.endswith('.server.jar'):
                        if f not in mods_to_zip:
                            mods_to_zip[f] = clientonly_dir / f
            
            # Create zip
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for filename, file_path in sorted(mods_to_zip.items()):
                    zf.write(file_path, arcname=filename)
            
            size_mb = zip_path.stat().st_size / (1024 * 1024)
            log_event("MOD_ZIP", 
                f"Created mods_latest.zip ({len(mods_to_zip)} mods, {size_mb:.2f} MB)")
            
            return zip_path
            
        except Exception as e:
            log_event("MOD_ZIP", f"Error creating mod zip: {e}")
            return None


def conditional_create_mod_zip(mods_dir: Path, cfg: Optional[ServerConfig] = None) -> Optional[Path]:
    """
    Create mod zip only if needed (not recently created).
    This is called when a client reports 0 correct mods.
    """
    global _last_zip_time
    
    if cfg is None:
        cfg = load_cfg()
    
    with _zip_creation_lock:
        # Check if we recently created a zip
        if _last_zip_time:
            time_since_last = time.time() - _last_zip_time
            if time_since_last < 300:  # Don't recreate within 5 minutes
                log_event("MOD_ZIP", 
                    f"Skipping zip creation - last created {time_since_last:.0f}s ago")
                return None
        
        # Create the zip
        result = create_mod_zip(mods_dir, cfg)
        if result:
            _last_zip_time = time.time()
        return result


def generate_powershell_script(cfg: ServerConfig) -> str:
    """Generate PowerShell install script for Windows."""
    hostname = _get_server_hostname(cfg)
    http_port = cfg.http_port
    
    return '''param(
    [string]$ServerHost = "''' + hostname + '''",
    [int]$ServerPort = ''' + str(http_port) + '''
)

$ErrorActionPreference = "Continue"

$baseUrl = "http://$ServerHost`:$ServerPort"
$mcDir = "$env:APPDATA\\.minecraft"
$modsDir = "$mcDir\\mods"
$oldDir = "$mcDir\\oldmods"

if (-not (Test-Path $modsDir)) { New-Item -ItemType Directory -Path $modsDir -Force | Out-Null }
if (-not (Test-Path $oldDir)) { New-Item -ItemType Directory -Path $oldDir -Force | Out-Null }

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  NeoRunner Mod Sync" -ForegroundColor Green
Write-Host "  Server: $ServerHost`:$ServerPort" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/4] Fetching server manifest..." -ForegroundColor Yellow
try {
    $manifest = Invoke-RestMethod -Uri "$baseUrl/download/manifest" -TimeoutSec 30 -UseBasicParsing
} catch {
    Write-Host "ERROR: Failed to fetch manifest: $_" -ForegroundColor Red
    exit 1
}

$serverFiles = @{}
foreach ($f in $manifest.files) {
    $serverFiles[$f.path] = $f.type
}
$serverCount = $serverFiles.Count
Write-Host "    Server mods: $serverCount" -ForegroundColor Gray

Write-Host "[2/4] Building local mods list..." -ForegroundColor Yellow
$localMods = Get-ChildItem -Path $modsDir -Filter "*.jar" -ErrorAction SilentlyContinue
$localCount = $localMods.Count
Write-Host "    Local mods: $localCount" -ForegroundColor Gray

$moved = 0
$downloaded = 0

Write-Host "[3/4] Syncing mods (checking for extras)..." -ForegroundColor Yellow

foreach ($mod in $localMods) {
    if (-not $serverFiles.ContainsKey($mod.Name)) {
        Write-Host "    [EXTRA] $($mod.Name) -> oldmods" -ForegroundColor Yellow
        Move-Item -Path $mod.FullName -Destination "$oldDir\\$($mod.Name)" -Force
        $moved++
    }
}

$missingMods = @()
foreach ($mod in $manifest.files) {
    $modName = $mod.path
    $localPath = Join-Path $modsDir $modName
    if (-not (Test-Path $localPath)) {
        $missingMods += $modName
    }
}

$missingCount = $missingMods.Count
Write-Host "    Missing: $missingCount" -ForegroundColor Gray

if ($missingCount -gt 0) {
    Write-Host "    Requesting custom zip from server..." -ForegroundColor Cyan
    $zipPath = "$env:TEMP\\neorunner_mods.zip"
    
    try {
        # Build JSON payload with list of missing mods
        $payload = @{
            mods = $missingMods
        } | ConvertTo-Json -Compress
        
        # Request custom zip from server (returns raw binary)
        Invoke-WebRequest -Uri "$baseUrl/download/zip" -Method Post -Body $payload -ContentType "application/json" -OutFile $zipPath -UseBasicParsing -TimeoutSec 300
        
        if (Test-Path $zipPath) {
            Expand-Archive -Path $zipPath -DestinationPath $modsDir -Force
            Remove-Item $zipPath -Force
            $downloaded = $missingCount
            Write-Host "    Downloaded $downloaded mods" -ForegroundColor Green
        }
    } catch {
        Write-Host "    ERROR: Failed to download: $_" -ForegroundColor Red
    }
} else {
    Write-Host "    All mods up to date!" -ForegroundColor Green
}
    } catch {
        Write-Host "    ERROR: Failed to download: $_" -ForegroundColor Red
    }
} else {
    Write-Host "    All mods up to date!" -ForegroundColor Green
}

Write-Host "[4/4] Complete!" -ForegroundColor Yellow

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Sync Complete!" -ForegroundColor Green
Write-Host "  Moved:     $moved" -ForegroundColor Yellow
Write-Host "  Downloaded: $downloaded" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan

pause
'''


def generate_bash_script(cfg: ServerConfig) -> str:
    """Generate Bash install script for Linux/Mac."""
    hostname = _get_server_hostname(cfg)
    http_port = cfg.http_port
    
    return f'''#!/bin/bash
# NeoRunner Mod Installer for Linux/Mac

SERVER_HOST="{hostname}"
SERVER_PORT="{http_port}"
BASE_URL="http://$SERVER_HOST:$SERVER_PORT"

# Detect Minecraft directory
if [[ "$OSTYPE" == "darwin"* ]]; then
    MINECRAFT_DIR="$HOME/Library/Application Support/minecraft"
else
    MINECRAFT_DIR="$HOME/.minecraft"
fi

MODS_DIR="$MINECRAFT_DIR/mods"

echo "═══════════════════════════════════════════"
echo "  NeoRunner Mod Installer"
echo "  Server: $SERVER_HOST:$SERVER_PORT"
echo "═══════════════════════════════════════════"
echo ""

# Create mods directory
mkdir -p "$MODS_DIR"

echo "Installing mods to: $MODS_DIR"
echo ""

# Get manifest
echo "Fetching mod manifest..."
MANIFEST=$(curl -s "$BASE_URL/download/manifest" --max-time 30)
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to fetch manifest"
    exit 1
fi

# Count mods
MOD_COUNT=$(echo "$MANIFEST" | grep -o '"path"' | wc -l)
echo "Found $MOD_COUNT mods to install"
echo ""

# Check existing mods
EXISTING_COUNT=$(ls "$MODS_DIR"/*.jar 2>/dev/null | wc -l)
echo "Existing mods: $EXISTING_COUNT"

# Report status to server
curl -s -X POST "$BASE_URL/api/client-status" \\
    -H "Content-Type: application/json" \\
    -d '{{"client_id":"$(hostname)","correct_mods":'$EXISTING_COUNT',"total_mods":'$MOD_COUNT'}}' > /dev/null 2>&1

# Download all mods using parallel downloads
echo ""
echo "Downloading mods..."
echo "$MANIFEST" | grep '"path"' | sed 's/.*"path": "\\([^"]*\\)".*/\\1/' | while read -r MOD_FILE; do
    if [ ! -f "$MODS_DIR/$MOD_FILE" ]; then
        echo "  Downloading $MOD_FILE..."
        curl -s -o "$MODS_DIR/$MOD_FILE" "$BASE_URL/download/mods/$MOD_FILE" --max-time 60
        if [ $? -eq 0 ]; then
            echo "    ✓ Downloaded"
        else
            echo "    ✗ Failed"
        fi
    else
        echo "  ✓ $MOD_FILE already exists"
    fi
done

echo ""
echo "═══════════════════════════════════════════"
echo "  Installation Complete!"
echo "═══════════════════════════════════════════"

# If 0 existing mods, also download full zip
if [ $EXISTING_COUNT -eq 0 ] && [ $MOD_COUNT -gt 0 ]; then
    echo ""
    echo "Downloading complete mod package..."
    ZIP_PATH="/tmp/mods_latest_$$.zip"
    curl -s -o "$ZIP_PATH" "$BASE_URL/download/all" --max-time 300
    if [ $? -eq 0 ]; then
        unzip -o "$ZIP_PATH" -d "$MODS_DIR" 2>/dev/null
        rm -f "$ZIP_PATH"
        echo "Complete package installed!"
    fi
fi

read -p "Press Enter to continue..."
'''


def get_server_ip() -> str:
    """Get the server IP address for client scripts."""
    # First, try config server_ip
    try:
        from .config import load_cfg
        cfg = load_cfg()
        if cfg and hasattr(cfg, 'server_ip') and cfg.server_ip:
            ip = cfg.server_ip
            if ip and ip != 'localhost' and not ip.startswith('127.'):
                return ip
    except:
        pass
    
    # Fallback to auto-detect
    return _get_local_ip()


def generate_bat_script(cfg: ServerConfig) -> str:
    """Generate batch script (install-mods.bat) that downloads only missing mods from server."""
    hostname = _get_server_hostname(cfg)
    http_port = cfg.http_port
    
    return '''@echo off
REM install-mods.bat - NeoRunner Client Mod Sync Script
setlocal enabledelayedexpansion

set "SERVER_HOST=''' + hostname + '''"
set "SERVER_PORT=''' + str(http_port) + '''"

if "%SERVER_HOST%"=="" set "SERVER_HOST=localhost"
if "%SERVER_PORT%"=="" set "SERVER_PORT=8000"

echo ==========================================
echo    NeoRunner Mod Sync
echo    Server: %SERVER_HOST%:%SERVER_PORT%
echo ==========================================
echo.

set "MINECRAFT=%APPDATA%\\.minecraft"
set "MODS_DIR=%MINECRAFT%\\mods"
set "OLD_DIR=%MINECRAFT%\\oldmods"

if not exist "%MODS_DIR%" mkdir "%MODS_DIR%"
if not exist "%OLD_DIR%" mkdir "%OLD_DIR%"

echo [1/4] Fetching server manifest...
curl.exe -s "http://%SERVER_HOST%:%SERVER_PORT%/download/manifest" -o "%TEMP%\\neorunner_manifest.json"
if errorlevel 1 (
    echo ERROR: Failed to fetch manifest
    pause
    exit /b 1
)

echo [2/4] Building local mods list...
set "LOCAL_COUNT=0"
for /f %%f in ('dir /b "%MODS_DIR%\\*.jar" 2^>nul') do set /a LOCAL_COUNT+=1
echo    Local mods: %LOCAL_COUNT%

echo [3/4] Syncing mods (compare, move extras, download missing)...
set "DOWNLOADED=0"
set "SKIPPED=0"
set "MOVED=0"

REM Build list of server mods - count lines with "path" in JSON
set "SERVER_COUNT=0"
for /f %%a in ('findstr /C:"\"path\"" "%TEMP%\\neorunner_manifest.json"') do set /a SERVER_COUNT+=1
echo    Server mods: %SERVER_COUNT%

REM Check each local mod - move extras to oldmods
for %%f in ("%MODS_DIR%\\*.jar") do (
    findstr /i "%%~nxf" "%TEMP%\\neorunner_manifest.json" >nul 2>&1
    if errorlevel 1 (
        echo    [EXTRA] %%~nf.jar -^> oldmods
        move "%%f" "%OLD_DIR%\\" >nul 2>&1
        set /a MOVED+=1
    ) else (
        set /a SKIPPED+=1
    )
)

set /a MISSING=%SERVER_COUNT%-%SKIPPED%
if %MISSING% LSS 0 set "MISSING=0"
echo    Missing: %MISSING%

if %MISSING% GTR 0 (
    echo    Downloading %MISSING% missing mods...
    curl.exe -sL "http://%SERVER_HOST%:%SERVER_PORT%/download/all" -o "%TEMP%\\neorunner_mods.zip"
    if errorlevel 1 (
        echo    ERROR: Failed to download mods
    ) else (
        REM Extract using tar (built into Windows 10 1803+)
        tar -xf "%TEMP%\\neorunner_mods.zip" -C "%MODS_DIR%" 2>nul
        if errorlevel 1 (
            echo    ERROR: Failed to extract zip
        ) else (
            set /a DOWNLOADED=%MISSING%
            echo    Downloaded %MISSING% mods
        )
        del "%TEMP%\\neorunner_mods.zip" 2>nul
    )
) else (
    echo    All mods up to date!
)

echo [4/4] Cleaning up...
del "%TEMP%\\neorunner_manifest.json" 2>nul

echo.
echo ==========================================
echo    Sync Complete
echo    Skipped:  %SKIPPED%
echo    Moved:    %MOVED%
echo    Downloaded: %DOWNLOADED%
echo ==========================================
pause
'''


def run_mod_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the mod hosting HTTP server."""
    log_event("MOD_SERVER", f"Starting mod hosting server on {host}:{port}")
    
    server = HTTPServer((host, port), SecureHTTPHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("MOD_SERVER", "Shutting down...")
        server.shutdown()
