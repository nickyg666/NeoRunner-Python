"""Self-healing and crash handling for Minecraft server.

Uses ferium for mod management, with CurseForge scraper for mod_id resolution.
"""

from __future__ import annotations

import os
import re
import json
import zipfile
import logging
import subprocess
import time
import random
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional

from .constants import CWD
from .log import log_event

log = logging.getLogger(__name__)

BUILTIN_MODS = {
    "neoforge", "forge", "minecraft", "java", "fml", "fabricloader", 
    "quilt_loader", "javafml", "lowcodefml", "mixin", "mixinextras",
}

# Known safe dependencies to auto-fetch (NeoForge common libs)
# These are safe to attempt downloading as they are well-known libraries
KNOWN_SAFE_DEPS = {
    # Core dependencies
    "supermartijn642corelib",
    "supermartijn642configlib", 
    "entity_model_features",
    "geckolib",
    "architectury",
    "cloth-config",
    "cloth-config-fabric",
    "collective",
    "cardinal-components",
    "cardinal-components-api",
    "cardinal-components-base",
    "cardinal-components-level",
    "cardinal-components-scoreboard",
    "ftb-lib",
    "ftb-essentials",
    "ftb-teams",
    "ftb-chunks",
    "jei",
    "kubejs",
    "patchouli",
    "cc-tweaked",
    "computercraft",
    "commonnetwork",
    "dayflower",
    "registrate",
    "mixinextras",
    # Worldgen/biome mods
    "addonslib",
    "mcwbyg",
    "biomeswevegone",
    # Other common deps
    "bclib",
    "blueprint",
    "citadel",
    "controlling",
    "creativecore",
    "creativewarden",
    "dummmmmmy",
    "engineered_builder",
    "extended_drawers",
    "ftb-quests",
    "ftb-ranks",
    "global_gamerules",
    "goodall",
    "inventoryhud",
    "itemfilters",
    "jade",
    "jadeaddons",
    "letmeeat",
    "light-overlay",
    "modularnetworks",
    "moonlight",
    "mousewheelie",
    "neruina",
    "nullscape",
    "oxidize",
    "packetfixer",
    "paraglider",
    "presencefootsteps",
    "respawningpets",
    "roughlyenoughitems",
    "shulkerboxtooltip",
    "supermartijn642corelib",
    "supermartijn642configlib",
    "sophisticatedbackpacks",
    "sophisticatedcore",
    "sophisticatedstorage",
    "spark",
    "structurized",
    "tetra",
    "tips",
    "trashslot",
    "variant动物",
    "visualworkbench",
    "waystones",
    "wirelessredstone",
    "wthit",
    "xcffabric",
    "yeremod",
}

CF_LOADER_IDS = {
    "neoforge": 6,
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
}

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    from playwright._impl._api_types import TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

STEALTH_AVAILABLE = False
try:
    from playwright_stealth import stealth_sync as Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    try:
        from stealth import stealth as Stealth
        STEALTH_AVAILABLE = True
    except ImportError:
        pass

CF_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

CF_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
]

CF_LOCALES = ["en-US", "en-GB", "en-CA", "en-AU"]
CF_TIMEZONES = ["America/New_York", "America/Los_Angeles", "America/Chicago", "Europe/London", "Europe/Berlin"]


