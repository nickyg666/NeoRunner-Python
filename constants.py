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
}

MAX_RESTART_ATTEMPTS = 5
MAX_TOTAL_RESTARTS = 15
CRASH_COOLDOWN_SECONDS = 10
