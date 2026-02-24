# NeoRunner - Quick Start Guide

## 30-Second Summary

NeoRunner is a complete Minecraft modded server management system with:
- ✅ Automatic mod management (Ferium)
- ✅ Web admin dashboard
- ✅ RCON server control
- ✅ Configurable update scheduling (every 1-24 hours)
- ✅ Fully headless (no GUI needed)
- ✅ One-command reproducible setup

## Installation (5 minutes)

```bash
# 1. Clone/download code to /home/services
cd /home/services

# 2. Run automated setup
bash setup.sh

# 3. Start server (interactive wizard)
./neorunner_env/bin/python3 run.py run

# During wizard, you'll configure:
# - RCON password & port
# - HTTP port for mod distribution
# - Minecraft version (1.21.11)
# - Modloader (neoforge/fabric/forge)
# - Mod update frequency (default: every 4 hours)
# - Weekly update schedule (default: Monday at 2am)
```

## Access Points

Once running, access:
- **Admin Dashboard**: http://localhost:8001
  - Server status
  - Mod management
  - Configuration
  - Live logs
- **Mod Downloads**: http://localhost:8000
  - Players download mods here
- **RCON**: localhost:25575
  - Server commands via RCON client

## Common Commands

```bash
# Start server (standalone)
./neorunner_env/bin/python3 run.py run

# Start as systemd service (production)
sudo systemctl start neorunner
sudo systemctl status neorunner

# Run mod curator (discover top 100 mods)
./neorunner_env/bin/python3 run.py curator

# Manage mods with ferium
./.local/bin/ferium list              # List mods
./.local/bin/ferium upgrade           # Update all mods
./.local/bin/ferium add sodium        # Add mod
./.local/bin/ferium remove sodium     # Remove mod

# Check logs
tail -50 live.log

# View server console
tmux attach -t MC
# Ctrl+B then D to detach
```

## Configuration

Edit `config.json` to change:
```json
{
  "ferium_update_interval_hours": 4,     // 1-24 (default: 4)
  "ferium_weekly_update_day": "mon",     // mon-sun (default: mon)
  "ferium_weekly_update_hour": 2,        // 0-23 (default: 2)
  "rcon_pass": "your-password",
  "mc_version": "1.21.11"
}
```

Then restart:
```bash
sudo systemctl restart neorunner
```

## Dashboard Features

### Server Status Tab
- Running state (yes/no)
- Modloader & version
- Mod count
- Player count
- RCON enabled/disabled

### Mods Tab
- List all installed mods
- Download individual mods
- Remove mods
- Upgrade all mods button

### Configuration Tab
- **Update Frequency**: 1-24 hours
- **Weekly Update Day**: Mon-Sun
- **Weekly Update Hour**: 0-23
- **Minecraft Version**: Custom
- Save/reload buttons

### Logs Tab
- Real-time server activity
- Auto-scrolls to latest
- Refresh button

## Update Schedule

### Automatic Updates

**Every N Hours** (configurable, default: 4)
```
04:00 → Check Modrinth for updates
04:02 → Check CurseForge (if enabled)
        ↓ Download & apply updates
08:00 → Repeat
12:00 → Repeat
16:00 → Repeat
20:00 → Repeat
00:00 → Repeat
```

**Weekly Strict Check** (configurable, default: Monday 2:00 AM)
```
Mon 02:00 → Only mods for current MC version
            Ignore newer Minecraft mods
            Ensures server version stays stable
```

## Troubleshooting

### Server won't start
```bash
# Check if port 25575 is free
lsof -i :25575

# Check Java is installed
java -version

# Check NeoForge libraries exist
ls libraries/net/neoforged/neoforge/21.11.38-beta/
```

### Dashboard not loading
```bash
# Check if port 8001 is free
lsof -i :8001

# Check Flask is installed
./neorunner_env/bin/python3 -c "import flask; print('✓')"

# Check logs for errors
tail live.log
```

### Mods not updating
```bash
# Check Ferium works
./.local/bin/ferium profile list

# Force update
./.local/bin/ferium upgrade

# Check logs
grep FERIUM live.log
```

## Scaling to Multiple Machines

### To deploy on another server:

```bash
# On new server:
cd /home/services
git clone <your-repo> .
bash setup.sh
./neorunner_env/bin/python3 run.py run  # Answer wizard
```

That's it! The new server gets the same setup.

## System Requirements

- **OS**: Linux (Ubuntu 20.04+, Debian 11+, etc.)
- **RAM**: 2GB minimum (4GB recommended)
- **Disk**: 10GB minimum
- **Java**: 21+ (for NeoForge 21.11.38-beta)
- **Internet**: For mod downloads

## What's Configured Automatically

✅ Ferium mod manager installed
✅ Python virtual environment created
✅ RCON enabled in server.properties
✅ HTTP servers set up (ports 8000, 8001)
✅ Daily world backups configured
✅ Mod scheduler started (4h updates)
✅ Dashboard running
✅ Systemd service registered (optional)

## First Run Checklist

- [ ] Server is running (`tmux list-sessions` shows MC)
- [ ] Dashboard loads (`http://localhost:8001`)
- [ ] Mods visible in dashboard
- [ ] RCON works (`echo list | nc localhost 25575`)
- [ ] Logs being written (`tail live.log`)
- [ ] Backups created (`ls backups/`)

## Performance

- **Setup**: 2-5 minutes
- **Server start**: 30-60 seconds
- **Mod check**: Runs in background, ~1 minute
- **Dashboard load**: <200ms
- **Mod list update**: <100ms

## Next Steps

1. **Access dashboard**: Open http://localhost:8001 in browser
2. **Add mods**: Via Ferium or through mod curator
3. **Configure schedule**: Adjust update frequency if needed
4. **Set up backups**: Already automatic (daily)
5. **Share with players**: Give them http://localhost:8000 for mod downloads

## Support

**For detailed setup**: See `DEPLOYMENT_GUIDE.md`
**For features**: See `NEORUNNER_README.md`
**For implementation details**: See `IMPLEMENTATION_SUMMARY.md`

---

**You're ready to go!** 🎮
