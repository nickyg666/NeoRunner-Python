"""
NeoRunner - Minecraft modded server manager.

A comprehensive Python module for managing NeoForge, Forge, and Fabric servers
with automated mod management, web dashboard, and crash recovery.
"""

__version__ = "2.4.0"
__author__ = "Nickyg666"
__license__ = "MIT"

from pathlib import Path

# All paths relative to this module directory
CWD = Path(__file__).parent.parent.resolve()

# Core modules
# Backup management
from .backup import (
    backup_world,
    cleanup_old_backups,
    list_backups,
    restore_backup,
)

# World upload / conversion
from .chunker import (
    CHUNKER_DOWNLOAD_URL,
    MIN_JAVA_REQUIRED,
    convert_world,
    ensure_chunker,
    get_chunker_jar,
    java_formats,
    list_available_formats,
    mc_to_chunker_format,
)

# CLI
from .cli import main as cli_main
from .config import ServerConfig, ensure_config, load_cfg, save_cfg, validate_config
from .constants import (
    CRASH_COOLDOWN_SECONDS,
    FORCE_CLIENT_ONLY_MODS,
    FORCED_SERVER_MODS,
    MAX_RESTART_ATTEMPTS,
    MAX_TOTAL_RESTARTS,
    MOD_LOADERS,
    PARALLEL_PORTS,
)

# Crash and network analysis
from .crash_analyzer import CrashAnalysis, CrashAnalyzer

# CurseForge scraping
from .curseforge import (
    PLAYWRIGHT_AVAILABLE,
    search_curseforge,
)
from .curseforge import (
    is_available as curseforge_available,
)

# Dashboard and web interface
from .dashboard import (
    app as dashboard_app,
)
from .dashboard import (
    run_dashboard,
)

# External access (dynamic DNS + automatic SSL)
from .external_access import (
    ExternalAccessError,
    setup_external_access,
)

# Ferium integration
from .ferium import (
    FeriumManager,
    setup_ferium_wizard,
)

# Installation and setup
from .installer import (
    check_system_deps,
    ensure_directories,
    ensure_eula,
    handle_client_only_mod,
    install_fabric,
    install_forge,
    install_loader,
    install_neoforge,
    install_system_deps,
    setup,
    strip_client_classes,
)

# Loader jar message patching
from .jar_message_patcher import (
    has_jar_signatures,
    loader_is_patched,
    patch_loader_messages,
    restore_loader_messages,
    strip_jar_signatures,
)

# Java manager
from .java_manager import (
    JavaManager,
    JavaVersion,
    get_java_info,
)

# Load order management
from .load_order import (
    generate_load_order,
    get_mod_load_order,
    read_load_order,
    restore_mod_names,
    save_load_order,
    strip_prefix,
)

# Loaders (NeoForge, Forge, Fabric)
from .loaders import (
    LoaderBase,
    get_loader,
)
from .loaders.fabric import FabricLoader
from .loaders.forge import ForgeLoader
from .loaders.neoforge import NeoForgeLoader
from .log import log_event
from .log_manager import LogManager, run_log_cleanup

# Mod browser
from .mod_browser import (
    ModBrowser,
    ModResult,
)

# Mod hosting server
from .mod_hosting import (
    SecureHTTPHandler,
    conditional_create_mod_zip,
    create_mod_zip,
    run_mod_server,
)

# Modpack converter
from .modpack_converter import (
    ModpackConverter,
    create_curseforge_pack,
)

# CurseForge modpack installer
from .modpack_installer import (
    InstallResult,
    download_cf_mod,
    extract_overrides,
    install_curseforge_pack,
    parse_manifest,
    resolve_file_name,
)

# Mod management
from .mods import (
    ModInfo,
    classify_mod,
    curate_mod_list,
    download_file,
    download_mod_from_modrinth,
    fetch_modrinth_mods,
    get_mod_dependencies_modrinth,
    is_library,
    parse_mod_manifest,
    preflight_mod_compatibility_check,
    resolve_mod_dependencies_modrinth,
    sort_mods_by_type,
)

# NBT parsing
from .nbt_parser import (
    get_world_version,
    parse_nbt,
)
from .network_channel_analyzer import ChannelMismatch, NetworkChannelAnalyzer

# Self-healing and crash handling
from .self_heal import (
    load_crash_history,
    preflight_dep_check,
    quarantine_mod,
    save_crash_history,
)

# Server management
from .server import (
    TmuxServer,
    get_events,
    get_server,
    is_server_running,
    restart_server,
    run_server,
    send_command,
    stop_server,
    wait_for_server,
)

# Admin user credential management
from .users import (
    add_user,
    has_users,
    list_users,
    remove_user,
    set_password,
    verify_credentials,
)

