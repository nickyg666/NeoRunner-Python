# NeoRunner - Headless Minecraft Server Management

A complete, fully-automated Minecraft modded server management system with web dashboard, mod management, RCON control, and scheduled updates.

## Features

- **Multi-Modloader Support**: NeoForge, Fabric, Forge
- **Automatic Mod Management**: Ferium-based mod discovery and updates
- **Web Dashboard**: Full-featured admin panel for server control
- **Scheduled Updates**: 
  - Configurable Modrinth updates (every 1-24 hours)
  - Optional CurseForge updates via Selenium or API
  - Weekly strict version compatibility checks
- **RCON Integration**: Server commands and player monitoring
- **Automated Backups**: Daily world backups with cleanup
- **HTTP Mod Distribution**: Direct mod download for players
- **Headless-Ready**: Works on minimal Linux systems without GUI
- **Reproducible Setup**: Single-command deployment to any machine

## System Requirements

- Linux (Ubuntu 20.04+, Debian 11+, or similar)
- 2GB+ RAM (4GB+ recommended for mod servers)
- 10GB+ free disk space
- Java 21+ (for NeoForge 21.11.38-beta)
- Internet connection

## Quick Start

### Option 1: Automated Setup (Recommended)

```bash
# Clone or download this repository
cd /home/services
bash setup.sh
```

The setup script will:
1. Check system dependencies
2. Create Python virtual environment
3. Install all Python packages
4. Download and install Ferium mod manager
5. Create necessary directories
6. Register with systemd (optional)

### Option 2: Manual Setup

```bash
# Create virtual environment
python3 -m venv neorunner_env
source neorunner_env/bin/activate

# Install dependencies
pip install selenium requests beautifulsoup4 lxml flask apscheduler

# Download Ferium (x86_64 Linux)
mkdir -p .local/bin
cd /tmp
curl -L -o ferium-nogui.zip https://github.com/gorilla-devs/ferium/releases/download/v4.7.1/ferium-linux-nogui.zip
unzip ferium-nogui.zip
mv ferium /path/to/services/.local/bin/

# Create directories
mkdir -p mods backups cache
```

## Installation Wizard

First run launches an interactive wizard:

```bash
./neorunner_env/bin/python3 run.py run
```

The wizard will prompt for:
1. **RCON Password** - For server remote commands
2. **RCON Port** - Default 25575
3. **HTTP Port** - For mod delivery (default 8000)
4. **Minecraft Version** - e.g., 1.21.11
5. **Modloader** - neoforge, fabric, or forge
6. **Ferium Profile Setup**:
   - Profile name
   - CurseForge integration (API key, Selenium, or skip)
   - Mod update frequency (1-24 hours, default 4)
   - Weekly update schedule (day + time)

## Configuration

Settings are saved in `config.json`:

```json
{
  "rcon_pass": "your-password",
  "rcon_port": "25575",
  "rcon_host": "localhost",
  "http_port": "8000",
  "mods_dir": "mods",
  "mc_version": "1.21.11",
  "loader": "neoforge",
  "ferium_profile": "neoserver",
  "ferium_enable_scheduler": true,
  "ferium_update_interval_hours": 4,
  "ferium_weekly_update_day": "mon",
  "ferium_weekly_update_hour": 2,
  "curseforge_method": "modrinth_only"
}
```

## Running the Server

### Standalone Mode
```bash
./neorunner_env/bin/python3 run.py run
```

### As Systemd Service
```bash
# Install service
sudo bash setup.sh  # Will show systemd installation instructions
sudo cp /tmp/neorunner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable neorunner
sudo systemctl start neorunner

# Check status
sudo systemctl status neorunner
sudo journalctl -u neorunner -f
```

### In Tmux Session (Interactive)
```bash
tmux new-session -s minecraft
cd /home/services
./neorunner_env/bin/python3 run.py run
# Press Ctrl+B then D to detach
# tmux attach -t minecraft  # to reconnect
```

## Dashboard Access

- **Admin Dashboard**: `http://localhost:8001`
- **Mod Download Server**: `http://localhost:8000`

### Dashboard Features

- **Server Status**: Running state, modloader, version, mod count, player count
- **Mod Management**: View, download, remove, and upgrade installed mods
- **Configuration**: Adjust update frequency, schedule, MC version
- **Live Logs**: Real-time server activity monitoring
- **Quick Actions**: Start/stop server, upgrade mods

## Mod Management

### Adding Mods

