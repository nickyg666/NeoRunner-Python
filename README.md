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

## Quick Start

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

## Production Deployment (systemd)

### Prerequisites

1. Install NeoRunner:
   ```bash
   cd /home/host/neorunner
   pip install -e .
   ```

2. Initialize the server:
   ```bash
   neorunner init --mc-version 1.21.11 --loader neoforge --xmx 6G
   neorunner setup
   ```

3. Create a dedicated user (recommended for security):
   ```bash
   sudo useradd -r -s /bin/false mcserver
   sudo chown -R mcserver:mcserver /home/host/neorunner
   ```

### Create systemd Service

Create `/etc/systemd/system/neorunner.service`:

```ini
[Unit]
Description=NeoRunner Minecraft Server
After=network.target
Wants=network.target

[Service]
Type=simple
User=mcserver
Group=mcserver
WorkingDirectory=/home/host/neorunner
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=/home/host/neorunner"

# Start server with dashboard
ExecStart=/usr/local/bin/python -m neorunner_pkg.cli start

# Restart on crash with cooldown
Restart=on-failure
RestartSec=30

# Logging
StandardOutput=append:/home/host/neorunner/systemd.log
StandardError=append:/home/host/neorunner/systemd.log

# Resource limits (adjust based on available memory)
MemoryMax=8G
MemoryHigh=6G

[Install]
WantedBy=multi-user.target
```

### Alternative: Separate Dashboard Service

For better isolation, run dashboard and server separately:

**`/etc/systemd/system/neorunner-dashboard.service`:**
```ini
[Unit]
Description=NeoRunner Web Dashboard
After=network.target

[Service]
Type=simple
User=mcserver
Group=mcserver
WorkingDirectory=/home/host/neorunner
ExecStart=/usr/local/bin/python -m neorunner_pkg.cli start --no-server
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/neorunner-server.service`:**
```ini
[Unit]
Description=NeoRunner Minecraft Server
After=network.target
PartOf=neorunner-dashboard.service

[Service]
Type=simple
User=mcserver
Group=mcserver
WorkingDirectory=/home/host/neorunner
ExecStart=/usr/local/bin/python -m neorunner_pkg.cli start --no-dashboard
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### Enable and Start Services

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable neorunner.service

# Start immediately
sudo systemctl start neorunner.service

# Check status
sudo systemctl status neorunner.service

# View logs
sudo journalctl -u neorunner.service -f
```

### Useful Commands

```bash
# Stop server gracefully
sudo systemctl stop neorunner.service

# Restart server
sudo systemctl restart neorunner.service

# View recent logs
sudo journalctl -u neorunner.service -n 50

# Check if running
systemctl is-active neorunner.service
```

### Security Considerations

1. **Firewall Rules** - Open required ports:
   ```bash
   sudo firewall-cmd --permanent --add-port=25565/tcp  # Minecraft
   sudo firewall-cmd --permanent --add-port=8000/tcp   # Dashboard
   sudo firewall-cmd --reload
   ```

2. **Resource Limits** - Adjust MemoryMax in service file based on available RAM

3. **Backup Strategy** - Add cron job for world backups:
   ```bash
   # /etc/cron.d/neorunner-backup
   0 3 * * * mcserver /usr/bin/python /home/host/neorunner/neorunner_pkg/backup.py >> /home/host/neorunner/backup.log 2>&1
   ```

4. **Log Rotation** - Configure journald to prevent log bloat:
   ```bash
   # /etc/systemd/journald.conf
   [Journal]
   SystemMaxUse=500M
   MaxRetentionSec=30day
   ```

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

## API Endpoints

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

### Production Issues

**Service fails to start:**
```bash
# Check detailed logs
sudo journalctl -u neorunner.service -xe

# Verify Python path
sudo -u mcserver python -c "from neorunner_pkg import cli; print('OK')"

# Check port availability
sudo lsof -i :8000
sudo lsof -i :25565
```

**Out of memory errors:**
- Increase `xmx` in config.json
- Adjust `MemoryMax` in systemd service
- Check for memory leaks in mods

**Performance issues:**
- Enable crash recovery with lower restart limits for testing
- Monitor with `/api/status` endpoint
- Check live.log for bottlenecks

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