# WebSocket support
from .websocket import (
    SOCKETIO_AVAILABLE,
    emit_event,
    init_socketio,
    start_websocket_services,
    stop_websocket_services,
)
from .world_upload import (
    abort_upload,
    accept_upload,
    analyze_upload,
    archive_dir,
    cleanup_stale_staging,
    create_staging,
    detect_platform,
    extract_archive_upload,
    find_world_root,
    installed_java_major,
    java_compatibility,
    list_archived_worlds,
    load_archived_world,
    min_java_major,
    resolve_staging,
    restore_archived_world,
    sanitize_rel_path,
    sanitize_world_name,
    stage_file,
)

# World management
from .worlds import (
    WorldManager,
    get_current_world,
    scan_worlds,
    switch_world,
)

__all__ = [
    "CHUNKER_DOWNLOAD_URL",
    "CRASH_COOLDOWN_SECONDS",
    "CWD",
    "FORCED_SERVER_MODS",
    "FORCE_CLIENT_ONLY_MODS",
    "MAX_RESTART_ATTEMPTS",
    "MAX_TOTAL_RESTARTS",
    "MIN_JAVA_REQUIRED",
    "MOD_LOADERS",
    "PARALLEL_PORTS",
    "PLAYWRIGHT_AVAILABLE",
    "SOCKETIO_AVAILABLE",
    "ChannelMismatch",
    "CrashAnalysis",
    "CrashAnalyzer",
    "ExternalAccessError",
    "FabricLoader",
    "FeriumManager",
    "ForgeLoader",
    "InstallResult",
    "JavaManager",
    "JavaVersion",
    "LoaderBase",
    "LogManager",
    "ModBrowser",
    "ModInfo",
    "ModResult",
    "ModpackConverter",
    "NeoForgeLoader",
    "NetworkChannelAnalyzer",
    "SecureHTTPHandler",
    "ServerConfig",
    "TmuxServer",
    "WorldManager",
    "__author__",
    "__license__",
    "__version__",
    "abort_upload",
    "accept_upload",
    "add_user",
    "analyze_upload",
    "archive_dir",
    "backup_world",
    "check_system_deps",
    "classify_mod",
    "cleanup_old_backups",
    "cleanup_stale_staging",
    "cli_main",
    "conditional_create_mod_zip",
    "convert_world",
    "create_curseforge_pack",
    "create_mod_zip",
    "create_staging",
    "curate_mod_list",
    "curseforge_available",
    "dashboard_app",
    "detect_platform",
    "download_cf_mod",
    "download_file",
    "download_mod_from_modrinth",
    "emit_event",
    "ensure_chunker",
    "ensure_config",
    "ensure_directories",
    "ensure_eula",
    "extract_archive_upload",
    "extract_overrides",
    "fetch_modrinth_mods",
    "find_world_root",
    "generate_load_order",
    "get_chunker_jar",
    "get_current_world",
    "get_events",
    "get_java_info",
    "get_loader",
    "get_mod_dependencies_modrinth",
    "get_mod_load_order",
    "get_server",
    "get_world_version",
    "handle_client_only_mod",
    "has_jar_signatures",
    "has_users",
    "init_socketio",
    "install_curseforge_pack",
    "install_fabric",
    "install_forge",
    "install_loader",
    "install_neoforge",
    "install_system_deps",
    "installed_java_major",
    "is_library",
    "is_server_running",
    "java_compatibility",
    "java_formats",
    "list_archived_worlds",
    "list_available_formats",
    "list_backups",
    "list_users",
    "load_archived_world",
    "load_cfg",
    "load_crash_history",
    "loader_is_patched",
    "log_event",
    "mc_to_chunker_format",
    "min_java_major",
    "parse_manifest",
    "parse_mod_manifest",
    "parse_nbt",
    "patch_loader_messages",
    "preflight_dep_check",
    "preflight_mod_compatibility_check",
    "quarantine_mod",
    "read_load_order",
    "remove_user",
    "resolve_file_name",
    "resolve_mod_dependencies_modrinth",
    "resolve_staging",
    "restart_server",
    "restore_archived_world",
    "restore_backup",
    "restore_loader_messages",
    "restore_mod_names",
    "run_dashboard",
    "run_log_cleanup",
    "run_mod_server",
    "run_server",
    "sanitize_rel_path",
    "sanitize_world_name",
    "save_cfg",
    "save_crash_history",
    "save_load_order",
    "scan_worlds",
    "search_curseforge",
    "send_command",
    "set_password",
    "setup",
    "setup_external_access",
    "setup_ferium_wizard",
    "sort_mods_by_type",
    "stage_file",
    "start_websocket_services",
    "stop_server",
    "stop_websocket_services",
    "strip_client_classes",
    "strip_jar_signatures",
    "strip_prefix",
    "switch_world",
    "validate_config",
    "verify_credentials",
    "wait_for_server",
]


def main():
    """Entry point for the neorunner command."""
    import sys
    sys.exit(cli_main())
