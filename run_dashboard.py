#!/usr/bin/env python3
"""Persistent dashboard starter using Flask threaded mode."""
import os
import sys

os.chdir('/home/host/neorunner')
sys.path.insert(0, '/home/host/neorunner')

from dashboard import app

print("Starting NeoRunner dashboard on http://0.0.0.0:8000")
app.run(host='0.0.0.0', port=8000, threaded=True, use_reloader=False)