def _run_cmd(cmd: str) -> subprocess.CompletedProcess:
    """Execute shell command."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def _cf_rate_limit() -> None:
    """Random delay between CurseForge requests."""
    time.sleep(random.uniform(1.0, 2.5))


def preflight_dep_check(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Proactive pre-flight: scan all installed mod JARs for required dependencies,
    check if they're installed, and auto-fetch missing ones via ferium.
    
    Tracks:
    - Required dependencies: always attempt to fetch
    - Optional dependencies: track which mods want them, log interop if 2+ mods want same
    - Dependents: track which mods depend on each library - used to confirm matches
    """
    if hasattr(cfg, 'get'):
        mc_version = cfg.get("mc_version", "1.21.11")
        loader_name = cfg.get("loader", "neoforge")
        mods_dir_str = cfg.get("mods_dir", "mods")
    else:
        mc_version = getattr(cfg, 'mc_version', "1.21.11")
        loader_name = getattr(cfg, 'loader', "neoforge")
        mods_dir_str = getattr(cfg, 'mods_dir', "mods")
    
    mods_dir = Path(mods_dir_str)
    if not mods_dir.is_absolute():
        mods_dir = CWD / mods_dir
    
    clientonly_dir_str = cfg.get("clientonly_dir", "clientonly") if isinstance(cfg, dict) else getattr(cfg, 'clientonly_dir', "clientonly")
    clientonly_dir = Path(clientonly_dir_str)
    if not clientonly_dir.is_absolute():
        clientonly_dir = CWD / clientonly_dir
    
    # Create clientonly dir if it doesn't exist
    clientonly_dir.mkdir(parents=True, exist_ok=True)
    
    result: Dict[str, Any] = {"fetched": 0, "optional_interop": [], "quarantined": [], "clientonly_moved": [], "warnings": []}
    
    if not mods_dir.exists():
        return result
    
    # NeoForge 1.21.11 beta has entity_texture_features mixin BAKED into the patched server jar
    # This is a known bug in NeoForge 21.11.38-beta - cannot be fixed by moving mods
    if mc_version == "1.21.11" and loader_name.lower() == "neoforge":
        server_jar = CWD / "server.jar"
        if server_jar.exists():
            try:
                with zipfile.ZipFile(server_jar, 'r') as zf:
                    names = zf.namelist()
                    has_etf_baked = any('entity_texture_features' in n for n in names[:500])
                    if has_etf_baked:
                        log_event("PREFLIGHT", "WARNING: NeoForge 1.21.11 beta has entity_texture_features mixin baked into server.jar - this WILL crash on startup!")
                        result["warnings"].append({
                            "type": "neoforge_1.21.11_bug",
                            "message": "NeoForge 1.21.11 beta (21.11.38-beta) has entity_texture_features baked into server.jar - server will crash. Solution: downgrade to 1.21.1 or 1.20.4"
                        })
            except Exception:
                pass
    
    # Move client-only mods to clientonly folder
    from .constants import FORCE_CLIENT_ONLY_MODS
    
    # Known client-side class patterns that indicate a mod is client-only
    CLIENT_CLASS_PATTERNS = [
        "net/minecraft/client/",
        "com/mojang/blaze3d/",
        "net/optifine/",
        "net/iris/",
        " client/renderer",
        "client/gui",
        "client/options",
        "client/settings",
    ]
    
    for fn in mods_dir.glob("*.jar"):
        fn_lower = fn.stem.lower()
        
        # First check against known client-only mod list
        moved = False
        for client_mod in FORCE_CLIENT_ONLY_MODS:
            if client_mod.lower() in fn_lower:
                dest = clientonly_dir / fn.name
                fn.rename(dest)
                result["clientonly_moved"].append(fn.name)
                log_event("PREFLIGHT", f"Moved to clientonly: {fn.name} (known client-side mod)")
                moved = True
                break
        
        # If not moved by name, scan JAR for client-side classes
        if not moved:
            try:
                with zipfile.ZipFile(fn, 'r') as zf:
                    names = zf.namelist()
                    # Check for client-side class patterns
                    has_client_class = any(
                        any(pattern.replace("/", ".") in n or pattern in n.lower() 
                            for pattern in CLIENT_CLASS_PATTERNS)
                        for n in names[:200]  # Check first 200 entries
                    )
                    # Also check for mixin targets referencing client classes
                    has_client_mixin = any(
                        "client" in n.lower() and ("mixin" in n.lower() or ".json" in n.lower())
                        for n in names[:50]
                    )
                    if has_client_class or has_client_mixin:
                        dest = clientonly_dir / fn.name
                        fn.rename(dest)
                        result["clientonly_moved"].append(fn.name)
                        log_event("PREFLIGHT", f"Moved to clientonly: {fn.name} (detected client-side classes)")
            except Exception:
                pass
    
    if not mods_dir.exists():
        return result
    
    # Detect installed Java version
    import subprocess
    try:
        java_version_output = subprocess.run(
            ["java", "-version"], capture_output=True, text=True, timeout=10
        )
        java_version_match = re.search(r'version "?(\d+)', java_version_output.stderr)
        installed_java_ver = int(java_version_match.group(1)) if java_version_match else 21
    except Exception:
        installed_java_ver = 21
    
    # Track all installed mod IDs and their files
    # NOTE: Only scan main mods_dir, NOT clientonly - clientonly mods are client-only
    installed_mod_ids: Dict[str, List[str]] = {}
    
    # Check for Java version mismatches
    java_version_mismatches: Dict[str, int] = {}  # mod_file -> required_java_version
    
    for fn in mods_dir.glob("*.jar"):
            try:
                with zipfile.ZipFile(fn, 'r') as zf:
                    names = zf.namelist()
                    toml_file = None
                    if 'META-INF/neoforge.mods.toml' in names:
                        toml_file = 'META-INF/neoforge.mods.toml'
                    elif 'META-INF/mods.toml' in names:
                        toml_file = 'META-INF/mods.toml'
                    
                    if toml_file:
                        try:
                            import tomllib
                        except ImportError:
                            import tomli as tomllib
                        raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                        toml_data = tomllib.loads(raw)
                        
                        # Check for Java version requirements (e.g., "[17,)" requires Java 17+)
                        all_deps = toml_data.get("dependencies", {})
                        if isinstance(all_deps, dict):
                            for dep_list in all_deps.values():
                                if isinstance(dep_list, list):
                                    for dep in dep_list:
                                        if isinstance(dep, dict) and dep.get("modId", "").lower() in ["javafml", "fml"]:
                                            java_version_range = dep.get("versionRange", "")
                                            if java_version_range:
                                                import re
                                                java_match = re.search(r'\[(\d+)', java_version_range)
                                                if java_match:
                                                    required_java = int(java_match.group(1))
                                                    if required_java != installed_java_ver:
                                                        java_version_mismatches[fn.name] = required_java
                        
                        for mod_entry in toml_data.get("mods", []):
                            mid = mod_entry.get("modId", "").lower()
                            if mid:
                                installed_mod_ids.setdefault(mid, []).append(fn.name)
                    elif 'fabric.mod.json' in names:
                        fabric_raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                        try:
                            import json
                            fabric_data = json.loads(fabric_raw)
                            mod_id = fabric_data.get("id", "").lower()
                            if mod_id:
                                installed_mod_ids.setdefault(mod_id, []).append(fn.name)
                            
                            # Check Fabric MC version
                            env = fabric_data.get("environment", {})
                            if env and "server" not in env.get("run", []):
                                # Client-only mod
                                quarantine_mod(mods_dir, fn.name, "Fabric client-only mod")
                        except Exception:
                            pass
            except Exception:
                continue
    
    # Handle Java version mismatches
    if java_version_mismatches:
        for mod_file, required_java in java_version_mismatches.items():
            if installed_java_ver > required_java:
                # Can't downgrade Java without breaking other mods - quarantine this mod
                log_event("PREFLIGHT", f"Quarantining {mod_file}: requires Java {required_java} < {installed_java_ver} (downgrade would break other mods)")
                quarantine_mod(mods_dir, mod_file, f"Requires Java {required_java}, have {installed_java_ver} (cannot downgrade)")
            elif installed_java_ver < required_java:
                # Need Java upgrade - may break other mods
                log_event("PREFLIGHT", f"WARNING: {mod_file} requires Java {required_java} > {installed_java_ver} - Java update needed but may break compatibility")
            # If equal, continue (compatible)
    
    # NOTE: Many mods are forward-compatible - skip strict MC version checking
    # The server will crash if there's an actual incompatibility, and crash detection will handle it
    
    log_event("PREFLIGHT", f"Scanning {len(installed_mod_ids)} installed mods for dependencies...")
    
    # Track dependencies with proper categorization
    required_deps: Dict[str, set] = {}  # dep_id -> set of requesting mod files
    optional_deps: Dict[str, set] = {}  # dep_id -> set of requesting mod files
    dependents: Dict[str, List[str]] = {}  # dep_id -> list of mod_ids that depend on it (for confirmation)
    
    for scan_dir in [mods_dir, clientonly_dir]:
        if not scan_dir.exists():
            continue
        for fn in scan_dir.glob("*.jar"):
            try:
                with zipfile.ZipFile(fn, 'r') as zf:
                    names = zf.namelist()
                    toml_file = None
                    mod_id_for_file = None
                    
                    if 'META-INF/neoforge.mods.toml' in names:
                        toml_file = 'META-INF/neoforge.mods.toml'
                    elif 'META-INF/mods.toml' in names:
                        toml_file = 'META-INF/mods.toml'
                    
                    if toml_file:
                        try:
                            import tomllib
                        except ImportError:
                            import tomli as tomllib
                        raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                        toml_data = tomllib.loads(raw)
                        
                        # Get mod ID for this file
                        for mod_entry in toml_data.get("mods", []):
                            mid = mod_entry.get("modId", "").lower()
                            if mid:
                                mod_id_for_file = mid
                                break
                        
                        all_deps = toml_data.get("dependencies", {})
                        if isinstance(all_deps, dict):
                            for dep_parent, dep_list in all_deps.items():
                                if not isinstance(dep_list, list):
                                    continue
                                for dep in dep_list:
                                    if not isinstance(dep, dict):
                                        continue
                                    dep_type = dep.get("type", "required").lower()
                                    dep_mod_id = dep.get("modId", "").lower()
                                    if not dep_mod_id or dep_mod_id in BUILTIN_MODS:
                                        continue
                                    
                                    # Track dependents for confirmation
                                    if mod_id_for_file:
                                        dependents.setdefault(dep_mod_id, []).append(mod_id_for_file)
                                    
                                    if dep_type == "required":
                                        required_deps.setdefault(dep_mod_id, set()).add(fn.name)
                                    else:
                                        optional_deps.setdefault(dep_mod_id, set()).add(fn.name)
                    
                    if 'fabric.mod.json' in names:
                        fabric_raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                        try:
                            import json
                            fabric_data = json.loads(fabric_raw)
                            mod_id_for_file = fabric_data.get("id", "").lower()
                            
                            for dep_id in fabric_data.get("depends", {}).keys():
                                dep_id_lower = dep_id.lower()
                                if dep_id_lower not in BUILTIN_MODS:
                                    if mod_id_for_file:
                                        dependents.setdefault(dep_id_lower, []).append(mod_id_for_file)
                                    required_deps.setdefault(dep_id_lower, set()).add(fn.name)
                        except Exception:
                            pass
            except Exception:
                continue
    
    # Check for optional dependency interop (2+ mods want same optional dep)
    for dep_id, requesters in optional_deps.items():
        if len(requesters) >= 2:
            mods_list = ", ".join(sorted(requesters)[:5])
            log_event("PREFLIGHT", f"[OPTIONAL_INTEROP] {dep_id} wanted by {len(requesters)} mods: {mods_list}")
            result["optional_interop"].append({
                "dep_id": dep_id,
                "count": len(requesters),
                "mods": list(requesters)
            })
    
    # Log dependents for key dependencies (for debugging/verification)
    for dep_id, dependent_mods in dependents.items():
        if len(dependent_mods) >= 2:
            log_event("PREFLIGHT", f"[DEPENDENTS] {dep_id} has {len(dependent_mods)} dependents: {dependent_mods[:5]}")
    
    # Find missing required dependencies
    missing_required: Dict[str, set] = {}
    for dep_id, requesters in required_deps.items():
        if dep_id not in installed_mod_ids:
            missing_required[dep_id] = requesters
    
    # Find missing optional dependencies (optional, but track them)
    missing_optional: Dict[str, set] = {}
    for dep_id, requesters in optional_deps.items():
        if dep_id not in installed_mod_ids:
            missing_optional[dep_id] = requesters
    
    log_event("PREFLIGHT", f"Found {len(missing_required)} missing required deps, {len(missing_optional)} missing optional deps")
    
    # Process missing required dependencies
    if missing_required:
        log_event("PREFLIGHT", f"=== PROCESSING {len(missing_required)} missing deps ===")
        for dep_id, requesters in missing_required.items():
            log_event("PREFLIGHT", f"Processing dep: {dep_id}")
            
            # Skip incompatible dependencies based on loader type
            loader_lower = loader_name.lower()
            is_fabric = loader_lower == "fabric"
            is_neoforge = loader_lower in ["neoforge", "forge"]
            
            # Skip Fabric deps for NeoForge/Forge (but still try others)
            if is_neoforge and (dep_id.startswith("fabric-") or dep_id in ["fabric-api-base", "fabric-resource-loader-v0", "fabric-lifecycle-events-v1"]):
                log_event("PREFLIGHT", f"Skipping {dep_id} (Fabric-only dep, incompatible with NeoForge)")
                continue
            
            # Skip NeoForge deps for Fabric
            if is_fabric and (dep_id.startswith("neoforge") or dep_id in ["neoforge", "forge", "fml", "javafml", "neoforgedatapackextensions"]):
                log_event("PREFLIGHT", f"Skipping {dep_id} (NeoForge-only dep, incompatible with Fabric)")
                continue
            
            # Always fetch the mod - don't skip anything unless it's a library with no dependents
            # We'll note optional/dependents but still fetch
            
            # Use dependents to confirm we're getting the right mod
            dependent_mods = dependents.get(dep_id, [])
            if dependent_mods:
                log_event("PREFLIGHT", f"[CONFIRM] Dep {dep_id} has dependents: {dependent_mods[:3]}")
            
            fetched = _fetch_dependency(dep_id, mc_version, loader_name, mods_dir, dependents=dependent_mods)
            if fetched:
                result["fetched"] += 1
    
    # Return missing deps for debugging
    result["missing_required"] = list(missing_required.keys())
    result["missing_optional"] = list(missing_optional.keys())
    
    # Write cache timestamp for dashboard preflight_status
    import time
    cache_file = CWD / ".preflight_cache"
    try:
        cache_file.write_text(str(time.time()))
    except Exception:
        pass
    
    return result





