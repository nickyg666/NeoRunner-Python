# NeoRunner

A comprehensive Python platform for managing self-hosted Minecraft modded servers with automated mod management, web dashboard, crash recovery, and client synchronization.

## Features

### Server Management
- **Multi-Loader Support**: NeoForge, Forge, and Fabric
- **Tmux-Based Process Management**: Server runs in tmux session with full output capture
- **Crash Recovery**: Automatic restart with configurable limits (5 attempts per crash loop, 15 total)
- **Preflight Dependency Checks**: Auto-fetch missing mod dependencies on startup
- **Java Version Detection**: Automatic Java version management per loader

### Web Dashboard
- **Real-Time Server Status**: Running state, player count, uptime
- **Mod Management**: Upload, delete, organize mods
- **World Management**: Scan, switch, backup worlds
- **Configuration UI**: Update ports, memory, mod settings
- **Live Log Streaming**: Real-time server log viewer
- **Network Channel Analysis**: Detect client/server mod mismatches

### Mod Management
- **Modrinth Integration**: Search and download mods via Modrinth API
- **CurseForge Integration**: Search via API or Selenium scraping
- **Ferium Integration**: Profile-based mod management with auto-updates
- **Mixin Conflict Resolution**: Detect and resolve mod mixin conflicts
- **Auto-Patching**: Patch mods for compatibility
- **Client/Server Classification**: Sort mods into `clientonly/` or `mods/` folders
- **Dependency Resolution**: Auto-fetch required dependencies

### Client Synchronization
- **HTTP Mod Hosting**: Serve mods to clients via built-in HTTP server
- **Manifest Generation**: JSON manifest of all server mods
- **Install Scripts**: Batch/PowerShell scripts for one-click client install
- **Client-Only Mod Handling**: Automatic client-side mod detection

### Logging & Diagnostics
- **Log Rotation**: Automatic rotation at configurable size
- **Retention Policies**: Configurable crash report and log retention (default 30 days)
- **Crash Log Analysis**: Parse client crash logs to identify issues
- **Network Channel Monitoring**: Real-time detection of mod mismatch at connection

### Backup & Restore
- **World Backups**: Compressed world backups with timestamp naming
- **Backup Rotation**: Configurable backup retention
- **Restore Functionality**: One-click world restore

## Architecture

```
neorunner/
├── __init__.py          # Package exports and entry point
├── config.py            # ServerConfig dataclass, load/save/validate
├── constants.py         # MOD_LOADERS, ports, CWD
├── server.py            # TmuxServer, crash monitoring, restart logic
├── dashboard.py         # Flask web UI and API endpoints
├── cli.py               # Command-line interface (argparse)
├── installer.py         # Loader installation, dependency checking
├── self_heal.py         # Preflight checks, dependency fetching
├── crash_analyzer.py    # Client crash log analysis
├── network_channel_analyzer.py  # Real-time mod mismatch detection
├── log_manager.py       # Log rotation and retention
├── mods.py              # Mod classification and curation
├── mod_browser.py       # Modrinth/CurseForge search
├── mod_hosting.py       # HTTP mod distribution server
├── mod_modder.py        # Mixin conflict detection/resolution
├── mod_patcher.py       # Auto-patch mods for compatibility
├── ferium.py            # Ferium integration with scheduler
├── worlds.py            # World scanning, switching, backup
├── backup.py            # World backup/restore
├── nbt_parser.py       # NBT parsing for level.dat
├── java_manager.py     # Java version detection
├── load_order.py       # Mod load order management
├── modpack_converter.py # Modpack format conversion
├── curseforge.py        # CurseForge API/scraping
├── websocket.py         # WebSocket support for real-time updates
├── log.py               # Event logging
├── verify.py            # Server verification
├── mod_stripper.py      # Strip client-only classes from server mods
├── loaders/            # Loader-specific implementations
│   ├── __init__.py     # get_loader factory
│   ├── neoforge.py     # NeoForgeLoader
│   ├── forge.py        # ForgeLoader
│   └── fabric.py       # FabricLoader
├── static/             # Static web assets
├── templates/          # HTML templates
└── tests/              # Test suite
```

## Installation

### Prerequisites
- Python 3.11+
- Java 21 (for NeoForge/Forge) or Java 17+ (for Fabric)
- tmux
- curl, rsync, unzip, zip

### Quick Start

```bash
# Install dependencies
pip install -e .

# Initialize configuration
neorunner init --mc-version 1.21.11 --loader neoforge --xmx 4G

# Run setup (install loader, create directories)
neorunner setup

# Start server with dashboard
neorunner start
```

