# NeoRunner Implementation Plan

## Overview
This document describes the implementation plan for NeoRunner features.
**IMPORTANT: Always use the dynamic version system. Never hardcode Minecraft versions.**

## Dynamic Version System

### Core Principle
ALL Minecraft version references must use the version module, not hardcoded strings:

```python
# CORRECT - use version module
from neorunner_pkg.version import get_latest_minecraft_version, get_all_minecraft_versions

version = get_latest_minecraft_version()  # Gets latest from Mojang API

# Also get loader-specific versions
from neorunner_pkg.version import get_latest_for_loader
forge_version = get_latest_for_loader("neoforge")  # Latest NeoForge for current MC
fabric_version = get_latest_for_loader("fabric")  # Latest Fabric
```

### Version Module Locations
- `/neorunner_pkg/version.py` - fetches from Mojang/Maven API
- Cached in `.cache/mc_versions.json` for offline use

### Configuration
- `config.py` ServerConfig.mc_version - uses dynamic default
- `constants.py` - provides get_current_mc_version()
- Config option: `version_check_interval_hours` (default 24)
---

## Phase 1: Crash Log Analyzer (Client-Side Analysis)

### Purpose
Analyze **CLIENT** crash logs to identify issues and auto-fetch missing mods/deps for client sync.

### Upload & Analysis Flow
```
User uploads CLIENT crash log → Server analyzes → Action
```

### Error Patterns & Actions

| Error Type | Detection Pattern | Server Has Mod? | Action |
|-----------|-------------------|-----------------|--------|
| **Missing Dependency** | `requires mod X`, `Mod X not found` | NO | Fetch X via scraper/ferium → put in `clientonly/` |
| **Missing Dependency** | `requires mod X` | YES (different version) | Report version mismatch → tell client to resync |
| **Missing Dependency** | `requires mod X` | YES (same version) | No action needed |
| **Client-Only Mod** | `net.minecraft.client.*` | - | Flag for client (informational only) |
| **Java Version** | `Class version 65` | - | Warn: client Java vs mod needs |
| **Mixin Error** | `MixinPreProcessorException` | - | Warn: client mod issue |
| **Mod Crash** | `caused by mod X` | - | Flag as problematic on client |
| **Version Mismatch** | MC version mismatch | - | Warn: client vs server version |

### Auto-Fetch Logic
1. **Server has mod = NO** → Fetch via mod scraper/ferium_manager → put in `clientonly/` folder
2. **Server has different version** → Report version mismatch event → client should resync
3. **Server has same version** → No action needed

### Manifest Updates
- Any mod added to `mods/` or `clientonly/` is automatically included in next `/download/manifest` fetch
- No explicit manifest update needed - it dynamically scans folders

---

## Phase 2: Network Channel Logging (Server-Side) ✅ COMPLETE

### Purpose
Detect client/server mod mismatch at connection time via network channel analysis.

### Implementation
- **Always-on monitoring**: Network channel analysis runs continuously every 5 seconds during server runtime (not just on crash)
- Tracks log file position and reads only new content
- Detects connection-time mismatches in real-time as clients connect

### Enable Verbose Logging
Always on via JVM args:
- NeoForge: `-Dneoforge.logging.debugNetwork=true` (neoforge.py:46)
- Forge: `-Dfml.query.verbose=true` (forge.py:50)

### Channel Mismatch Detection
Parse server logs for:
- `Unknown custom packet identifier`
- `Channel not registered`
- `Missing channel: mod_id`
- `CustomPayload`

### Event Generation
```
[CHANNEL] Connection rejected: client 192.168.1.X has mod "X" that server doesn't
[CHANNEL] Channel mismatch - client missing: mod_id
[CHANNEL] Version mismatch: client has mod X v1.0, server has v2.0
```

### Files Created
- `network_channel_analyzer.py` - Channel detection and mapping

---

## Phase 3: Log Management ✅ COMPLETE

### Configuration (config.json)
```json
{
  "log_retention_days": 30,
  "crash_report_retention_days": 30,
  "live_log_max_size_mb": 10,
  "live_log_backup_count": 5
}
```

### Cleanup Implementation
- Run on server startup (in `server.py` start method)
- Delete crash-reports older than `crash_report_retention_days`
- Rotate live.log at `live_log_max_size_mb`
- Keep `live_log_backup_count` rotated files

### Config Validation (for reinstalls)
- `validate_config(cfg)` - validates required fields, fails fast
- `ensure_config(cfg)` - fills defaults for missing fields (canonical function)
- `neorunner init` - creates default config
- Config validated on startup in `cmd_start`

### Files Created
- `log_manager.py` - LogManager class with cleanup/rotation

### CLI Commands Added
- `neorunner init` - Initialize default config with options:
  - `--force` - Overwrite existing config
  - `--mc-version` - Minecraft version (default: 1.21.11)
  - `--loader` - Mod loader (neoforge/forge/fabric)
  - `--xmx` - Max memory (default: 4G)

---

## Phase 4: Comprehensive Testing ✅ COMPLETE (25 tests)