def _search_curseforge_scraper(dep_name: str, mc_version: str, loader_name: str) -> Optional[str]:
    """Use Playwright to search CurseForge and get the mod slug."""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    _cf_rate_limit()
    
    loader_id = CF_LOADER_IDS.get(loader_name.lower(), 6)
    dep_norm = re.sub(r'[^a-z0-9]', '', dep_name.lower())
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    
    try:
        if STEALTH_AVAILABLE:
            with Stealth().use_sync(sync_playwright()) as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-infobars",
                        "--no-first-run",
                        "--disable-extensions",
                        "--mute-audio",
                    ]
                )
                context = browser.new_context(
                    user_agent=ua,
                    viewport=viewport,
                    locale=locale,
                    color_scheme="dark" if random.random() > 0.5 else "light",
                )
                page = context.new_page()
                
                # Visit homepage first to establish cookies
                page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2.0, 3.5))
                
                search_url = f"https://www.curseforge.com/minecraft/search?search={dep_name}&version={mc_version}&gameVersionTypeId={loader_id}"
                log_event("SCRAPER", f"CurseForge search URL: {search_url}")
                
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(random.uniform(3.0, 5.0))
                    
                    title = page.title()
                    if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking"]):
                        log_event("SCRAPER", "CurseForge: Cloudflare challenge, waiting...")
                        time.sleep(random.uniform(8.0, 15.0))
                        page.wait_for_load_state("networkidle", timeout=45000)
                    
                    cards = page.query_selector_all("div.project-card")
                    if not cards:
                        log_event("SCRAPER", f"CurseForge: no results for '{dep_name}'")
                        context.close()
                        browser.close()
                        return None
                    
                    best_match = None
                    best_score = 0
                    
                    for card in cards[:10]:
                        try:
                            name_el = card.query_selector("a.name span.ellipsis")
                            if not name_el:
                                name_el = card.query_selector("a.name")
                            card_name = name_el.inner_text().strip() if name_el else ""
                            
                            slug_el = card.query_selector("a.overlay-link")
                            href = slug_el.get_attribute("href") if slug_el else ""
                            slug_match = re.search(r'/minecraft/mc-mods/([^/?]+)', href) if href else None
                            card_slug = slug_match.group(1) if slug_match else ""
                            
                            if not card_name or not card_slug:
                                continue
                            
                            card_norm = re.sub(r'[^a-z0-9]', '', card_name.lower())
                            slug_norm = re.sub(r'[^a-z0-9]', '', card_slug.lower())
                            
                            score = 0
                            if dep_norm == card_norm or dep_norm == slug_norm:
                                score = 100
                            elif dep_norm in card_norm or dep_norm in slug_norm:
                                score = 75
                            elif card_norm in dep_norm or slug_norm in dep_norm:
                                score = 50
                            
                            if score > best_score:
                                best_score = score
                                dl_cta = card.query_selector("a.download-cta")
                                dl_href = dl_cta.get_attribute("href") if dl_cta else ""
                                file_match = re.search(r'/download/(\d+)', dl_href) if dl_href else None
                                
                                best_match = {
                                    "name": card_name,
                                    "slug": card_slug,
                                    "file_id": file_match.group(1) if file_match else "",
                                    "download_href": dl_href,
                                }
                        except Exception:
                            continue
                    
                    context.close()
                    browser.close()
                    
                    if best_match and best_score >= 50:
                        log_event("SCRAPER", f"CurseForge found '{best_match['name']}' (score={best_score}) for dep '{dep_name}'")
                        return best_match["slug"]
                    else:
                        log_event("SCRAPER", f"CurseForge: no good match for '{dep_name}' (best score={best_score})")
                        
                except Exception as e:
                    log_event("SCRAPER", f"CurseForge search error: {e}")
                
                try:
                    context.close()
                    browser.close()
                except:
                    pass
                
        else:
            # Fallback without stealth
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            
            context = browser.new_context(user_agent=ua, viewport=viewport, locale=locale)
            page = context.new_page()
            
            page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.0, 3.0))
            
            search_url = f"https://www.curseforge.com/minecraft/search?search={dep_name}&version={mc_version}&gameVersionTypeId={loader_id}"
            
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(random.uniform(3.0, 5.0))
                
                title = page.title()
                if any(kw in title.lower() for kw in ["just a moment", "attention required"]):
                    time.sleep(random.uniform(8.0, 12.0))
                
                cards = page.query_selector_all("div.project-card")
                if not cards:
                    context.close()
                    browser.close()
                    playwright.stop()
                    return None
                
                for card in cards[:5]:
                    try:
                        name_el = card.query_selector("a.name span.ellipsis")
                        if not name_el:
                            name_el = card.query_selector("a.name")
                        card_name = name_el.inner_text().strip() if name_el else ""
                        
                        slug_el = card.query_selector("a.overlay-link")
                        href = slug_el.get_attribute("href") if slug_el else ""
                        slug_match = re.search(r'/minecraft/mc-mods/([^/?]+)', href) if href else None
                        card_slug = slug_match.group(1) if slug_match else ""
                        
                        if not card_name or not card_slug:
                            continue
                        
                        card_norm = re.sub(r'[^a-z0-9]', '', card_name.lower())
                        slug_norm = re.sub(r'[^a-z0-9]', '', card_slug.lower())
                        
                        if dep_norm == card_norm or dep_norm == slug_norm:
                            context.close()
                            browser.close()
                            playwright.stop()
                            return card_slug
                            
                    except Exception:
                        continue
                
                context.close()
                browser.close()
                playwright.stop()
                
            except Exception as e:
                log_event("SCRAPER", f"CurseForge search error: {e}")
            
            try:
                context.close()
                browser.close()
            except Exception:
                pass
            playwright.stop()
            
    except Exception as e:
        log_event("SCRAPER", f"CurseForge scraper failed: {e}")
    
    return None


