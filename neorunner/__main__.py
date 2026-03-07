#!/usr/bin/env python3
"""
NeoRunner Entry Point - Complete Implementation

Handles:
1. System requirement checks
2. Package installation (bash + python)
3. First-start wizard (if no server.properties)
4. Normal startup (if server exists)
"""

import sys
import os
import subprocess
import shutil
from pathlib import Path

# Determine working directory - use the module location as server root
NEORUNNER_HOME = Path(__file__).parent.resolve()
os.chdir(NEORUNNER_HOME)
sys.path.insert(0, str(NEORUNNER_HOME))

from neorunner import load_cfg, save_cfg, ServerConfig, log_event
from neorunner.constants import CWD


def check_system_prerequisites():
    """Check system prerequisites and return missing items."""
    missing = {
        "packages": [],
        "python_modules": []
    }
    
    # Check system packages
    required_packages = {
        "java": ["java", "openjdk"],
        "tmux": ["tmux"],
        "curl": ["curl"],
        "rsync": ["rsync"],
        "unzip": ["unzip"],
        "zip": ["zip"],
    }
    
    for pkg_name, check_cmds in required_packages.items():
        found = False
        for cmd in check_cmds:
            if shutil.which(cmd):
                found = True
                break
        if not found:
            missing["packages"].append(pkg_name)
    
    # Check Python modules
    required_python = [
        "flask",
        "requests",
        "apscheduler",
    ]
    
    for module in required_python:
        try:
            __import__(module)
        except ImportError:
            missing["python_modules"].append(module)
    
    return missing


def get_package_install_commands():
    """Get installation commands for current system."""
    commands = {
        "packages": {},
        "java_package": ""
    }
    
    # Detect package manager and Java package
    if shutil.which("apt-get"):
        commands["packages"]["apt-get"] = "sudo apt-get update && sudo apt-get install -y tmux curl rsync unzip zip"
        commands["java_package"] = "openjdk-21-jre-headless"
        commands["install_java"] = "sudo apt-get install -y openjdk-21-jre-headless"
    
    elif shutil.which("dnf"):
        commands["packages"]["dnf"] = "sudo dnf install -y tmux curl rsync unzip zip"
        commands["java_package"] = "java-21-openjdk-headless"
        commands["install_java"] = "sudo dnf install -y java-21-openjdk-headless"
    
    elif shutil.which("yum"):
        # Amazon Linux 2 and older RHEL/CentOS
        commands["packages"]["yum"] = "sudo yum install -y tmux curl rsync unzip zip"
        # Amazon Linux 2 has different Java package naming
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                content = f.read()
                if "amzn" in content.lower():
                    commands["java_package"] = "java-21-amazon-corretto"
                    commands["install_java"] = "sudo amazon-linux-extras install java-openjdk21 -y || sudo yum install -y java-21-amazon-corretto"
                else:
                    commands["java_package"] = "java-21-openjdk"
                    commands["install_java"] = "sudo yum install -y java-21-openjdk"
        else:
            commands["java_package"] = "java-21-openjdk"
            commands["install_java"] = "sudo yum install -y java-21-openjdk"
    
    elif shutil.which("pacman"):
        commands["packages"]["pacman"] = "sudo pacman -Sy --noconfirm tmux curl rsync unzip zip"
        commands["java_package"] = "jre21-openjdk-headless"
        commands["install_java"] = "sudo pacman -S --noconfirm jre21-openjdk-headless"
    
    elif shutil.which("zypper"):
        commands["packages"]["zypper"] = "sudo zypper install -y tmux curl rsync unzip zip"
        commands["java_package"] = "java-21-openjdk"
        commands["install_java"] = "sudo zypper install -y java-21-openjdk"
    
    return commands


def install_prerequisites(missing):
    """Install missing prerequisites."""
    print("\n" + "="*70)
    print("INSTALLING PREREQUISITES")
    print("="*70 + "\n")
    
    commands = get_package_install_commands()
    
    # Install system packages
    if missing["packages"]:
        print(f"Missing system packages: {', '.join(missing['packages'])}")
        
        if commands["packages"]:
            pkg_mgr = list(commands["packages"].keys())[0]
            cmd = commands["packages"][pkg_mgr]
            
            print(f"\nDetected package manager: {pkg_mgr}")
            print(f"Running: {cmd}")
            
            try:
                subprocess.run(cmd, shell=True, check=True)
                print("✓ System packages installed")
            except subprocess.CalledProcessError as e:
                print(f"✗ Failed to install system packages: {e}")
                return False
        
        # Install Java separately (might need special handling)
        if "java" in missing["packages"]:
            print(f"\nInstalling Java...")
            if "install_java" in commands:
                try:
                    subprocess.run(commands["install_java"], shell=True, check=True)
                    print("✓ Java installed")
                except subprocess.CalledProcessError as e:
                    print(f"✗ Failed to install Java: {e}")
                    print(f"Please install Java manually:")
                    print(f"  Package name: {commands.get('java_package', 'java-21-openjdk')}")
                    return False
    
    # Install Python modules
    if missing["python_modules"]:
        print(f"\nMissing Python modules: {', '.join(missing['python_modules'])}")
        cmd = f"pip3 install {' '.join(missing['python_modules'])}"
        print(f"Running: {cmd}")
        
        try:
            subprocess.run(cmd, shell=True, check=True)
            print("✓ Python modules installed")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install Python modules: {e}")
            return False
    
    print("\n✓ All prerequisites installed!")
    return True


