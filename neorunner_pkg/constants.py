"""Constants for NeoRunner."""

import os
from pathlib import Path

# All paths relative to the installation directory
# Try: NEORUNNER_DIR env, then find dir with config.json, then CWD, then package dir
def _find_cwd():
    # Check env var first
    if 'NEORUNNER_DIR' in os.environ:
        return Path(os.environ['NEORUNNER_DIR'])
    # Try to find config.json in current path or parents
    for path in [Path.cwd(), Path(__file__).parent.parent.resolve()]:
        if (path / "config.json").exists():
            return path
    # Default to where neorunner is run from
    return Path.cwd()

CWD = _find_cwd()

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

# Version check interval in seconds (default 1 hour)
VERSION_CHECK_INTERVAL = 3600


def get_current_mc_version() -> str:
    """Get current configured MC version from config or latest."""
    from .config import load_cfg
    from .version import get_latest_minecraft_version
    
    try:
        cfg = load_cfg()
        if cfg and cfg.mc_version:
            return cfg.mc_version
    except Exception:
        pass
    return get_latest_minecraft_version()


def get_configured_loader() -> str:
    """Get currently configured loader."""
    from .config import load_cfg
    try:
        cfg = load_cfg()
        return cfg.loader if cfg else "neoforge"
    except Exception:
        return "neoforge"