def _search_modrinth_api(mod_name: str, mc_version: str, loader: str, dependents: Optional[List[str]] = None) -> Optional[str]:
    """Search Modrinth API using the mod_name directly.
    
    Just use mod_name as-is for search query. No dashifying or splitting.
    """
    from urllib.parse import quote as url_quote
    
    # Simple search - use mod_name directly
    try:
        url = f"https://api.modrinth.com/v2/search?query={url_quote(mod_name)}&limit=10"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            hits = data.get("hits", [])
            
            if hits:
                # Just return the first hit's slug
                slug = hits[0].get("slug")
                log_event("PREFLIGHT", f"Found {mod_name} as '{slug}' on Modrinth")
                return slug
    except Exception as e:
        log_event("PREFLIGHT", f"Modrinth search failed for {mod_name}: {e}")
    
    return None


def _lookup_slug_from_cache(mod_id: str, mc_version: str) -> Optional[str]:
    """Look up slug from curator cache using mod_id or its dependencies.
    
    Also populates a global dep_slug_map for future lookups.
    """
    global _dep_slug_map
    
    # Check if we already mapped this mod_id
    if mod_id in _dep_slug_map:
        return _dep_slug_map[mod_id]
    
    mod_id_norm = mod_id.lower().replace('-', '').replace('_', '')
    
    # Check Modrinth curator cache
    mr_cache = CWD / f"curator_cache_{mc_version}_neoforge.json"
    if mr_cache.exists():
        try:
            data = json.loads(mr_cache.read_text())
            for proj_id, proj in data.items():
                # Match by id or normalized name
                proj_id_norm = proj_id.lower().replace('-', '').replace('_', '')
                proj_name_norm = proj.get("name", "").lower().replace('-', '').replace('_', '').replace(' ', '')
                if proj_id_norm == mod_id_norm or proj_name_norm == mod_id_norm:
                    slug = proj.get("slug") or proj.get("cf_slug")
                    _dep_slug_map[mod_id] = slug
                    
                    # Also cache all deps from this mod for future lookups
                    for dep in proj.get("cf_deps_required", []) + proj.get("cf_deps_optional", []):
                        dep_name = dep.get("name", "").lower().replace(' ', '').replace('-', '').replace('_', '')
                        dep_slug = dep.get("slug", "")
                        if dep_slug and dep_name:
                            _dep_slug_map[dep_name] = dep_slug
                    
                    return slug
        except Exception:
            pass
    
    # Check CurseForge cache
    cf_cache = CWD / f"curseforge_cache_{mc_version}_neoforge.json"
    if cf_cache.exists():
        try:
            data = json.loads(cf_cache.read_text())
            for proj_id, proj in data.items():
                proj_name_norm = proj.get("name", "").lower().replace('-', '').replace('_', '').replace(' ', '')
                if proj_name_norm == mod_id_norm:
                    slug = proj.get("slug")
                    _dep_slug_map[mod_id] = slug
                    return slug
        except Exception:
            pass
    
    return None


