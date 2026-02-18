# NeoRunner

Production-ready modded Minecraft server manager. Single Python file, runs everything.

## What It Does

- **Runs a modded MC server** (NeoForge, Forge, or Fabric) with auto-restart via systemd
- **Curates mods from two sources**: Top 100 from Modrinth API + Top 100 from CurseForge (web scraper) — deduplicated into up to 200 unique mods
- **Auto-fetches dependencies**: Required deps downloaded automatically for both sources. CurseForge deps scraped from each mod's relations page.
- **Flags optional dep interoperability**: If 2+ selected mods share an optional dependency, you get notified so you can install it for better compatibility
- **Self-heals on crash**: Detects missing mod dependencies from crash logs, fetches them from Modrinth, restarts
- **Web dashboard on port 8000**: Admin panel + mod browser + download endpoint for clients
- **Auto-detects existing installs**: Reads `server.properties` and generates config if none exists

## Quick Start

```bash
git clone https://github.com/nickyg666/NeoRunner-Python.git
cd NeoRunner-Python
pip3 install flask playwright playwright-stealth --break-system-packages
python3 -m playwright install chromium
python3 run.py run
```

Dashboard at `http://<your-ip>:8000`. MC server on port `1234`.

## Key Commands

```bash
python3 run.py run              # Start everything (server + web dashboard)
python3 run.py curator          # Interactive mod curator (dual-source)
python3 run.py --reconfigure    # Re-detect loader/version from disk
```

## How Mod Curation Works

1. Fetches top mods from **Modrinth** (API) and **CurseForge** (Playwright stealth scraper)
2. Filters out libraries/APIs (~40 known + pattern matching)
3. Deduplicates by normalized name across sources
4. Displays merged list sorted by downloads (`[M]`=Modrinth, `[C]`=CurseForge, `[+]`=both)
5. You pick mods — system downloads them + all required deps
6. If 2+ of your picks share an optional dep, you get an interop flag

CurseForge scraping uses headless Chromium with stealth to bypass Cloudflare. No API key needed (their key only works for uploads).

## Architecture

Everything runs from `run.py` (~3100 lines). Key sections:

| Section | What |
|---------|------|
| Flask HTTP server | Dashboard UI, API endpoints, mod downloads (port 8000) |
| CurseForge scraper | Playwright stealth, search + dependency page scraping |
| Modrinth integration | API-based mod search, version fetching, dep resolution |
| Curator command | Dual-source aggregation, dedup, dep handling, interop flags |
| Server runner | tmux-based MC server with crash detection + self-heal |
| RCON client | Binary Source RCON protocol for server commands |

## Config

`config.json` — auto-generated on first run or from existing `server.properties`:

```json
{
  "loader": "neoforge",
  "mc_version": "1.21.1",
  "http_port": 8000,
  "server_port": 1234,
  "rcon_host": "192.168.0.19",
  "mods_dir": "mods"
}
```

## Dependencies

- Python 3.8+, Java 21+, tmux, Linux
- `flask` — web dashboard
- `playwright` + `playwright-stealth` — CurseForge scraping
- Chromium browser (installed via `playwright install chromium`)

## systemd

The included service file auto-restarts on crash:

```ini
[Service]
ExecStart=/usr/bin/python3 run.py run
Restart=always
RestartSec=10
```

Install: `sudo cp mcserver.service /etc/systemd/system/ && sudo systemctl enable --now mcserver`
