# NeoRunner-Python
Built for a linux host, this (vibe-coded) program will download/run the latest neoforged server (others supported as well) and try to sync mods it finds into client side to sidestep modloader swaps and client/server upgrades. I am a huge fan of the automodpack mod for what it's worth, and this is nowhere near complete. it does kind of work, but xvfb is not required, some deps may be missing. some documentation may be erroneous, it is mostly ai driven, and I largely did not check it for accuracy. I typically focus on good docs after everything works and I'm in a feature freeze, but I keep spiraling past any stopping point. the project is rather unfinished and a mess of things at this point. 

## shout-out to skidam for making that mod and giving me the idea. 
This has spiraled into a whole expansive hosting and mod management console, dependent on Ferium to manage downloads, uses a stealth browser to check curseforge, and modrinths super cool API that's free to use for the modrinth side. Should give you top 100 non-lib/api downloads from either suppier by default, but you can sort but other criteria in the settings.
there are many more features I didn't mention, check it out!

## I burned up all my copilot tokens on this in a day, may slowly edit until they replenish next month. You can sponsor the repo if you like what I'm doing and are feeling generous. $10 gets me a month of anthropic's claude + GitHub copilot in my favorite program: opencode.ai editor! 

As always, big shout-out to 

# My wife Sage, who understands that after I get home from work all I really want to do is more work. I love her more than trees love carbon dioxide.

# To my son, Lorenzo, who is the whole reason I would ever touch minecraft in the first place, let alone get this involved with it.


Here is the idea behind the project:

run script, it handles a lot of stuff so you don't have to. goal: move from minecraft version to version, modloader agnostic and able to grab whatever mods you had before that got updated. Offer install scripts to pull latest mods from server to client. Web UI just for fun, helps reach more users that way, and helps me be lazier with my leisure activities.

you don't have to know a ton about minecraft modding to get started.

you run the script, you enable RCON (so it can tell your clients what they need when they try to connect), and set other configs.

it runs in a tmux for persistence, optionally will autostart. It will get all the things it needs on first run. It will prompt for authentication when it needs to install software.


visit server portal, manage mods and get client script to download latest mods -> restart minecraft -> sees new mods -> connect to server and have fun! Or find a reason to do more work like me haha!



## I vibe coded this for max time efficiency in getting started, then manually tweaked it to actually work. Used ChatGPT, Claude haiku and Claude opus 4.6, it did not enjoy this task as much as I did not enjoy pointing out all of their errors.

## I then had to totally rewrite it due to adding too many features, changing too much four haiku to deal with. then I had to move to opus which is credit intensive!
workflow is generally -> workshop ideas on chatGPT/any free LLM -> turn into starter script -> manually improve -> development enters support mode (we are here right now - 02.16.2026) || feed to more advanced coding AI like claude haiku 4.5 + github copilot + opencode.ai ide (here right now! 2/18/2026) -> finished product (hopefully 2/18?) I've graduated off to anthropic's Opus 4.6, because my tasking need is outgrowing AI pretty quickly; I'll have to get better at coding fast - but I can't type 400WPM like an LLM can!

This workflow maximizes the bang for my buck (or so I hope) on the copilot token usage - I don't waste any precious paid tokens on prototyping!

<!--- CLAUDE, YOU CAN DO YOUR INFO STUFF DOWN HERE, DON'T REMIX MINE -----!>

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
