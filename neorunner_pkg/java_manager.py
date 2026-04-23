"""
Java version management for NeoRunner.
Handles Java installation, version detection, and switching.
"""

from __future__ import annotations

import os
import re
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .config import ServerConfig, load_cfg
from .constants import CWD
from .log import log_event


@dataclass
class JavaVersion:
    """Information about a Java installation."""
    path: str
    version: str
    version_number: int
    vendor: str
    is_default: bool = False


class JavaManager:
    """Manages Java installations for the server."""
    
    # Known Java vendors
    VENDORS = {
        "openjdk": "OpenJDK",
        "temurin": "Eclipse Temurin",
        "amazon": "Amazon Corretto",
        "microsoft": "Microsoft Build of OpenJDK",
        "graalvm": "GraalVM",
    }
    
    def __init__(self):
        self.installations: List[JavaVersion] = []
        self.scan_installations()
    
    @staticmethod
    def get_required_java_version(loader: str = "neoforge", loader_version: str = None) -> int:
        """Get required Java version based on loader/loader version.
        
        NeoForge 26.x requires Java 25
        NeoForge 21.x requires Java 21
        """
        if loader == "neoforge" and loader_version:
            # Check for 26.x versions (e.g., "26.1.2.22", "21.11.42")
            major = loader_version.split(".")[0]
            try:
                if int(major) >= 26:
                    return 25
            except (ValueError, IndexError):
                pass
        # Default: Java 21
        return 21
    
    def _get_loader_version(self) -> str:
        """Get current loader version from config."""
        try:
            cfg = load_cfg()
            loader = cfg.loader
            # Get loader version - check libraries first
            lib_path = CWD / "libraries" / "net" / "neoforged" / "neoforge"
            if lib_path.exists():
                versions = [d.name for d in lib_path.iterdir() if d.is_dir()]
                if versions:
                    return sorted(versions)[-1]
            # Fallback: just return a high version to trigger Java 25
            return "21.11.42"
        except Exception:
            return "21.11.42"
    
    @property
    def MIN_VERSION(self) -> int:
        """Dynamic minimum Java version based on config."""
        return self.get_required_java_version(loader_version=self._get_loader_version())
    
    def scan_installations(self):
        """Scan system for Java installations."""
        self.installations = []
        found_paths = set()
        
        # Check JAVA_HOME
        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            java_path = Path(java_home) / "bin" / "java"
            if java_path.exists():
                version = self._get_java_version(str(java_path))
                if version:
                    self.installations.append(version)
                    found_paths.add(str(java_path))
        
        # Check PATH
        java_in_path = shutil.which("java")
        if java_in_path and java_in_path not in found_paths:
            version = self._get_java_version(java_in_path)
            if version:
                version.is_default = True
                self.installations.append(version)
                found_paths.add(java_in_path)
        
        # Check common installation locations
        common_paths = [
            Path("/usr/lib/jvm"),
            Path("/usr/java"),
            Path("/opt/java"),
            Path("/Library/Java/JavaVirtualMachines"),  # macOS
            Path.home() / ".sdkman/candidates/java",
            Path.home() / ".jabba/jdk",
        ]
        
        for base_path in common_paths:
            if not base_path.exists():
                continue
            
            for item in base_path.iterdir():
                if item.is_dir():
                    java_path = item / "bin" / "java"
                    if java_path.exists() and str(java_path) not in found_paths:
                        version = self._get_java_version(str(java_path))
                        if version:
                            self.installations.append(version)
                            found_paths.add(str(java_path))
        
        # Sort by version number (descending)
        self.installations.sort(key=lambda x: x.version_number, reverse=True)
    
    def _get_java_version(self, java_path: str) -> Optional[JavaVersion]:
        """Get version information from a Java executable."""
        try:
            result = subprocess.run(
                [java_path, "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Parse version from stderr (Java prints version to stderr)
            output = result.stderr + result.stdout
            
            # Extract version number
            version_match = re.search(r'version "?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[._])?(\d+)?', output)
            if not version_match:
                version_match = re.search(r'openjdk version "(\d+)', output)
            
            if version_match:
                major = int(version_match.group(1))
                version_str = f"{major}"
                
                # Extract vendor
                vendor = "Unknown"
                for key, name in self.VENDORS.items():
                    if key in output.lower():
                        vendor = name
                        break
                
                return JavaVersion(
                    path=java_path,
                    version=version_str,
                    version_number=major,
                    vendor=vendor
                )
        
        except Exception as e:
            log_event("JAVA_SCAN", f"Error checking {java_path}: {e}")
        
        return None
    
    def get_compatible_installations(self) -> List[JavaVersion]:
        """Get Java installations that meet minimum requirements."""
        return [j for j in self.installations if j.version_number >= self.get_required_java_version()]
    
    def get_best_java(self) -> Optional[JavaVersion]:
        """Get the best available Java installation."""
        compatible = self.get_compatible_installations()
        return compatible[0] if compatible else None
    
    def set_java_home(self, java_path: str) -> bool:
        """Set JAVA_HOME to specific Java installation."""
        try:
            java_bin = Path(java_path)
            if not java_bin.exists():
                return False
            
            # Find JAVA_HOME (parent of bin directory)
            if java_bin.name == "java":
                java_home = java_bin.parent.parent
            else:
                java_home = java_bin
            
            # Update environment
            os.environ["JAVA_HOME"] = str(java_home)
            
            # Update service file if exists
            self._update_service_file(java_home)
            
            log_event("JAVA_SET", f"Set JAVA_HOME to {java_home}")
            return True
        
        except Exception as e:
            log_event("JAVA_SET_ERROR", f"Error setting JAVA_HOME: {e}")
            return False
    
    def _update_service_file(self, java_home: Path):
        """Update systemd service file with new JAVA_HOME."""
        service_path = Path.home() / ".config" / "systemd" / "user" / "mcserver.service"
        
        if not service_path.exists():
            return
        
        try:
            content = service_path.read_text()
            
            # Update or add JAVA_HOME
            if "JAVA_HOME=" in content:
                content = re.sub(
                    r'Environment="JAVA_HOME=.*"',
                    f'Environment="JAVA_HOME={java_home}"',
                    content
                )
            else:
                # Add after NEORUNNER_HOME
                content = content.replace(
                    'Environment="NEORUNNER_HOME=',
                    f'Environment="JAVA_HOME={java_home}"\nEnvironment="NEORUNNER_HOME='
                )
            
            service_path.write_text(content)
            log_event("JAVA_SERVICE", "Updated service file with new JAVA_HOME")
        
        except Exception as e:
            log_event("JAVA_SERVICE_ERROR", f"Error updating service: {e}")
    
    def install_java(self, version: int = 21, vendor: str = "openjdk") -> Tuple[bool, str]:
        """Install Java using system package manager."""
        log_event("JAVA_INSTALL", f"Installing Java {version} ({vendor})")
        
        # Detect package manager
        pkg_mgr = None
        for mgr in ["apt-get", "dnf", "pacman", "yum", "zypper"]:
            if shutil.which(mgr):
                pkg_mgr = mgr
                break
        
        if not pkg_mgr:
            return False, "No supported package manager found"
        
        # Map vendor to package names
        package_map = {
            "apt-get": {
                "openjdk": f"openjdk-{version}-jre-headless",
                "temurin": f"temurin-{version}-jre",
            },
            "dnf": {
                "openjdk": f"java-{version}-openjdk-headless",
            },
            "pacman": {
                "openjdk": f"jre{version}-openjdk-headless",
            },
            "yum": {
                "openjdk": f"java-{version}-openjdk-headless",
            },
        }
        
        packages = package_map.get(pkg_mgr, {}).get(vendor, f"openjdk-{version}-jre-headless")
        
        try:
            if pkg_mgr == "apt-get":
                subprocess.run(["sudo", "apt-get", "update"], check=True)
                subprocess.run(["sudo", "apt-get", "install", "-y", packages], check=True)
            elif pkg_mgr == "dnf":
                subprocess.run(["sudo", "dnf", "install", "-y", packages], check=True)
            elif pkg_mgr == "pacman":
                subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm", packages], check=True)
            elif pkg_mgr == "yum":
                subprocess.run(["sudo", "yum", "install", "-y", packages], check=True)
            
            # Rescan installations
            self.scan_installations()
            
            return True, f"Java {version} installed successfully"
        
        except subprocess.CalledProcessError as e:
            return False, f"Installation failed: {e}"
    
    def check_java_compatibility(self, mods_dir: Path) -> Dict[str, Any]:
        """Check if mods are compatible with current Java version."""
        best_java = self.get_best_java()
        
        if not best_java:
            return {
                "has_java": False,
                "message": "No compatible Java installation found",
                "required_version": self.get_required_java_version(),
            }
        
        # Check for Java-specific issues in mods
        issues = []
        
        if best_java.version_number < self.get_required_java_version():
            issues.append({
                "type": "version",
                "message": f"Java {best_java.version} is too old. Minimum required: {JavaManager.get_required_java_version()}",
                "severity": "error"
            })
        
        return {
            "has_java": True,
            "java_version": best_java.version,
            "java_path": best_java.path,
            "vendor": best_java.vendor,
            "compatible": best_java.version_number >= self.MIN_VERSION and len(issues) == 0,
            "issues": issues
        }
    
    def get_install_command(self, version: int = 21) -> str:
        """Get the installation command for the current system."""
        if shutil.which("apt-get"):
            return f"sudo apt-get update && sudo apt-get install -y openjdk-{version}-jre-headless"
        elif shutil.which("dnf"):
            return f"sudo dnf install -y java-{version}-openjdk-headless"
        elif shutil.which("pacman"):
            return f"sudo pacman -Sy --noconfirm jre{version}-openjdk-headless"
        elif shutil.which("yum"):
            return f"sudo yum install -y java-{version}-openjdk-headless"
        else:
            return "# Please install Java manually from https://adoptium.net/"


def get_java_info() -> Dict[str, Any]:
    """Get current Java information."""
    manager = JavaManager()
    
    return {
        "installations": [
            {
                "path": j.path,
                "version": j.version,
                "vendor": j.vendor,
                "is_default": j.is_default,
                "compatible": j.version_number >= JavaManager.get_required_java_version(loader_version=manager._get_loader_version())
            }
            for j in manager.installations
        ],
        "best_java": manager.get_best_java().path if manager.get_best_java() else None,
        "min_version": JavaManager.MIN_VERSION,
    }
