# NeoRunner - Advanced Minecraft Server Manager

A Python-based automation system for managing modded Minecraft servers with intelligent mod curation, player event handling, and RCON integration.

## Features

### 🎮 Core Server Management
- **Automatic Server Control**: Start/stop server via tmux integration
- **Crash Detection & Auto-Restart**: Monitors server health and auto-restarts via systemd
- **World Backups**: Daily automated backups with compression
- **HTTP Mod Distribution**: Host mods on HTTP server for client downloads
- **RCON Integration**: Remote console access and automated commands

### 📦 Intelligent Mod Curator
- **Top 100 Mod Discovery**: Scans Modrinth for top mods per loader (NeoForge/Fabric)
- **Library Filtering**: Automatically filters out unnecessary libraries and APIs
- **On-Join Display**: Shows mod list when players join server
- **Player-Driven Downloads**: Players download mods via chat commands
- **Dependency Resolution**: Automatically resolves mod dependencies
- **Background Downloads**: Non-blocking mod fetching in daemon threads
- **Auto Server Restart**: Seamlessly restarts server to load new mods

### 🎯 Player Event System
- **Join Hook**: Displays mod list on player join
- **Download Hook**: Parses mod download commands from chat
- **Death Announcements**: Custom death messages
- **Chat Patterns**: Custom responses to chat keywords
- **Event Logging**: Full logging of all player events

### ⚙️ System Integration
- **Systemd Service**: Auto-start and auto-restart on failure
- **Dual-Loader Support**: NeoForge and Fabric mod loaders
- **Configuration Management**: Centralized config.json
- **Logging**: Comprehensive event and error logging to live.log

## Quick Start

### Prerequisites
- Python 3.7+
- Java 21+
- tmux
- Linux/Mac (systemd recommended)

### Installation

```bash
# Clone repository
git clone https://github.com/nickyg666/NeoRunner-Python.git
cd NeoRunner-Python

# Run first time setup
python3 run.py run

# Follow prompts for initial configuration
```

### Configuration

Edit `config.json`:

```json
{
  "loader": "neoforge",              // "neoforge" or "fabric"
  "mc_version": "1.21.11",           // Minecraft version
  "mods_dir": "mods",                // Directory for mods
  "http_port": 8000,                 // HTTP server port
  "rcon_pass": "1",                  // RCON password (auto-synced to server.properties)
  "rcon_port": "25575",              // RCON port
  "rcon_host": "localhost",          // RCON host
  "run_curator_on_startup": false,   // Launch interactive curator on first run
  "curator_limit": 100               // Max mods to curate
}
```

## Player Experience

### When Player Joins

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 NEOFORGE MOD LIST - Top 100
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Sodium (121M downloads)
  2. Iris Shaders (93M downloads)
  3. Entity Culling (86M downloads)
  ... (showing top 20 mods)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Type: download all | download 1-10 | download 1,5,15
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Download Commands

Players can type in chat:

```
download all              # Downloads all 100 mods
download 1-10             # Downloads mods 1 through 10
download 1,5,15           # Downloads specific mods (1, 5, and 15)
```

### Download Flow

1. Player types command → confirmation message in chat
2. Mods download in background (non-blocking)
3. Server displays: `✓ Downloaded 5 mod(s)! Restarting server...`
4. Server stops cleanly → systemd restarts with new mods
5. Next server start loads all downloaded mods

## Architecture

### Event Monitoring

The system continuously monitors `live.log` for player events and triggers hooks:

- **PlayerJoinHook**: Displays mod list when player joins
- **ModDownloadHook**: Parses "download" commands from chat
- **PlayerDeathHook**: Shows death messages
- **ChatPatternHook**: Responds to !help, !status, !tps commands

### Mod List Generation

At server startup:

1. Scan Modrinth for top 500 mods per loader
2. Filter out libraries/APIs (keeps user-facing mods only)
3. Select top 100 by download count
4. Cache in memory for player display

### RCON Configuration

The system automatically ensures RCON is properly configured:

- Reads `server.properties` on every server load
- Updates/adds: `enable-rcon=true`, `rcon.password`, `rcon.port`
- Values synced from `config.json` settings
- Works for both new and existing installations

## Key Functions

### Core Server Functions

- `send_server_command(cmd)` - Send command via tmux to MC session
- `send_chat_message(msg)` - Broadcast message to server chat
- `send_rcon_command(cfg, cmd)` - Send command via RCON (if available)
- `ensure_rcon_enabled(cfg)` - Ensure RCON properly configured in server.properties
- `generate_mod_lists_for_loaders(mc_version, limit)` - Generate top 100 mods per loader

