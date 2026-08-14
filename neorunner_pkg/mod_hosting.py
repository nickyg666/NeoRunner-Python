"""
Mod hosting server with HTTP endpoints for mod distribution.
Provides secure mod downloads with rate limiting and conditional zip creation.
"""


import io
import json
import os
import shutil
import socket
import threading
import time
import urllib.request
import zipfile
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from .config import ServerConfig, load_cfg
from .constants import CWD
from .log import log_event

# Public host used when no hostname is configured (the tunnel/reverse-proxy host
# that external clients reach the download endpoints through).
DEFAULT_PUBLIC_HOST = "mc.w8.mom"


def public_download_base(cfg: ServerConfig) -> str:
    """Base public URL clients use to reach the download endpoints.

    Prefers ``cfg.hostname`` (the configured public host), falling back to the
    known public tunnel host when unset.
    """
    host = cfg.hostname or DEFAULT_PUBLIC_HOST
    return f"https://{host}"


def public_download_link(cfg: ServerConfig, path: str = "/dl/mods.zip") -> str:
    """Full public URL for a download endpoint (the mods.zip bundle by default)."""
    return public_download_base(cfg) + path


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
        return first == 127
    except Exception:
        return False


def _get_local_ip() -> str:
    """Detect the local LAN IP address of this machine."""
    import subprocess
    
    # Known VPN/tunnel interface prefixes to avoid
    vpn_prefixes = ['as0t', 'wg', 'tun', 'tap', 'vpn', 'chi', 'utun', 'en0']
    
    try:
        result = subprocess.run(
            ["ip", "addr", "show"], check=False,
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
                        for i, p in enumerate(parts):
                            if p in ['enp0s3', 'eth0', 'eth1', 'wlan0', 'eno1', 'en0', 'en1']:
                                break
                            if 'scope' in p and i + 1 < len(parts):
                                # Next thing might be interface
                                pass
                        
                        # Also check end of line for interface
                        line_end = parts[-1] if parts else ''
                        if line_end not in ['lo', 'inet6'] and any(x in line_end for x in ['enp', 'eth', 'wlan', 'eno']):
                            pass
                        
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
_zip_creation_lock = threading.RLock()
_last_zip_time: float | None = None


class SecureHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler with security checks and individual mod downloads."""
    
    last_request_time = 0
    
    def log_message(self, format, *args):
        """Suppress default logging."""
    
    def do_GET(self):
        """Handle GET requests with security checks."""
        cfg = load_cfg()
        
        # Track downloads
        self.path.startswith("/download/mods") or self.path.endswith(".zip")
        
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
        
        # Handle install scripts (install-mods.bat only; PowerShell removed)
        if self.path.startswith("/install-mods.bat") or self.path == "/download/install-mods.bat":
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
            mods_to_zip: dict[str, Path] = {}
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
        
        # /download/install (PowerShell) removed; fall through to other handlers.

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


def update_manifest(mods_dir: Path, cfg: ServerConfig | None = None) -> bool:
    """Update manifest.json with current mod list including client-only mods."""
    mods_dir = Path(mods_dir)
    if cfg is None:
        cfg = load_cfg()
    clientonly_dir = Path(cfg.clientonly_dir)
    if not clientonly_dir.is_absolute():
        clientonly_dir = CWD / clientonly_dir
    manifest_path = mods_dir / "manifest.json"
    
    try:
        # Never ship two versions of the same mod (e.g. two Sodium builds): a
        # conflicting duplicate crashes clients. Resolve before listing.
        try:
            from .mods import dedupe_mod_versions
            dedupe_mod_versions(mods_dir, clientonly_dir)
        except Exception as e:
            log_event("MANIFEST", f"Dedupe skipped: {e}")

        mods: dict[str, Path] = {}
        
        # Collect server mods (skip .server.jar)
        if mods_dir.exists():
            for f in os.listdir(mods_dir):
                if f.endswith('.jar') and not f.endswith('.server.jar'):
                    mods[f] = mods_dir / f
        
        # Add client-only mods with type indicator
        clientonly_mods = {}
        if clientonly_dir.exists():
            for f in os.listdir(clientonly_dir):
                if f.endswith('.jar') and not f.endswith('.server.jar') and f not in mods:
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


def create_mod_zip(mods_dir: Path, cfg: ServerConfig | None = None) -> Path | None:
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
            
            mods_to_zip: dict[str, Path] = {}
            
            # Collect server mods (skip .server.jar)
            if mods_dir.exists():
                for f in os.listdir(mods_dir):
                    if f.endswith('.jar') and not f.endswith('.server.jar'):
                        mods_to_zip[f] = mods_dir / f
            
            # Add client-only mods
            if clientonly_dir.exists():
                for f in os.listdir(clientonly_dir):
                    if f.endswith('.jar') and not f.endswith('.server.jar') and f not in mods_to_zip:
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


def conditional_create_mod_zip(mods_dir: Path, cfg: ServerConfig | None = None) -> Path | None:
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


def _loader_installer_path(cfg: ServerConfig) -> Path | None:
    """Locate (or download) the loader's client installer jar.

    The installer jar is what installs the loader + creates the launcher profile
    on a client. The server-side install deletes it after use, so we re-fetch it
    from Maven and cache it under .cache/ for the download endpoints.
    """
    loader = getattr(cfg, "loader", "neoforge") or "neoforge"
    cache_dir = CWD / ".cache" / "loader_installer"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if loader == "neoforge":
        # Resolve the installed NeoForge version (matching mc_version).
        lib = CWD / "libraries" / "net" / "neoforged" / "neoforge"
        versions = sorted((d.name for d in lib.iterdir() if d.is_dir()), reverse=True) if lib.exists() else []
        if not versions:
            return None
        ver = versions[0]
        jar_name = f"neoforge-{ver}-installer.jar"
        cached = cache_dir / jar_name
        if cached.exists() and cached.stat().st_size > 10_000:
            return cached
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{ver}/{jar_name}"
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if len(data) > 10_000:
                cached.write_bytes(data)
                return cached
        except Exception as e:
            log_event("LOADER_INSTALLER", f"Failed to download {jar_name}: {e}")
        return None

    if loader == "fabric":
        return None  # Fabric installer is fetched by the client installer differently
    if loader == "forge":
        return None
    return None


def build_launcher_zip_bytes(cfg: ServerConfig | None = None) -> io.BytesIO | None:
    """Build the client launcher zip: README + mods/ (server+clientonly jars) + config/ + defaultconfigs/.

    This is the 'drop into .minecraft' pack. Returns in-memory bytes.
    """
    if cfg is None:
        cfg = load_cfg()

    mods_dir = Path(cfg.mods_dir)
    if not mods_dir.is_absolute():
        mods_dir = CWD / mods_dir
    clientonly_dir = Path(cfg.clientonly_dir)
    if not clientonly_dir.is_absolute():
        clientonly_dir = CWD / clientonly_dir

    mc_version = getattr(cfg, 'mc_version', None) or '1.21.11'
    loader = getattr(cfg, 'loader', 'neoforge') or 'neoforge'
    installer = _loader_installer_path(cfg)

    readme = (
        "NeoRunner modpack\n"
        "=================\n\n"
        "To install:\n"
        "  1. Run " + (installer.name if installer else "the loader installer") + " to install " + loader + " (this creates the launcher profile).\n"
        "  2. Open your .minecraft folder (Windows: %appdata%\\.minecraft)\n"
        "  3. Unzip the contents of this file INTO .minecraft so that the\n"
        "     'mods' and 'config' folders land next to 'saves'.\n"
        "  4. Launch Minecraft with the " + loader + " profile and join the server!\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zi = zipfile.ZipInfo("README.txt", date_time=(2020, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zi, readme)

        # Include the loader client installer at the zip root so the client can
        # install the loader + create the launcher profile.
        if installer is not None and installer.exists():
            zf.write(str(installer), arcname=installer.name)

        for d in (mods_dir, clientonly_dir):
            if d.exists():
                for f in sorted(d.glob("*.jar")):
                    if f.name.endswith(".server.jar"):
                        continue
                    zf.write(str(f), arcname=f"mods/{f.name}")

        # Ship client-facing asset folders extracted from CurseForge overrides/:
        # config/defaultconfigs plus shaderpacks and resourcepacks.
        for folder in ("config", "defaultconfigs", "shaderpacks", "resourcepacks"):
            path = CWD / folder
            if path.exists():
                for f in sorted(path.rglob("*")):
                    if f.is_file():
                        zf.write(str(f), arcname=f"{folder}/{f.relative_to(path)}")

    buf.seek(0)
    log_event("MOD_ZIP", f"Built launcher.zip for {loader} {mc_version}" + (" (with installer)" if installer else ""))
    return buf


def generate_powershell_script(cfg: ServerConfig) -> str:
    """Generate PowerShell install script for Windows."""
    hostname = _get_server_hostname(cfg)
    base_url = f"https://{hostname}" if hostname else f"http://localhost:{cfg.http_port}"
    
    return '''param(
    [string]$BaseUrl = "''' + base_url + '''"
)

$ErrorActionPreference = "Continue"

$baseUrl = $BaseUrl
$mcDir = "$env:APPDATA\\.minecraft"
$modsDir = "$mcDir\\mods"
$oldDir = "$mcDir\\oldmods"

if (-not (Test-Path $modsDir)) { New-Item -ItemType Directory -Path $modsDir -Force | Out-Null }
if (-not (Test-Path $oldDir)) { New-Item -ItemType Directory -Path $oldDir -Force | Out-Null }

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  NeoRunner Mod Sync" -ForegroundColor Green
Write-Host "  Server: $baseUrl" -ForegroundColor Gray
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
    base_url = f"https://{hostname}" if hostname else f"http://localhost:{cfg.http_port}"
    
    return f'''#!/bin/bash
# NeoRunner Mod Installer for Linux/Mac

BASE_URL="{base_url}"

# Detect Minecraft directory
if [[ "$OSTYPE" == "darwin"* ]]; then
    MINECRAFT_DIR="$HOME/Library/Application Support/minecraft"
else
    MINECRAFT_DIR="$HOME/.minecraft"
fi

MODS_DIR="$MINECRAFT_DIR/mods"

echo "═══════════════════════════════════════════"
echo "  NeoRunner Mod Installer"
echo "  Server: $BASE_URL"
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
    except Exception:
        pass
    
    # Fallback to auto-detect
    return _get_local_ip()


def generate_bat_script(cfg: ServerConfig) -> str:
    """Generate batch script (install-mods.bat) that downloads only missing mods from server."""
    hostname = _get_server_hostname(cfg)
    # Public clients reach the download endpoints over HTTPS through the
    # Cloudflare tunnel (https://<hostname>), not the internal HTTP port.
    base_url = f"https://{hostname}" if hostname else f"http://localhost:{cfg.http_port}"
    
    return '''@echo off
REM install-mods.bat - NeoRunner Client Mod Sync Script
setlocal enabledelayedexpansion

set "BASE_URL=''' + base_url + '''"

echo ==========================================
echo    NeoRunner Mod Sync
echo    Server: %BASE_URL%
echo ==========================================
echo.

set "MINECRAFT=%APPDATA%\\.minecraft"
set "MODS_DIR=%MINECRAFT%\\mods"
set "OLD_DIR=%MINECRAFT%\\oldmods"

if not exist "%MODS_DIR%" mkdir "%MODS_DIR%"
if not exist "%OLD_DIR%" mkdir "%OLD_DIR%"

echo [1/4] Fetching server manifest...
curl.exe -s "%BASE_URL%/download/manifest" -o "%TEMP%\\neorunner_manifest.json"
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
    curl.exe -sL "%BASE_URL%/download/all" -o "%TEMP%\\neorunner_mods.zip"
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


def adoptium_jre_url(os_name: str, arch: str, java_major: int = 21) -> str:
    """Adoptium (Temurin) JRE download URL for a given OS/arch.

    Returns a ``*.zip`` (Windows) or ``*.tar.gz`` (Linux/macOS) URL. OS names:
    ``windows``, ``linux``, ``mac``; arch: ``x64``, ``aarch64``, ``x86``, ``arm``.
    """
    return (
        f"https://api.adoptium.net/v3/binary/latest/{java_major}/ga/"
        f"{os_name}/{arch}/jre/hotspot/normal/eclipse"
    )


# Java (Temurin) installers bundled into mods.zip so Java-less clients can
# install a JRE before running the installer JAR. Windows/macOS use the native
# installers; Linux uses the portable tarball.
_JAVA_INSTALLER_SPECS: dict[str, tuple[str, str]] = {
    # name -> (adoptium url, filename in the zip)
    "windows": (
        "https://api.adoptium.net/v3/installer/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse",
        "java-windows-x64.msi",
    ),
    "mac": (
        "https://api.adoptium.net/v3/installer/latest/21/ga/mac/x64/jre/hotspot/normal/eclipse",
        "java-mac-x64.pkg",
    ),
    "linux": (
        "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jre/hotspot/normal/eclipse",
        "java-linux-x64.tar.gz",
    ),
}


def _java_installer_cache_dir() -> Path:
    return CWD / ".cache" / "java_installers"


def _download_binary(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.4.7 installer"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _ensure_java_installers() -> dict[str, Path]:
    """Download (and cache) the Temurin JRE installers for windows/mac/linux."""
    cache = _java_installer_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name, (url, filename) in _JAVA_INSTALLER_SPECS.items():
        dest = cache / filename
        if dest.exists() and dest.stat().st_size > 10_000_000:
            out[name] = dest
            continue
        log_event("MOD_ZIP", f"Downloading Java installer ({name})...")
        try:
            _download_binary(url, dest)
            out[name] = dest
        except Exception as e:
            log_event("MOD_ZIP", f"Failed to download Java installer ({name}): {e}")
    return out


def _mods_bundle_readme(cfg: ServerConfig, installer_jar_name: str) -> str:
    from .mod_hosting import _get_server_hostname  # local import avoids cycles
    host = _get_server_hostname(cfg) or DEFAULT_PUBLIC_HOST
    address = host
    try:
        mc_port = int(getattr(cfg, "mc_port", 25565) or 25565)
        if mc_port != 25565:
            address = f"{host}:{mc_port}"
    except Exception:
        pass
    return f"""NeoRunner modpack installer
================================

This bundle contains:
  - {installer_jar_name}   (the one-click installer: NeoForge loader + all mods, configs and shaderpacks)
  - java/                  (Java 21 runtimes for Windows, macOS and Linux)

How to install
--------------
1. If you don't already have Java 21 installed, install it:
     Windows:  run  java\\java-windows-x64.msi
     macOS:    run  java\\java-mac-x64.pkg
     Linux:    extract java\\java-linux-x64.tar.gz and add its bin/ folder to your PATH
2. Run the installer:
     Double-click {installer_jar_name}  (or run: java -jar {installer_jar_name})
3. Launch Minecraft and connect to: {address}

Need help? Re-download the latest bundle at any time.
"""


def build_mods_bundle_zip(cfg: ServerConfig) -> Path:
    """Build (and cache) the all-in-one ``mods.zip`` bundle.

    Contains the self-contained installer JAR plus Java 21 installers for
    Windows/macOS/Linux, so a client without Java can still get going.
    """
    from .installer_jar import build_installer_jar

    jar = build_installer_jar(cfg)
    jre = _ensure_java_installers()

    cache_dir = _java_installer_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    bundle = cache_dir / f"mods-{jar.stem}.zip"

    if bundle.exists() and bundle.stat().st_size > 0:
        return bundle

    tmp = bundle.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(jar, arcname=jar.name)
        for name, path in sorted(jre.items()):
            zf.write(path, arcname=f"java/{path.name}")
        zf.writestr("README.txt", _mods_bundle_readme(cfg, jar.name))
    shutil.move(str(tmp), str(bundle))
    log_event("MOD_ZIP", f"Built mods.zip bundle ({bundle.stat().st_size / 1e6:.1f} MB)")
    return bundle


def _client_base_url(cfg: ServerConfig) -> str:
    hostname = _get_server_hostname(cfg)
    return f"https://{hostname}" if hostname else f"http://{_get_local_ip()}:{cfg.http_port}"


def generate_java_bootstrap_sh(cfg: ServerConfig) -> str:
    """Native (shell) bootstrap for macOS/Linux that ensures Java then runs the
    self-contained installer JAR.

    A plain JAR cannot run without Java, so this native launcher checks for a
    JVM first and, if none is present, downloads a portable Temurin JRE, then
    runs the installer with it.
    """
    base = _client_base_url(cfg)
    return f'''#!/bin/bash
# NeoRunner modpack installer bootstrap (macOS / Linux)
set -e
BASE_URL="{base}"

echo "== NeoRunner modpack installer =="

JAVA_BIN=""
if command -v java >/dev/null 2>&1; then
    JAVA_BIN="java"
else
    echo "Java not found - downloading a portable JRE..."
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    case "$(uname -m)" in
        x86_64|amd64) ARCH=x64 ;;
        aarch64|arm64) ARCH=aarch64 ;;
        *) ARCH=x64 ;;
    esac
    case "$OS" in
        darwin) OS_NAME=mac ;;
        *) OS_NAME=linux ;;
    esac
    JRE_URL="https://api.adoptium.net/v3/binary/latest/21/ga/$OS_NAME/$ARCH/jre/hotspot/normal/eclipse"
    JRE_DIR="${{TMPDIR:-/tmp}}/neorunner-jre"
    JRE_ARCHIVE="${{TMPDIR:-/tmp}}/neorunner-jre.tar.gz"
    echo "  Downloading JRE ($OS_NAME/$ARCH)..."
    if command -v curl >/dev/null 2>&1; then
        curl -fL "$JRE_URL" -o "$JRE_ARCHIVE"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$JRE_URL" -O "$JRE_ARCHIVE"
    else
        echo "ERROR: need curl or wget to download Java" >&2
        exit 1
    fi
    rm -rf "$JRE_DIR" && mkdir -p "$JRE_DIR"
    tar -xzf "$JRE_ARCHIVE" -C "$JRE_DIR" --strip-components=1
    JAVA_BIN="$JRE_DIR/bin/java"
fi

echo "Downloading installer..."
INSTALLER="${{TMPDIR:-/tmp}}/neorunner-installer.jar"
if command -v curl >/dev/null 2>&1; then
    curl -fL "$BASE_URL/download/installer.jar" -o "$INSTALLER"
else
    wget -q "$BASE_URL/download/installer.jar" -O "$INSTALLER"
fi

echo "Running installer (Java: $($JAVA_BIN -version 2>&1 | head -1))..."
"$JAVA_BIN" -jar "$INSTALLER" "$@"
'''


def generate_java_bootstrap_bat(cfg: ServerConfig) -> str:
    """Native (batch) bootstrap for Windows that ensures Java then runs the
    self-contained installer JAR (delegates JRE download to PowerShell)."""
    base = _client_base_url(cfg)
    return f'''@echo off
setlocal EnableDelayedExpansion
REM NeoRunner modpack installer bootstrap (Windows)
set "BASE_URL={base}"

echo == NeoRunner modpack installer ==

where java >nul 2>&1
if %errorlevel%==0 (
    set "JAVA_CMD=java"
    goto :download
)

echo Java not found - downloading a portable JRE...
set "JRE_DIR=%TEMP%\\neorunner-jre"
set "JRE_ZIP=%TEMP%\\neorunner-jre.zip"

REM Detect arch and download Temurin JRE via PowerShell
powershell -NoProfile -Command "$u = if ([Environment]::Is64BitOperatingSystem) {{ 'https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse' }} else {{ 'https://api.adoptium.net/v3/binary/latest/21/ga/windows/x86/jre/hotspot/normal/eclipse' }}; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri $u -OutFile '%JRE_ZIP%' -UseBasicParsing"
if not exist "%JRE_ZIP%" (
    echo ERROR: failed to download Java
    pause
    exit /b 1
)
powershell -NoProfile -Command "Expand-Archive -Path '%JRE_ZIP%' -DestinationPath '%JRE_DIR%' -Force"
if not exist "%JRE_DIR%" (
    echo ERROR: failed to extract Java
    pause
    exit /b 1
)
REM The zip extracts to a single jdk-* directory
for /d %%D in ("%JRE_DIR%\\jdk*") do set "JAVA_CMD=%%D\\bin\\java.exe"
if not defined JAVA_CMD (
    echo ERROR: could not locate java.exe in extracted JRE
    pause
    exit /b 1
)

:download
echo Downloading installer...
set "INSTALLER=%TEMP%\\neorunner-installer.jar"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%BASE_URL%/download/installer.jar' -OutFile '%INSTALLER%' -UseBasicParsing"
if not exist "%INSTALLER%" (
    echo ERROR: failed to download installer
    pause
    exit /b 1
)

echo Running installer...
"%JAVA_CMD%" -jar "%INSTALLER%" %*
pause
'''
