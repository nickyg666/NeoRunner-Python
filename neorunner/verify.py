#!/usr/bin/env python3
"""
Verification script for NeoRunner installation
"""

import sys
import os
from pathlib import Path

NEORUNNER_HOME = str(Path(__file__).parent.resolve())
os.chdir(NEORUNNER_HOME)
sys.path.insert(0, NEORUNNER_HOME)

print("="*70)
print("NEORUNNER VERIFICATION")
print("="*70)
print()

# Check 1: Module imports
print("1. Checking module imports...")
try:
    from neorunner import (
        load_cfg, ServerConfig, run_server, 
        is_server_running, dashboard_app
    )
    print("   ✅ Core modules import successfully")
except Exception as e:
    print(f"   ❌ Import error: {e}")
    sys.exit(1)

# Check 2: Dashboard endpoints
print("\n2. Checking dashboard endpoints...")
try:
    from neorunner.dashboard import app
    endpoints = [r for r in app.url_map.iter_rules() if 'api' in r.endpoint]
    print(f"   ✅ Found {len(endpoints)} API endpoints")
    
    # Check for key endpoints
    key_endpoints = [
        'api_health',
        'api_setup_install',
        'api_setup_install_prereqs',
    ]
    
    missing = []
    for ep in key_endpoints:
        if not any(ep in str(r.endpoint) for r in app.url_map.iter_rules()):
            missing.append(ep)
    
    if missing:
        print(f"   ⚠️  Missing new endpoints: {', '.join(missing)}")
    else:
        print("   ✅ All setup endpoints present")
        
except Exception as e:
    print(f"   ❌ Error: {e}")

# Check 3: File structure
print("\n3. Checking file structure...")
import os
from pathlib import Path

checks = [
    ("Python modules", "*.py", 20),
    ("Templates", "templates/*.html", 1),
    ("Worlds", "world", 0),  # Directory
    ("Mods", "mods/*.jar", 100),
    ("Server config", "server.properties", 0),
]

for name, pattern, min_count in checks:
    path = Path(NEORUNNER_HOME) / pattern
    if '*' in pattern:
        count = len(list(Path(NEORUNNER_HOME).glob(pattern)))
        if count >= min_count:
            print(f"   ✅ {name}: {count} found")
        else:
            print(f"   ⚠️  {name}: only {count} found (expected {min_count}+)")
    else:
        if path.exists():
            print(f"   ✅ {name}: exists")
        else:
            print(f"   ❌ {name}: not found")

# Check 4: Prerequisites
print("\n4. Checking prerequisites...")
import shutil

prereqs = {
    "Java": shutil.which("java"),
    "tmux": shutil.which("tmux"),
    "curl": shutil.which("curl"),
    "Python 3": shutil.which("python3"),
}

for name, path in prereqs.items():
    if path:
        print(f"   ✅ {name}: {path}")
    else:
        print(f"   ❌ {name}: not found")

# Check 5: Systemd service
print("\n5. Checking systemd service...")
service_file = Path.home() / ".config/systemd/user/mcserver.service"
if service_file.exists():
    content = service_file.read_text()
    if "neorunner" in content and NEORUNNER_HOME in content:
        print("   ✅ Service file configured correctly")
    else:
        print("   ⚠️  Service file may need updating")
else:
    print("   ⚠️  Service file not found (run install.py)")

# Check 6: Import test
print("\n6. Testing imports...")
try:
    from neorunner.dashboard import app
    from neorunner.mod_browser import ModBrowser
    from neorunner.java_manager import JavaManager
    print("   ✅ All imports successful")
except Exception as e:
    print(f"   ❌ Import error: {e}")

print("\n" + "="*70)
print("VERIFICATION COMPLETE")
print("="*70)
print(f"\nNeoRunner home: {NEORUNNER_HOME}")
print("\nTo start NeoRunner:")
print("  1. Run: python3 -m neorunner")
print("  2. Or:   systemctl --user start mcserver")
print("\nDashboard will be available at: http://0.0.0.0:8000")
print("="*70)
