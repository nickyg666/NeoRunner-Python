# NeoRunner v2.3.0 Progress

## Latest Changes (2026-04-22)

### Version Module
- `version.py` - Dynamic fetching from Mojang/Maven/Fabric APIs
- Handles new Mojang versioning (26.x -> 1.21.x format conversion)
- Caches for 1 hour in `.cache/mc_versions.json`

### Dynamic Updates
- All hardcoded "1.21.11" references replaced with dynamic calls
- Config uses `version_check_interval_hours` (default 24h)
- CLI: `neorunner init --latest` fetches latest MC version

### Auto Features
- **Self-heal**: `preflight_dep_check()` auto-fetches missing deps
- **ModPatcher**: Auto-patches mods for compatibility
- **ModModder**: Resolves mixin conflicts
- **CrashAnalyzer**: Analyzes crashes, auto-fetches missing

### Daemon Mode
- `neorunner start --daemon` or `-d`
- `--pid-file /path/to/pid` for service management
- `--foreground` to run in foreground

### Install Script
```bash
# Normal install
curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash

# Fresh reinstall (cleans old)
curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash -s --fresh
```

## Verified Working

| Feature | Status |
|---------|--------|
| Dashboard | ✅ |
| API endpoints (/api/status, /config, /mods, /worlds) | ✅ |
| CLI commands (start, stop, install, init) | ✅ |
| Self-heal (preflight) | ✅ |
| ModPatcher | ✅ |
| ModModder | ✅ |
| CrashAnalyzer | ✅ |
| Version fetching | ✅ |
| Daemon mode | ✅ |

## Commands

| Command | Description |
|---------|-------------|
| `neorunner start` | Start server |
| `neorunner start --daemon` | Background |
| `neorunner stop` | Stop |
| `neorunner restart` | Restart |
| `neorunner init` | Create config |
| `neorunner init --latest` | Latest version |
| `neorunner install` | Full setup |
| `neorunner setup` | Alias |

## Dashboard

- URL: http://localhost:8000
- Shows setup wizard on fresh install (no server.properties)
- Real-time status, mods, worlds
- Mod hosting for client sync