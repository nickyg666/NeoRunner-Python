"""CurseForge scraping for mod downloads using Playwright.

This module provides functionality to search and download mods from CurseForge
when the official API is not available (Cloudflare protection).
"""

from __future__ import annotations

import os
import re
import time
import random
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from .constants import CWD

log = logging.getLogger(__name__)

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
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

CF_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

CF_LOCALES = ["en-US", "en-GB", "en-CA"]

CF_LOADER_IDS = {
    "neoforge": 6,
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
}

_last_cf_request_time = 0


def _cf_rate_limit() -> None:
    """Random delay between CurseForge requests to appear human-like."""
    global _last_cf_request_time
    now = time.time()
    elapsed = now - _last_cf_request_time
    delay = random.uniform(1.5, 5.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_cf_request_time = time.time()


def _get_cf_headers() -> Dict[str, str]:
    """Get randomized headers for CurseForge requests."""
    return {
        "User-Agent": random.choice(CF_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
    }


def search_curseforge(
    dep_name: str,
    mc_version: str,
    loader_name: str,
    mods_dir: Path,
) -> bool:
    """Search CurseForge live for a dependency and download it.
    
    Uses Playwright stealth browser to search CurseForge, find a matching mod,
    and download the appropriate file for the given MC version + loader.
    
    Args:
        dep_name: Name of the dependency to search for
        mc_version: Minecraft version (e.g., "1.21.11")
        loader_name: Loader name (neoforge, forge, fabric)
        mods_dir: Directory to download mods to
        
    Returns:
        True if successfully downloaded, False otherwise
    """
    if not PLAYWRIGHT_AVAILABLE:
        log.warning("Playwright not available - cannot search CurseForge")
        return False
    
    _cf_rate_limit()
    
    loader_id = CF_LOADER_IDS.get(loader_name.lower(), 6)
    dep_norm = re.sub(r'[^a-z0-9]', '', dep_name.lower())
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--disable-extensions",
            ]
        )
        
        context = browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale=locale,
        )
        page = context.new_page()
        
        if STEALTH_AVAILABLE:
            try:
                Stealth(page)
            except Exception:
                pass
        
        page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(2.0, 3.5))
        
        search_url = f"https://www.curseforge.com/minecraft/search?search={dep_name}&version={mc_version}&gameVersionTypeId={loader_id}"
        log.info(f"CurseForge search URL: {search_url}")
        
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(3.0, 5.0))
            
            title = page.title()
            if any(kw in title.lower() for kw in ["just a moment", "attention required", "checking"]):
                log.info("CurseForge: Cloudflare challenge, waiting...")
                time.sleep(random.uniform(8.0, 15.0))
                page.wait_for_load_state("networkidle", timeout=45000)
            
            cards = page.query_selector_all("div.project-card")
            if not cards:
                log.info(f"CurseForge: no results for '{dep_name}'")
                context.close()
                browser.close()
                playwright.stop()
                return False
            
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
            playwright.stop()
            
            if best_match and best_score >= 50:
                log.info(f"CurseForge found '{best_match['name']}' (score={best_score}) for dep '{dep_name}'")
                mod_info = {
                    "name": best_match["name"],
                    "slug": best_match["slug"],
                    "file_id": best_match["file_id"],
                }
                result = _download_from_curseforge(mod_info, mods_dir, mc_version, loader_name)
                if result:
                    log.info(f"Downloaded {best_match['name']} from CurseForge")
                    return True
            else:
                log.info(f"CurseForge: no good match for '{dep_name}' (best score={best_score})")
                
        except Exception as e:
            log.error(f"CurseForge search error for '{dep_name}': {e}")
        
        try:
            context.close()
            browser.close()
        except Exception:
            pass
        playwright.stop()
        
    except Exception as e:
        log.error(f"CurseForge search failed: {e}")
        try:
            playwright.stop()
        except Exception:
            pass
    
    return False


