"""Installation and setup for NeoRunner."""

from __future__ import annotations

import os
import re
import subprocess
import urllib.request
import json
import shutil
from pathlib import Path
from typing import Optional

from .constants import CWD, MOD_LOADERS
from .config import ServerConfig
from .log import log_event


SYSTEM_PACKAGES = ["curl", "rsync", "unzip", "zip", "java"]


def check_system_deps() -> bool:
    """Check if required system dependencies are installed."""
    missing = []
    for pkg in SYSTEM_PACKAGES:
        result = subprocess.run(["which", pkg], capture_output=True)
        if result.returncode != 0:
            missing.append(pkg)
    return len(missing) == 0


def install_system_deps() -> bool:
    """Install required system dependencies."""
    log_event("INFO", "Installing system dependencies...")
    
    # Detect package manager
    if shutil.which("apt"):
        pkg_mgr = "apt"
    elif shutil.which("dnf"):
        pkg_mgr = "dnf"
    elif shutil.which("pacman"):
        pkg_mgr = "pacman"
    elif shutil.which("yum"):
        pkg_mgr = "yum"
    else:
        log_event("ERROR", "No supported package manager found")
        return False
    
    try:
        if pkg_mgr == "apt":
            subprocess.run(["sudo", "apt", "update"], check=True, capture_output=True)
            subprocess.run(["sudo", "apt", "install", "-y"] + SYSTEM_PACKAGES, check=True)
        elif pkg_mgr == "dnf":
            subprocess.run(["sudo", "dnf", "install", "-y"] + SYSTEM_PACKAGES, check=True)
        elif pkg_mgr == "pacman":
            subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"] + SYSTEM_PACKAGES, check=True)
        elif pkg_mgr == "yum":
            subprocess.run(["sudo", "yum", "install", "-y"] + SYSTEM_PACKAGES, check=True
            )
        log_event("INFO", "System dependencies installed")
        return True
    except subprocess.CalledProcessError as e:
        log_event("ERROR", f"Failed to install deps: {e}")
        return False


def ensure_eula(cfg: ServerConfig) -> None:
    """Ensure eula.txt exists with eula=true."""
    eula_path = CWD / "eula.txt"
    
    if not eula_path.exists():
        eula_path.write_text("eula=true\n")
        log_event("INFO", "Created eula.txt with eula=true")
    else:
        content = eula_path.read_text()
        if "eula=false" in content.lower():
            eula_path.write_text(content.replace("eula=false", "eula=true"))
            log_event("INFO", "Updated eula.txt to eula=true")