def check_java_compatibility():
    """Check Java version compatibility."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True
        )
        output = result.stderr + result.stdout
        
        # Parse version
        import re
        version_match = re.search(r'version "?(\d+)', output)
        if version_match:
            version = int(version_match.group(1))
            if version >= 21:
                print(f"✓ Java {version} detected (compatible)")
                return True
            else:
                print(f"⚠ Java {version} detected (requires Java 21+)")
                return False
    except:
        print("✗ Java not found")
        return False


def is_first_start():
    """Check if this is first start (no server.properties)."""
    return not (NEORUNNER_HOME / "server.properties").exists()


def start_first_start_wizard():
    """Start the first-start wizard in the dashboard."""
    print("\n" + "="*70)
    print("FIRST START WIZARD")
    print("="*70)
    print("\nNo server.properties found.")
    print("Starting web-based setup wizard...")
    print(f"\nOpen your browser to: http://0.0.0.0:8000")
    print("\nThe wizard will guide you through:")
    print("  • Minecraft version selection")
    print("  • Mod loader installation")
    print("  • Port configuration")
    print("  • Server setup")
    print("\n" + "="*70 + "\n")
    
    # Import and start dashboard in wizard mode
    from neorunner.dashboard import app
    app.config['FIRST_START'] = True
    app.run(host='0.0.0.0', port=8000, debug=False)


def start_normal_mode():
    """Start in normal mode."""
    print("\n" + "="*70)
    print("STARTING NEORUNNER")
    print("="*70 + "\n")
    
    cfg = load_cfg()
    
    # Check if server is already running
    from neorunner.server import is_server_running
    if is_server_running():
        print("⚠ Server is already running")
    
    # Start services
    print("Starting services...")
    print(f"  Dashboard: http://localhost:{cfg.http_port}")
    print(f"  Minecraft: port {cfg.mc_port}")
    
    # Import and start the full application
    from neorunner.cli import main as cli_main
    sys.argv = ['neorunner', 'start']
    cli_main()


def main():
    """Main entry point with prerequisite checks."""
    print("\n" + "="*70)
    print("NEORUNNER v2.1.0")
    print("="*70)
    print(f"Working directory: {NEORUNNER_HOME}")
    
    # Check prerequisites
    missing = check_system_prerequisites()
    
    if missing["packages"] or missing["python_modules"]:
        print("\n⚠ Missing prerequisites detected:")
        if missing["packages"]:
            print(f"  System packages: {', '.join(missing['packages'])}")
        if missing["python_modules"]:
            print(f"  Python modules: {', '.join(missing['python_modules'])}")
        
        response = input("\nInstall missing prerequisites? [Y/n]: ").strip().lower()
        if response in ['', 'y', 'yes']:
            if not install_prerequisites(missing):
                print("\n✗ Failed to install prerequisites")
                print("Please install manually and try again.")
                sys.exit(1)
        else:
            print("\n⚠ Continuing without prerequisites (may not work)")
    
    # Check Java
    if not check_java_compatibility():
        print("\n⚠ Java 21+ is required but not found")
        commands = get_package_install_commands()
        if "install_java" in commands:
            response = input("Install Java? [Y/n]: ").strip().lower()
            if response in ['', 'y', 'yes']:
                try:
                    subprocess.run(commands["install_java"], shell=True, check=True)
                    print("✓ Java installed")
                except:
                    print("✗ Failed to install Java")
                    sys.exit(1)
    
    # Check if first start
    if is_first_start():
        start_first_start_wizard()
    else:
        # Check if we need to generate config from server.properties
        cfg = load_cfg()
        if not cfg.server_jar and (NEORUNNER_HOME / "server.properties").exists():
            print("\nGenerating configuration from server.properties...")
            # Config will be auto-generated on load
        start_normal_mode()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nShutdown requested. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
