# NeoRunner User Guide

This guide covers everything you can do from the NeoRunner web dashboard, with a
focus on the mod management workflow. For installation and systemd deployment
see `README.md`; for internals see `ARCHITECTURE.md`.

---

## 1. The Dashboard

Open `http://<your-server>:8000/admin` (or `https://<your-domain>/admin` when
external access is configured) and log in with your admin credentials. The
public root (`/`) is the player-facing download/status page; `/admin` is the
management UI.

The dashboard is organised into tabs:

- **Status** — server state, players, world, memory, logs
- **Mods** — the mod management workspace (see §2)
- **Modpack** — upload/install a CurseForge modpack export (§3)
- **Worlds** — scan, switch, backup, restore worlds (§4)
- **Loaders** — switch/install loaders and MC versions (§5)
- **Config** — ports, memory, retention, hostname (§6)

---

## 2. Mod Management

The **Mods** tab lists every mod in `mods/` (server mods) and `clientonly/`
(client-only mods). From here you can upload, organise, patch, and search for
mods.

### Uploading mods
Drag `.jar` files into the drop zone or use the file picker. Uploaded files land
in `mods/`. NeoRunner detects which mods are client-only and offers to move them
to `clientonly/` (these are *not* loaded by the server but are shipped to
players via the modpack download).

### Organising: client vs server
- **Sort client mods** — scans `mods/` for client-only mods and moves them to
  `clientonly/`.
- **Quarantine** — moves mods out of the active folders into `quarantine/`
  without deleting them. Use this to isolate a problematic mod before removing
  it, or to temporarily disable a set.
- **Restore from quarantine** — moves mods back into `mods/`.
- **Delete** — permanently removes selected mods.

### Searching & installing mods
Use the search box to query Modrinth (and CurseForge where available). Results
are filtered to your configured Minecraft version and loader. Click **Install**
on a result to download it (and its declared dependencies) straight into
`mods/`. You can also install several mods at once by keyword (e.g.
`furniture windows`) which resolves dependencies for each.

### Analysing for mixin conflicts
The **Analyze** action scans every mod's mixin configs and detects conflicts:
- two mods targeting the same class,
- duplicate field declarations,
- priority conflicts,
- missing refmaps.

It reports the conflicts and, where possible, resolves them by adjusting load
order or priority. Run this after adding a batch of mods or before updating.

### Optimizing load order
The **Optimize** action renames mods with a numeric prefix so loaders pick them
up in a sane order — libraries/APIs first, then regular mods, then add-ons. This
matters for Fabric/Quilt and for any loader that respects filename ordering.
Run it after a large install, or whenever a mod's features aren't taking effect.

### Patching for compatibility
The **Patch** action runs the compatibility patcher over `mods/`:
- adds missing mixin priorities,
- patches broken mixin refmaps,
- flags native/JNI and coremod conflicts that cannot be auto-resolved.

Patching modifies the mod jars in place (with `.orig` backups kept). Use it when
a mod refuses to load or throws mixin errors, or after an MC/loader version
change. The result view lists exactly what was patched, what was skipped, and
what needs manual attention.

### Upgrading mods
The **Upgrade** action checks your installed mods against the configured loader
and MC version and offers newer compatible builds where available.

### General workflow order
1. Upload / search-install the mods you want.
2. **Sort client mods** to split client-only files.
3. **Analyze** for mixin conflicts; fix any reported.
4. **Optimize** load order.
5. **Patch** for compatibility.
6. Start the server and watch the logs; **Quarantine** anything that crashes.

---

## 3. Modpacks

The **Modpack** tab accepts a CurseForge modpack export (`.zip`). NeoRunner:

1. Reads the pack manifest (`manifest.json`),
2. Downloads each listed mod from the CurseForge CDN into `mods/`,
3. Applies the `overrides/` folder (configs, scripts, resource packs),
4. Reports installed/failed/skipped counts.