def ensure_directories(cfg: ServerConfig) -> None:
    """Create required directories."""
    dirs = [
        CWD / cfg.mods_dir,
        CWD / cfg.clientonly_dir,
        CWD / cfg.quarantine_dir,
        CWD / "libraries",
        CWD / "backups",
        CWD / "config",
        CWD / "logs",
        CWD / "crash-reports",
    ]
    
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def install_neoforge(cfg: ServerConfig) -> bool:
    """Download and install NeoForge server."""
    mc_version = cfg.mc_version
    loader_dir = CWD / "libraries" / "net" / "neoforged" / "neoforge"
    
    if loader_dir.exists():
        log_event("INFO", "NeoForge already installed")
        return True
    
    log_event("INFO", f"Installing NeoForge for MC {mc_version}...")
    
    # Determine NeoForge version
    mc_parts = mc_version.split(".")
    prefix = f"{mc_parts[1]}.{mc_parts[2]}" if len(mc_parts) >= 3 else "21.11"
    
    # Fetch latest version from Maven
    neo_version = None
    try:
        versions_url = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
        req = urllib.request.Request(versions_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            versions_data = json.loads(resp.read().decode())
            matching = [v for v in versions_data.get("versions", []) if v.startswith(prefix)]
            if matching:
                neo_version = matching[-1]
    except Exception as e:
        log_event("ERROR", f"Version lookup failed: {e}")
    
    if not neo_version:
        log_event("ERROR", f"No NeoForge version found for MC {mc_version}")
        return False
    
    # Download installer
    installer_jar = f"neoforge-{neo_version}-installer.jar"
    installer_url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{neo_version}/{installer_jar}"
    installer_path = CWD / installer_jar
    
    try:
        log_event("INFO", f"Downloading NeoForge {neo_version}...")
        req = urllib.request.Request(installer_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
            if len(data) < 10000:
                log_event("ERROR", "Download too small, likely 404")
                return False
            installer_path.write_bytes(data)
        
        # Run installer
        log_event("INFO", "Running installer...")
        result = subprocess.run(
            ["java", "-jar", installer_jar, "--installServer"],
            cwd=CWD, capture_output=True, text=True, timeout=600
        )
        
        installer_path.unlink()
        
        if loader_dir.exists():
            log_event("INFO", f"NeoForge {neo_version} installed")
            # Update config with the correct server_jar path
            from .config import load_cfg, save_cfg
            cfg = load_cfg()
            server_jar_path = str(loader_dir / f"neoforge-{neo_version}-universal.jar")
            cfg.server_jar = server_jar_path
            # Also set server_port from version if needed
            save_cfg(cfg)
            log_event("INFO", f"Config updated: server_jar={server_jar_path}")
            return True
        else:
            log_event("ERROR", f"Install failed: {result.stderr[:500]}")
            return False
    except Exception as e:
        log_event("ERROR", f"Failed: {e}")
        if installer_path.exists():
            installer_path.unlink()
        return False


def install_fabric(cfg: ServerConfig) -> bool:
    """Download and install Fabric server."""
    import urllib.request
    import shutil
    
    log_event("INFO", f"Installing Fabric for MC {cfg.mc_version}...")
    
    mc_version = cfg.mc_version
    loader_dir = CWD / "libraries" / "net" / "fabricmc" / "yarn" / f"{mc_version}+build.1" / "v2"
    installer_path = None
    
    if loader_dir.exists():
        log_event("INFO", "Fabric already installed")
        return True
    
    try:
        # Get Fabric loader version
        versions_url = "https://meta.fabricmc.net/v2/versions/loader"
        req = urllib.request.Request(versions_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            versions_data = json.loads(resp.read().decode())
        
        if not versions_data:
            log_event("ERROR", "No Fabric versions found")
            return False
        
        loader_version = versions_data[0]["version"]
        installer_url = f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_version}/server/jar"
        installer_path = CWD / f"fabric-server-{mc_version}-{loader_version}-launcher.jar"
        
        # Download installer
        log_event("INFO", f"Downloading Fabric {loader_version}...")
        req = urllib.request.Request(installer_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
            if len(data) < 1000:
                log_event("ERROR", "Download too small, likely 404")
                return False
            installer_path.write_bytes(data)
        
        # Run installer
        log_event("INFO", "Running Fabric installer...")
        result = subprocess.run(
            ["java", "-jar", str(installer_path), "--installServer"],
            cwd=CWD, capture_output=True, text=True, timeout=600
        )
        
        installer_path.unlink()
        
        if loader_dir.exists():
            log_event("INFO", f"Fabric {loader_version} installed")
            return True
        else:
            log_event("ERROR", f"Install failed: {result.stderr[:500]}")
            return False
    except Exception as e:
        log_event("ERROR", f"Failed: {e}")
        if installer_path and installer_path.exists():
            installer_path.unlink()
        return False


def install_forge(cfg: ServerConfig) -> bool:
    """Download and install Forge server."""
    import urllib.request
    
    log_event("INFO", f"Installing Forge for MC {cfg.mc_version}...")
    
    mc_version = cfg.mc_version
    mc_parts = mc_version.split(".")
    version_major = f"{mc_parts[1]}.{mc_parts[2]}" if len(mc_parts) >= 3 else mc_version
    installer_path = None
    
    mc_version = cfg.mc_version
    mc_parts = mc_version.split(".")
    version_major = f"{mc_parts[1]}.{mc_parts[2]}" if len(mc_parts) >= 3 else mc_version
    
    # Determine Forge version - need to find installer
    forge_version = None
    try:
        # Try Maven Central for Forge versions
        versions_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.json"
        req = urllib.request.Request(versions_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            versions_data = json.loads(resp.read().decode())
            versions = versions_data.get("versions", [])
            # Find version matching our MC version
            for v in reversed(versions):
                if version_major in v:
                    forge_version = v
                    break
    except Exception as e:
        log_event("WARN", f"Could not fetch Forge versions: {e}")
    
    if not forge_version:
        log_event("ERROR", f"No Forge version found for MC {mc_version}")
        return False
    
    try:
        # Download installer
        installer_jar = f"forge-{forge_version}-installer.jar"
        installer_url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{forge_version}/{installer_jar}"
        installer_path = CWD / installer_jar
        
        log_event("INFO", f"Downloading Forge {forge_version}...")
        req = urllib.request.Request(installer_url, headers={"User-Agent": "NeoRunner/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
            if len(data) < 1000:
                log_event("ERROR", "Download too small, likely 404")
                return False
            installer_path.write_bytes(data)
        
        # Run installer
        log_event("INFO", "Running Forge installer...")
        result = subprocess.run(
            ["java", "-jar", installer_jar, "--installServer"],
            cwd=CWD, capture_output=True, text=True, timeout=600
        )
        
        installer_path.unlink()
        
        loader_dir = CWD / "libraries" / "net" / "minecraftforge" / "forge" / forge_version
        if loader_dir.exists():
            log_event("INFO", f"Forge {forge_version} installed")
            return True
        else:
            log_event("ERROR", f"Install failed: {result.stderr[:500]}")
            return False
    except Exception as e:
        log_event("ERROR", f"Failed: {e}")
        if installer_path and installer_path.exists():
            installer_path.unlink()
        return False


def install_loader(cfg: ServerConfig) -> bool:
    """Install the required loader based on config."""
    loader = cfg.loader.lower()
    
    if loader == "neoforge":
        return install_neoforge(cfg)
    elif loader == "fabric":
        return install_fabric(cfg)
    elif loader == "forge":
        return install_forge(cfg)
    else:
        log_event("ERROR", f"Unknown loader: {loader}")
        return False


def ensure_dependency(dep_name: str, cfg: ServerConfig) -> bool:
    """Search for and download a missing dependency using clientonly/Modrinth/CurseForge.
    
    Args:
        dep_name: Name of the dependency (e.g., "architectury")
        cfg: Server configuration
        
    Returns:
        True if dependency was found and downloaded, False otherwise
    """
    from .mod_browser import ModBrowser, ModInstaller, CurseForgeScraper, PLAYWRIGHT_AVAILABLE
    
    log_event("SELF_HEAL", f"Searching for missing dependency: {dep_name}")
    
    mods_dir = CWD / cfg.mods_dir
    if not mods_dir.exists():
        mods_dir.mkdir(parents=True, exist_ok=True)
    
    clientonly_dir = CWD / cfg.clientonly_dir
    search_name = dep_name.lower().replace("-", "").replace("_", "")
    
    if clientonly_dir.exists():
        for jar in clientonly_dir.glob("*.jar"):
            jar_name = jar.stem.lower().replace("-", "").replace("_", "")
            if search_name in jar_name or jar_name in search_name:
                dest = mods_dir / jar.name
                if not dest.exists():
                    shutil.copy2(jar, dest)
                    log_event("SELF_HEAL", f"Copied {jar.name} from clientonly/ to mods/")
                return True
    
    installer = ModInstaller(cfg)
    
    # First try Modrinth
    browser = ModBrowser(cfg)
    
    search_variations = [
        dep_name.lower(),
        dep_name.replace("-", " ").lower(),
        dep_name.replace("_", " ").lower(),
        f"{dep_name} api",
    ]
    
    for variation in search_variations:
        try:
            results = browser.search(variation, limit=5)
            if results:
                best_match = None
                for r in results:
                    title = r.name.lower()
                    slug = r.slug.lower()
                    search_term = variation.lower()
                    
                    if search_term in title or search_term in slug:
                        best_match = r
                        break
                
                if not best_match and results:
                    best_match = results[0]
                
                if best_match:
                    project_id = best_match.id
                    if project_id:
                        success, msg = installer.install_mod(project_id, "modrinth")
                        if success:
                            log_event("SELF_HEAL", f"Downloaded dependency: {best_match.name} ({dep_name})")
                            return True
                        else:
                            log_event("WARN", f"Failed to install {best_match.name}: {msg}")
        except Exception as e:
            log_event("WARN", f"Error searching Modrinth for {dep_name}: {e}")
            continue
    
    # Try CurseForge scraper if Playwright is available
    if PLAYWRIGHT_AVAILABLE:
        log_event("SELF_HEAL", f"Searching CurseForge for: {dep_name}")
        try:
            cf = CurseForgeScraper(cfg)
            cf_results = cf.search(dep_name, limit=5)
            
            for result in cf_results:
                # Try to get download from CurseForge
                try:
                    from playwright.sync_api import sync_playwright
                    from playwright_stealth import Stealth
                    
                    loader_id = 1754  # NeoForge
                    mc_version = cfg.mc_version
                    url = f"https://www.curseforge.com/minecraft/mc-mods/{result.slug}/files?gameVersion={mc_version}"
                    
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        )
                        page = context.new_page()
                        Stealth().apply_stealth_sync(page)
                        
                        try:
                            page.goto(url, timeout=30000)
                            page.wait_for_selector("tr.project-file-list-item", timeout=15000)
                        except:
                            browser.close()
                            continue
                        
                        rows = page.query_selector_all("tr.project-file-list-item")
                        for row in rows[:10]:
                            try:
                                version_el = row.query_selector("td.version-col")
                                if version_el:
                                    version_text = version_el.inner_text().strip()
                                    if mc_version in version_text and "NeoForge" in version_text:
                                        dl_link = row.query_selector("a.btn[href*='/download/']")
                                        if dl_link:
                                            dl_href = dl_link.get_attribute("href")
                                            if not dl_href:
                                                continue
                                            file_id_match = re.search(r'/download/(\d+)', dl_href)
                                            if file_id_match:
                                                file_id = file_id_match.group(1)
                                                download_url = f"https://www.curseforge.com{dl_href}"
                                                
                                                req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                                                with urllib.request.urlopen(req, timeout=60) as response:
                                                    final_url = response.geturl()
                                                    with urllib.request.urlopen(urllib.request.Request(final_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}), timeout=120) as dl_response:
                                                        filename = result.slug + ".jar"
                                                        file_path = mods_dir / filename
                                                        file_path.write_bytes(dl_response.read())
                                                        log_event("SELF_HEAL", f"Downloaded {filename} from CurseForge")
                                                        browser.close()
                                                        return True
                                                break
                            except:
                                continue
                        
                        browser.close()
                except Exception as e:
                    log_event("WARN", f"CurseForge download failed for {result.name}: {e}")
                    continue
        except Exception as e:
            log_event("WARN", f"CurseForge search failed for {dep_name}: {e}")
    
    log_event("ERROR", f"Could not find dependency: {dep_name}")
    return False


def ensure_dependencies(cfg: ServerConfig, required_deps: list[str]) -> int:
    """Ensure all required dependencies are installed.
    
    Args:
        cfg: Server configuration
        required_deps: List of dependency names to check/install
        
    Returns:
        Number of dependencies successfully installed
    """
    mods_dir = CWD / cfg.mods_dir
    existing_mods = set()
    
    if mods_dir.exists():
        for f in mods_dir.glob("*.jar"):
            name = f.stem.lower()
            for dep in required_deps:
                if dep.lower().replace("-", "").replace("_", "") in name.replace("-", "").replace("_", ""):
                    existing_mods.add(dep.lower())
    
    to_install = [d for d in required_deps if d.lower() not in existing_mods]
    
    installed = 0
    for dep in to_install:
        if ensure_dependency(dep, cfg):
            installed += 1
    
    return installed


def strip_client_classes(jar_path: Path) -> bool:
    """Strip client-side classes from a mod JAR to make it server-compatible.
    
    This removes classes that are only loaded on the client, allowing mods
    that have client-only components to run on dedicated servers.
    
    Args:
        jar_path: Path to the mod JAR file
        
    Returns:
        True if successfully stripped, False otherwise
    """
    import zipfile
    
    client_class_patterns = [
        "client/",
        "Client",
        "_client_",
        "clientonly",
    ]
    
    temp_path = jar_path.parent / f"{jar_path.stem}.tmp"
    stripped_path = jar_path.parent / f"{jar_path.stem}.server.jar"
    
    try:
        with zipfile.ZipFile(jar_path, 'r') as src_zip:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as dst_zip:
                for item in src_zip.infolist():
                    # Skip client-side files
                    should_skip = any(
                        pattern.lower() in item.filename.lower() 
                        for pattern in client_class_patterns
                    )
                    
                    # Also skip common client-only class patterns
                    if item.filename.endswith('.class'):
                        basename = os.path.basename(item.filename)
                        if 'client' in basename.lower() or basename.startswith('Client'):
                            should_skip = True
                    
                    if not should_skip:
                        dst_zip.writestr(item, src_zip.read(item.filename))
        
        # Replace original with stripped version
        if stripped_path.exists():
            stripped_path.unlink()
        temp_path.rename(stripped_path)
        
        log_event("SELF_HEAL", f"Stripped client classes from {jar_path.name} -> {stripped_path.name}")
        return True
        
    except Exception as e:
        log_event("ERROR", f"Failed to strip client classes from {jar_path.name}: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return False


def handle_client_only_mod(mod_name: str, reason: str, mods_dir: Path) -> bool:
    """Handle a mod that only has client-side components.
    
    1. Move original to clientonly/ for clients to download
    2. Create .server.jar version for server to run
    
    Args:
        mod_name: Name of the mod file
        reason: Reason for handling (e.g., "client-only classes")
        mods_dir: Path to mods directory
        
    Returns:
        True if successfully handled
    """
    jar_path = mods_dir / mod_name
    clientonly_dir = mods_dir / "clientonly"
    clientonly_dir.mkdir(exist_ok=True)
    
    if not jar_path.exists():
        return False
    
    # Skip if already processed
    if mod_name.endswith(".server.jar"):
        return True
    
    # Move original to clientonly/ for clients
    clientonly_path = clientonly_dir / mod_name
    if not clientonly_path.exists():
        shutil.move(str(jar_path), str(clientonly_path))
        log_event("SELF_HEAL", f"Moved {mod_name} to clientonly/ for client downloads")
    
    # Create .server.jar for server from the clientonly copy
    try:
        if strip_client_classes(clientonly_path):
            # Move stripped version to mods/
            stripped_path = clientonly_dir / f"{clientonly_path.stem}.server.jar"
            if stripped_path.exists():
                dest = mods_dir / stripped_path.name
                shutil.move(str(stripped_path), str(dest))
                log_event("SELF_HEAL", f"Created {stripped_path.name} for server")
            return True
        else:
            # If stripping fails, just use original in mods/
            shutil.move(str(clientonly_path), str(jar_path))
            log_event("WARN", f"Could not strip {mod_name}, using original")
            return False
    except Exception as e:
        log_event("ERROR", f"Failed to handle client-only mod {mod_name}: {e}")
        return False
    
    # Check if it's already a .server.jar
    if mod_name.endswith(".server.jar"):
        return True
    
    # Try to strip client classes
    if strip_client_classes(jar_path):
        return True
    
    # If stripping failed, leave the original
    log_event("WARN", f"Could not strip client classes from {mod_name}, keeping original")
    return False


def setup(cfg: ServerConfig) -> bool:
    """Run full setup process."""
    log_event("INFO", "Starting NeoRunner setup...")
    
    # Check/install system deps
    if not check_system_deps():
        if not install_system_deps():
            return False
    
    # Create directories
    ensure_directories(cfg)
    
    # Ensure EULA
    ensure_eula(cfg)
    
    # Install loader
    if not install_loader(cfg):
        return False
    
    log_event("INFO", "Setup complete!")
    return True
