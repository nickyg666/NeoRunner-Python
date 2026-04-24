#!/usr/bin/env python3
"""Start the NeoRunner dashboard - simple version."""

import os
import sys

ROOT = os.getcwd()
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = ''  # Fix for relative imports
    spec.loader.exec_module(module)
    return module

# Load core modules first
constants = load_module('constants', f'{ROOT}/constants.py')
CWD = constants.CWD
MOD_LOADERS = constants.MOD_LOADERS

config = load_module('config', f'{ROOT}/config.py')
ServerConfig = config.ServerConfig
load_cfg = config.load_cfg
save_cfg = config.save_cfg

log = load_module('log', f'{ROOT}/log.py')
log_event = log.log_event

# Now load dashboard
print("Loading dashboard...")
dashboard = load_module('dashboard', f'{ROOT}/dashboard.py')
app = dashboard.app

print("Starting NeoRunner dashboard on http://0.0.0.0:8000")
app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False, threaded=True)
