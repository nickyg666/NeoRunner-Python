"""
CLI for NeoRunner.
Provides command-line interface for server management.
"""


import argparse
import fcntl
import json
import os
import signal
import sys
import threading
import time

from .config import ServerConfig, load_cfg, save_cfg
from .constants import CWD, PID_FILE
from .log import log_event


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    print("\n\nReceived shutdown signal. Cleaning up...")
    sys.exit(0)


def _read_daemon_pid() -> int | None:
    """Return the running daemon's PID from the pid file, or None if absent/stale."""
    try:
        if not PID_FILE.exists():
            return None
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 0 else None


def _pid_alive(pid: int) -> bool:
    """True if a process with the given PID currently exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _is_neorunner_process(pid: int) -> bool:
    """True if the PID's command line looks like a NeoRunner process."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\x00", b" ")
        return b"neorunner" in cmdline
    except OSError:
        return False


def _running_daemon_pid() -> int | None:
    """Return the PID of a live NeoRunner daemon, or None."""
    pid = _read_daemon_pid()
    if pid is None:
        return None
    if not _pid_alive(pid):
        return None
    if not _is_neorunner_process(pid):
        return None
    return pid


def _acquire_instance_lock() -> int | None:
    """Acquire the single-instance lock (``fcntl.flock`` on the pid file).

    Returns the open lock file descriptor, or ``None`` if another NeoRunner
    instance already holds the lock.  The flock is released automatically when
    the process exits, so a crashed daemon never leaves a stale lock behind.
    """
    try:
        fd = os.open(str(PID_FILE), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        print(f"Warning: could not open pid file {PID_FILE}: {e}")
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode())
    except OSError:
        pass
    return fd


def _stop_daemon(wait: float = 10.0) -> bool:
    """Terminate a running daemon (SIGTERM) and wait for it to exit."""
    pid = _running_daemon_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.time() + wait
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.1)
    return not _pid_alive(pid)


def _signal_daemon_reload() -> bool:
    """Ask the running daemon to reload config + users (SIGHUP)."""
    pid = _running_daemon_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGHUP)
        return True
    except OSError:
        return False


