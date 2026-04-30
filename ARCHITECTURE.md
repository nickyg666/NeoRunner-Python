# NeoRunner Architecture

## Overview

NeoRunner is a comprehensive Minecraft modded server management platform written in Python. It provides automated mod management, web-based dashboard, crash recovery, and client synchronization capabilities.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        NeoRunner Platform                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │   CLI Layer   │    │  Dashboard   │    │   API Layer  │    │
│  │   (argparse)  │    │   (Flask)    │    │   (REST)     │    │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    │
│         │                   │                   │              │
│         └───────────────────┼───────────────────┘              │
│                             │                                    │
│                    ┌────────▼────────┐                         │
│                    │   Core Engine   │                         │
│                    │    (server.py)  │                         │
│                    └────────┬────────┘                         │
│                             │                                    │
│         ┌───────────────────┼───────────────────┐              │
│         │                   │                   │              │
│  ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐       │
│  │  TmuxServer │    │  LogManager │    │  SelfHealer │       │
│  │  Process   │    │  Rotation   │    │  Preflight  │       │
│  └─────────────┘    └─────────────┘    └─────────────┘       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Mod Management                         │  │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌─────────────┐   │  │
│  │  │ Browser │ │ Patcher │ │ Modder   │ │   Hosting  │   │  │
│  │  │(Modrinth│ │(Mixin)  │ │(Conflict)│ │  (HTTP)    │   │  │
│  │  │CurseForge)│ │         │ │Resolution│ │            │   │  │
│  │  └─────────┘ └─────────┘ └──────────┘ └─────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Loaders Layer                          │  │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐              │  │
│  │  │ NeoForge│    │  Forge  │    │ Fabric  │              │  │
│  │  └─────────┘    └─────────┘    └─────────┘              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Minecraft      │
                    │  Server (JVM)  │
                    └─────────────────┘
```

## Core Components

### 1. Server Management (`neorunner_pkg/server.py`)

The `TmuxServer` class is the heart of the system:

```
TmuxServer
├── Configuration (ServerConfig)
├── Loader (NeoForge/Forge/Fabric)
├── Process Management
│   ├── start() - Launch in tmux session
│   ├── stop() - Graceful shutdown via RCON
│   ├── restart() - Restart with cooldown
│   └── send_command() - Direct RCON commands
├── Crash Detection
│   ├── Pattern matching for crash logs
│   ├── Restart limit enforcement (5 per loop, 15 total)
│   └── Cooldown period between restarts
└── Event System
    ├── SERVER_START, SERVER_STOPPED, CRASH_DETECT
    ├── SELF_HEAL, QUARANTINE, MOD_INSTALL
    └── Dashboard integration via WebSocket
```

**Key Design Decisions:**
- Tmux isolation provides process resilience and log capture
- In-memory event store (200 events max) for dashboard polling
- Crash cooldown prevents boot loops (configurable)

### 2. Configuration Management (`neorunner_pkg/config.py`)

```
ServerConfig (dataclass)
├── Connection Settings
│   ├── http_port (8000) - Dashboard
│   ├── mc_port (25565) - Minecraft
│   └── rcon_port (25575) - Remote console
├── Server Settings
│   ├── mc_version (dynamic default)
│   ├── loader (neoforge/forge/fabric)
│   ├── xmx, xms (memory limits)
│   └── server_jar (loader JAR)
├── Directory Configuration
│   ├── mods_dir (server mods)
│   ├── clientonly_dir (client-only mods)
│   └── quarantine_dir (problematic mods)
└── Retention Policies
    ├── log_retention_days (30)
    ├── crash_report_retention_days (30)
    └── live_log_max_size_mb (10)
