# NeoRunner v2.3.0 Progress

## Latest Changes (2026-08-09)

### Loader/MC Version Switch Rework (Backend + UI)
- `POST /api/loaders/switch` rewritten: stops server, snapshots config+server.properties+mods+worlds into `snapshots/pre_<loader>_switch_<ts>.tar.gz`, archives mods into `loader_archive/<old_loader>/<old_mc>/<new_mc>/` (+ `clientonly/` subdir) unless `keep_mods`, archives incompatible worlds (via `nbt_parser.get_world_version`) into `worlds_archive/mc-<old_mc>/`, updates config, installs new loader. Returns `{success, message, snapshot, archived_mods, archived_worlds, install_ok}`.
- New `POST /api/loaders/restore` (extract snapshot with `filter="data"` + path-traversal guard) and `POST /api/loaders/restore-mods` (move jars back from `loader_archive/`).
- `/api/loaders/snapshots` now lists `*.tar.gz` with size/size_mb/created.
- World delete: `POST /api/worlds/delete` moves world to `worlds_trash/` (recoverable, blocks on active world). `GET /api/worlds/archives` lists archive+trash; `POST /api/worlds/restore` brings them back.
- Dashboard UI: Delete button per world, Archived/Trashed worlds section with Restore, Quick Actions "Loader & MC Version Quick Switch" widget (switch + snapshot restore), Restore buttons on snapshots + archived mods, theme selector restored (Chrome/Minecraft/Cyberpunk/Mario via `localStorage neorunner-theme`).

### Tests (296 passing)
- All AGENTS.md NOT-IMPLEMENTED test files written: `test_mod_browser.py` (26), `test_self_heal.py`, `test_server.py`, `test_client_sync.py`, `tests/loaders/test_neoforge.py` (24), `test_fabric.py` (10), `test_forge.py` (10), `tests/mod_management/test_curation.py` (16), `test_downloads.py` (3).
- `tests/test_dashboard_api.py::TestLoaderSwitch` (19 tests) covering snapshot/archive/restore flow.
- Coverage: config 100%, log_manager 100%, network_channel_analyzer 100%, mod_browser 98%, fabric 91%, forge 91%, neoforge 85%, client_only_detector 85%, crash_analyzer 82%, mod_hosting 41%. Overall package ~25% (was 19.55%).

### Real Bugs Fixed
- `network_channel_analyzer.py`: regex truncated `minecraft:brand` → added `:` to char class.
- `client_only_detector.py`: `patch_mixin_config` wrote unmodified bytes → encode modified text.
- `crash_analyzer.py`: jar regex captured `8` from `sodium-0.5.8.jar` → proper mod-name pattern.
- `mod_hosting.py`: duplicated `catch/else` block in PS1 script (invalid syntax); deadlock from `threading.Lock()` in zip creation → `RLock`.
- `mod_browser.py`: used nonexistent `response.text` in CurseForge HTTP search → use parsed `html`.

## Previous: Latest Changes (2026-04-22)

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