def cmd_start(args):
    """Start the NeoRunner server and services with crash recovery."""
    # Single-instance guard: refuse to spin up a second daemon/dashboard.
    lock_fd = _acquire_instance_lock()
    if lock_fd is None:
        print("NeoRunner is already running.")
        print("Use 'neorunner restart' to restart, or 'neorunner stop' first.")
        return 1

    if args.daemon:
        pid = os.fork()
        if pid > 0:
            if args.pid_file:
                try:
                    with open(args.pid_file, 'w') as f:
                        f.write(str(pid))
                except OSError:
                    pass
            sys.exit(0)
        
        os.setsid()
        
        # Refresh the pid file with our (child) pid now that we are the daemon.
        try:
            os.ftruncate(lock_fd, 0)
            os.lseek(lock_fd, 0, os.SEEK_SET)
            os.write(lock_fd, str(os.getpid()).encode())
        except OSError:
            pass
        
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
    
    cfg = load_cfg()
    
    from .config import ensure_config, validate_config
    cfg = ensure_config(cfg)
    
    valid, errors = validate_config(cfg, fail_on_error=False)
    if not valid:
        print(f"WARNING: Config has issues: {'; '.join(errors)}")
        print("Run 'neorunner init --force' to regenerate default config")
        if not args.force:
            return 1
    
    print(f"Starting NeoRunner server (MC {cfg.mc_version}, {cfg.loader})...")
    print(f"Working directory: {CWD}")
    
    # Import here to avoid circular imports
    from .dashboard import run_dashboard
    from .installer import check_system_deps, setup
    from .server import is_server_running, run_server, stop_server, wait_for_server
    
    # Check system dependencies
    if not check_system_deps():
        print("WARNING: Some system dependencies are missing.")
        print("Run 'neorunner setup' to install them.")
        if not args.force:
            response = input("Continue anyway? [y/N]: ")
            if response.lower() != 'y':
                return 1
    
    # Run setup if needed
    if not (CWD / "server.properties").exists():
        print("No server.properties found. Running setup...")
        if not setup(cfg):
            print("Setup failed!")
            return 1
    
    # Ensure the loader jar shows the modpack download link instead of the
    # generic "Incompatible client!" message (idempotent; re-applies after
    # loader version bumps that replace the jar).
    try:
        from .jar_message_patcher import loader_is_patched, patch_loader_messages
        if not loader_is_patched(cfg.loader):
            print("Patching loader jar with modpack download message...")
            patch_loader_messages(cfg.loader)
    except Exception as e:
        log_event("WARN", f"Could not patch loader jar: {e}")
    
    # Start services
    threads = []
    server_process = None
    shutdown_requested = False
    
    # Start dashboard (Flask handles both web UI and mod downloads)
    if not args.no_dashboard:
        print(f"Starting dashboard on port {cfg.http_port}...")
        dashboard_thread = threading.Thread(
            target=run_dashboard,
            args=("0.0.0.0", cfg.http_port),
            daemon=True
        )
        dashboard_thread.start()
        threads.append(dashboard_thread)
        time.sleep(1)
    
    # Handle shutdown signals
    def request_shutdown():
        nonlocal shutdown_requested
        shutdown_requested = True
        if server_process:
            stop_server()
        try:
            os.close(lock_fd)
        except OSError:
            pass

    # SIGHUP: reload config + user store (sent by `neorunner users` and others).
    def handle_reload(signum, frame):
        nonlocal cfg
        try:
            from .config import ensure_config
            from .config import load_cfg as _reload_cfg
            cfg = ensure_config(_reload_cfg())
            log_event("RELOAD", "Reloaded config and user store (SIGHUP)")
        except Exception as e:
            log_event("WARN", f"Reload failed: {e}")

    signal.signal(signal.SIGINT, lambda s, f: request_shutdown())
    signal.signal(signal.SIGTERM, lambda s, f: request_shutdown())
    signal.signal(signal.SIGHUP, handle_reload)
    
    # Start Minecraft server with crash recovery loop
    if not args.no_server:
        restart_count = 0
        max_restarts = cfg.max_restart_attempts
        crash_cooldown = 30  # seconds between restarts
        
        while not shutdown_requested:
            if is_server_running():
                print("Minecraft server is already running!")
                break
            
            # Run preflight/dependency check in background thread
            # NOTE: Server.py now handles dependency resolution - don't double-fetch
            if not args.no_preflight:
                print("Running preflight checks...")
                def run_preflight():
                    try:
                        from .self_heal import preflight_dep_check
                        preflight_dep_check(cfg)
                    except Exception as e:
                        log_event("WARN", f"Preflight error: {e}")

                preflight_thread = threading.Thread(target=run_preflight, daemon=True)
                preflight_thread.start()
            
            print("Starting Minecraft server...")
            server_started = run_server(cfg)
            
            if not server_started:
                print("Failed to start Minecraft server!")
                if restart_count >= max_restarts:
                    log_event("ERROR", f"Max restarts ({max_restarts}) reached, giving up")
                    break
                restart_count += 1
                print(f"Restarting in {crash_cooldown}s (attempt {restart_count}/{max_restarts})...")
                time.sleep(crash_cooldown)
                continue
            
            print("Minecraft server started")
            
            # Wait for server to actually bind ports
            if not wait_for_server(timeout=60):
                print("Server failed to bind ports within 60s")
                restart_count += 1
                if restart_count >= max_restarts:
                    log_event("ERROR", f"Max restarts ({max_restarts}) reached")
                    break
                time.sleep(crash_cooldown)
                continue
            
            # Server is running - monitor it
            restart_count = 0  # Reset on successful start
            while not shutdown_requested:
                if not is_server_running():
                    # Server crashed
                    log_event("CRASH", "Server process died")
                    print(f"\nServer crashed! Restarting in {crash_cooldown}s...")
                    break
                time.sleep(5)
            
            if shutdown_requested:
                break
    
    print("\n" + "="*50)
    print("NeoRunner is running!")
    print(f"Dashboard: http://0.0.0.0:{cfg.http_port}")
    print("  (Access from any device on your network)")
    print("Press Ctrl+C to stop")
    print("="*50 + "\n")
    
    # Keep running - this is the main loop that monitors Java
    restart_attempts = 0
    max_restart_attempts = cfg.max_restart_attempts
    restart_delay = 5
    try:
        while not shutdown_requested:
            if args.no_server:
                break
            # Check if server is still running
            if not is_server_running() and not shutdown_requested:
                if restart_attempts >= max_restart_attempts:
                    log_event("ERROR", f"Server failed to start after {max_restart_attempts} attempts. Stopping auto-restart.")
                    break
                log_event("WARN", f"Server stopped unexpectedly, attempting restart ({restart_attempts + 1}/{max_restart_attempts})...")
                restart_attempts += 1
                time.sleep(2)
                if run_server(cfg, max_retries=2):
                    log_event("INFO", "Server restarted successfully")
                    restart_attempts = 0
                else:
                    log_event("ERROR", "Failed to restart server")
                    time.sleep(restart_delay)
                continue
            restart_attempts = 0
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        if server_process:
            stop_server()
    
    return 0