# Global map for mod_id -> slug
_dep_slug_map: Dict[str, str] = {}


def _modrinth_direct_lookup(mod_name: str, mc_version: str, loader: str) -> Optional[str]:
    """Try curator cache first, then direct Modrinth lookup."""
    from urllib.parse import quote as url_quote
    
    # 1. Try curator cache first - we already scraped this
    slug = _lookup_slug_from_cache(mod_name, mc_version)
    if slug:
        return slug
    
    # 2. Try direct project lookup
    try:
        url = f"https://api.modrinth.com/v2/project/{url_quote(mod_name)}"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            proj = json.loads(resp.read().decode())
        if proj.get("id"):
            return proj.get("slug")
    except Exception:
        pass
    
    # Fallback: search by mod_name as query
    try:
        url = f"https://api.modrinth.com/v2/search?query={url_quote(mod_name)}&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        hits = data.get("hits", [])
        if hits:
            return hits[0].get("slug")
    except Exception:
        pass
    
    return None


def _fetch_dependency(dep_id: str, mc_version: str, loader_name: str, mods_dir: Path, dependents: Optional[List[str]] = None) -> bool:
    """Fetch a missing dependency.
    
    Flow:
    1. Try CurseForge scraper FIRST (better coverage)
    2. Try Modrinth API search
    3. Try ferium as last resort
    """
    if dependents is None:
        dependents = []
    
    if dependents:
        log_event("PREFLIGHT", f"[DEPENDENTS] Searching for {dep_id}, confirmed by: {dependents[:3]}")
    
    # 1. Try CurseForge scraper FIRST
    log_event("PREFLIGHT", f"Checking CurseForge for {dep_id}...")
    cf_slug = _search_curseforge_scraper(dep_id, mc_version, loader_name)
    
    if cf_slug:
        log_event("PREFLIGHT", f"Found {dep_id} as '{cf_slug}' on CurseForge, downloading...")
        if _download_from_curseforge_by_slug(cf_slug, mods_dir, mc_version, loader_name):
            log_event("PREFLIGHT", f"Downloaded {cf_slug} from CurseForge")
            return True
    
    # 2. Try Modrinth search
    log_event("PREFLIGHT", f"Checking Modrinth for {dep_id}...")
    slug = _search_modrinth_api(dep_id, mc_version, loader_name)
    
    if slug:
        log_event("PREFLIGHT", f"Found {dep_id} as '{slug}' on Modrinth, downloading...")
        if _download_from_modrinth(slug, mods_dir, mc_version, loader_name):
            log_event("PREFLIGHT", f"Downloaded {slug} from Modrinth")
            return True
    
    # 3. Try ferium as fallback
    ferium_bin = CWD / ".local" / "bin" / "ferium"
    if ferium_bin.exists():
        log_event("PREFLIGHT", f"Trying ferium add for {dep_id}...")
        
        result = subprocess.run(
            [str(ferium_bin), "add", dep_id],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0 or "already" in result.stderr.lower():
            log_event("PREFLIGHT", f"Added {dep_id} via ferium (may need upgrade)")
            # Trigger ferium upgrade to actually download
            subprocess.run(
                [str(ferium_bin), "upgrade"],
                capture_output=True,
                text=True,
                timeout=120
            )
            return True
    
    # Try CurseForge scraper
    cf_slug = _search_curseforge_scraper(dep_id, mc_version, loader_name)
    if cf_slug:
        log_event("PREFLIGHT", f"Found {dep_id} as {cf_slug} on CurseForge...")
        if _download_from_curseforge_by_slug(cf_slug, mods_dir, mc_version, loader_name):
            return True
    
    log_event("PREFLIGHT", f"Could not fetch dependency: {dep_id}")
    return False


def _download_from_modrinth(mod_slug: str, mods_dir: Path, mc_version: str, loader: str) -> bool:
    """Download mod directly from Modrinth API."""
    import urllib.request
    import urllib.parse
    
    try:
        # First get project ID
        url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(mod_slug)}"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        
        with urllib.request.urlopen(req, timeout=15) as response:
            project = json.loads(response.read().decode())
            mod_id = project.get("id")
            mod_name = project.get("title", mod_slug)
        
        if not mod_id:
            return False
        
        # Get versions
        url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
        
        with urllib.request.urlopen(req, timeout=30) as response:
            all_versions = json.loads(response.read().decode())
        
        loader_lower = loader.lower()
        
        # Find matching version
        matching_version = None
        for v in all_versions:
            if mc_version in v.get("game_versions", []) and loader_lower in [l.lower() for l in v.get("loaders", [])]:
                matching_version = v
                break
        
        if not matching_version:
            return False
        
        files = matching_version.get("files", [])
        if not files:
            return False
        
        # Get primary file
        file_info = files[0]
        for f in files:
            if f.get("primary"):
                file_info = f
                break
        
        download_url = file_info.get("url")
        file_name = file_info.get("filename")
        
        if not download_url or not file_name:
            return False
        
        # Check if already exists
        file_path = mods_dir / file_name
        if file_path.exists() and file_path.stat().st_size > 0:
            return True
        
        # Download
        log_event("PREFLIGHT", f"Downloading {file_name} from Modrinth...")
        urllib.request.urlretrieve(download_url, file_path)
        
        return file_path.exists() and file_path.stat().st_size > 0
        
    except Exception as e:
        log_event("PREFLIGHT", f"Modrinth download failed for {mod_slug}: {e}")
        return False


