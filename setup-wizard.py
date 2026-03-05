#!/usr/bin/env python3
"""
Interactive setup wizard for NeoRunner.
Guides users through initial configuration and installation.
"""

from __future__ import annotations

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from neorunner import load_cfg, save_cfg, ServerConfig
from neorunner.constants import CWD
from neorunner.log import log_event


class Colors:
    """Terminal colors."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{Colors.HEADER}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{text.center(70)}{Colors.END}")
    print(f"{Colors.HEADER}{'='*70}{Colors.END}\n")


def print_step(step_num: int, total: int, text: str):
    """Print a step header."""
    print(f"\n{Colors.CYAN}[Step {step_num}/{total}] {text}{Colors.END}")
    print("-" * 70)


def print_success(text: str):
    """Print success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_warning(text: str):
    """Print warning message."""
    print(f"{Colors.WARNING}⚠ {text}{Colors.END}")


def print_error(text: str):
    """Print error message."""
    print(f"{Colors.FAIL}✗ {text}{Colors.END}")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{prompt} [{default_str}]: ").strip().lower()
    
    if not response:
        return default
    
    return response in ['y', 'yes']


def ask_input(prompt: str, default: str = "") -> str:
    """Ask for input with default value."""
    if default:
        response = input(f"{prompt} [{default}]: ").strip()
        return response if response else default
    else:
        return input(f"{prompt}: ").strip()


def ask_choice(prompt: str, choices: list, default: int = 0) -> int:
    """Ask user to choose from list."""
    print(f"\n{prompt}")
    for i, choice in enumerate(choices, 1):
        marker = " (default)" if i-1 == default else ""
        print(f"  {i}. {choice}{marker}")
    
    while True:
        try:
            response = input(f"Enter choice [1-{len(choices)}]: ").strip()
            if not response:
                return default
            
            choice = int(response) - 1
            if 0 <= choice < len(choices):
                return choice
            else:
                print_error("Invalid choice")
        except ValueError:
            print_error("Please enter a number")


def check_system_deps() -> Dict[str, bool]:
    """Check which system dependencies are installed."""
    deps = {
        "java": shutil.which("java") is not None,
        "tmux": shutil.which("tmux") is not None,
        "curl": shutil.which("curl") is not None,
        "rsync": shutil.which("rsync") is not None,
        "unzip": shutil.which("unzip") is not None,
        "zip": shutil.which("zip") is not None,
    }
    return deps


def install_system_deps() -> bool:
    """Install missing system dependencies."""
    print_step(2, 7, "Installing System Dependencies")
    
    # Detect package manager
    pkg_managers = {
        "apt": shutil.which("apt-get"),
        "dnf": shutil.which("dnf"),
        "pacman": shutil.which("pacman"),
        "yum": shutil.which("yum"),
    }
    
    available = [(name, path) for name, path in pkg_managers.items() if path]
    
    if not available:
        print_error("No supported package manager found")
        print("Please install the following manually:")
        print("  - Java 21 (openjdk-21-jre-headless)")
        print("  - tmux, curl, rsync, unzip, zip")
        return False
    
    pkg_name, pkg_path = available[0]
    print(f"Detected package manager: {pkg_name}")
    
    packages = ["tmux", "curl", "rsync", "unzip", "zip"]
    
    # Check if Java is installed
    if not shutil.which("java"):
        if pkg_name in ["apt", "dnf", "yum"]:
            packages.append("openjdk-21-jre-headless")
        elif pkg_name == "pacman":
            packages.append("jre21-openjdk-headless")
    
    print(f"Installing: {', '.join(packages)}")
    
    try:
        if pkg_name == "apt":
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            subprocess.run(["sudo", "apt-get", "install", "-y"] + packages, check=True)
        elif pkg_name == "dnf":
            subprocess.run(["sudo", "dnf", "install", "-y"] + packages, check=True)
        elif pkg_name == "pacman":
            subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"] + packages, check=True)
        elif pkg_name == "yum":
            subprocess.run(["sudo", "yum", "install", "-y"] + packages, check=True)
        
        print_success("System dependencies installed")
        return True
    
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to install dependencies: {e}")
        return False


def configure_server() -> ServerConfig:
    """Interactive server configuration."""
    print_step(3, 7, "Server Configuration")
    
    cfg = ServerConfig()
    
    # Minecraft version
    cfg.mc_version = ask_input("Minecraft version", "1.21.11")
    
    # Loader selection
    loaders = ["NeoForge", "Forge", "Fabric"]
    loader_idx = ask_choice("Select mod loader:", loaders, default=0)
    cfg.loader = loaders[loader_idx].lower()
    
    # Ports
    print("\nPort configuration (press Enter for defaults):")
    cfg.http_port = int(ask_input("HTTP/Dashboard port", "8000") or "8000")
    cfg.mc_port = int(ask_input("Minecraft server port", "25565") or "25565")
    cfg.rcon_port = int(ask_input("RCON port", "25575") or "25575")
    
    # RCON password
    cfg.rcon_pass = ask_input("RCON password", "1")
    
    # Server name/MOTD
    cfg.hostname = ask_input("Server hostname/IP (for client scripts)", "localhost")
    
    # Ferium settings
    if ask_yes_no("Enable automatic mod updates?", default=True):
        cfg.ferium_enable_scheduler = True
        
        intervals = ["1 hour", "2 hours", "4 hours", "6 hours", "12 hours", "24 hours"]
        interval_idx = ask_choice("Update interval:", intervals, default=2)
        interval_map = [1, 2, 4, 6, 12, 24]
        cfg.ferium_update_interval_hours = interval_map[interval_idx]
        
        print("\nWeekly update schedule:")
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_idx = ask_choice("Day for weekly compatibility check:", days, default=0)
        cfg.ferium_weekly_update_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day_idx]
        cfg.ferium_weekly_update_hour = int(ask_input("Hour for weekly update (0-23)", "2") or "2")
    
    return cfg