def cmd_stop(args):
    """Stop the NeoRunner server."""
    from .server import is_server_running, stop_server
    
    print("Stopping NeoRunner...")
    
    if is_server_running():
        if stop_server():
            print("Server stopped.")
        else:
            print("Failed to stop server!")
    else:
        print("Server is not running.")
    
    # Also terminate the daemon (dashboard + monitor) so a later `start` can
    # re-acquire the single-instance lock.
    if _stop_daemon():
        print("Daemon stopped.")
    else:
        print("Daemon is not running.")
    
    return 0


def cmd_restart(args):
    """Restart the NeoRunner server."""
    cmd_stop(args)
    time.sleep(2)
    return cmd_start(args)


def cmd_setup(args):
    """Run setup wizard - prompts unless --yes flag or all args provided."""
    from .config import ensure_config, load_cfg, save_cfg
    from .installer import setup
    from .version import (
        get_all_minecraft_versions,
        get_latest_for_loader,
        get_latest_minecraft_version,
    )
    
    cfg = load_cfg()
    cfg = ensure_config(cfg)
    
    # Always prompt unless --yes flag OR all required args provided
    has_all_args = bool(args.mc_version and args.loader and args.xmx and args.http_port)
    skip_prompts = args.yes or has_all_args
    
    if args.mc_version:
        if args.mc_version.lower() == "latest":
            print("  Fetching latest Minecraft version...")
            cfg.mc_version = get_latest_minecraft_version()
        else:
            cfg.mc_version = args.mc_version
    if args.loader:
        cfg.loader = args.loader
    if args.xmx:
        cfg.xmx = args.xmx
        if "G" in args.xmx:
            val = int(args.xmx.replace("G", "")) // 2
            cfg.xms = f"{val}G"
    if args.xms:
        cfg.xms = args.xms
    if args.http_port:
        cfg.http_port = args.http_port
    
    print("="*50)
    print("NeoRunner Setup Wizard")
    print("="*50)
    
    if skip_prompts:
        # Non-interactive: use defaults or command-line args, skip prompts
        print("Running in non-interactive mode...")
        if has_all_args:
            print(f"  Using: MC {cfg.mc_version}, {cfg.loader}, {cfg.xmx}, HTTP {cfg.http_port}")
    else:
        # Interactive mode - only if TTY is available
        print("\nStep 1: Select Minecraft Version")
        print(f"  Current: {cfg.mc_version}")
        print("  [1] Latest (auto-detect)")
        print("  [2] Custom version")
        ver_choice = input("  Select [1]: ").strip() or "1"
        
        if ver_choice == "1":
            print("    Fetching latest version...")
            cfg.mc_version = get_latest_minecraft_version()
            print(f"    Using: {cfg.mc_version}")
        elif ver_choice == "2":
            all_vers = get_all_minecraft_versions()
            print(f"  Available: {', '.join(all_vers[:5])}")
            try:
                cfg.mc_version = input("  Enter version: ").strip() or cfg.mc_version
            except (EOFError, AttributeError):
                pass
        
        print("\nStep 2: Select Mod Loader")
        print(f"  Current: {cfg.loader}")
        print("  [1] NeoForge (recommended)")
        print("  [2] Forge")
        print("  [3] Fabric")
        try:
            loader_choice = input("  Select [1]: ").strip() or "1"
        except (EOFError, AttributeError):
            loader_choice = "1"
        
        loader_map = {"1": "neoforge", "2": "forge", "3": "fabric"}
        cfg.loader = loader_map.get(loader_choice, "neoforge")
        
        print(f"    Fetching latest {cfg.loader} version...")
        loader_ver = get_latest_for_loader(cfg.loader)
        print(f"    Version: {loader_ver}")
        
        print("\nStep 3: Memory Allocation")
        print(f"  Current max: {cfg.xmx}")
        try:
            xmx_input = input(f"  Enter max memory [default: {cfg.xmx}]: ").strip()
            if xmx_input:
                cfg.xmx = xmx_input
                if "G" in xmx_input:
                    val = int(xmx_input.replace("G", "")) // 2
                    cfg.xms = f"{val}G"
                else:
                    cfg.xms = cfg.xmx
        except (EOFError, AttributeError):
            pass
        
        print("\nStep 4: Server Configuration")
        print(f"  HTTP Port: {cfg.http_port}")
        try:
            port_input = input(f"  Enter HTTP port [default: {cfg.http_port}]: ").strip()
            if port_input and port_input.isdigit():
                cfg.http_port = int(port_input)
        except (ValueError, EOFError, AttributeError):
            pass  # Keep default
        
        save_cfg(cfg)
        print("\nConfiguration saved!")
    
    print("\nRunning NeoRunner setup...")
    if not setup(cfg):
        print("Setup failed!")
        return 1
    print("Setup complete!")
    print("\nServer configured for:")
    print(f"  Minecraft: {cfg.mc_version}")
    print(f"  Loader: {cfg.loader}")
    print(f"  Memory: {cfg.xms} -> {cfg.xmx}")
    print(f"  HTTP Port: {cfg.http_port}")

    # External access (dynamic DNS + automatic SSL) - first-class, hard-fails.
    from .external_access import (
        ExternalAccessError,
        setup_external_access,
        setup_systemd,
    )

    wants_external = bool(args.domain and args.external_access)
    if wants_external:
        print(f"\nConfiguring external access via {args.external_access} for {args.domain}...")
        try:
            setup_external_access(cfg, {
                "domain": args.domain,
                "external_access": args.external_access,
                "cf_token": args.cf_token or "",
                "mc_port": args.mc_port,
                "ddclient": args.ddclient,
                "ddclient_provider": args.ddclient_provider,
                "ddclient_login": args.ddclient_login,
                "ddclient_password": args.ddclient_password,
            })
            print(f"  External access configured: https://{args.domain}")
        except ExternalAccessError as e:
            print(f"  FAILED to configure external access: {e}")
            return 1
    elif args.domain and not args.external_access:
        print("  Note: --domain given but no --external-access provider; skipping (use --external-access caddy|cloudflare)")

    if args.systemd:
        print("\nInstalling systemd service for persistence...")
        try:
            setup_systemd(cfg)
            print("  systemd service installed (neorunner.service, auto-start on boot)")
        except ExternalAccessError as e:
            print(f"  FAILED to install systemd service: {e}")
            return 1

    return 0