def _download_from_curseforge_by_slug(slug: str, mods_dir: Path, mc_version: str, loader: str) -> bool:
    """Download mod from CurseForge by slug."""
    # This would require the CurseForge scraper to get the download URL
    # For now, return False and let the scraper handle it separately
    return False


def quarantine_mod(mods_dir: Path, mod_id_or_file: str, reason: str) -> Optional[Path]:
    """Move a mod to quarantine directory."""
    quarantine_dir = mods_dir / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    
    for search_dir in [mods_dir, mods_dir / "clientonly"]:
        if not search_dir.exists():
            continue
        for fn in search_dir.glob("*.jar"):
            if mod_id_or_file.lower() in fn.name.lower():
                dest = quarantine_dir / fn.name
                try:
                    import shutil
                    shutil.move(str(fn), str(dest))
                    reason_file = quarantine_dir / f"{fn.name}.reason.txt"
                    with open(reason_file, 'w') as f:
                        f.write(reason)
                    log_event("QUARANTINE", f"Quarantined {fn.name}: {reason}")
                    return dest
                except Exception as e:
                    log_event("QUARANTINE", f"Failed to quarantine {fn.name}: {e}")
                    return None
    
    log_event("QUARANTINE", f"Could not find mod matching '{mod_id_or_file}' to quarantine")
    return None


