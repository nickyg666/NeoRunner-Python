"""Version management for NeoRunner - dynamic Minecraft version fetching."""

import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MC_VERSION = "1.21.11"

CACHE_DIR = Path(__file__).parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

VERSIONS_CACHE = CACHE_DIR / "mc_versions.json"


def _is_valid_release_version(ver: str) -> bool:
    """True if *ver* looks like a real Minecraft release (1.x.y), not a snapshot.

    Snapshot IDs use the ``26.x`` or ``26w14a`` format; release IDs are
    ``1.21.2``, ``1.20.1``, etc. Reject anything that doesn't start with
    ``1.`` or doesn't match the dotted-decimal pattern.
    """
    if not ver or not isinstance(ver, str):
        return False
    if not ver.startswith("1."):
        return False
    parts = ver.split(".")
    if len(parts) < 2 or len(parts) > 3:
        return False
    for p in parts:
        if not p.isdigit():
            return False
    return True


def get_latest_minecraft_version(force_refresh: bool = False) -> str:
    """Fetch latest Minecraft RELEASE version from Mojang.

    Returns the latest stable release version (e.g. ``1.21.2``), NEVER a
    snapshot ID like ``26.2`` or ``26w14a``. The Mojang manifest marks each
    version with a ``type`` field; only ``release`` types are accepted.
    """
    if not force_refresh and VERSIONS_CACHE.exists():
        try:
            import time
            age = time.time() - VERSIONS_CACHE.stat().st_mtime
            if age < 3600:
                data = json.loads(VERSIONS_CACHE.read_text())
                cached = data.get("latest_release", DEFAULT_MC_VERSION)
                if _is_valid_release_version(cached):
                    return cached
        except Exception:
            pass

    latest = DEFAULT_MC_VERSION

    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

            for v in data.get("versions", []):
                vid = v.get("id", "")
                if v.get("type") == "release" and _is_valid_release_version(vid):
                    latest = vid
                    break

            cache_data = {
                "latest_release": latest,
                "versions": [v["id"] for v in data.get("versions", [])],
            }
            VERSIONS_CACHE.write_text(json.dumps(cache_data, indent=2))

            return latest
    except Exception as e:
        logger.warning(f"Failed to fetch latest MC version: {e}")
        return DEFAULT_MC_VERSION


def get_all_minecraft_versions(force_refresh: bool = False) -> list[str]:
    """Return every Minecraft version ID from the Mojang manifest."""
    if not force_refresh and VERSIONS_CACHE.exists():
        try:
            import time
            age = time.time() - VERSIONS_CACHE.stat().st_mtime
            if age < 3600:
                data = json.loads(VERSIONS_CACHE.read_text())
                return data.get("versions", [])
        except Exception:
            pass

    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            versions = [v["id"] for v in data.get("versions", [])]
            cache_data = {
                "latest_release": get_latest_minecraft_version(),
                "versions": versions,
            }
            VERSIONS_CACHE.write_text(json.dumps(cache_data, indent=2))
            return versions
    except Exception as e:
        logger.warning(f"Failed to fetch MC versions: {e}")
        return []


def get_latest_for_loader(loader: str, mc_version: str | None = None) -> str:
    """Return the latest loader build for the given MC version.

    For NeoForge this returns the NeoForge build number (e.g. ``26.1.2.95``),
    not the Minecraft version. Falls back to fetching from the loader's
    metadata API.
    """
    if mc_version is None:
        mc_version = get_latest_minecraft_version()

    if loader.lower() == "neoforge":
        try:
            url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode()
                # NeoForge version format: <mc_version>.<build> e.g. 26.1.2.95
                pattern = re.compile(
                    rf"<version>{re.escape(mc_version)}\.(\d+)</version>"
                )
                matches = pattern.findall(content)
                if matches:
                    build = max(int(m) for m in matches)
                    return f"{mc_version}.{build}"
        except Exception as e:
            logger.warning(f"Failed to fetch NeoForge version: {e}")

    return mc_version  # fallback