## Configuration

Configuration is stored in `config.json`:

```json
{
  "mc_version": "1.21.11",
  "loader": "neoforge",
  "http_port": 8000,
  "mc_port": 25565,
  "rcon_port": 25575,
  "rcon_pass": "1",
  "xmx": "6G",
  "xms": "4G",
  "mods_dir": "mods",
  "clientonly_dir": "clientonly",
  "quarantine_dir": "quarantine",
  "log_retention_days": 30,
  "crash_report_retention_days": 30,
  "live_log_max_size_mb": 10,
  "live_log_backup_count": 5,
  "ferium_update_interval_hours": 4,
  "ferium_weekly_update_day": "mon",
  "ferium_weekly_update_hour": 2,
  "forced_server_mods": [],
  "forced_client_mods": [],
  "mod_blacklist": []
}
```

### Config Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mc_version` | string | "1.21.11" | Minecraft version |
| `loader` | string | "neoforge" | Mod loader (neoforge/forge/fabric) |
| `http_port` | int | 8000 | Dashboard HTTP port |
| `mc_port` | int | 25565 | Minecraft server port |
| `rcon_port` | int | 25575 | RCON port |
| `xmx` | string | "6G" | Maximum heap memory |
| `xms` | string | "4G" | Initial heap memory |
| `log_retention_days` | int | 30 | Days to keep logs |
| `crash_report_retention_days` | int | 30 | Days to keep crash reports |
| `live_log_max_size_mb` | int | MB | Size threshold for log rotation |
| `live_log_backup_count` | int | 5 | Number of rotated logs to keep |

## Usage

### CLI Commands

```bash
# Start server and dashboard
neorunner start

# Start without dashboard
neorunner start --no-dashboard

# Start without server (dashboard only)
neorunner start --no-server

# Stop server
neorunner stop

# Restart server
neorunner restart

# View logs
neorunner logs

# Setup wizard
neorunner setup

# Initialize config
neorunner init --force --mc-version 1.21.11 --loader neoforge

# Upgrade mods via Ferium
neorunner upgrade-mods

# Backup world
neorunner backup

# List worlds
neorunner worlds list

# Switch world
neorunner worlds switch myworld

# Curate mod list
neorunner curate

# Check for updates
neorunner check-updates
```

### Dashboard API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Server status |
| `/api/config` | GET/PUT | Configuration |
| `/api/mods` | GET | List mods |
| `/api/mods/<name>` | DELETE | Remove mod |
| `/api/server/start` | POST | Start server |
| `/api/server/stop` | POST | Stop server |
| `/api/worlds` | GET | List worlds |
| `/api/worlds/switch` | POST | Switch world |
| `/api/logs` | GET | Get logs |
| `/api/loaders` | GET | Loader status |

### Mod Hosting Endpoints

| Endpoint | Description |
|----------|-------------|
| `/download/manifest` | JSON manifest of mods |
| `/download/all` | ZIP of all mods |
| `/download/<modname>` | Individual mod download |
| `/download/install-mods.bat` | Windows install script |
| `/download/install` | PowerShell install script |

## Module Reference

### Core

- **`config.py`**: `ServerConfig` dataclass, `load_cfg()`, `save_cfg()`, `ensure_config()`, `validate_config()`
- **`constants.py`**: `MOD_LOADERS`, `PARALLEL_PORTS`, `CWD`, `MAX_RESTART_ATTEMPTS`
- **`server.py`**: `TmuxServer` class, `run_server()`, `stop_server()`, `restart_server()`, `send_command()`, `is_server_running()`, `get_events()`
- **`cli.py`**: CLI entry point with argparse subcommands

### Dashboard

- **`dashboard.py`**: Flask app with all API endpoints, `run_dashboard()`
- **`websocket.py`**: WebSocket support via socketio, `emit_event()`

### Mod Management

- **`mods.py`**: `classify_mod()`, `sort_mods_by_type()`, `preflight_mod_compatibility_check()`, `curate_mod_list()`, `ModInfo`
- **`mod_browser.py`**: `ModBrowser`, `ModResult` for Modrinth/CurseForge search
- **`mod_hosting.py`**: `run_mod_server()`, `create_mod_zip()`, `generate_bat_script()`
- **`mod_modder.py`**: `ModModder`, `MixinConflictResolver` for mixin conflict resolution
- **`mod_patcher.py`**: `ModPatcher`, `ModCompatibilityManager` for auto-patching
- **`ferium.py`**: `FeriumManager`, `setup_ferium_wizard()` for Ferium integration

### Diagnostics