```

**Configuration Flow:**
1. `load_cfg()` - Load from config.json
2. `ensure_config()` - Fill defaults for missing fields
3. `validate_config()` - Verify required fields and types
4. `save_cfg()` - Write back to disk

### 3. Dashboard (`neorunner_pkg/dashboard.py`)

Flask-based web interface with real-time updates:

```
Dashboard Routes
├── Static Assets
│   ├── /static/* - CSS, JS, images
│   └── / - Main dashboard HTML
├── API Endpoints (REST)
│   ├── GET /api/status - Server state
│   ├── GET/POST /api/config - Configuration
│   ├── GET /api/mods - List mods
│   ├── DELETE /api/mods/<name> - Remove mod
│   ├── POST /api/server/start - Start server
│   ├── POST /api/server/stop - Stop server
│   └── GET /api/logs - Stream log output
├── Mod Hosting
│   ├── GET /download/manifest - JSON mod list
│   ├── GET /download/all - ZIP of all mods
│   ├── GET /download/<mod> - Individual download
│   └── GET /download/install - Install scripts
└── WebSocket Events
    ├── server_status - State changes
    ├── server_log - Real-time log streaming
    └── player_event - Player join/leave
```

### 4. Mod Management System

#### Mod Browser (`neorunner_pkg/mod_browser.py`)
- **Modrinth API**: Direct HTTP calls with version filtering
- **CurseForge**: API key or Selenium scraping fallback
- Returns `ModResult` objects with version compatibility info

#### Mod Host (`neorunner_pkg/mod_hosting.py`)
- Python HTTP server for mod distribution
- Manifest generation (JSON)
- Install script generation (Batch/PowerShell)
- Client-only mod filtering

#### Mod Patchers
- **`mod_patcher.py`**: Auto-patch mods for compatibility
- **`mod_modder.py`**: Mixin conflict detection and resolution

### 5. Diagnostics & Recovery

#### Crash Analyzer (`neorunner_pkg/crash_analyzer.py`)
Analyzes **client** crash logs:
- Missing dependency detection
- Client-only mod identification
- Java version mismatch warnings
- Mixin error detection
- Auto-fetch missing mods to `clientonly/`

#### Network Channel Analyzer (`neorunner_pkg/network_channel_analyzer.py`)
**Server-side** connection monitoring:
- Always-on monitoring (every 5 seconds)
- Parse logs for `Unknown custom packet identifier`
- Detect client/server mod mismatches at connection time
- Generate `CHANNEL` events for dashboard

#### Log Manager (`neorunner_pkg/log_manager.py`)
- Log rotation at size threshold
- Crash report retention cleanup
- Configurable retention periods
- Runs on server startup

#### Self Heal (`neorunner_pkg/self_heal.py`)
Preflight dependency checking:
- Scan all mods for required dependencies
- Auto-fetch missing deps to `mods/`
- Skip incompatible dependencies (Fabric deps on NeoForge)
- Quarantine problematic mods

## Loader Architecture

Each loader implements the common interface:

```
LoaderBase (ABC)
├── get_loader_display_name() - Human-readable name
├── get_minecraft_version() - Required MC version
├── prepare_environment() - Setup directories
├── build_java_command() - JVM arguments
└── get_start_command() - Server launch command

Implementations:
├── NeoForgeLoader (1.20.4+)
├── ForgeLoader (1.19.2-1.20.1)
└── FabricLoader (1.14+)
```

**Key differences:**
- NeoForge requires Java 21+
- Different JVM arguments for network debugging
- Loader-specific crash patterns

## Data Flow

### Server Startup Flow
```
1. CLI: neorunner start
2. Load config (config.json)
3. Ensure config (fill defaults)
4. Validate config
5. LogManager: cleanup old logs/crash reports
6. SelfHealer: preflight dependency check
7. TmuxServer: start tmux session
8. Load server.jar with JVM args
9. Dashboard: serve web interface
10. WebSocket: emit status updates
```

### Client Sync Flow
```
1. Client fetches /download/manifest
2. Compare with local mods/
3. Move extra mods to oldmods/
4. Download missing from /download/all
5. Run install script
```

### Crash Recovery Flow
```
1. Detect crash pattern in live.log
2. Check restart limits (5 per loop, 15 total)
3. Wait cooldown period (30s default)
4. Run preflight checks
5. Restart server
6. Emit CRASH_DETECT and SERVER_RESTART events
```

## Directory Structure

```
/home/host/neorunner/
├── config.json              # Runtime configuration
├── server.jar              # Minecraft server JAR
├── server.properties       # Vanilla server properties
├── eula.txt               # Mojang EULA acceptance
├── live.log               # Current server log
├── mods/                  # Server-side mods
├── clientonly/            # Client-only mods
├── quarantine/            # Problematic mods
├── backups/               # World backups
├── worlds/               # Available worlds
├── crash-reports/        # Crash logs
├── templates/            # Dashboard HTML
└── neorunner_pkg/        # Python package
    ├── __init__.py
    ├── config.py
    ├── constants.py
    ├── server.py
    ├── dashboard.py
    ├── cli.py
    ├── loaders/
    ├── mod_*.py
    ├── crash_analyzer.py
    ├── log_manager.py
    └── ...
```

## Security Considerations

1. **Input Validation**: All API endpoints validate input
2. **Path Traversal**: Mod downloads checked against allowed paths
3. **RCON Authentication**: Configurable password protection
4. **File Permissions**: Recommended running as dedicated user
5. **Firewall**: Only open necessary ports (25565, 8000)

## Performance Characteristics

- **Dashboard**: ~100ms response for status endpoints
- **Log streaming**: WebSocket with 100ms broadcast interval
- **Mod hosting**: Direct file serving (bottleneck is network)
- **Crash detection**: Polls log every 1 second
- **Memory**: Minimal (~50MB Python overhead)

## Extensibility Points

1. **New Loaders**: Subclass `LoaderBase` in `loaders/`
2. **Custom Mod Sources**: Add to `mod_browser.py`
3. **Additional Diagnostics**: Extend `crash_analyzer.py`
4. **Dashboard UI**: Modify `templates/dashboard.html`
5. **CLI Commands**: Add to `cli.py` argparse

## Dependencies

- **Python**: 3.11+
- **Java**: 21 (NeoForge) or 17+ (Fabric)
- **tmux**: Process isolation
- **Flask**: Web dashboard
- **requests**: HTTP client
- **APScheduler**: Background tasks

## Testing

- **Unit Tests**: pytest with fixtures
- **Coverage Target**: 90%+
- **Test Categories**:
  - Configuration validation
  - Crash detection patterns
  - Log rotation
  - Network channel analysis
  - Mod management

---

*Last updated: 2026-04-30*
