#!/usr/bin/env python3
"""Start the NeoRunner dashboard - simplified for Python 3.14+ compatibility."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from neorunner_pkg.dashboard import app

print("Starting NeoRunner dashboard on http://0.0.0.0:8000")
app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False, threaded=True)