- **`self_heal.py`**: `preflight_dep_check()`, `quarantine_mod()`, `load_crash_history()`, dependency fetching
- **`crash_analyzer.py`**: `CrashAnalyzer`, `CrashAnalysis` for crash log parsing
- **`network_channel_analyzer.py`**: `NetworkChannelAnalyzer`, `ChannelMismatch` for mod mismatch detection
- **`log_manager.py`**: `LogManager`, `run_log_cleanup()` for log rotation/retention

### Infrastructure

- **`installer.py`**: `setup()`, `install_loader()`, `install_neoforge()`, `install_forge()`, `install_fabric()`, `check_system_deps()`
- **`worlds.py`**: `WorldManager`, `scan_worlds()`, `switch_world()`, `get_current_world()`
- **`backup.py`**: `backup_world()`, `list_backups()`, `restore_backup()`, `cleanup_old_backups()`
- **`java_manager.py`**: `JavaManager`, `JavaVersion`, `get_java_info()`
- **`nbt_parser.py`**: `get_world_version()`, `parse_nbt()` for level.dat parsing
- **`load_order.py`**: `restore_mod_names()`, `generate_load_order()`, `get_mod_load_order()`

### Utilities

- **`curseforge.py`**: `search_curseforge()`, `is_available()`, `PLAYWRIGHT_AVAILABLE`
- **`modpack_converter.py`**: `ModpackConverter`, `create_curageforge_pack()`
- **`log.py`**: `log_event()` for structured event logging
- **`verify.py`**: Server verification utilities
- **`mod_stripper.py`**: Strip client-only classes from server JARs

### Loaders

- **`loaders/__init__.py`**: `get_loader()` factory function
- **`loaders/neoforge.py`**: `NeoForgeLoader` - NeoForge-specific installation and commands
- **`loaders/forge.py`**: `ForgeLoader` - Forge-specific installation and commands
- **`loaders/fabric.py`**: `FabricLoader` - Fabric-specific installation and commands

## Roadmap

### Planned Features

- [ ] **GUI Setup Wizard**: Web-based initial configuration
- [ ] **Modpack Import**: Import from CurseForge/modrinth modpacks
- [ ] **Player Management**: Whitelist, ban list, permissions
- [ ] **Scheduled Tasks**: Cron-like task scheduling
- [ ] **Metrics/Stats**: Player activity, mod usage stats
- [ ] **Plugin Support**: Extensible plugin system
- [ ] **Cluster Support**: Multiple server instances

### In Progress

- [x] Basic server management
- [x] Web dashboard
- [x] Mod management (Modrinth/CurseForge)
- [x] Client synchronization
- [x] Crash recovery
- [x] Log management
- [x] Mixin conflict resolution

### Known Limitations

- **Filename-based load order**: Not all launchers respect mod filename prefixes; proper dependency declarations in mods.toml/fabric.mod.json are more reliable
- **CurseForge scraping**: Uses Selenium which requires Firefox; API key is faster
- **RCON player list**: Basic parsing; may not work with all server configurations

## Troubleshooting

### Server Won't Start

1. Check Java version: `java -version` (requires Java 21 for NeoForge)
2. Verify loader is installed: `neorunner loaders`
3. Check logs: `neorunner logs` or `tail -f live.log`
4. Validate config: `neorunner init --force`

### Mod Crashes

1. Check crash-reports/ folder for crash logs
2. Use dashboard to analyze crash: `/api/mods/analyze`
3. Run mixin conflict resolution: `/api/mods/optimize-load-order`
4. Quarantine problematic mods

### Client Connection Issues

1. Check network channel events in dashboard
2. Ensure client has same mods as server
3. Run install script on client: `curl -sL "http://SERVER:8000/download/install" | powershell -`

### Dashboard Not Working

1. Check port is not in use: `lsof -i :8000`
2. Verify Flask is running: `ps aux | grep flask`
3. Check dashboard logs

## Development

### Running Tests

```bash
pip install pytest pytest-cov
pytest tests/ -v --cov=neorunner --cov-report=html
```

### Adding a New Loader

1. Create `loaders/myloader.py` with `LoaderBase` subclass
2. Add to `MOD_LOADERS` in `constants.py`
3. Add loader option to CLI and config validation

### Adding Dashboard API

1. Add route in `dashboard.py`: `@app.route('/api/endpoint', methods=['GET'])`
2. Add to exports in `__init__.py` if needed
3. Update HTML template to use new endpoint

## License

MIT License - See LICENSE file for details

## Credits

- Minecraft by Mojang Studios
- NeoForge, Forge, Fabric communities
- Modrinth and CurseForge APIs
