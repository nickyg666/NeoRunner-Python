"""Constants for NeoRunner."""

import os
from pathlib import Path

# All paths relative to this module directory
CWD = Path(__file__).parent.parent.resolve()

MOD_LOADERS = ["neoforge", "forge", "fabric"]

DEFAULT_PORTS = {
    "neoforge": 25565,
    "forge": 25565,
    "fabric": 25565,
}

PARALLEL_PORTS = {
    "http": 8001,
    "minecraft": 1235,
    "rcon": 25576,
}

FORCED_SERVER_MODS = {
    "entity_model_features",
}

FORCE_CLIENT_ONLY_MODS = {
    "glassential",
    "controlify",
    "sound_visualizer",
    "smoothswapping",
    "entity_texture_features",
    "entitytexturefeatures",
    "sodium",
    "xaerominimap",
    "xaero_minimap",
    "optifine",
    "iris",
    "modmenu",
    "inventoryhud",
    "inventory_hud",
    "itemscroller",
    "journeymap",
    "replaymod",
    "worldedit",
    "litematica",
    "minihud",
    "sidebarrecipes",
    "roughlyenoughitems",
    "emi",
    "emi_dev",
    "craftingtweaks",
    "jade",
    "wthit",
    "consecution",
    "voxelmap",
    "malisis",
    "betterthirdperson",
    "betterf3",
    "better_title",
    "bettertitlescreen",
    "pseudo",
    "essential",
    "pepsi",
    "krypton",
    "fabric",
    "ferritecore",
    "kjsptags",
    "beautifiedchat",
    "beautifiedchatclient",
    "enhancedvisuals",
    "enhanced_visual",
    "skinlayers",
    "skin_layers",
    "skinlayer",
    "invis",
    "invisible",
    "invmove",
    "cosmetic",
    "capes",
    "cape",
    "xat",
    "glowing",
    "particle",
    "notenoughanimations",
    "continuity",
    "dynamicfps",
    "zoomify",
    "lambdabettergrass",
    "lambdadynamiclights",
    "smoothchunk",
    "献",
    "cit",
    "fancymenu",
    "rsls",
    "customplayermodels",
    "playeranimation",
    "playerrevive",
    "players",
    "tcdcommons",
    "t_and_t",
}

MAX_RESTART_ATTEMPTS = 5
MAX_TOTAL_RESTARTS = 15
CRASH_COOLDOWN_SECONDS = 10

# Default version if unable to fetch
DEFAULT_MC_VERSION = "1.21.11"


def get_latest_minecraft_version() -> str:
    """Fetch latest Minecraft version from Mojang."""
    import json
    import urllib.request
    
    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            # Get latest release version
            return data.get("latest", {}).get("release", DEFAULT_MC_VERSION)
    except Exception:
        return DEFAULT_MC_VERSION


def get_latest_minecraft_versions() -> dict:
    """Fetch all available Minecraft versions."""
    import json
    import urllib.request
    
    try:
        url = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
        req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.3.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return {
                "latest_release": data.get("latest", {}).get("release"),
                "latest_snapshot": data.get("latest", {}).get("snapshot"),
                "versions": [v["id"] for v in data.get("versions", [])]
            }
    except Exception:
        return {
            "latest_release": DEFAULT_MC_VERSION,
            "latest_snapshot": DEFAULT_MC_VERSION,
            "versions": [DEFAULT_MC_VERSION]
        }
