"""Server management for NeoRunner with tmux-based process monitoring."""

from __future__ import annotations

import subprocess
import signal
import os
import time
import threading
import logging
import re
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from .constants import CWD, MAX_RESTART_ATTEMPTS, MAX_TOTAL_RESTARTS, CRASH_COOLDOWN_SECONDS
from .config import ServerConfig, load_cfg
from .log import log_event
from .loaders import get_loader
from .self_heal import preflight_dep_check, quarantine_mod, load_crash_history, save_crash_history

log = logging.getLogger(__name__)

SERVER_EVENT_TYPES = {
    "CRASH_DETECT", "SELF_HEAL", "QUARANTINE", "SERVER_RESTART",
    "SERVER_STOPPED", "SERVER_RUNNING", "SERVER_START", "SERVER_ERROR",
    "SERVER_TIMEOUT", "PREFLIGHT", "MOD_INSTALL"
}

_in_memory_events = []
_max_events = 200


def _add_event(event_type: str, message: str) -> None:
    """Add event to in-memory store for dashboard."""
    from datetime import datetime
    _in_memory_events.append({
        "type": event_type,
        "message": message,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    while len(_in_memory_events) > _max_events:
        _in_memory_events.pop(0)


class TmuxServer:
    """Minecraft server running in tmux with full output capture."""
    
    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self.loader = get_loader(cfg)
        self.tmux_session = "MC"
        self.tmux_socket = f"/tmp/tmux-{os.getuid()}/default"
        self.log_file = CWD / "live.log"
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
    
    def _ensure_tmux_socket(self) -> None:
        """Ensure tmux socket directory exists."""
        socket_dir = os.path.dirname(self.tmux_socket)
        os.makedirs(socket_dir, exist_ok=True)
        try:
            os.chmod(socket_dir, 0o700)
        except Exception:
            pass
    
    def _get_java_command(self) -> str:
        """Build the Java command using the loader."""
        java_cmd_parts = self.loader.build_java_command()
        return " ".join(java_cmd_parts)
    
    def start(self) -> bool:
        """Start the server in tmux."""
        self._ensure_tmux_socket()
        
        log_event("SERVER_START", f"Starting {self.loader.get_loader_display_name()} server (MC {self.cfg.mc_version})")
        
        java_cmd = self._get_java_command()
        log_event("SERVER_START", f"Java command: {java_cmd}")
        
        self.loader.prepare_environment()
        
        try:
            from .log_manager import run_log_cleanup
            cleanup_result = run_log_cleanup(self.cfg)
            if cleanup_result["crash_reports_deleted"] > 0 or cleanup_result["old_logs_deleted"] > 0:
                log_event("LOG_MANAGE", f"Cleanup: {cleanup_result['crash_reports_deleted']} crash reports, {cleanup_result['old_logs_deleted']} old logs removed")
        except Exception as e:
            log_event("LOG_MANAGE", f"Cleanup failed (non-fatal): {e}")
        
        try:
            log_event("DEBUG", "Starting preflight_dep_check...")
            preflight_result = preflight_dep_check({
                "mc_version": self.cfg.mc_version,
                "loader": self.cfg.loader,
                "mods_dir": self.cfg.mods_dir,
            })
            log_event("DEBUG", f"Preflight returned fetched={preflight_result.get('fetched')}")
            if preflight_result.get("fetched", 0) > 0:
                log_event("SERVER_START", f"Pre-flight fetched {preflight_result['fetched']} missing deps")
        except Exception as e:
            log_event("SERVER_START", f"Pre-flight check failed (non-fatal): {e}")
        
        if self.is_running():
            log_event("SERVER_START", "Killing existing tmux session first")
            self.stop()
            time.sleep(2)
        
        log_size_before = 0
        if self.log_file.exists():
            try:
                log_size_before = self.log_file.stat().st_size
            except Exception:
                pass
        
        tmux_cmd = f"cd '{CWD}' && stdbuf -oL -eL {java_cmd}"
        
        result = subprocess.run(
            f"tmux -S {self.tmux_socket} new-session -d -s {self.tmux_session} \"cd '{CWD}' && stdbuf -oL -eL {java_cmd} 2>&1 | tee -a {self.log_file}\"",
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            log_event("SERVER_ERROR", f"Failed to start tmux session: {result.stderr}")
            return False
        
        try:
            os.chmod(self.tmux_socket, 0o700)
        except Exception:
            pass
        
        log_event("SERVER_RUNNING", f"Server started in tmux session '{self.tmux_session}'")
        
        self.running = True
        self.stop_flag.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        return True
    
    def _monitor_loop(self) -> None:
        """Monitor tmux session for crashes and network channel issues."""
        log_event("MONITOR", "Server monitor started")
        
        last_log_position = 0
        channel_analyzer = None
        
        try:
            from .network_channel_analyzer import NetworkChannelAnalyzer
            channel_analyzer = NetworkChannelAnalyzer()
        except Exception as e:
            log_event("CHANNEL_ERROR", f"Failed to load network channel analyzer: {e}")
        
        while not self.stop_flag.is_set():
            if not self.is_running():
                log_event("SERVER_STOPPED", "Server process ended, analyzing...")
                self._analyze_crash()
                break
            
            if channel_analyzer and self.log_file.exists():
                try:
                    with open(self.log_file, "r") as f:
                        f.seek(last_log_position)
                        new_log_content = f.read()
                        last_log_position = f.tell()
                    
                    if new_log_content.strip():
                        mismatches = channel_analyzer.analyze_log(new_log_content)
                        if mismatches:
                            channel_analyzer.generate_events(mismatches)
                except Exception as e:
                    log_event("CHANNEL_ERROR", f"Failed to analyze network channels: {e}")
            
            time.sleep(5)
        
        self.running = False
        log_event("MONITOR", "Server monitor stopped")
    
    def _analyze_crash(self) -> None:
        """Analyze crash log and attempt self-healing."""
        crash_history = load_crash_history()
        
        new_log = self._get_recent_log(500)
        
        # Check for crash indicators FIRST - these override any "Stopping server" messages
        # because old crash logs may contain "Stopping server" from previous runs
        crash_indicators = [
            "fatal",
            "crash",
            "error encountered",
            "fml loading error",
            "mod loading exception",
            "failed to start fml",
            "fatal startupexception",
            "modloadingexception",
            "loading errors encountered",
        ]
        
        has_crash = any(indicator in new_log.lower() for indicator in crash_indicators)
        
        if has_crash:
            # Crash indicators found - this is a crash, not a clean shutdown
            # Continue with crash analysis below
            pass
        elif "Stopping server" in new_log or "Stopping the server" in new_log:
            # No crash indicators AND "Stopping server" found - likely a clean shutdown
            log_event("SERVER_STOPPED", "Clean shutdown detected")
            return
        
        if not has_crash:
            # No crash indicators found - might be a clean stop
            # But also check if there were any errors during startup
            log_lower = new_log.lower()
            if ("currently" in log_lower and "not installed" in log_lower) or \
               ("requires" in log_lower and "not installed" in log_lower) or \
               ("mod" in log_lower and "not installed" in log_lower and "requires" in log_lower):
                # This is a startup failure, not a clean shutdown
                has_crash = True
                log_event("CRASH_DETECT", "Startup failure detected (missing mods)")
        
        crash_info = self.loader.detect_crash_reason(new_log)
        crash_type = crash_info.get("type", "unknown")
        culprit = crash_info.get("culprit")
        
        log_event("CRASH_DETECT", f"Crash type: {crash_type}" + (f", culprit: {culprit}" if culprit else ""))
        
        if crash_info.get("message"):
            log_event("CRASH_DETECT", f"Details: {crash_info['message'][:200]}")
        
        if crash_type == "benign_mixin_warning":
            log_event("SELF_HEAL", "Benign mixin warning - NOT a crash")
            return
        
        self._try_self_heal(crash_info, crash_history)
    
    def _try_self_heal(self, crash_info: Dict[str, Any], crash_history: Dict[str, int]) -> None:
        """Attempt to fix crash by fetching deps or quarantining bad mods."""
        crash_type = crash_info.get("type", "unknown")
        culprit = crash_info.get("culprit")
        mods_dir = CWD / self.cfg.mods_dir
        
        # Check for Java version incompatibility errors
        new_log = self._get_recent_log(300)
        
        java_error_patterns = [
            "UnsupportedClassVersionError",
            "Class version", 
            "java.lang.UnsupportedClassVersion",
            "requires Java",
            "major version",
            "JAVA_VERSION",
        ]
        
        if any(p in new_log.lower() for p in java_error_patterns):
            log_event("SELF_HEAL", "Java version incompatibility detected - checking mods...")
            
            # Check for mods requiring different Java version
            try:
                import subprocess
                java_version_output = subprocess.run(
                    ["java", "-version"], capture_output=True, text=True, timeout=10
                )
                import re
                java_match = re.search(r'version "?(\d+)', java_version_output.stderr)
                installed_java = int(java_match.group(1)) if java_match else 21
                
                # Scan mods for Java version requirements
                for mod_file in mods_dir.glob("*.jar"):
                    try:
                        import zipfile
                        with zipfile.ZipFile(mod_file) as zf:
                            if 'META-INF/neoforge.mods.toml' in zf.namelist():
                                raw = zf.read('META-INF/neoforge.mods.toml').decode()
                                try:
                                    import tomllib
                                except ImportError:
                                    import tomli as tomllib
                                data = tomllib.loads(raw)
                                deps = data.get('dependencies', {})
                                for dep_list in deps.values():
                                    if isinstance(dep_list, list):
                                        for dep in dep_list:
                                            if isinstance(dep, dict) and dep.get('modId', '').lower() in ['javafml', 'fml']:
                                                vr = dep.get('versionRange', '')
                                                if vr:
                                                    java_ver_match = re.search(r'\[(\d+)', vr)
                                                    if java_ver_match:
                                                        required_java = int(java_ver_match.group(1))
                                                        if installed_java > required_java:
                                                            # Can't downgrade - quarantine
                                                            log_event("SELF_HEAL", f"Java mismatch: {mod_file.name} requires Java {required_java} < {installed_java} - quarantining (cannot downgrade)")
                                                            quarantine_mod(mods_dir, mod_file.name, f"Requires Java {required_java}, have {installed_java}")
                                                        elif installed_java < required_java:
                                                            log_event("SELF_HEAL", f"WARNING: {mod_file.name} requires Java {required_java} > {installed_java} - Java upgrade needed but may break other mods")
                    except Exception:
                        continue
            except Exception as e:
                log_event("SELF_HEAL", f"Error checking Java versions: {e}")
            
            log_event("SELF_HEAL", "Attempting restart after Java version fix...")
            self.restart()
            return
        
        # Check for client-side class errors - these indicate client-only mods
        # Look for common client mod classes in the crash
        new_log = self._get_recent_log(300)
        
        # Detect client-side mod class errors from crash report
        client_mod_patterns = [
            "clientonly", "client_only", "client side", 
            "net.minecraft.client", "client.renderer", "client.gui",
            "com/mojang/blaze3d", "net.minecraft.client.render",
        ]
        
        if any(p in new_log.lower() for p in client_mod_patterns):
            log_event("SELF_HEAL", "Client-side class error detected - scanning for client-only mods...")
            
            # Scan mods for client-only indicators
            for mod_file in mods_dir.glob("*.jar"):
                try:
                    with zipfile.ZipFile(mod_file) as zf:
                        names = zf.namelist()
                        # Check for client-only class patterns
                        has_client_class = any(
                            "client" in n.lower() and any(x in n.lower() for x in ["renderer", "gui", "texture", "model"])
                            for n in names[:100]  # Check first 100 files
                        )
                        if has_client_class:
                            log_event("SELF_HEAL", f"Client-only mod detected: {mod_file.name} - quarantining")
                            quarantine_mod(mods_dir, mod_file.name, "Client-side mod causes crash")
                except Exception:
                    continue
            
            # Try to restart after removing client-only mods
            log_event("SELF_HEAL", "Attempting restart after removing client-only mods...")
            self.restart()
            return
        
        if crash_type == "missing_dep":
            dep_name = crash_info.get("dep", "")
            culprit = crash_info.get("culprit")
            
            # Check for known client-only mod patterns - quarantine these immediately
            client_only_patterns = [
                "cobblemon", "playerxp", "dbx", "pladailyboss", "project_icbp",
                "mcwbyg", "biomeswevegone", "fix_cobblemon", 
            ]
            
            if culprit and any(p in culprit.lower() for p in client_only_patterns):
                log_event("SELF_HEAL", f"Client-only mod detected: {culprit} - quarantining")
                quarantine_mod(mods_dir, culprit, "Client-only mod causes server crash")
                return
            
            if dep_name:
                log_event("SELF_HEAL", f"Missing dependency: {dep_name}" + (f" (required by {culprit})" if culprit else ""))
                
                dep_key = dep_name
                crash_history[dep_key] = crash_history.get(dep_key, 0) + 1
                save_crash_history(crash_history)
                
                if crash_history[dep_key] > 2:
                    # If dep can't be resolved, check if culprit is a bad mod
                    if culprit:
                        log_event("SELF_HEAL", f"Dep {dep_name} not resolved after {crash_history[dep_key]} attempts. Quarantining {culprit}")
                        quarantine_mod(mods_dir, culprit, f"Missing dep {dep_name} after {crash_history[dep_key]} attempts")
                else:
                    log_event("SELF_HEAL", f"Attempting to fetch missing dep: {dep_name}")
        
        elif crash_type == "mod_error":
            subtype = crash_info.get("subtype", "")
            bad_file = crash_info.get("bad_file")
            
            if subtype == "client_only":
                mod_to_quarantine = bad_file or culprit
                if mod_to_quarantine:
                    log_event("SELF_HEAL", f"Client-only mod detected: {mod_to_quarantine}")
                    quarantine_mod(mods_dir, mod_to_quarantine, "Client-only mod crashes server")
            elif culprit:
                crash_history[culprit] = crash_history.get(culprit, 0) + 1
                save_crash_history(crash_history)
                
                if crash_history[culprit] >= 2:
                    log_event("SELF_HEAL", f"Quarantining {culprit} after {crash_history[culprit]} crashes")
                    quarantine_mod(mods_dir, culprit, f"Caused {crash_history[culprit]} crashes")
        
        elif crash_type == "mod_conflict":
            culprits = crash_info.get("culprits", [])
            conflict_type = crash_info.get("conflict_type", "unknown")
            log_event("SELF_HEAL", f"Mod conflict ({conflict_type}): {', '.join(culprits) if culprits else 'unknown'}")
            
            if culprits:
                primary = culprits[-1]
                quarantine_mod(mods_dir, primary, f"Mod conflict: {conflict_type}")
        
        elif crash_type == "version_mismatch":
            if culprit:
                log_event("SELF_HEAL", f"Version mismatch: {culprit}")
                quarantine_mod(mods_dir, culprit, "Version mismatch with server")
    
    def _get_recent_log(self, lines: int = 100) -> str:
        """Get recent log output."""
        if not self.log_file.exists():
            return ""
        
        try:
            with open(self.log_file, "r") as f:
                all_lines = f.readlines()
                return "".join(all_lines[-lines:])
        except Exception:
            return ""
    
    def is_running(self) -> bool:
        """Check if tmux session exists."""
        result = subprocess.run(
            f"tmux -S {self.tmux_socket} has-session -t {self.tmux_session} 2>/dev/null",
            shell=True
        )
        return result.returncode == 0
    
    def send_command(self, cmd: str) -> bool:
        """Send command to tmux session."""
        if not self.is_running():
            return False
        
        cmd_safe = cmd.replace("'", "'\\''")
        result = subprocess.run(
            f"tmux -S {self.tmux_socket} send-keys -t {self.tmux_session} '{cmd_safe}' Enter",
            shell=True,
            capture_output=True
        )
        return result.returncode == 0
    
    def stop(self) -> bool:
        """Stop the server."""
        self.stop_flag.set()
        
        if self.is_running():
            log_event("SERVER_STOP", "Stopping server via tmux")
            self.send_command("stop")
            time.sleep(5)
            
            if self.is_running():
                subprocess.run(
                    f"tmux -S {self.tmux_socket} kill-session -t {self.tmux_session}",
                    shell=True
                )
        
        self.running = False
        return True
    
    def restart(self) -> bool:
        """Restart the server."""
        log_event("SERVER_RESTART", "Restarting server...")
        self.stop()
        time.sleep(3)
        return self.start()


_server_instance: Optional[TmuxServer] = None


def get_server() -> TmuxServer:
    """Get or create the server instance."""
    global _server_instance
    if _server_instance is None:
        cfg = load_cfg()
        _server_instance = TmuxServer(cfg)
    return _server_instance


def is_server_running() -> bool:
    """Check if the Minecraft server is running."""
    global _server_instance
    
    # Check tmux session first
    if _server_instance and _server_instance.running:
        if _server_instance.is_running():
            return True
    
    # Check for java processes
    result = subprocess.run(
        ["pgrep", "-f", "neoforge.*nogui|forge.*nogui|fabric.*nogui|minecraft.*server"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return True
    
    result = subprocess.run(
        ["pgrep", "-a", "java"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if any(x in line.lower() for x in ["neoforge", "forge", "fabric", "minecraft"]):
                return True
    
    return False


def wait_for_server(timeout: int = 60) -> bool:
    """Wait for the Minecraft server to bind its ports."""
    import socket
    
    cfg = load_cfg()
    port = int(cfg.mc_port)
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_server_running():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                if result == 0:
                    log_event("INFO", f"Server is ready on port {port}")
                    return True
            except Exception:
                pass
        time.sleep(2)
    
    log_event("WARN", f"Server did not bind port {port} within {timeout}s")
    return False


def run_server(cfg: Optional[ServerConfig] = None, max_retries: int = 3) -> bool:
    """Start the Minecraft server.
    
    Args:
        cfg: Server configuration (optional, will load from config)
        max_retries: Maximum restart attempts
        
    Returns:
        True if started successfully
    """
    global _server_instance
    
    if cfg is None:
        cfg = load_cfg()
    
    _server_instance = TmuxServer(cfg)
    return _server_instance.start()


def stop_server() -> bool:
    """Stop the Minecraft server."""
    global _server_instance
    
    # If we have an instance, use it
    if _server_instance:
        return _server_instance.stop()
    
    # Otherwise, try to stop via tmux directly (dashboard process)
    from .config import load_cfg
    cfg = load_cfg()
    tmux_session = f"neorunner-{cfg.mc_version}-{cfg.loader}"
    tmux_socket = "/tmp/tmux-1000/default"  # Default socket
    
    # Try to send stop command via tmux
    subprocess.run(
        f"tmux -S {tmux_socket} send-keys -t {tmux_session} 'stop' Enter",
        shell=True,
        capture_output=True
    )
    time.sleep(5)
    
    # Kill if still running
    subprocess.run(
        f"tmux -S {tmux_socket} kill-session -t {tmux_session}",
        shell=True,
        capture_output=True
    )
    
    return True


def restart_server(cfg: Optional[ServerConfig] = None) -> bool:
    """Restart the Minecraft server."""
    global _server_instance
    
    # Stop first
    stop_server()
    time.sleep(3)
    
    # Then start
    if _server_instance:
        return _server_instance.restart()
    
    # Or start fresh
    return run_server(cfg)


def send_command(cmd: str) -> bool:
    """Send a command to the running server."""
    global _server_instance
    if _server_instance:
        return _server_instance.send_command(cmd)
    return False


def get_events() -> list:
    """Get recent server events for dashboard."""
    return list(_in_memory_events)


__all__ = [
    "run_server",
    "stop_server",
    "restart_server",
    "send_command",
    "is_server_running",
    "wait_for_server",
    "get_server",
    "get_events",
    "TmuxServer",
]