### Test Structure
```
/home/services/dev/neorunner/tests/
├── __init__.py
├── test_config.py                 # 8 tests - config validation
├── test_crash_analyzer.py         # 7 tests - crash detection
├── test_log_management.py         # 4 tests - cleanup/rotation
├── test_network_channels.py      # 6 tests - channel analysis
├── test_mod_browser.py            # NOT IMPLEMENTED
├── test_self_heal.py              # NOT IMPLEMENTED
├── test_server.py                 # NOT IMPLEMENTED
├── test_client_sync.py            # NOT IMPLEMENTED
└── test_loaders/
    ├── __init__.py
    ├── test_neoforge.py          # NOT IMPLEMENTED
    └── test_fabric.py            # NOT IMPLEMENTED
```

### Implemented Tests (25 total)
| File | Tests | Status |
|------|-------|--------|
| test_config.py | 8 | ✅ Complete |
| test_crash_analyzer.py | 7 | ✅ Complete |
| test_log_management.py | 4 | ✅ Complete |
| test_network_channels.py | 6 | ✅ Complete |

### test_config.py Tests
1. `test_validate_config_valid` - valid config passes
2. `test_validate_config_missing_mc_version` - fails on missing mc_version
3. `test_validate_config_invalid_loader` - fails on invalid loader
4. `test_ensure_config_fills_defaults` - fills missing fields
5. `test_ensure_config_preserves_existing` - keeps existing valid values
6. `test_default_values` - default config values
7. `test_to_dict` - config serialization
8. `test_from_dict` - config deserialization

### Test Coverage Required

#### test_crash_analyzer.py (6 tests)
| Test | Description |
|------|-------------|
| `test_java_version_detection()` | Parse "Class version 65 required" |
| `test_missing_dependency_detection()` | Parse "requires mod X" |
| `test_client_only_mod_detection()` | Parse "net.minecraft.client" |
| `test_mixin_error_detection()` | Parse MixinPreProcessorException |
| `test_mod_crash_detection()` | Parse "caused by mod X" |
| `test_full_client_log_analysis()` | Integration - full log parsing + auto-fetch |

#### test_mod_browser.py (4 tests)
| Test | Description |
|------|-------------|
| `test_search_filters_by_mc_version()` | facets versions:1.21.11 |
| `test_search_filters_by_loader()` | facets categories:neoforge |
| `test_version_exact_match()` | Only return exact version matches |
| `test_excludes_libraries()` | Filter lib/api mods |

#### test_self_heal.py (6 tests)
| Test | Description |
|------|-------------|
| `test_java_version_detection()` | Detect installed Java from process |
| `test_fabric_deps_skipped_on_neoforge()` | Fabric deps filtered for NeoForge |
| `test_neoforge_deps_skipped_on_fabric()` | NeoForge deps filtered for Fabric |
| `test_quarantine_mod()` | Quarantine function moves files |
| `test_dependency_resolution()` | Find missing deps from TOML |
| `test_known_safe_deps_filtering()` | Only fetch curated deps |

#### test_server.py (4 tests)
| Test | Description |
|------|-------------|
| `test_crash_detection_vs_clean_shutdown()` | Distinguish crash from stop |
| `test_java_version_crash_handling()` | Detect Java version errors |
| `test_client_side_error_detection()` | Detect client mod errors |
| `test_restart_loop_prevention()` | Max 5 restarts |

#### test_log_management.py (3 tests)
| Test | Description |
|------|-------------|
| `test_cleanup_old_crash_reports()` | Delete files > 30 days |
| `test_live_log_rotation()` | Rotate at 10MB threshold |
| `test_retention_config()` | Read config for retention days |

#### test_network_channels.py (3 tests)
| Test | Description |
|------|-------------|
| `test_channel_mismatch_detection()` | Parse "Unknown custom packet" |
| `test_channel_event_generation()` | Create proper event message |
| `test_client_ip_extraction()` | Extract client IP from log line |

#### test_client_sync.py (4 tests)
| Test | Description |
|------|-------------|
| `test_manifest_includes_clientonly()` | clientonly folder in manifest |
| `test_auto_fetch_missing_dep()` | Fetch → clientonly folder |
| `test_resync_when_server_has_mod()` | Resync prompt |
| `test_ps1_fetches_latest_manifest()` | Manifest updates |

#### test_loaders/test_neoforge.py (3 tests)
| Test | Description |
|------|-------------|
| `test_all_crash_patterns()` | Test each NeoForge pattern |
| `test_version_extraction()` | Extract MC version from log |
| `test_fml_earlyCrashDetection()` | Early crash detection |

#### test_mod_management/test_curation.py (4 tests)
| Test | Description |
|------|-------------|
| `test_curation_process()` | Full curation workflow |
| `test_client_only_detection()` | Detect client-only mods |
| `test_version_mismatch_detection()` | Detect version issues |
| `test_quarantine_workflow()` | Move to quarantine |

#### test_mod_management/test_downloads.py (3 tests)
| Test | Description |
|------|-------------|
| `test_mod_download()` | Download from Modrinth |
| `test_ferium_download()` | Download via ferium_manager |
| `test_version_matching()` | Match version for MC/loader |

