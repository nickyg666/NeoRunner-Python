"""Server management for NeoRunner with tmux-based process monitoring."""


import logging
import os
import subprocess
import threading
import time
from datetime import UTC
from typing import Any

from .config import ServerConfig, load_cfg
from .constants import (
    CWD,
)
from .loaders import get_loader
from .log import log_event
from .self_heal import (
    _fetch_dependency,
    load_crash_history,
    preflight_dep_check,
    quarantine_mod,
    save_crash_history,
)

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
        "time": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
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
        self.monitor_thread: threading.Thread | None = None
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

        # Remediate level.dat permissions/stale locks before boot so the world
        # can be opened, and move any version-incompatible world aside so a
        # fresh one generates instead of crashing on startup.
        try:
            from .worlds import (
                auto_move_incompatible_world,
                remediate_world_lock,
            )
            lock_result = remediate_world_lock()
            if lock_result.get("fixed_permissions") or lock_result.get("removed_stale_lock"):
                log_event("WORLD_LOCK", f"World lock remediation: perms={lock_result.get('fixed_permissions')} stale_lock={lock_result.get('removed_stale_lock')}")
            move_result = auto_move_incompatible_world(
                server_mc_version=self.cfg.mc_version,
                loader=self.cfg.loader,
            )
            if move_result.get("moved"):
                log_event("SERVER_START", f"World was incompatible (MC {move_result.get('world_version')}) - moved aside, fresh world will generate")
        except Exception as e:
            log_event("SERVER_START", f"World pre-check failed (non-fatal): {e}")
        
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
        
        # Check if preflight was recently run (within last 10 minutes) - skip to prevent bootloop
        preflight_cache = CWD / ".preflight_cache"
        skip_preflight = False
        try:
            if preflight_cache.exists():
                import datetime
                cache_time = float(preflight_cache.read_text().strip())
                cache_dt = datetime.datetime.fromtimestamp(cache_time, tz=datetime.UTC)
                now = datetime.datetime.now(datetime.UTC)
                if (now - cache_dt).total_seconds() < 600:  # 10 min cooldown
                    skip_preflight = True
                    log_event("DEBUG", "Skipping preflight - recently ran")
        except Exception:
            pass
        
        if not skip_preflight:
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
        
        result = subprocess.run(            f"tmux -S {self.tmux_socket} new-session -d -s {self.tmux_session} \"cd '{CWD}' && stdbuf -oL -eL {java_cmd} 2>&1 | tee -a {self.log_file}\"", check=False,
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
                            # Try to kick players rejected during handshake with
                            # the modpack download link (no-op if already gone).
                            for mm in mismatches:
                                reason = channel_analyzer.kick_reason(mm)
                                if reason and mm.player:
                                    self.send_command(f"kick {mm.player} {reason}")
                except Exception as e:
                    log_event("CHANNEL_ERROR", f"Failed to analyze network channels: {e}")
            
            time.sleep(5)
        
        # Only clear `running` if we're still the active monitor thread. A
        # self-heal path may have called restart(), spawning a new monitor
        # thread and setting running=True; the stale thread must not clobber it.
        if self.monitor_thread is threading.current_thread():
            self.running = False
        log_event("MONITOR", "Server monitor stopped")
    
    def _analyze_crash(self) -> None:
        """Analyze crash log and attempt self-healing - with timestamp verification."""
        crash_history = load_crash_history()
        
        new_log = self._get_recent_log(500)
        
        # Check for crash indicators - but ONLY if they're RECENT (last 5 min)
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
        
        # Check if any crash indicators are actually recent
        has_recent_crash = False
        for indicator in crash_indicators:
            if self._is_recent_crash(indicator):
                has_recent_crash = True
                break
        
        if has_recent_crash:
            # Recent crash found - continue with analysis
            log_event("CRASH_DETECT", "Recent crash indicator found; analyzing")
        elif "Stopping server" in new_log or "Stopping the server" in new_log:
            # No recent crash AND "Stopping server" found - likely a clean shutdown
            log_event("SERVER_STOPPED", "Clean shutdown detected")
            return
        else:
            # No recent crash indicators - this might be stale log data
            log_event("SERVER_STOPPED", "No recent crash detected - possible stale log")
            return

        # Detect world-level boot failures (incompatible/corrupt world, level.dat
        # lock/permission issues) and auto-remediate before mod analysis.
        world_indicators = [
            "failed to load world",
            "unable to open level",
            "failed to open level",
            "unable to load level.dat",
            "cannot load level",
            "incompatible world",
            "world version mismatch",
            "level.dat",
            "session.lock",
            "could not create level.dat",
            "failed to start the minecraft server",
            "encountered an unexpected exception",
        ]
        log_lower = new_log.lower()
        if any(w in log_lower for w in world_indicators):
            # Narrow to actual world errors: crash text that mentions world/level
            # AND is not a mod-dependency failure.
            world_mentions = any(w in log_lower for w in ["level", "world"])
            bind_fail = "address already in use" in log_lower or "failed to bind" in log_lower
            if world_mentions and not bind_fail:
                log_event("CRASH_DETECT", "World-level boot failure detected - attempting remediation")
                try:
                    from .worlds import (
                        auto_move_incompatible_world,
                        remediate_world_lock,
                    )
                    lock_result = remediate_world_lock()
                    move_result = auto_move_incompatible_world(
                        server_mc_version=self.cfg.mc_version,
                        loader=self.cfg.loader,
                    )
                    if lock_result.get("fixed_permissions") or lock_result.get("removed_stale_lock"):
                        log_event("WORLD_LOCK", f"Remediated world lock: perms={lock_result.get('fixed_permissions')} stale_lock={lock_result.get('removed_stale_lock')}")
                    if move_result.get("moved"):
                        log_event("SELF_HEAL", f"Auto-moved incompatible world to {move_result.get('destination')}")
                    elif move_result.get("errors"):
                        log_event("SELF_HEAL", f"World remediation errors: {move_result['errors'][:3]}")
                    log_event("SELF_HEAL", "Attempting restart after world remediation...")
                    self.restart()
                    return
                except Exception as e:
                    log_event("SELF_HEAL", f"World remediation failed (non-fatal): {e}")
        
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
    
    def _try_self_heal(self, crash_info: dict[str, Any], crash_history: dict[str, int]) -> None:
        """Attempt to fix crash by fetching deps or quarantining bad mods."""
        crash_type = crash_info.get("type", "unknown")
        culprit = crash_info.get("culprit")
        mods_dir = CWD / self.cfg.mods_dir
        clientonly_dir = CWD / self.cfg.clientonly_dir
        clientonly_dir.mkdir(parents=True, exist_ok=True)
        
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
                    ["java", "-version"], check=False, capture_output=True, text=True, timeout=10
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
                                                        if installed_java < required_java:
                                                            # Mod needs a newer Java than installed - can't run, quarantine
                                                            log_event("SELF_HEAL", f"Java mismatch: {mod_file.name} requires Java {required_java} > {installed_java} - quarantining (mod can't run on this Java)")
                                                            quarantine_mod(mods_dir, mod_file.name, f"Requires Java {required_java}, server has Java {installed_java}")
                                                        else:
                                                            # Java is forward-compatible - newer than required is fine
                                                            log_event("SELF_HEAL", f"OK: {mod_file.name} requires Java {required_java} <= {installed_java} (compatible)")
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
                
                if crash_history[dep_key] > self.cfg.max_crashes_before_quarantine:
                    # If dep can't be resolved, check if culprit is a bad mod
                    if culprit:
                        log_event("SELF_HEAL", f"Dep {dep_name} not resolved after {crash_history[dep_key]} attempts. Quarantining {culprit}")
                        quarantine_mod(mods_dir, culprit, f"Missing dep {dep_name} after {crash_history[dep_key]} attempts")
                else:
                    log_event("SELF_HEAL", f"Attempting to fetch missing dep: {dep_name}")
                    try:
                        # Client-only mods (e.g. sodium fetched for iris) belong in
                        # clientonly/, not the server mods folder. Detect by the
                        # known client-only name list before choosing the target dir.
                        from .constants import FORCE_CLIENT_ONLY_MODS
                        dep_lower = dep_name.lower()
                        target_dir = clientonly_dir if any(cm in dep_lower for cm in FORCE_CLIENT_ONLY_MODS) else mods_dir
                        fetched = _fetch_dependency(
                            dep_id=dep_name,
                            mc_version=self.cfg.mc_version,
                            loader_name=self.cfg.loader,
                            mods_dir=target_dir,
                            dependents=[culprit] if culprit else None,
                        )
                        if fetched:
                            log_event("SELF_HEAL", f"Fetched missing dep {dep_name} -> {target_dir.name}")
                        else:
                            log_event("SELF_HEAL", f"Could not fetch missing dep {dep_name}")
                    except Exception as e:
                        log_event("SELF_HEAL", f"Error fetching dep {dep_name}: {e}")
        
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
                
                if crash_history[culprit] >= self.cfg.max_crashes_before_quarantine:
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
        """Get recent log output - only from live.log, verify timestamps are recent."""
        if not self.log_file.exists():
            return ""
        
        try:
            with open(self.log_file, "r") as f:
                all_lines = f.readlines()
                # Only look at the last N lines from live.log (not rotated logs)
                return "".join(all_lines[-lines:])
        except Exception:
            return ""
    
    def _is_recent_crash(self, crash_indicator: str) -> bool:
        """Check if a crash indicator is from a recent run (last 5 minutes)."""
        import datetime
        try:
            with open(self.log_file, "r") as f:
                lines = f.readlines()
                recent_lines = lines[-500:]  # Last 500 lines
            
            # Scan newest-first: the first match is the most recent occurrence.
            for line in reversed(recent_lines):
                if crash_indicator.lower() in line.lower():
                    # Try to extract timestamp from line
                    # Format: 2026-03-09 20:11:39 |
                    import re
                    ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    if ts_match:
                        ts_str = ts_match.group(1)
                        ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.UTC)
                        now = datetime.datetime.now(datetime.UTC)
                        # Most recent match is timestamped: recent iff within 5 min.
                        # Older matches are even older, so this decides it.
                        return (now - ts).total_seconds() < 300
                    # No timestamp on the most recent match: be conservative.
                    return True
            return False
        except Exception:
            return False
    
    def is_running(self) -> bool:
        """Check if tmux session exists."""
        result = subprocess.run(
            f"tmux -S {self.tmux_socket} has-session -t {self.tmux_session} 2>/dev/null", check=False,
            shell=True
        )
        return result.returncode == 0
    
    def send_command(self, cmd: str) -> bool:
        """Send command to tmux session."""
        if not self.is_running():
            return False
        
        cmd_safe = cmd.replace("'", "'\\''")
        result = subprocess.run(
            f"tmux -S {self.tmux_socket} send-keys -t {self.tmux_session} '{cmd_safe}' Enter", check=False,
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
                    f"tmux -S {self.tmux_socket} kill-session -t {self.tmux_session}", check=False,
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


_server_instance: TmuxServer | None = None


def get_server() -> TmuxServer:
    """Get or create the server instance."""
    global _server_instance
    if _server_instance is None:
        cfg = load_cfg()
        _server_instance = TmuxServer(cfg)
    return _server_instance


def is_server_running() -> bool:
    """Check if the Minecraft server is running."""
    # Check tmux session first
    if _server_instance and _server_instance.running and _server_instance.is_running():
        return True
    
    # Check for java processes
    result = subprocess.run(
        ["pgrep", "-f", "neoforge.*nogui|forge.*nogui|fabric.*nogui|minecraft.*server"], check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return True
    
    result = subprocess.run(
        ["pgrep", "-a", "java"], check=False,
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


def run_server(cfg: ServerConfig | None = None, max_retries: int = 3) -> bool:
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
    for attempt in range(max_retries + 1):
        if _server_instance.start():
            return True
        if attempt < max_retries:
            log_event("SERVER_ERROR", f"Server start failed (attempt {attempt + 1}/{max_retries}), retrying...")
            time.sleep(3)
    return False


def stop_server() -> bool:
    """Stop the Minecraft server."""
    # If we have an instance, use it
    if _server_instance:
        return _server_instance.stop()
    
    # Otherwise, try to stop via tmux directly (dashboard process). The session
    # name and socket must match TmuxServer's ("MC" + per-uid socket path).
    from .config import load_cfg
    load_cfg()
    tmux_session = "MC"
    tmux_socket = f"/tmp/tmux-{os.getuid()}/default"
    
    # Try to send stop command via tmux
    subprocess.run(
        f"tmux -S {tmux_socket} send-keys -t {tmux_session} 'stop' Enter", check=False,
        shell=True,
        capture_output=True
    )
    time.sleep(5)
    
    # Kill if still running
    subprocess.run(
        f"tmux -S {tmux_socket} kill-session -t {tmux_session}", check=False,
        shell=True,
        capture_output=True
    )
    
    return True


def restart_server(cfg: ServerConfig | None = None) -> bool:
    """Restart the Minecraft server."""
    # If we hold an instance, restart() already stops + starts in one shot.
    if _server_instance:
        return _server_instance.restart()
    
    # Otherwise, stop via tmux and start fresh.
    stop_server()
    time.sleep(3)
    return run_server(cfg)


def send_command(cmd: str) -> bool:
    """Send a command to the running server."""
    if _server_instance:
        return _server_instance.send_command(cmd)
    return False


def get_events() -> list:
    """Get recent server events for dashboard."""
    return list(_in_memory_events)


__all__ = [
    "TmuxServer",
    "get_events",
    "get_server",
    "is_server_running",
    "restart_server",
    "run_server",
    "send_command",
    "stop_server",
    "wait_for_server",
]
