# NeoRunner v2.3.0 Progress

## Latest Changes (2026-04-22)

### Version Module (NEW!)
- Created `/neorunner_pkg/version.py` with dynamic version fetching
- Fetches latest MC from Mojang API
- Fetches latest NeoForge from Maven API
- Fetches latest Fabric from Fabric API
- Caches versions for 1 hour
- Provides `get_java_version_for_mc()` for Java version requirements

### Dynamic Version Updates
- `constants.py` - Now uses version module for defaults
- `config.py` - Dynamic default MC version, added `version_check_interval_hours` setting
- `cli.py` - Added `--daemon`/`-d` and `--pid-file` flags for background running
- `dashboard.py` - Fixed fresh install handling, all hardcoded versions replaced with dynamic calls

### Known Issues
- pip cache on client machines may show old commands - need to force reinstall: `pip install -e . --force-reinstall`
- The `install` command was already in the code but may have been cached as old version

## Installation

```bash
# Quick install
curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash

# Manual
git clone https://github.com/nickyg666/NeoRunner-Python.git
cd NeoRunner-Python
python3 -m venv neorunner_venv
source neorunner_venv/bin/activate
pip install -e .
neorunner install  # Full interactive setup
neorunner start --daemon  # Background mode
```

## Commands

| Command | Description |
|---------|-------------|
| `neorunner start` | Start server |
| `neorunner start --daemon` | Start in background |
| `neorunner stop` | Stop server |
| `neorunner restart` | Restart server |
| `neorunner init` | Create config |
| `neorunner init --latest` | Use latest MC version |
| `neorunner install` | Run full installer |
| `neorunner setup` | Alias for install |
| `neorunner status` | Show status |

## Dashboard

- Start: `neorunner dashboard` or auto-starts with server
- URL: http://localhost:8000
- Shows setup wizard on fresh install (no server.properties)

## Remaining Tasks

- [ ] Test daemon mode thoroughly
- [ ] Verify version check on boot works
- [ ] Test fresh install flow end-to-end
- [ ] Add version check scheduling in dashboard