"""Constants for NeoRunner."""

import os
from pathlib import Path

# All paths relative to this module directory
CWD = Path(__file__).parent.resolve()

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