def load_crash_history() -> Dict[str, int]:
    """Load crash history from persistent file."""
    history_file = CWD / ".crash_history.json"
    if history_file.exists():
        try:
            with open(history_file) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_crash_history(history: Dict[str, int]) -> None:
    """Save crash history to persistent file."""
    history_file = CWD / ".crash_history.json"
    try:
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass


def resolve_dependency_tree(
    mod_ids: List[str],
    mc_version: str,
    loader_name: str,
    mods_dir: Path,
) -> Dict[str, Any]:
    """Resolve the full dependency tree for mods using CurseForge scraper.
    
    This uses the CurseForge relationships API via Playwright to get:
    - Required dependencies
    - Optional dependencies
    - Interop/embedded libraries
    - Dependents (mods that depend on these)
    
    Args:
        mod_ids: List of mod IDs or slugs to resolve
        mc_version: Minecraft version
        loader_name: Loader name
        mods_dir: Directory to download missing mods to
        
    Returns:
        Dict with:
        - 'required': List of required dependency slugs to fetch
        - 'optional': List of optional dependency slugs (for info)
        - 'interops': List of interop/library slugs (for info)
        - 'dependents': Dict of mod -> list of dependents
        - 'all_resolved': Dict of resolved mod info
        - 'fetched': Count of newly fetched mods
    """
    from .curseforge import fetch_full_dependency_tree, get_mod_info_by_id_or_slug
    
    result: Dict[str, Any] = {
        "required": [],
        "optional": [],
        "interops": [],
        "dependents": {},
        "all_resolved": {},
        "fetched": 0,
    }
    
    if not mod_ids:
        return result
    
    log_event("DEPTREE", f"Resolving dependency tree for {len(mod_ids)} mods: {mod_ids}")
    
    tree = fetch_full_dependency_tree(
        initial_mods=mod_ids,
        mc_version=mc_version,
        loader_name=loader_name,
        max_depth=8,
    )
    
    result["required"] = tree.get("required", [])
    result["optional"] = tree.get("optional", [])
    result["interops"] = tree.get("interops", [])
    result["dependents"] = tree.get("dependents", {})
    result["all_resolved"] = tree.get("all_mods", {})
    
    installed_mod_ids: Dict[str, str] = {}
    
    for fn in mods_dir.glob("*.jar"):
        try:
            with zipfile.ZipFile(fn, 'r') as zf:
                names = zf.namelist()
                toml_file = None
                if 'META-INF/neoforge.mods.toml' in names:
                    toml_file = 'META-INF/neoforge.mods.toml'
                elif 'META-INF/mods.toml' in names:
                    toml_file = 'META-INF/mods.toml'
                
                if toml_file:
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib
                    raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                    toml_data = tomllib.loads(raw)
                    for mod_entry in toml_data.get("mods", []):
                        mid = mod_entry.get("modId", "").lower()
                        if mid:
                            installed_mod_ids[mid] = fn.name
                elif 'fabric.mod.json' in names:
                    fabric_raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                    try:
                        import json
                        fabric_data = json.loads(fabric_raw)
                        mod_id = fabric_data.get("id", "").lower()
                        if mod_id:
                            installed_mod_ids[mod_id] = fn.name
                    except Exception:
                        pass
        except Exception:
            continue
    
    missing_required = []
    for dep_slug in result["required"]:
        dep_norm = re.sub(r'[^a-z0-9]', '', dep_slug.lower())
        if dep_norm not in installed_mod_ids:
            missing_required.append(dep_slug)
    
    if missing_required:
        log_event("DEPTREE", f"Missing required dependencies: {missing_required}")
        for dep_slug in missing_required:
            fetched = _fetch_dependency(dep_slug, mc_version, loader_name, mods_dir)
            if fetched:
                result["fetched"] += 1
    
    if result["optional"]:
        log_event("DEPTREE", f"Optional dependencies available: {result['optional']}")
    
    if result["interops"]:
        log_event("DEPTREE", f"Interop/embedded libraries: {result['interops']}")
    
    return result