### Event Handling Functions

- `show_mod_list_on_join(player, cfg)` - Display mod list to joining player
- `handle_mod_download_command(player, command, cfg)` - Parse download commands
- `download_selected_mods(indices, mods, cfg, player)` - Download mods in background
- `restart_server_for_mods(cfg)` - Stop server for mod loading

### Mod Discovery Functions

- `fetch_modrinth_mods(mc_version, loader, limit, offset)` - Fetch mods from Modrinth
- `is_library(mod_name)` - Determine if mod is library/API
- `download_mod_from_modrinth(mod_data, mods_dir, mc_version, loader)` - Download individual mod
- `resolve_mod_dependencies_modrinth(mod_id, ...)` - Resolve dependencies recursively

## Logging

All events logged to `live.log`:

```bash
# View mod curator events
tail -f live.log | grep "MOD\|HOOK_MOD"

# View all events
tail -f live.log
```

Event types:

- `HOOK_PLAYER_JOIN` - Player joined server
- `MOD_LIST_SHOWN` - Mod list displayed to player
- `HOOK_MOD_DOWNLOAD` - Download command received
- `MOD_DOWNLOAD` - Mod downloaded successfully
- `MOD_DOWNLOAD_ERROR` - Download failed
- `SERVER_RESTART` - Server restarting for mod update
- `RCON_SETUP` - RCON configuration updated

## Troubleshooting

### No mod list on player join
```bash
# Check if mod lists were generated
tail live.log | grep "Generating mod lists"

# Check if PlayerJoinHook is working
tail live.log | grep "HOOK_PLAYER_JOIN"
```

### RCON not working
```bash
# Verify RCON is enabled in server.properties
grep "enable-rcon" server.properties

# Check RCON settings match config
grep "rcon" config.json
grep "rcon" server.properties

# The system auto-configures RCON on startup - no action needed
```

### Download commands not recognized
```bash
# Check if ModDownloadHook triggered
tail live.log | grep "HOOK_MOD_DOWNLOAD"

# Ensure command format is correct: "download all", "download 1-10", "download 1,5,15"
```

### Mods not loading after download
```bash
# Check if mods downloaded to mods/ directory
ls -la mods/ | grep .jar

# Check server logs for mod loading errors
tail server.log

# Verify server restarted
tail live.log | grep "SERVER_RESTART"
```

## Mod Filtering Logic

The curator filters out libraries/APIs to show only user-facing mods:

**Filtered Out:**
- "cloth config", "ferrite", "yacl", "architectury"
- "geckolib", "puzzles lib", "forge config api"
- Anything with "lib " prefix or " lib" suffix

**Always Included:**
- "fabric api", "fabric-api", "fabric loader"

## Commands

### Interactive Curator

```bash
# Launch interactive mod selection
python3 run.py curator
```

### Server Management

```bash
# Start server with all automation
python3 run.py run

# Check if server is running
tmux list-sessions

# Stop server
tmux send-keys -t MC "stop" Enter
```

## Requirements Met

✅ **Automatic RCON Configuration** - Syncs password and settings from config.json to server.properties on every startup  
✅ **On-Player-Join Mod Display** - Shows top 20 mods when player joins with download instructions  
✅ **Chat-Based Mod Downloads** - Parse "download X" commands from player chat  
✅ **Background Processing** - Downloads happen asynchronously without blocking server  
✅ **Automatic Server Restart** - Restarts cleanly to load new mods  
✅ **Dependency Resolution** - Recursively fetches required mod dependencies  
✅ **Dual-Loader Support** - Works with NeoForge and Fabric  
✅ **Event System** - Comprehensive hook system for player events  
✅ **Systemd Integration** - Auto-start and auto-restart on failure  
✅ **Full Logging** - All events logged for debugging  

## Git Repository

**Repository:** https://github.com/nickyg666/NeoRunner-Python  
**Branch:** master  
**Latest Commits:**

```
f02a18d - fix: Ensure RCON is properly configured in server.properties...
056005a - feat: Implement mod curator on-player-join display and download system
e33ed5f - Revise NeoForged script documentation for clarity
```

## License

MIT

## Support

For issues, questions, or feedback:
- Open an issue on GitHub
- Check logs in `live.log`
- Review configuration in `config.json`
