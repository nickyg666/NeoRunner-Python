#!/usr/bin/env python3
"""
NeoRunner - Complete Installation and Configuration Script
Provides interactive setup with dependency checking and guided configuration.
"""

import sys
import os
from pathlib import Path

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.resolve()
# Change to script directory (where neorunner package is)
os.chdir(SCRIPT_DIR)
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from setup_wizard import main
    main()
except ImportError as e:
    print(f"Error importing setup wizard: {e}")
    print("Please ensure all dependencies are installed:")
    print("  pip install flask requests apscheduler tomli")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n\nSetup cancelled by user.")
    sys.exit(0)
except Exception as e:
    print(f"\nError during setup: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