A live progress banner appears at the top-right of your viewing area while the
pack installs (it stays put 75px from the top of the window, far right, and
won't scroll away). You can also **convert** a modpack intended for a different
loader before installing.

---

## 4. Worlds

- **Scan** — detect worlds on disk and their MC version (from `level.dat`).
- **Switch** — change the active world the server loads.
- **Backup** — compress the active world to a timestamped archive.
- **Restore** — load an archived world back.
- **Archive/Load & Switch** — stage an old world and switch to it later.

Worlds that belong to a different loader or MC version are flagged; switching to
an incompatible world warns you first.

---

## 5. Loaders

Switch between **NeoForge**, **Forge**, and **Fabric**, or install a loader for a
different Minecraft version. NeoRunner downloads the matching installer, runs it,
and re-patches the loader jars so a mismatched/vanilla client is shown a
clickable "download the modpack" link instead of the generic
"Incompatible client!" message.

---

## 6. Configuration

The **Config** tab edits `config.json`:

| Setting | Purpose |
|---------|---------|
| `mc_version` | Minecraft version (defaults to latest from Mojang) |
| `loader` | neoforge / forge / fabric |
| `http_port` | Dashboard/download HTTP port (default 8000) |
| `mc_port` | Game port clients connect to |
| `xmx` / `xms` | JVM heap (e.g. `6G` / `4G`) |
| `hostname` | Public hostname used in download links and kick messages |
| `log_retention_days` | How long logs are kept |
| `crash_report_retention_days` | How long crash reports are kept |
| `live_log_max_size_mb` | When `live.log` rotates |

The `hostname` field is the single source of truth for every externally visible
URL (modpack download link, in-game kick link, join address). Set it via the
external-access setup (or the `neorunner install --domain ...` flags) and it
flows through automatically — you never need to edit a hardcoded domain.

---

## 7. External Access (public domain)

`neorunner install` (or `neorunner config --setup`) can expose the dashboard and
downloads on a public domain:

```
neorunner install --domain play.example.com --external-access caddy
neorunner install --domain play.example.com --external-access cloudflare --cf-token <TOKEN>
```

- **Caddy** — reverse-proxies `https://<domain>` to the dashboard with automatic
  Let's Encrypt SSL. Requires a public A/AAAA record pointing at the machine.
- **Cloudflare Tunnel** — `cloudflared` dials out to Cloudflare; no inbound port
  or public IP needed. If you choose Cloudflare and don't pass `--cf-token`,
  the setup wizard prints the link to create one
  (`https://dash.cloudflare.com/profile/api-tokens`) and prompts for it.
- **ddclient** (`--ddclient`) — keeps the domain's DNS A/AAAA record tracking a
  changing public IP. If you enable it without `--ddclient-login` /
  `--ddclient-password`, the wizard prompts for your DDNS provider credentials.

### How routing works
Cloudflare/Tunnel ingress rules match on *hostname*, not on client type, and the
Minecraft client speaks raw TCP (not HTTPS). So:

- browsers → `https://<domain>/` → dashboard download/status page,
- admin → `https://<domain>/admin` → management UI,
- Minecraft clients → `<domain>:<mc_port>` directly (raw TCP), not through the
  tunnel.

The dashboard's root route detects a Minecraft-style user agent and returns the
join address (`<hostname>:<mc_port>`); everyone else gets the download page.

---

## 8. Client Synchronization

Players get the modpack one of three ways:

- **`/download/install-mods.bat`** — Windows one-liner that fetches the manifest,
  moves extra mods to `oldmods/`, downloads missing ones, and prints stats.
- **`/download/install.sh`** — the Linux/macOS equivalent.
- **`/download/mods.zip`** (`/dl/mods.zip`) — everything in one bundle: the
  one-click installer, all mods, configs, shaderpacks, and Java installers.

The manifest (`/download/manifest`) is generated dynamically by scanning
`mods/` and `clientonly/`, so any mod you add via the dashboard is automatically
included in the next client fetch — no manual manifest update needed.

---

## 9. Logging & Diagnostics

- **Live log** — stream the server log in the Status tab.
- **Network channel analysis** — always-on; logs a `[CHANNEL]` event when a
  client's mod set doesn't match the server's at connection time.
- **Crash log analyzer** — upload a *client* crash log; NeoRunner identifies
  missing dependencies, client-only mods, Java-version issues, and mixin
  errors, and can auto-fetch missing mods into `clientonly/`.
- **Log retention** — crash reports and old logs are pruned per the config
  (default 30 days); `live.log` rotates at `live_log_max_size_mb`.

---

## 10. Common Tasks

**Add a new mod to everyone:**
Mods → search/upload → Sort client mods → Analyze → Optimize → Patch → Start.

**A client can't connect with a mod mismatch:**
Check the network-channel events; the kick message links them to the modpack
download. Upload the missing mods and restart.

**A mod crashes the server:**
Quarantine it (not delete), restart; re-introduce later if needed.

**Change the public domain:**
Re-run external-access setup (or set `hostname` in Config). All download links
and the in-game kick link update automatically.
