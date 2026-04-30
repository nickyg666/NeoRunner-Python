"""Test fixtures for neorunner tests."""

import pytest
import sys
import os

# Add the parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This allows relative imports to work
import neorunner_pkg
sys.modules['neorunner_pkg'] = neorunner_pkg