---

## CI/CD Integration

### GitHub Actions
```yaml
name: Tests & Lint
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install pytest pytest-cov ruff
      - run: pytest tests/ -v --cov=neorunner --cov-report=xml --cov-fail-under=90
      - run: ruff check neorunner/ --output-format=github
```

---

## Key Dependencies

### Mod Fetching for Auto-Recovery
When crash analyzer detects missing dependency:
1. Use **mod scraper** (Modrinth API/CurseForge scraper) to find mod's slug id for ferium
2. Use **ferium_manager** to download correct version for MC version + loader
3. Put in appropriate folder (`clientonly/` for client-only deps/mods, `mods/` for server deps/mods)
4. Next manifest fetch automatically includes the new mod, but trigger it after fetching

### Files Involved
- `self_heal.py` - Dependency resolution and fetching
- `mod_browser.py` - Mod search and version matching
- `mod_hosting.py` - Manifest generation and PS1 script
- `ferium.py` - Ferium integration for downloads
- `crash_analyzer.py` - NEW: Client side crash log analysis (this phase)

---

## Implementation Order

1. **Create `crash_analyzer.py`** - Core analysis logic with all error patterns
2. **Add dashboard endpoint** - `POST /api/analyze-crash` for file upload
3. **Add UI to Server Status** - Upload component in dashboard
4. **Implement auto-fetch** - Use scraper/ferium to fetch missing mods
5. **Add network channel logging** - Parse logs for channel mismatches
6. **Add log cleanup** - Implement retention policy
7. **Write comprehensive tests** - 90% coverage target
8. **Run lint/format** - Fix any issues

---

## Success Criteria

- [x] User can upload client crash log via dashboard (`POST /api/analyze-crash-log`)
- [x] Server correctly identifies: missing deps, client-only mods, Java issues, mixin errors
- [x] Missing mods are auto-fetched to appropriate folder (via crash_analyzer)
- [x] Manifest automatically includes newly fetched mods
- [x] Network channel mismatches are logged as events (always-on monitoring)
- [x] Logs are cleaned up per retention policy
- [ ] 90%+ test coverage achieved (25 tests, ~40% coverage estimate)
- [x] All tests pass (25/25 passing)

---

## Cleanup & Refactoring

### Issues Fixed
1. **Type annotations**: Fixed `Dict[str, any]` → `Dict[str, Any]` in loaders
2. **Config consolidation**: Removed redundant `get_config()`, kept `ensure_config()` as canonical
3. **Missing exports**: Added to `__init__.py`:
   - `validate_config`, `ensure_config` from config
   - `LogManager`, `run_log_cleanup` from log_manager
   - `CrashAnalyzer`, `CrashAnalysis` from crash_analyzer
   - `NetworkChannelAnalyzer`, `ChannelMismatch` from network_channel_analyzer
   - Fixed mod_browser exports (`ModResult` instead of non-existent `ModInstaller`)
4. **Import consistency**: Made all relative imports consistent

### Files Created
- `crash_analyzer.py` - Client crash log analysis
- `network_channel_analyzer.py` - Network channel mismatch detection
- `log_manager.py` - Log retention and rotation
- `tests/test_config.py` - Config validation tests
- `tests/test_crash_analyzer.py` - Crash analyzer tests
- `tests/test_log_management.py` - Log manager tests
- `tests/test_network_channels.py` - Network channel tests

### Install Flow
```bash
pip install -e .
neorunner init --mc-version 1.21.11 --loader neoforge --xmx 4G
neorunner setup
neorunner start
```

---

## Client Sync Implementation

### Flow
1. Server hosts `/download/manifest` - JSON list of all mod filenames
2. Client downloads bat script or uses one-liner
3. Bat script:
   - Fetches manifest from server
   - Compares local `%appdata%\.minecraft\mods` against server list
   - Moves extra mods to `oldmods` folder
   - Downloads missing mods as zip from `/download/all`
   - Shows statistics

### Endpoints
- `GET /download/manifest` - Returns JSON with `"files": [{"path": "modname.jar"}]`
- `GET /download/all` - Returns zip of all mods
- `GET /download/install-mods.bat` - Returns batch script (wraps PS1 logic)
- `GET /download/install` - Returns PowerShell script

### One-Liner
```
curl.exe -sL "http://IP:PORT/download/install-mods.bat" -o %TEMP%\install-mods.bat && %TEMP%\install-mods.bat
```

### Dashboard Status
Shows: Status, Loader, MC Version, World (version), Server Mods, Client Mods, Players, Preflight, Java path

### Preflight
- Runs on server startup via `preflight_dep_check()`
- Scans all mods for required dependencies
- Auto-fetches missing deps to `mods/` folder
- Skips Fabric-only deps for NeoForge and vice versa

---

## Current Issues Fixed
1. PowerShell script had syntax errors (extra duplicated code) - FIXED
2. NBT world version detection returning "unknown" - FIXED (handles nested Data structure)
3. Preflight skipping deps not in whitelist - FIXED (removed whitelist restriction)
4. Dashboard layout - 3 rows with 2 columns each