def check_and_fix_dependency_chain(
    mod_id: str,
    mc_version: str,
    loader_name: str,
    mods_dir: Path,
) -> Dict[str, Any]:
    """Check a single mod's dependencies and fetch missing ones.
    
    This is useful when you know a mod ID (from a crash log) but need to
    find its CurseForge slug and fetch all its dependencies.
    
    Args:
        mod_id: The mod ID from crash log (e.g., "supermartijn642corelib")
        mc_version: Minecraft version
        loader_name: Loader name
        mods_dir: Directory for mods
        
    Returns:
        Dict with resolution results
    """
    from .curseforge import get_mod_info_by_id_or_slug, get_mod_relationships
    
    result: Dict[str, Any] = {
        "found": False,
        "slug": None,
        "cf_mod_id": None,
        "dependencies": [],
        "optional": [],
        "interops": [],
        "dependents": [],
        "fetched": [],
        "failed": [],
    }
    
    mod_info = get_mod_info_by_id_or_slug(mod_id, mc_version, loader_name)
    
    if not mod_info:
        log_event("DEPTREE", f"Could not find mod: {mod_id}")
        return result
    
    result["found"] = True
    result["slug"] = mod_info["slug"]
    result["cf_mod_id"] = mod_info.get("cf_mod_id", "")
    
    log_event("DEPTREE", f"Found {mod_id} as {result['slug']} (CF ID: {result['cf_mod_id']})")
    
    relationships = get_mod_relationships(result["slug"], mc_version, loader_name)
    
    result["dependencies"] = [d["slug"] for d in relationships.get("dependencies", [])]
    result["optional"] = [d["slug"] for d in relationships.get("dependencies", []) if d.get("is_optional")]
    result["interops"] = [i["slug"] for i in relationships.get("interops", [])]
    result["dependents"] = [d["slug"] for d in relationships.get("dependents", [])]
    
    installed_mod_ids: Dict[str, str] = {}
    for fn in mods_dir.glob("*.jar"):
        try:
            with zipfile.ZipFile(fn, 'r') as zf:
                names = zf.namelist()
                if 'META-INF/neoforge.mods.toml' in names or 'META-INF/mods.toml' in names:
                    toml_file = 'META-INF/neoforge.mods.toml' if 'META-INF/neoforge.mods.toml' in names else 'META-INF/mods.toml'
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib
                    raw = zf.read(toml_file).decode('utf-8', errors='ignore')
                    toml_data = tomllib.loads(raw)
                    for mod_entry in toml_data.get("mods", []):
                        mid = mod_entry.get("modId", "").lower()
                        if mid:
                            installed_mod_ids[mid] = fn.name
                elif 'fabric.mod.json' in names:
                    fabric_raw = zf.read('fabric.mod.json').decode('utf-8', errors='ignore')
                    try:
                        import json
                        fabric_data = json.loads(fabric_raw)
                        mod_id_key = fabric_data.get("id", "").lower()
                        if mod_id_key:
                            installed_mod_ids[mod_id_key] = fn.name
                    except Exception:
                        pass
        except Exception:
            continue
    
    all_deps_to_fetch = list(result["dependencies"])
    all_deps_to_fetch.extend(result["optional"])
    
    for dep_slug in all_deps_to_fetch:
        dep_norm = re.sub(r'[^a-z0-9]', '', dep_slug.lower())
        
        if dep_norm in installed_mod_ids:
            log_event("DEPTREE", f"  Dependency already installed: {dep_slug}")
            continue
        
        log_event("DEPTREE", f"  Fetching dependency: {dep_slug}")
        
        fetched = _fetch_dependency(dep_slug, mc_version, loader_name, mods_dir)
        
        if fetched:
            result["fetched"].append(dep_slug)
            installed_mod_ids[dep_norm] = f"{dep_slug}.jar"
        else:
            result["failed"].append(dep_slug)
    
    return result


__all__ = [
    "preflight_dep_check",
    "quarantine_mod",
    "load_crash_history",
    "save_crash_history",
    "resolve_dependency_tree",
    "check_and_fix_dependency_chain",
]
