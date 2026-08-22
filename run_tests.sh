#!/bin/bash
# NeoRunner Test Runner - runs all tests and validates the system

set -e

 cd /development/neorunner

echo "=== NeoRunner Test Suite ==="
echo ""

# Test 1: Syntax checks
echo "[1/5] Checking syntax..."
python3 -m py_compile neorunner_pkg/loaders/neoforge.py
python3 -m py_compile neorunner_pkg/loaders/forge.py
python3 -m py_compile neorunner_pkg/loaders/fabric.py
python3 -m py_compile neorunner_pkg/config.py
python3 -m py_compile neorunner_pkg/cli.py
python3 -m py_compile neorunner_pkg/dashboard.py
echo "  ✓ Syntax OK"
echo ""

# Test 2: Import checks
echo "[2/5] Checking imports..."
python3 -c "from neorunner_pkg.loaders import get_loader; print('  ✓ Loaders import OK')"
python3 -c "from neorunner_pkg.config import load_cfg; print('  ✓ Config import OK')"
python3 -c "from neorunner_pkg.dashboard import app; print('  ✓ Dashboard import OK')"
echo ""

# Test 3: Config validation
echo "[3/5] Testing config..."
python3 -c "
from neorunner_pkg.config import ServerConfig
cfg = ServerConfig()
print(f'  Default xmx: {cfg.xmx}')
print(f'  Default xms: {cfg.xms}')

# Verify values are strings not containing echo
assert not 'echo' in cfg.xmx, f'xmx corrupted: {cfg.xmx}'
assert not 'echo' in cfg.xms, f'xms corrupted: {cfg.xms}'
print('  ✓ Config values valid')
"
echo ""

# Test 4: Loader JVM args
echo "[4/5] Testing loader JVM args..."

# Test NeoForge
python3 << 'PYEOF'
import os, sys, shutil
sys.path.insert(0, '/development/neorunner')
from neorunner_pkg.loaders.neoforge import NeoForgeLoader
from neorunner_pkg.config import ServerConfig

test_dir = '/tmp/nr_test_quick'
if os.path.exists(test_dir):
    shutil.rmtree(test_dir)
os.makedirs(test_dir)

# Test with various memory settings
for xmx, xms in [('2G', '1G'), ('4G', '2G'), ('6G', '3G'), ('8G', '4G')]:
    cfg = ServerConfig()
    cfg.xmx = xmx
    cfg.xms = xms
    cfg.loader = 'neoforge'
    cfg.mc_version = '1.21.4'
    
    loader = NeoForgeLoader(cfg, test_dir)
    loader._setup_jvm_args()
    
    content = open(f'{test_dir}/user_jvm_args.txt').read()
    
    assert f'-Xmx{xmx}' in content, f'Missing -Xmx{xmx}: {content[:100]}'
    assert f'-Xms{xms}' in content, f'Missing -Xms{xms}: {content}'
    assert 'echo' not in content, f'Contains echo: {content[:50]}'
    assert 'Dashboard' not in content, f'Contains Dashboard: {content[:50]}'

print(f'  ✓ NeoForge JVM args OK (2G-8G)')

shutil.rmtree(test_dir)
PYEOF
echo ""

# Test 5: Java commands
echo "[5/5] Testing Java commands..."
python3 << 'PYEOF'
import os, sys, shutil
sys.path.insert(0, '/development/neorunner')
from neorunner_pkg.loaders import get_loader
from neorunner_pkg.config import ServerConfig

test_dir = '/tmp/nr_test_java'
if os.path.exists(test_dir):
    shutil.rmtree(test_dir)
os.makedirs(test_dir)

cfg = ServerConfig()
cfg.loader = 'neoforge'
cfg.mc_version = '1.21.4'
cfg.xmx = '4G'
cfg.xms = '2G'

loader = get_loader(cfg, test_dir)
loader.prepare_environment()  # This creates user_jvm_args.txt

cmd = loader.build_java_command()

assert 'java' in cmd
assert '@user_jvm_args.txt' in cmd
assert '-jar' in cmd
assert 'nogui' in cmd

# Verify file was created
jvm_file = os.path.join(test_dir, 'user_jvm_args.txt')
assert os.path.exists(jvm_file), f'user_jvm_args.txt not created'

content = open(jvm_file).read()
assert '-Xmx4G' in content
assert 'echo' not in content

print(f'  ✓ Java command: {" ".join(cmd[:4])}')
print(f'  ✓ JVM args: {content.split(chr(10))[0]}')

shutil.rmtree(test_dir)
PYEOF
echo ""

echo "=== All Tests Passed ==="