def cmd_init(args):
    """Initialize default config - only if missing or --force."""
    from .config import ensure_config, load_cfg, save_cfg
    from .constants import CWD
    from .version import get_latest_minecraft_version
    
    config_path = CWD / "config.json"
    
    # If config exists and --force not given, show info and exit
    if config_path.exists():
        if not args.force:
            print(f"Config already exists at {config_path}")
            # Show current config instead of error
            cfg = load_cfg()
            print(f"  MC: {cfg.mc_version}, Loader: {cfg.loader}, Memory: {cfg.xmx}")
            print("  Use --force to regenerate, or 'neorunner config --setup' to edit interactively")
            return 0
        # With --force, we still shouldn't destroy good config, ask user
        print("Config exists. Use 'neorunner config --setup' to edit, or delete config.json first")
        return 1
    
    # Determine MC version
    if args.latest:
        print("Fetching latest Minecraft version...")
        mc_version = get_latest_minecraft_version()
        print(f"  Latest: {mc_version}")
    elif args.mc_version:
        mc_version = args.mc_version
    else:
        mc_version = "1.21.11"
    
    cfg = ServerConfig(
        mc_version=mc_version,
        loader=args.loader,
        xmx=args.xmx,
        xms=args.xmx.replace("G", "G").replace("M", "M") if "G" in args.xmx else args.xmx,
    )
    
    if cfg.xms == cfg.xmx and "G" in cfg.xmx:
        val = int(cfg.xmx.replace("G", "")) // 2
        cfg.xms = f"{val}G"
    
    cfg = ensure_config(cfg)
    save_cfg(cfg)
    
    print(f"Created default config at {config_path}")
    print(f"  MC Version: {cfg.mc_version}")
    print(f"  Loader: {cfg.loader}")
    print(f"  Memory: {cfg.xms} -> {cfg.xmx}")
    print("\nRun 'neorunner setup' to complete installation")
    
    return 0


