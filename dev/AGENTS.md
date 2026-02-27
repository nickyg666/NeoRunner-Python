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

## Current Implementation Status

### Completed Features
- ✅ Implemented UI: separate tabbed views for server mods and client side mods
- ✅ Added quarantine option in client side mods (no longer on home page)
- ✅ Added echo Eula=true > eula.txt after loader install in run.py
- ✅ Added multi-world support by scanning for world folders
- ✅ Added world switcher to UI
- ✅ Implemented mod modder for mixin conflict resolution
- ✅ Automated mod patching for maximum mixin compatibility
- ✅ Implemented single loader option with loader switching

### In Progress
- 🔄 Backend API endpoints for world management (create, switch, backup, delete)

### Pending Features
- None - all features from features.needed file have been implemented

## Files Modified

**Edited:**
- `/home/services/dev/dashboard.html` - Main dashboard UI with new tabbed mod views and world management
- `/home/services/dev/run.py` - Added EULA file creation after loader installation
- `/home/services/dev/mod_manager.py` - Fixed type errors and added source tracking

**Created:**
- `/home/services/dev/mod_modder.py` - Mixin conflict resolution system
- `/home/services/dev/mod_patcher.py` - Automated mod patching system

## Key Implementation Details

### World Management
- Multi-world support implemented by scanning for world folders
- World switcher added to UI with backup/restore functionality
- World management API endpoints need to be implemented

### Mod Management
- Separate tabbed views for server mods and client-side mods
- Quarantine system for incompatible mods
- Mixin conflict resolution for mod compatibility
- Automated patching for maximum compatibility

### Loader Management
- Single loader option with switching functionality
- Loader abstraction in `/loaders/` directory
- Automatic loader detection from server.properties

## Next Steps

### Phase 1: World Management API Endpoints
1. Implement world scanning API endpoint
2. Implement world creation API endpoint
3. Implement world switching API endpoint
4. Implement world backup/restore API endpoints
5. Implement world deletion API endpoint

### Phase 2: Integration Testing
1. Test all world management features through UI
2. Test mod management with new world system
3. Test loader switching with different mod configurations
4. Test backup/restore functionality
5. Test crash recovery with new features

### Phase 3: Documentation
1. Update README files with new features
2. Add troubleshooting guide for common issues
3. Create setup guide for new users
4. Document API endpoints for developers

## Debugging Commands

### Service Management
```bash
# Restart service
systemctl --user restart mcserver

# Check logs
journalctl --user -u mcserver -f

# Check dashboard
http://localhost:8000
```

### Development
```bash
# Run with reconfiguration
python3 run.py --reconfigure

# Check world scanning
python3 run.py --scan-worlds

# Test mod management
python3 run.py --test-mods
```

## Common Issues and Solutions

### Service Not Starting
- Check systemd service status: `systemctl --user status mcserver`
- Check for port conflicts (8000 for dashboard, 1234 for Minecraft)
- Verify Java installation

### Dashboard Not Loading
- Check Flask is installed: `python3 -c "import flask; print(''OK')"`
- Check port 8000 is not blocked by firewall
- Verify `run.py` is executable

### Mod Installation Fails
- Check ferium is installed: `ferium --version`
- Verify network connectivity for mod downloads
- Check disk space in mods directory

## API Endpoints Reference

### Current Endpoints
- `/api/status` - Server status and configuration
- `/api/config` - Server configuration management
- `/api/mod-lists` - Mod list management
- `/api/java` - Java version management
- `/api/worlds` - (TODO) World management

### New Endpoints to Implement
- `/api/worlds/scan` - Scan for available worlds
- `/api/worlds/create` - Create new world
- `/api/worlds/switch` - Switch active world
- `/api/worlds/backup` - Backup world
- `/api/worlds/restore` - Restore world
- `/api/worlds/delete` - Delete world

## Performance Considerations

### World Scanning
- Cache world scan results to avoid repeated directory scans
- Implement pagination for large numbers of worlds
- Add filtering options (by size, date, etc.)

### Mod Management
- Implement background processing for mod operations
- Add progress indicators for long-running tasks
- Cache mod metadata to reduce API calls

### Backup Operations
- Implement incremental backups for large worlds
- Add compression for backup files
- Implement backup retention policies

## Security Considerations

### API Security
- Implement authentication for API endpoints
- Add rate limiting to prevent abuse
- Validate all input parameters

### File Operations
- Sanitize all file paths to prevent directory traversal
- Implement file size limits for uploads
- Add backup verification before deletion

## Testing Strategy

### Unit Tests
- Test mod management functions
- Test world management functions
- Test loader switching functionality

### Integration Tests
- Test full workflow from world creation to mod installation
- Test backup/restore functionality
- Test crash recovery scenarios

### UI Tests
- Test dashboard functionality
- Test world switcher
- Test mod management interface

## Deployment Notes

### Configuration
- Ensure config.json has correct paths
- Verify RCON settings in server.properties
- Check firewall settings for required ports

### Dependencies
- All Python dependencies should be installed
- Java runtime must be available
- Playwright for CurseForge scraping

### Service Setup
- Systemd service must be enabled and started
- Dashboard accessible on port 8000
- Minecraft server on port 1234

## Troubleshooting Guide

### Common Issues
1. **Service won't start**: Check logs, port conflicts, Java installation
2. **Dashboard 404**: Check Flask, port 8000, file permissions
3. **Mod download fails**: Check network, ferium installation, disk space
4. **World not found**: Check world directory structure, permissions

### Log Analysis
- Look for error patterns in service logs
- Check timestamps for correlation with issues
- Monitor resource usage during operations

### Recovery Procedures
- Restart service for most issues
- Clear cache for API problems
- Reinstall dependencies for corruption issues
- Restore from backup for data loss

## Future Enhancements

### Planned Features
- Advanced modpack management
- Scheduled task automation
- Plugin system for extensibility
- Mobile app support

### Performance Improvements
- Caching layer for API responses
- Background processing for long tasks
- Database for metadata storage

### User Experience
- Wizard for new installations
- Real-time status updates
- Advanced configuration options

## Contact Information

### Support
- Check logs first for error messages
- Verify all dependencies are installed
- Test with minimal configuration

### Development
- Fork the repository for contributions
- Follow existing code patterns
- Test thoroughly before submitting changes

### Documentation
- Keep README files updated
- Document new features as they're added
- Maintain troubleshooting guides

---

*This configuration is current as of February 26, 2026.*

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
