# NeoRunner — PROGRESS.md

> Living progress tracker. Companion to SOUL.md (identity/memory),
> CONTEXT.md (state snapshot), CONVERSATION_HISTORY.md (session log),
> CHANGELOG.md (git history).

**Current version: 2.5.0** · Latest commit `6d68177` (2026-08-23) · 412 tests passing

---

## Status Summary

| Area | Status |
|------|--------|
| Modded server (NeoForge 26.1.2, port 25565) | ✅ running |
| Dashboard (port 8000) | ✅ running |
| Waiting room / holding cell (port 1234) | ✅ running |
| systemd `neorunner.service` | ✅ active |
| Client installer pipeline (JAR + /dl/mods.zip) | ✅ |
| Preflight dependency healing | ✅ |
| Client sync + clickable download link | ✅ |
| Network channel mismatch detection (always-on) | ✅ |
| Log rotation & retention | ✅ |
| Crash recovery | ✅ |
| Dynamic MC/loader versions | ✅ |
| World upload + Chunker conversion | ✅ |
| Test suite | ✅ 412 passing |

---

## Latest Milestone — 2026-08-23 (v2.5.0)

### 1. Installer uses domain, not IP
- `installer_jar.py:55-66` — `build_installer_properties` prefers
  `cfg.hostname` (w8.mom) for `serverAddress`; direct game address is a
  fallback only. `baseUrl` = `https://w8.mom`.
- Test updated in `tests/test_installer_jar.py`.

### 2. Missing deps now ship in the bundle
Root cause: preflight's local `installed_mod_ids` was too narrow. Fixed in
`self_heal.py`:
- Scan now includes `clientonly/` **and** merges JarJar-bundled ids
  (`_jij_provided_mod_ids`).
- `scena` (jarjar inside Chisels & Bits) no longer chased as a phantom dep —
  was wrongly resolving to `nbtexporter`.
- `entity_texture_features` (client-only dep of `entity_model_features`) no
  longer wrongly quarantined/deleted.
- Mod-ID matching normalizes `-`/`_` (`cloth-config` vs `cloth_config`).
- `scena` added to `KNOWN_SAFE_DEPS` whitelist.
- Fetched `cloth-config-26.1.154.jar`; restored `entity_texture_features`.

### Verified
- Bundle rebuilt: 53 mods in embedded `pack.zip` incl. cloth-config + ETF.
- Preflight: **zero** wrongly-quarantined mods.
- 412 tests passing (added `TestDependencyResolutionFixes` in
  `tests/test_self_heal.py`).
- Committed `6d68177`, pushed to `main`.

---

## Earlier Milestones

| Version | Highlights |
|---------|-----------|
| 2.4.9 | Waiting-room polish: user-guide book, glass walls, short ceiling, domain-only downloads; kick msg `click_event/url`; **fixed modded server never starting** (room matched `is_server_running`) |
| 2.4.8 | Client-side mod making disconnect download link clickable |
| 2.4.7 | Short `/dl/mods.zip` bundle (installer JAR + Java installers) |
| 2.4.6 | Native installer bootstrap installs Java if missing |
| 2.4.5 | Deduplicate mods — never ship two versions of the same mod |
| 2.4.4 | Quarantine fetched mods with unsatisfiable required deps |
| 2.4.3 | `--no-preflight` gates all start/recovery paths |
| 2.4.2 | Resolve chunker-cli.jar via GitHub API |
| 2.4.1 | Stop preflight destructively moving server mods |
| 2.4.0 | World upload + Bedrock/version conversion via Chunker; modpack zip installer; admin auth; kick links |
| 2.3.0 | Dynamic versions, self-heal, patchers, crash analyzer, network channels, log manager, daemon, systemd |

---

## Test Suite

```
tests/ — 412 passing across 32 files (~67s)
python3 -m pytest tests/ -q
```

Major files: `test_config`, `test_config_validation`, `test_constants`,
`test_crash_analyzer`, `test_network_channels`, `test_log_management`,
`test_self_heal`, `test_server`, `test_server_status`, `test_cli`,
`test_dashboard`, `test_dashboard_api`, `test_holding_cell`,
`test_installer_jar`, `test_jar_message_patcher`, `test_client_mod`,
`test_client_sync`, `test_mod_browser`, `test_mod_hosting`,
`test_mod_dedupe`, `test_modpack_installer`, `test_modpack_auth_kick`,
`test_loader_detection`, `test_loader_properties`, `test_loaders`,
`test_ferium_installer`, `test_curseforge_zip`, `test_external_access`,
`test_users`, `test_world_upload`, `test_chunker`.

---

## Open Items

- [ ] Confirm Fabric-only mods (pulling fabric-api / fabric-resource-loader-v1
      / lambdynlights_api) don't belong in a NeoForge pack
- [ ] Re-check `spruceui` / `yumi_mc_core` Modrinth fetch failures
- [ ] Measure coverage vs 90% target (`pytest --cov=neorunner_pkg`)
- [ ] Resolve `FABRIC_IMPLEMENTATION_PLANS.MD` (abandoned Fabric port?)

---

## Key Commands

```bash
python3 -m pytest tests/ -q                 # run tests (412)
sudo systemctl status neorunner             # check services
pip install -e .                            # reinstall package
neorunner init --mc-version 26.1.2 --loader neoforge --xmx 4G
neorunner setup && neorunner start
```

### Client one-liner
```
curl.exe -sL "http://w8.mom:8000/download/install-mods.bat" -o %TEMP%\install-mods.bat && %TEMP%\install-mods.bat
```

---
*Updated 2026-08-23*