def cmd_status(args):
    """Show server status."""
    from .server import is_server_running
    
    cfg = load_cfg()
    
    print("NeoRunner Status")
    print("="*50)
    print(f"Working directory: {CWD}")
    print(f"Minecraft version: {cfg.mc_version}")
    print(f"Loader: {cfg.loader}")
    print(f"HTTP port: {cfg.http_port}")
    print(f"Server running: {'Yes' if is_server_running() else 'No'}")
    
    return 0


def cmd_config(args):
    """Manage configuration."""
    cfg = load_cfg()
    
    if args.setup:
        # Interactive config wizard
        return cmd_config_setup(cfg)
    
    if args.show:
        print("Current Configuration:")
        print(json.dumps(cfg.to_dict(), indent=2))
    elif args.key and args.value:
        # Update config value
        if hasattr(cfg, args.key):
            old_value = getattr(cfg, args.key)
            setattr(cfg, args.key, args.value)
            save_cfg(cfg)
            print(f"Updated {args.key}: {old_value} -> {args.value}")
        else:
            print(f"Unknown config key: {args.key}")
            return 1
    else:
        print("Use --show to display config, --setup for interactive wizard, or KEY VALUE to update")
    
    return 0


def cmd_config_setup(cfg):
    """Interactive configuration wizard."""
    from .config import ensure_config, save_cfg
    from .version import get_latest_for_loader, get_latest_minecraft_version
    
    print("="*50)
    print("NeoRunner Configuration Wizard")
    print("="*50)
    
    try:
        print(f"\n  Current MC: {cfg.mc_version}, Loader: {cfg.loader}")
        mc_input = input("  Enter MC version (or 'latest' for auto): ").strip()
        if mc_input.lower() == "latest" or not mc_input:
            cfg.mc_version = get_latest_minecraft_version()
            print(f"  Using: {cfg.mc_version}")
        elif mc_input:
            cfg.mc_version = mc_input
        
        print(f"\n  Current Loader: {cfg.loader}")
        print("  [1] NeoForge  [2] Forge  [3] Fabric")
        loader_choice = input("  Select loader [1]: ").strip() or "1"
        loader_map = {"1": "neoforge", "2": "forge", "3": "fabric"}
        cfg.loader = loader_map.get(loader_choice, "neoforge")
        
        if cfg.loader:
            latest = get_latest_for_loader(cfg.loader)
            print(f"  Latest {cfg.loader}: {latest}")
        
        print(f"\n  Current Memory: {cfg.xmx}")
        xmx_input = input("  Enter max memory [e.g. 4G, Enter for default]: ").strip()
        if not xmx_input:
            xmx_input = "4G"
        cfg.xmx = xmx_input
        if "G" in xmx_input:
            val = int(xmx_input.replace("G", "")) // 2
            cfg.xms = f"{val}G"
        
        print(f"\n  Current HTTP Port: {cfg.http_port}")
        port_input = input("  Enter HTTP port [Enter for default]: ").strip()
        if port_input and port_input.isdigit():
            cfg.http_port = int(port_input)
        elif not port_input:
            cfg.http_port = 8000
        
        cfg = ensure_config(cfg)
        save_cfg(cfg)
        print("Configuration saved!")
        
        # Now install the loader
        from .installer import setup
        print("\nInstalling loader...")
        if setup(cfg):
            print("Loader installed!")
        else:
            print("Loader install had issues - try 'neorunner setup' later")
        
        return 0
        
    except EOFError:
        print("\nCancelled.")
        return 1


