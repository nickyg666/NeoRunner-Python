"""
NeoRunner - Minecraft modded server manager.

A comprehensive Python module for managing NeoForge, Forge, and Fabric servers
with automated mod management, web dashboard, and crash recovery.
"""

__version__ = "2.2.0"
__author__ = "Nickyg666"
__license__ = "MIT"

from pathlib import Path
import os

# All paths relative to this module directory
CWD = Path(__file__).parent.parent.resolve()

# Core modules
from .config import load_cfg, save_cfg, ensure_config, validate_config, ServerConfig
from .constants import (
    PARALLEL_PORTS, 
    MOD_LOADERS, 
    FORCED_SERVER_MODS, 
    FORCE_CLIENT_ONLY_MODS,
    MAX_RESTART_ATTEMPTS,
    MAX_TOTAL_RESTARTS,
    CRASH_COOLDOWN_SECONDS,
)
from .log import log_event
from .log_manager import LogManager, run_log_cleanup

# Server management
from .server import (
    run_server,
    stop_server,
    restart_server,
    send_command,
    is_server_running,
    wait_for_server,
    get_server,
    get_events,
    TmuxServer,
)

# Mod management
from .mods import (
    classify_mod,
    sort_mods_by_type,
    preflight_mod_compatibility_check,
    curate_mod_list,
    ModInfo,
    parse_mod_manifest,
    fetch_modrinth_mods,
    download_mod_from_modrinth,
    get_mod_dependencies_modrinth,
    resolve_mod_dependencies_modrinth,
    download_file,
    is_library,
)

# Backup management
from .backup import (
    backup_world,
    list_backups,
    restore_backup,
    cleanup_old_backups,
)

# Installation and setup
from .installer import (
    setup, 
    install_loader, 
    install_neoforge,
    install_fabric,
    install_forge,
    check_system_deps,
    install_system_deps,
    ensure_eula,
    ensure_directories,
    ensure_dependency,
    ensure_dependencies,
    strip_client_classes,
    handle_client_only_mod,
)

# Load order management
from .load_order import (
    restore_mod_names,
    generate_load_order,
    save_load_order,
    read_load_order,
    get_mod_load_order,
    strip_prefix,
)

# Ferium integration
from .ferium import (
    FeriumManager,
    setup_ferium_wizard,
)

# World management
from .worlds import (
    WorldManager,
    scan_worlds,
    switch_world,
    get_current_world,
)

# NBT parsing
from .nbt_parser import (
    get_world_version,
    parse_nbt,
)

# Dashboard and web interface
from .dashboard import (
    app as dashboard_app,
    run_dashboard,
)

# Mod hosting server
from .mod_hosting import (
    run_mod_server,
    create_mod_zip,
    conditional_create_mod_zip,
    SecureHTTPHandler,
)

# Mod browser
from .mod_browser import (
    ModBrowser,
    ModResult,
)

# Modpack converter
from .modpack_converter import (
    ModpackConverter,
    create_curseforge_pack,
)

# Java manager
from .java_manager import (
    JavaManager,
    JavaVersion,
    get_java_info,
)

# WebSocket support
from .websocket import (
    init_socketio,
    start_websocket_services,
    stop_websocket_services,
    emit_event,
    SOCKETIO_AVAILABLE,
)

# Loaders (NeoForge, Forge, Fabric)
from .loaders import (
    get_loader,
    LoaderBase,
)
from .loaders.neoforge import NeoForgeLoader
from .loaders.forge import ForgeLoader
from .loaders.fabric import FabricLoader

# Self-healing and crash handling
from .self_heal import (
    preflight_dep_check,
    quarantine_mod,
    load_crash_history,
    save_crash_history,
)

# Crash and network analysis
from .crash_analyzer import CrashAnalyzer, CrashAnalysis
from .network_channel_analyzer import NetworkChannelAnalyzer, ChannelMismatch

# CurseForge scraping
from .curseforge import (
    search_curseforge,
    is_available as curseforge_available,
    PLAYWRIGHT_AVAILABLE,
)

# CLI
from .cli import main as cli_main

__all__ = [
    # Metadata
    "__version__",
    "__author__",
    "__license__",
    "CWD",
    
    # Constants
    "MOD_LOADERS",
    "FORCED_SERVER_MODS",
    "FORCE_CLIENT_ONLY_MODS",
    "PARALLEL_PORTS",
    "MAX_RESTART_ATTEMPTS",
    "MAX_TOTAL_RESTARTS",
    "CRASH_COOLDOWN_SECONDS",
    
    # Config
    "load_cfg",
    "save_cfg",
    "ensure_config",
    "validate_config",
    "ServerConfig",
    
    # Server
    "run_server",
    "stop_server",
    "restart_server",
    "send_command",
    "is_server_running",
    "wait_for_server",
    "get_server",
    "get_events",
    "TmuxServer",
    
    # Mods
    "classify_mod",
    "sort_mods_by_type",
    "preflight_mod_compatibility_check",
    "curate_mod_list",
    "ModInfo",
    "parse_mod_manifest",
    "fetch_modrinth_mods",
    "download_mod_from_modrinth",
    "get_mod_dependencies_modrinth",
    "resolve_mod_dependencies_modrinth",
    "download_file",
    "is_library",
    
    # Backup
    "backup_world",
    "list_backups",
    "restore_backup",
    "cleanup_old_backups",
    
    # Log
    "log_event",
    "LogManager",
    "run_log_cleanup",
    
    # Installer
    "setup",
    "install_loader",
    "install_neoforge",
    "install_fabric", 
    "install_forge",
    "check_system_deps",
    "install_system_deps",
    "ensure_eula",
    "ensure_directories",
    "ensure_dependency",
    "ensure_dependencies",
    "strip_client_classes",
    "handle_client_only_mod",
    
    # Load Order
    "restore_mod_names",
    "generate_load_order",
    "save_load_order",
    "read_load_order",
    "get_mod_load_order",
    "strip_prefix",
    
    # Ferium
    "FeriumManager",
    "setup_ferium_wizard",
    
    # Worlds
    "WorldManager",
    "scan_worlds",
    "switch_world",
    "get_current_world",
    
    # NBT
    "get_world_version",
    "parse_nbt",
    
    # Dashboard
    "dashboard_app",
    "run_dashboard",
    
    # Mod Hosting
    "run_mod_server",
    "create_mod_zip",
    "conditional_create_mod_zip",
    "SecureHTTPHandler",
    
    # Mod Browser
    "ModBrowser",
    "ModResult",
    
    # Modpack Converter
    "ModpackConverter",
    "create_curseforge_pack",
    
    # Java Manager
    "JavaManager",
    "JavaVersion",
    "get_java_info",
    
    # WebSocket
    "init_socketio",
    "start_websocket_services",
    "stop_websocket_services",
    "emit_event",
    "SOCKETIO_AVAILABLE",
    
    # Loaders
    "get_loader",
    "LoaderBase",
    "NeoForgeLoader",
    "ForgeLoader",
    "FabricLoader",
    
    # Self-healing
    "preflight_dep_check",
    "quarantine_mod",
    "load_crash_history",
    "save_crash_history",
    
    # Crash and Network Analysis
    "CrashAnalyzer",
    "CrashAnalysis",
    "NetworkChannelAnalyzer",
    "ChannelMismatch",
    "LogManager",
    "run_log_cleanup",
    
    # CurseForge
    "search_curseforge",
    "curseforge_available",
    "PLAYWRIGHT_AVAILABLE",
    
    # CLI
    "cli_main",
]


def main():
    """Entry point for the neorunner command."""
    import sys
    sys.exit(cli_main())