```bash
# Use ferium to add mods
./neorunner_env/bin/python3 -c "from ferium_manager import FeriumManager; m = FeriumManager(); m.add_modrinth_mod('sodium')"
```

Or via dashboard:
1. Go to Mods tab
2. Click "📥 Download" on a mod to get it
3. Add new mods via terminal commands above

### Automatic Updates

Mods are automatically updated based on configured schedule:
- **Every N hours**: Check Modrinth and CurseForge for updates
- **Weekly**: Strict compatibility check (maintains current MC version)

## Ports

- **8000**: HTTP mod download server (for players)
- **8001**: Admin dashboard (web UI for management)
- **25575**: RCON server command interface (configurable)

## Troubleshooting

### Server won't start
```bash
# Check if port 25575 is in use
lsof -i :25575

# Check Java installation
java -version

# Check NeoForge libraries
ls libraries/net/neoforged/neoforge/21.11.38-beta/
```

### Mods not updating
```bash
# Check ferium installation
./.local/bin/ferium --version

# Check ferium profile
./.local/bin/ferium profile list

# Force upgrade mods
./.local/bin/ferium upgrade
```

### RCON not working
```bash
# Verify RCON is enabled
grep "enable-rcon" server.properties

# Test connection
echo "list" | nc -w 1 localhost 25575
```

### Dashboard not loading
```bash
# Check Flask is installed
./neorunner_env/bin/python3 -c "import flask; print(flask.__version__)"

# Check if port 8001 is in use
lsof -i :8001

# Check logs
tail -50 live.log
```

## Deploying to Multiple Machines

### Method 1: Git Repository (Recommended)

```bash
# On new machine:
cd /home/services
git clone <your-repo> .
bash setup.sh
./neorunner_env/bin/python3 run.py run  # Interactive wizard
```

### Method 2: Manual Copy

```bash
# On new machine:
cd /home/services
scp -r user@old-server:/home/services/{run.py,ferium_manager.py,dashboard.py,dashboard.html} .
bash setup.sh

# Re-run wizard (config.json will be regenerated)
./neorunner_env/bin/python3 run.py run
```

### Method 3: Docker (Future)

```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    python3 python3-venv curl tmux rsync unzip zip openjdk-21-jre-headless git
WORKDIR /home/services
COPY . .
RUN bash setup.sh
EXPOSE 8000 8001 25575
CMD ["./neorunner_env/bin/python3", "run.py", "run"]
```

## Architecture

```
NeoRunner
├── run.py                 # Main application + wizard
├── ferium_manager.py      # Ferium integration + scheduler
├── dashboard.py           # (Alternative) standalone Flask app
├── dashboard.html         # Web UI templates
├── setup.sh              # Installation script
├── config.json           # Configuration (generated)
├── server.properties     # Minecraft server config
├── live.log              # Server logs
│
├── neorunner_env/        # Python virtual environment
├── .local/bin/ferium     # Ferium binary
│
├── mods/                 # Server + client mods
│   └── clientonly/       # Client-only mods folder
├── backups/              # World backups (daily)
├── cache/                # Scraper cache
│
└── libraries/
    └── net/neoforged/    # NeoForge loader (install separately)
```

## Environment Variables

Optional environment variables:

```bash
# Custom ferium config directory
export FERIUM_CONFIG_FILE=/path/to/ferium/config.json

# CurseForge API key
export CURSEFORGE_API_KEY=your-key-here

# GitHub personal access token (for mod scanning)
export GITHUB_TOKEN=your-token-here
```

## Performance Tips

1. **Disable Unused Modloader Checks**: Edit `config.json` to set only used loaders
2. **Limit Mod Update Frequency**: Increase interval from 4h to 6h or 12h to reduce network load
3. **Use SSD**: Place mods directory on SSD for faster mod loading
4. **Adjust JVM Memory**: Edit `user_jvm_args.txt` to allocate more RAM if needed

## Security Considerations

⚠️ **Important**:
- Change RCON password immediately after setup
- Don't expose ports 8000/8001 to public internet without auth
- Use firewall to restrict dashboard access
- Rotate API keys periodically
- Keep server.properties secure (contains passwords)

## Support & Documentation

- **Issues**: Check logs in `live.log`
- **Ferium Docs**: https://github.com/gorilla-devs/ferium
- **Modrinth API**: https://docs.modrinth.com/
- **NeoForge**: https://neoforged.net/

## License

[Your License Here]

## Contributing

Contributions welcome! Submit issues and PRs at [your-repo].

---

**Last Updated**: 2026-02-18
**NeoRunner Version**: 1.0.0