def cmd_world(args):
    """World management commands."""
    from .worlds import WorldManager
    
    manager = WorldManager()
    
    if args.list:
        worlds = manager.scan_worlds()
        print("\nAvailable Worlds:")
        print("-" * 60)
        print(f"{'Name':<20} {'Version':<12} {'Size (MB)':<12} {'Status'}")
        print("-" * 60)
        
        current = manager.get_current_world()
        for world in worlds:
            status = "(current)" if world["name"] == current else ""
            version = world.get("mc_version", "unknown") or "unknown"
            size = world.get("size_mb", 0)
            print(f"{world['name']:<20} {version:<12} {size:<12.1f} {status}")
        print()
    
    elif args.switch:
        success, message = manager.switch_world(args.switch, force=args.force)
        print(message)
        return 0 if success else 1
    
    elif args.backup:
        print(f"Creating backup of {args.backup}...")
        success, message = manager.backup_world(args.backup)
        print(message)
        return 0 if success else 1
    
    elif args.info:
        info = manager.get_world_info(args.info)
        print(json.dumps(info, indent=2))
    
    else:
        print("Use --list, --switch NAME, --backup NAME, or --info NAME")
    
    return 0


def cmd_mods(args):
    """Mod management commands."""
    cfg = load_cfg()
    
    if args.list:
        from .mods import sort_mods_by_type
        
        mods_dir = CWD / cfg.mods_dir
        result = sort_mods_by_type(mods_dir, cfg)
        
        print(f"\nMods in {mods_dir}:")
        print("-" * 60)
        print(f"\nServer mods ({len(result.get('server', []))}):")
        for mod in result.get("server", [])[:20]:  # Show first 20
            print(f"  - {mod.name}")
        if len(result.get("server", [])) > 20:
            print(f"  ... and {len(result.get('server', [])) - 20} more")
        
        print(f"\nClient-only mods ({len(result.get('clientonly', []))}):")
        for mod in result.get("clientonly", [])[:10]:  # Show first 10
            print(f"  - {mod.name}")
        if len(result.get("clientonly", [])) > 10:
            print(f"  ... and {len(result.get('clientonly', [])) - 10} more")
        print()
    
    elif args.upgrade:
        print("Upgrading mods via ferium...")
        from .ferium import FeriumManager
        
        manager = FeriumManager()
        if manager.upgrade_mods():
            print("Mods upgraded successfully!")
        else:
            print("Mod upgrade failed!")
            return 1
    
    elif args.keywords:
        # Install by keywords
        from .mod_manager import ModManager
        cfg_dict = {'loader': cfg.loader, 'mc_version': cfg.mc_version, 'mods_dir': cfg.mods_dir}
        mm = ModManager(cfg_dict, cwd=str(CWD))
        result = mm.install_by_keywords(args.keywords)
        print(f"\nInstalled: {len(result.get('installed', []))}")
        for slug in result.get('installed', []):
            print(f"  + {slug}")
        if result.get('failed'):
            print(f"Failed: {len(result['failed'])}")
        return 0
    
    elif args.sort:
        print("Sorting mods by type...")
        import shutil

        from .mods import sort_mods_by_type
        
        mods_dir = CWD / cfg.mods_dir
        clientonly_dir = mods_dir / "clientonly"
        clientonly_dir.mkdir(exist_ok=True)
        
        result = sort_mods_by_type(mods_dir, cfg)
        
        moved = 0
        for jar_path in result.get("clientonly", []):
            dest = clientonly_dir / jar_path.name
            if not dest.exists():
                shutil.move(str(jar_path), str(dest))
                moved += 1
        
        print(f"Moved {moved} client-only mods to {clientonly_dir}")
    
    else:
        print("Use --list, --upgrade, or --sort")
    
    return 0


