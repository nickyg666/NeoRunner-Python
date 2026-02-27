# Agent Configuration for NeoRunner Project

## Project Overview
NeoRunner is a comprehensive Minecraft modded server manager written in Python. It handles NeoForge, Forge, and Fabric servers with automated mod management, web dashboard, and crash recovery.

## Key Files and Locations
- **Main entry point**: `/home/services/run.py` (330KB, ~7200 lines)
- **Configuration**: `/home/services/config.json` and `/home/services/server.properties`
- **Service file**: `/home/services/mcserver.service` (systemd user service)
- **Dependencies**: Flask, Playwright, requests, apscheduler, tomli
- **Service directory**: `/home/services/.config/systemd/user/mcserver.service`

## Service Management Commands
```bash
# Restart service
systemctl --user restart mcserver

# Start service
systemctl --user start mcserver

# Stop service
systemctl --user stop mcserver

# Check status
systemctl --user status mcserver
```

## Project Structure
- **Core**: Single monolithic `run.py` file with embedded web server and mod management
- **Loaders**: `/home/services/loaders/` directory with NeoForge, Forge, Fabric implementations
- **Utilities**: `ferium_manager.py`, `mod_manager.py`, `dashboard.py`, `webui.py`
- **Documentation**: Multiple README files and guides

## Dependencies Status
- All Python dependencies are installed and functional
- Playwright Chromium browser is installed
- Java is available for Minecraft server

## Configuration
- Auto-detects loader/version from existing server.properties
- RCON enabled for client-server communication
- HTTP dashboard runs on port 8000
- Minecraft server runs on port 1234

## Operational Status
✅ Service is active and running
✅ Dependencies are installed
✅ Configuration files are present
✅ Documentation is comprehensive
✅ Git repository is initialized
✅ Dashboard is fully integrated and accessible at port 8000
✅ All APIs are operational (status, config, mod-lists, java, etc.)
✅ Playwright is installed and functional for CurseForge scraping

## Key Commands for Development
```bash
# Run interactive mod curator
python3 run.py curator

# Run with reconfiguration
python3 run.py --reconfigure

# Check service logs
journalctl --user -u mcserver -f

# Dashboard access
http://localhost:8000
```

## Service File Location
The actual service file is loaded from:
`/home/services/.config/systemd/user/mcserver.service`

## Important Notes
- Service runs as user 'services' with working directory `/home/services`
- Auto-restarts on crash with 10-second delay
- Uses tmux for server persistence
- RCON password is set in config.json (currently '1')
- Dashboard is fully integrated and accessible at port 8000
- All APIs are operational (status, config, mod-lists, java, etc.)
- Playwright is installed and functional for CurseForge scrapingTODO: Fix playwright chromium install attempt on every svc start