def create_directories(cfg: ServerConfig):
    """Create required directories."""
    print_step(4, 7, "Creating Directories")
    
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
        print(f"  Created: {d}")
    
    print_success("Directories created")


def create_eula():
    """Create EULA file."""
    print_step(5, 7, "EULA Agreement")
    
    print("\nBy running this Minecraft server, you agree to the Minecraft EULA.")
    print("Read it at: https://account.mojang.com/documents/minecraft_eula")
    
    if ask_yes_no("Do you agree to the EULA?", default=True):
        eula_path = CWD / "eula.txt"
        eula_path.write_text("eula=true\n")
        print_success("EULA accepted")
    else:
        print_error("You must accept the EULA to run the server")
        sys.exit(1)


def install_mod_loader(cfg: ServerConfig) -> bool:
    """Install the selected mod loader."""
    print_step(6, 7, f"Installing {cfg.loader.title()}")
    
    from neorunner.installer import install_loader
    
    if install_loader(cfg):
        print_success(f"{cfg.loader.title()} installed successfully")
        return True
    else:
        print_error(f"Failed to install {cfg.loader}")
        return False


def create_service_file():
    """Create systemd service file."""
    print_step(7, 7, "Creating Systemd Service")
    
    service_content = f"""[Unit]
Description=Minecraft {cfg.loader} {cfg.mc_version} Server (NeoRunner)
After=network.target

[Service]
Type=simple
WorkingDirectory={CWD}
ExecStart=/usr/bin/python3 -m neorunner start
Restart=always
RestartSec=10
StandardOutput=append:{CWD}/live.log
StandardError=append:{CWD}/live.log
Environment="NEORUNNER_HOME={CWD}"
Environment="PYTHONPATH={CWD}"

[Install]
WantedBy=default.target
"""
    
    service_path = Path.home() / ".config" / "systemd" / "user" / "mcserver.service"
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service_content)
    
    print_success(f"Service file created: {service_path}")
    print("\nTo manage the service:")
    print(f"  {Colors.CYAN}systemctl --user start mcserver{Colors.END}")
    print(f"  {Colors.CYAN}systemctl --user stop mcserver{Colors.END}")
    print(f"  {Colors.CYAN}systemctl --user status mcserver{Colors.END}")
    print(f"\nTo enable auto-start on boot:")
    print(f"  {Colors.CYAN}systemctl --user enable mcserver{Colors.END}")


def setup_ferium_profile(cfg: ServerConfig):
    """Setup ferium mod manager profile."""
    print("\n" + "="*70)
    print("FERIUM MOD MANAGER SETUP")
    print("="*70)
    
    from neorunner.ferium import setup_ferium_wizard
    
    try:
        cfg = setup_ferium_wizard(cfg)
        save_cfg(cfg)
        print_success("Ferium configured")
    except Exception as e:
        print_warning(f"Ferium setup incomplete: {e}")
        print("You can configure it later from the dashboard")


def main():
    """Run the interactive setup wizard."""
    print_header("NeoRunner Interactive Setup Wizard")
    
    print("This wizard will guide you through setting up your Minecraft server.")
    print(f"Working directory: {Colors.CYAN}{CWD}{Colors.END}")
    
    if not ask_yes_no("\nContinue with setup?", default=True):
        print("Setup cancelled.")
        return
    
    # Step 1: Check dependencies
    print_step(1, 7, "Checking System Dependencies")
    deps = check_system_deps()
    
    print("Checking installed dependencies:")
    for dep, installed in deps.items():
        if installed:
            print_success(f"{dep}: installed")
        else:
            print_warning(f"{dep}: missing")
    
    if not all(deps.values()):
        if ask_yes_no("\nInstall missing dependencies?", default=True):
            if not install_system_deps():
                print_warning("Some dependencies may need to be installed manually")
        else:
            print_warning("Continuing without all dependencies - server may not work properly")
    
    # Step 2-3: Configure server
    global cfg
    cfg = configure_server()
    
    # Step 4: Create directories
    create_directories(cfg)
    
    # Step 5: EULA
    create_eula()
    
    # Step 6: Install loader
    if not install_mod_loader(cfg):
        print_warning("Loader installation failed - you can retry later")
    
    # Step 7: Create service
    if ask_yes_no("\nCreate systemd service file?", default=True):
        create_service_file()
    
    # Setup ferium
    if ask_yes_no("\nConfigure Ferium mod manager?", default=True):
        setup_ferium_profile(cfg)
    
    # Save configuration
    save_cfg(cfg)
    
    # Final message
    print_header("Setup Complete!")
    
    print(f"\n{Colors.GREEN}Your Minecraft server has been configured!{Colors.END}\n")
    print("Next steps:")
    print(f"  1. Access the dashboard: {Colors.CYAN}http://localhost:{cfg.http_port}{Colors.End}")
    print(f"  2. Start the server: {Colors.CYAN}systemctl --user start mcserver{Colors.END}")
    print(f"  3. View logs: {Colors.CYAN}tail -f {CWD}/live.log{Colors.END}")
    print(f"  4. Add mods through the dashboard or place them in {CWD}/{cfg.mods_dir}/")
    
    print(f"\n{Colors.BOLD}Enjoy your Minecraft server!{Colors.END}\n")


if __name__ == "__main__":
    main()