def cmd_users(args):
    """Admin user management (dashboard login credentials)."""
    from .users import add_user, list_users, remove_user, set_password

    if args.list:
        users = list_users()
        if not users:
            print("No admin users configured (dashboard falls back to env bootstrap credentials).")
        else:
            print("Admin users:")
            for u in users:
                print(f"  - {u}")
        return 0

    if args.add:
        if not args.password:
            import getpass
            args.password = getpass.getpass(f"Password for {args.add}: ")
        if add_user(args.add, args.password):
            print(f"Added/updated user '{args.add}'.")
            if _signal_daemon_reload():
                print("Daemon reloaded; the new user can log in now.")
            else:
                print("No running daemon; changes apply on next 'neorunner start'.")
            return 0
        print("Error: username and password are required.")
        return 1

    if args.remove:
        if remove_user(args.remove):
            print(f"Removed user '{args.remove}'.")
            _signal_daemon_reload()
            return 0
        print(f"User '{args.remove}' not found.")
        return 1

    if args.set_password:
        if not args.password:
            import getpass
            args.password = getpass.getpass(f"New password for {args.set_password}: ")
        if set_password(args.set_password, args.password):
            print(f"Updated password for '{args.set_password}'.")
            _signal_daemon_reload()
            return 0
        print(f"User '{args.set_password}' not found.")
        return 1

    print("Usage: neorunner users [--list | --add USER | --remove USER | --set-password USER] [--password PASS]")
    return 1


