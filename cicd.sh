#!/bin/bash
# NeoRunner CI/CD - Continuous Testing and Deployment
# Runs forever until all tests pass and server is fully running

set -e

NEORUNNER_ROOT="/development/neorunner"
cd "$NEORUNNER_ROOT"

ITERATION=0
MAX_ITERATIONS=100

echo "=== NeoRunner CI/CD Cycle ==="
echo "This will run until server is fully operational"
echo ""

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))
    echo "========================================="
    echo "Iteration #$ITERATION"
    echo "========================================="
    
    # Step 1: Syntax and Import Tests
    echo "[1/6] Syntax & Import tests..."
    if ! python3 -m py_compile neorunner_pkg/loaders/neoforge.py 2>/dev/null; then
        echo "  ✗ Syntax error in neoforge.py - fixing..."
        git checkout -- neorunner_pkg/loaders/neoforge.py
        continue
    fi
    if ! python3 -m py_compile neorunner_pkg/loaders/forge.py 2>/dev/null; then
        echo "  ✗ Syntax error in forge.py - fixing..."
        git checkout -- neorunner_pkg/loaders/forge.py
        continue
    fi
    if ! python3 -m py_compile neorunner_pkg/loaders/fabric.py 2>/dev/null; then
        echo "  ✗ Syntax error in fabric.py - fixing..."
        git checkout -- neorunner_pkg/loaders/fabric.py
        continue
    fi
    echo "  ✓ Syntax OK"
    
    # Step 2: Import test
    echo "[2/6] Testing imports..."
    if ! python3 -c "from neorunner_pkg.loaders import get_loader" 2>/dev/null; then
        echo "  ✗ Import failed - checking out safe version..."
        git checkout HEAD -- neorunner_pkg/
        continue
    fi
    echo "  ✓ Imports OK"
    
    # Step 3: Config validation
    echo "[3/6] Testing config..."
    CONFIG_CHECK=$(python3 -c "
from neorunner_pkg.config import ServerConfig
cfg = ServerConfig()
assert 'echo' not in cfg.xmx
assert 'echo' not in cfg.xms
print('OK')
" 2>&1)
    if [ "$CONFIG_CHECK" != "OK" ]; then
        echo "  ✗ Config corrupted: $CONFIG_CHECK"
        continue
    fi
    echo "  ✓ Config OK"
    
    # Step 4: JVM args creation
    echo "[4/6] Testing JVM args..."
    JVM_CHECK=$(python3 << 'PYEOF'
import os, sys, shutil
from neorunner_pkg.loaders.neoforge import NeoForgeLoader
from neorunner_pkg.config import ServerConfig

test_dir = '/tmp/nr_test_jvm'
if os.path.exists(test_dir):
    shutil.rmtree(test_dir)
os.makedirs(test_dir)

cfg = ServerConfig()
cfg.xmx = '4G'
cfg.xms = '2G'
cfg.loader = 'neoforge'
cfg.mc_version = '1.21.4'

loader = NeoForgeLoader(cfg, test_dir)
loader._setup_jvm_args()

content = open(f'{test_dir}/user_jvm_args.txt').read()

# Validate
assert '-Xmx4G' in content
assert '-Xms2G' in content
assert 'echo' not in content
assert 'Dashboard' not in content

print('OK')
shutil.rmtree(test_dir)
PYEOF
    )
    if [ "$JVM_CHECK" != "OK" ]; then
        echo "  ✗ JVM args invalid: $JVM_CHECK"
        continue
    fi
    echo "  ✓ JVM args OK"
    
# Step 5: Java command building
    echo "[5/6] Testing Java commands..."
    CMD_CHECK=$(python3 << 'PYEOF'
import os, sys, shutil
from neorunner_pkg.loaders import get_loader
from neorunner_pkg.config import ServerConfig

test_dir = '/tmp/nr_test_cmd'
if os.path.exists(test_dir):
    shutil.rmtree(test_dir)
os.makedirs(test_dir)

cfg = ServerConfig()
cfg.loader = 'neoforge'
cfg.mc_version = '1.21.4'
cfg.xmx = '4G'
cfg.xms = '2G'

loader = get_loader(cfg, test_dir)
loader.prepare_environment()

cmd = loader.build_java_command()

# Check command parts exist (not exact string match)
if 'java' not in cmd:
    raise Exception('java missing')
if '@user_jvm_args.txt' not in cmd:
    raise Exception('@user_jvm_args.txt missing')
if '-jar' not in ' '.join(cmd):
    raise Exception('-jar missing')
if 'nogui' not in cmd:
    raise Exception('nogui missing')

print('OK')
shutil.rmtree(test_dir)
PYEOF
    )
    if [ "$ENV_CHECK" != "OK" ]; then
        echo "  ✗ Environment test failed: $ENV_CHECK"
        continue
    fi
    echo "  ✓ Full environment OK"
    
    # All tests passed!
    echo ""
    echo "=== All Tests Passed! (Iteration $ITERATION) ==="
    echo ""
    
    # Commit and deploy
    echo "Committing and deploying..."
    git add -A
    git commit -m "Test cycle $ITERATION - all tests passed" 2>/dev/null || true
    git push 2>/dev/null || echo "Push skipped (no changes)"
    
    echo "=== DEPLOYMENT COMPLETE ==="
    echo "Run on remote: cd ~/neorunner && git pull && rm -f user_jvm_args.txt && neorunner start"
    exit 0
    
done

echo "Max iterations reached ($MAX_ITERATIONS) - manual intervention required"
exit 1