def _download_from_curseforge(
    mod_info: Dict[str, Any],
    mods_dir: Path,
    mc_version: str,
    loader: str,
) -> bool:
    """Download a mod from CurseForge.
    
    Args:
        mod_info: Dict with 'name', 'slug', 'file_id'
        mods_dir: Directory to download to
        mc_version: Minecraft version
        loader: Loader name
        
    Returns:
        True if downloaded successfully
    """
    if not mod_info.get("file_id"):
        return False
    
    download_url = f"https://www.curseforge.com/minecraft/mc-mods/{mod_info['slug']}/download/{mod_info['file_id']}"
    
    try:
        from ..mods import download_file
        return download_file(download_url, mods_dir, mod_info["name"])
    except Exception as e:
        log.error(f"Failed to download {mod_info['name']}: {e}")
        return False


def is_available() -> bool:
    """Check if CurseForge scraping is available."""
    return PLAYWRIGHT_AVAILABLE


def get_mod_info_by_id_or_slug(
    mod_id_or_slug: str,
    mc_version: str,
    loader_name: str,
) -> Optional[Dict[str, Any]]:
    """Resolve a mod ID or slug to CurseForge mod info.
    
    Args:
        mod_id_or_slug: The mod ID (e.g., "supermartijn642corelib") or slug (e.g., "supermartijn642-config-lib")
        mc_version: Minecraft version
        loader_name: Loader name (neoforge, forge, fabric)
        
    Returns:
        Dict with 'mod_id', 'slug', 'name', 'cf_mod_id' or None if not found
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    _cf_rate_limit()
    
    loader_id = CF_LOADER_IDS.get(loader_name.lower(), 6)
    search_term = mod_id_or_slug.replace("-", " ").replace("_", " ")
    dep_norm = re.sub(r'[^a-z0-9]', '', mod_id_or_slug.lower())
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--disable-extensions",
            ]
        )
        
        context = browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale=locale,
        )
        page = context.new_page()
        
        if STEALTH_AVAILABLE:
            try:
                Stealth(page)
            except Exception:
                pass
        
        page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.5, 2.5))
        
        search_url = f"https://www.curseforge.com/minecraft/search?search={search_term}&version={mc_version}&gameVersionTypeId={loader_id}"
        
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(2.5, 4.0))
            
            if any(kw in page.title().lower() for kw in ["just a moment", "attention required", "checking"]):
                log.info("CurseForge: Cloudflare challenge, waiting...")
                time.sleep(random.uniform(8.0, 15.0))
                page.wait_for_load_state("networkidle", timeout=45000)
            
            cards = page.query_selector_all("div.project-card")
            if not cards:
                context.close()
                browser.close()
                playwright.stop()
                return None
            
            for card in cards[:8]:
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
                    
                    if score >= 50:
                        cf_mod_id_match = re.search(r'/minecraft/mc-mods/[^/]+-(\d+)', href) if href else None
                        cf_mod_id = cf_mod_id_match.group(1) if cf_mod_id_match else ""
                        
                        if not cf_mod_id:
                            cf_mod_id = _extract_mod_id_from_page(page, card_slug)
                        
                        context.close()
                        browser.close()
                        playwright.stop()
                        
                        return {
                            "mod_id": mod_id_or_slug.lower(),
                            "slug": card_slug,
                            "name": card_name,
                            "cf_mod_id": cf_mod_id,
                        }
                except Exception:
                    continue
            
            context.close()
            browser.close()
            playwright.stop()
            
        except Exception as e:
            log.error(f"CurseForge search error for '{mod_id_or_slug}': {e}")
        
        try:
            context.close()
            browser.close()
        except Exception:
            pass
        playwright.stop()
        
    except Exception as e:
        log.error(f"CurseForge mod info lookup failed: {e}")
        try:
            playwright.stop()
        except Exception:
            pass
    
    return None


def _extract_mod_id_from_page(page, slug: str) -> str:
    """Extract the CurseForge mod ID from the mod's page."""
    try:
        mod_page_url = f"https://www.curseforge.com/minecraft/mc-mods/{slug}"
        page.goto(mod_page_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(random.uniform(1.5, 2.5))
        
        page_content = page.content()
        cf_id_match = re.search(r'"modId"\s*:\s*(\d+)', page_content)
        if cf_id_match:
            return cf_id_match.group(1)
        
        data_attr_match = re.search(r'data-mod-id="(\d+)"', page_content)
        if data_attr_match:
            return data_attr_match.group(1)
            
    except Exception as e:
        log.debug(f"Failed to extract mod ID from page: {e}")
    
    return ""


def get_mod_relationships(
    mod_slug: str,
    mc_version: str,
    loader_name: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Get all relationships (dependencies, dependents, interop) for a mod.
    
    Args:
        mod_slug: The CurseForge slug (e.g., "supermartijn642-config-lib")
        mc_version: Minecraft version
        loader_name: Loader name
        
    Returns:
        Dict with 'dependencies', 'dependents', 'interops' - each a list of mod info dicts
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {"dependencies": [], "dependents": [], "interops": []}
    
    _cf_rate_limit()
    
    ua = random.choice(CF_USER_AGENTS)
    viewport = random.choice(CF_VIEWPORTS)
    locale = random.choice(CF_LOCALES)
    
    result = {
        "dependencies": [],
        "dependents": [],
        "interops": [],
    }
    
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--disable-extensions",
            ]
        )
        
        context = browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale=locale,
        )
        page = context.new_page()
        
        if STEALTH_AVAILABLE:
            try:
                Stealth(page)
            except Exception:
                pass
        
        page.goto("https://www.curseforge.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.5, 2.5))
        
        relationships_url = f"https://www.curseforge.com/minecraft/mc-mods/{mod_slug}/relations"
        
        try:
            page.goto(relationships_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(2.5, 4.0))
            
            if any(kw in page.title().lower() for kw in ["just a moment", "attention required"]):
                log.info("CurseForge: Cloudflare challenge on relationships page")
                time.sleep(random.uniform(8.0, 15.0))
                page.wait_for_load_state("networkidle", timeout=45000)
            
            result["dependencies"] = _scrape_relationship_cards(page, "dependencies")
            result["dependents"] = _scrape_relationship_cards(page, "dependents")
            result["interops"] = _scrape_relationship_cards(page, "embeddedlibraries")
            
        except Exception as e:
            log.error(f"Error fetching relationships for {mod_slug}: {e}")
        
        try:
            context.close()
            browser.close()
        except Exception:
            pass
        playwright.stop()
        
    except Exception as e:
        log.error(f"CurseForge relationships lookup failed: {e}")
        try:
            playwright.stop()
        except Exception:
            pass
    
    return result


def _scrape_relationship_cards(page, relationship_type: str) -> List[Dict[str, Any]]:
    """Scrape relationship cards from the relationships page.
    
    Args:
        page: Playwright page object
        relationship_type: 'dependencies', 'dependents', or 'embeddedlibraries'
        
    Returns:
        List of mod info dicts
    """
    mods = []
    
    section_selectors = {
        "dependencies": ["section.dependencies", "div.dependencies-section", "div.relations-dependencies"],
        "dependents": ["section.dependents", "div.dependents-section", "div.relations-dependents"],
        "embeddedlibraries": ["section.embedded-libraries", "div.embeddedlibraries-section", "div.relations-embedded"],
    }
    
    selectors = section_selectors.get(relationship_type, [])
    
    cards = []
    for sel in selectors:
        try:
            section = page.query_selector(sel)
            if section:
                cards = section.query_selector_all("a.project-card")
                if cards:
                    break
        except Exception:
            continue
    
    if not cards:
        cards = page.query_selector_all("a.project-card")[:20]
    
    for card in cards:
        try:
            href = card.get_attribute("href") or ""
            slug_match = re.search(r'/minecraft/mc-mods/([^/?]+)', href)
            if not slug_match:
                continue
            
            slug = slug_match.group(1)
            
            title_el = card.query_selector("span.ellipsis") or card.query_selector("span") or card.query_selector("div")
            name = title_el.inner_text().strip() if title_el else slug
            
            type_badge = card.query_selector("span.badge") or card.query_selector("span.optional-badge")
            is_optional = type_badge and "optional" in type_badge.inner_text().lower()
            
            mods.append({
                "slug": slug,
                "name": name,
                "is_optional": is_optional,
                "relationship_type": relationship_type,
            })
        except Exception:
            continue
    
    return mods


def fetch_full_dependency_tree(
    initial_mods: List[str],
    mc_version: str,
    loader_name: str,
    visited: Optional[set] = None,
    depth: int = 0,
    max_depth: int = 10,
) -> Dict[str, Any]:
    """Fetch the full dependency tree for a list of mods.
    
    Recursively resolves all dependencies (and their dependencies) to build
    a complete dependency tree. Also tracks dependents for reference.
    
    Args:
        initial_mods: List of mod IDs or slugs to start with
        mc_version: Minecraft version
        loader_name: Loader name
        visited: Set of already-visited mod slugs (for recursion)
        depth: Current recursion depth
        max_depth: Maximum recursion depth
        
    Returns:
        Dict with:
        - 'all_mods': Dict of all resolved mods (slug -> mod info)
        - 'required': List of required dependency slugs
        - 'optional': List of optional dependency slugs
        - 'interops': List of interop/library slugs
        - 'dependents': Dict of mod -> list of dependents
    """
    if visited is None:
        visited = set()
    
    if depth >= max_depth:
        log.warning(f"Max dependency depth ({max_depth}) reached")
        return {"all_mods": {}, "required": [], "optional": [], "interops": [], "dependents": {}}
    
    all_mods: Dict[str, Dict[str, Any]] = {}
    required: List[str] = []
    optional: List[str] = []
    interops: List[str] = []
    dependents: Dict[str, List[str]] = {}
    
    mods_to_process = list(initial_mods)
    
    while mods_to_process:
        mod_id_or_slug = mods_to_process.pop(0)
        
        mod_norm = re.sub(r'[^a-z0-9]', '', mod_id_or_slug.lower())
        if mod_norm in visited:
            continue
        visited.add(mod_norm)
        
        log.info(f"Resolving dependencies for: {mod_id_or_slug} (depth={depth})")
        
        mod_info = get_mod_info_by_id_or_slug(mod_id_or_slug, mc_version, loader_name)
        
        if not mod_info:
            log.warning(f"Could not find mod: {mod_id_or_slug}")
            continue
        
        slug = mod_info["slug"]
        slug_norm = re.sub(r'[^a-z0-9]', '', slug.lower())
        
        if slug_norm in all_mods:
            continue
        
        all_mods[slug_norm] = {
            "slug": slug,
            "name": mod_info.get("name", slug),
            "cf_mod_id": mod_info.get("cf_mod_id", ""),
            "resolved_from": mod_id_or_slug,
            "depth": depth,
        }
        
        relationships = get_mod_relationships(slug, mc_version, loader_name)
        
        for dep in relationships.get("dependencies", []):
            dep_slug = dep.get("slug", "")
            dep_norm = re.sub(r'[^a-z0-9]', '', dep_slug.lower())
            
            if dep_norm and dep_norm not in visited:
                if dep.get("is_optional"):
                    optional.append(dep_slug)
                else:
                    required.append(dep_slug)
                    mods_to_process.append(dep_slug)
            
            if dep_slug:
                dependents.setdefault(dep_slug, []).append(slug)
        
        for interop in relationships.get("interops", []):
            interop_slug = interop.get("slug", "")
            if interop_slug and interop_slug not in interops:
                interops.append(interop_slug)
        
        for dep in relationships.get("dependents", []):
            dep_slug = dep.get("slug", "")
            if dep_slug:
                dependents.setdefault(slug, []).append(dep_slug)
    
    return {
        "all_mods": all_mods,
        "required": required,
        "optional": optional,
        "interops": interops,
        "dependents": dependents,
    }


__all__ = [
    "search_curseforge",
    "is_available",
    "PLAYWRIGHT_AVAILABLE",
    "get_mod_info_by_id_or_slug",
    "get_mod_relationships",
    "fetch_full_dependency_tree",
]