def _add_start_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared start/restart options to a subparser."""
    parser.add_argument('--no-server', action='store_true', help='Run dashboard only, skip Minecraft server')
    parser.add_argument('--no-dashboard', action='store_true', help='Run server only, skip dashboard')
    parser.add_argument('--xmx', default=None, help='Override max heap memory')
    parser.add_argument('--xms', default=None, help='Override initial heap memory')
    parser.add_argument('--no-preflight', action='store_true', help='Skip preflight dependency checks')
    parser.add_argument('--force', action='store_true', help='Force start even with missing deps')
    parser.add_argument('--foreground', action='store_true', help='Run in foreground (don\'t daemonize)')
    parser.add_argument('--daemon', '-d', action='store_true', help='Run in background (daemon mode)')
    parser.add_argument('--pid-file', help='PID file to write when daemonizing')


def main():
    """Main CLI entry point."""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = argparse.ArgumentParser(
        prog='neorunner',
        description='NeoRunner - Minecraft Modded Server Manager'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start the server')
    _add_start_args(start_parser)
    
    # Stop command
    subparsers.add_parser('stop', help='Stop the server and daemon')
    
    # Restart command (shares start options)
    restart_parser = subparsers.add_parser('restart', help='Restart the server')
    _add_start_args(restart_parser)
    
    # Help command - full verbosity for every command
    subparsers.add_parser('help', help='Show full help for all commands and options')
    
    # Install command - full installation with external access + persistence
    install_parser = subparsers.add_parser('install', help='Install NeoRunner (config, loader, external access, systemd)')
    install_parser.add_argument('--mc-version', default=None, help='Minecraft version (auto-detected if not specified)')
    install_parser.add_argument('--loader', default=None, choices=['neoforge', 'forge', 'fabric'], help='Mod loader (NeoForge default)')
    install_parser.add_argument('--xmx', default=None, help='Max heap memory (default: 4G)')
    install_parser.add_argument('--xms', default=None, help='Initial heap memory')
    install_parser.add_argument('--http-port', type=int, default=None, help='HTTP port for dashboard')
    install_parser.add_argument('--query-port', type=int, default=None, help='Game port')
    install_parser.add_argument('--force', action='store_true', help='Force setup even if config exists')
    install_parser.add_argument('--yes', '-y', action='store_true', help='Skip all prompts, use defaults')
    install_parser.add_argument('--domain', default=None, help='Public domain for external access (e.g. play.example.com)')
    install_parser.add_argument('--external-access', default=None, choices=['caddy', 'cloudflare'], help='Expose dashboard/downloads (and MC port) publicly')
    install_parser.add_argument('--cf-token', default=None, help='Cloudflare API token for named-tunnel setup')
    install_parser.add_argument('--mc-port', type=int, default=None, help='Public TCP port to proxy Minecraft through (Caddy)')
    install_parser.add_argument('--ddclient', action='store_true', help='Configure ddclient dynamic DNS for --domain')
    install_parser.add_argument('--ddclient-provider', default='dyndns2', help='ddclient protocol (dyndns2, cloudflare, noip...)')
    install_parser.add_argument('--ddclient-login', default='', help='ddclient account/login')
    install_parser.add_argument('--ddclient-password', default='', help='ddclient password/token')
    install_parser.add_argument('--systemd', action='store_true', help='Install a systemd service for auto-start (persistence)')
    
    # Init command - create default config
    init_parser = subparsers.add_parser('init', help='Initialize default config')
    init_parser.add_argument('--force', action='store_true', help='Overwrite existing config')
    init_parser.add_argument('--latest', action='store_true', help='Use latest Minecraft version')
    init_parser.add_argument('--mc-version', default=None, help='Minecraft version')
    init_parser.add_argument('--loader', default='neoforge', choices=['neoforge', 'forge', 'fabric'], help='Mod loader')
    init_parser.add_argument('--xmx', default='4G', help='Max heap memory')
    
    # Status command
    subparsers.add_parser('status', help='Show server status')
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Manage configuration')
    config_parser.add_argument('--show', action='store_true', help='Show current config')
    config_parser.add_argument('--setup', action='store_true', help='Interactive configuration wizard')
    config_parser.add_argument('key', nargs='?', help='Config key to update')
    config_parser.add_argument('value', nargs='?', help='New value')
    
    # World command
    world_parser = subparsers.add_parser('world', help='World management')
    world_parser.add_argument('--list', action='store_true', help='List worlds')
    world_parser.add_argument('--switch', help='Switch to world')
    world_parser.add_argument('--backup', help='Backup world')
    world_parser.add_argument('--info', help='Show world info')
    world_parser.add_argument('--force', action='store_true', help='Force operation')
    
    # Mods command
    mods_parser = subparsers.add_parser('mods', help='Mod management')
    mods_parser.add_argument('--list', action='store_true', help='List mods')
    mods_parser.add_argument('--upgrade', action='store_true', help='Upgrade mods')
    mods_parser.add_argument('--sort', action='store_true', help='Sort mods by type')
    mods_parser.add_argument('--keywords', nargs='+', help='Keywords to search/install mods')

    # Users command - admin credential management
    users_parser = subparsers.add_parser('users', help='Manage admin dashboard users')
    users_parser.add_argument('--list', action='store_true', help='List admin users')
    users_parser.add_argument('--add', help='Add a user (or reset their password)')
    users_parser.add_argument('--remove', help='Remove a user')
    users_parser.add_argument('--set-password', help='Change a user password')
    users_parser.add_argument('--password', help='Password (prompts if omitted)')
    
    args = parser.parse_args()
    
    if args.command is None or args.command == 'help':
        # Full verbosity: main usage + every subcommand's full options.
        parser.print_help()
        print("\n" + "=" * 70)
        print("Command reference (full options)")
        print("=" * 70)
        for name, sub in subparsers.choices.items():
            print(f"\n$ neorunner {name}")
            sub.print_help()
        return 0
    
    # Route to appropriate handler
    handlers = {
        'start': cmd_start,
        'stop': cmd_stop,
        'restart': cmd_restart,
        'init': cmd_init,
        'install': cmd_setup,
        'status': cmd_status,
        'config': cmd_config,
        'world': cmd_world,
        'mods': cmd_mods,
        'users': cmd_users,
    }
    
    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
