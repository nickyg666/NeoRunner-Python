#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
# For fresh reinstall: rm -rf ~/neorunner && curl -sL ... | bash
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

FORCE_FRESH=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --fresh|-f)
            FORCE_FRESH=true
            ;;
    esac
    shift
done

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║           NeoRunner Installer                ║"
...
LATEST_TAG=${LATEST_TAG:-main}
echo "  Version: $LATEST_TAG"

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"

# Fresh install if no config exists
echo -e "${GREEN}[5/8] Preparing installation directory...${NC}"
mkdir -p "$INSTALL_DIR"

# Clean old installation if no config
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    echo "  Fresh install - cleaning old installation..."
    # Kill any running processes
    pkill -f "neorunner" 2>/dev/null || true
    pkill -f "waitress" 2>/dev/null || true
    tmux kill-session -t neorunner 2>/dev/null || true
    tmux kill-session -t MC 2>/dev/null || true
    
    # Remove old files but preserve server data
    rm -rf "$INSTALL_DIR/neorunner_venv" 2>/dev/null || true
    rm -rf "$INSTALL_DIR/neorunner_pkg.egg-info" 2>/dev/null || true
    rm -rf "$INSTALL_DIR/__pycache__" 2>/dev/null || true
    rm -rf "$INSTALL_DIR/neorunner_pkg/__pycache__" 2>/dev/null || true
    
    echo "  ✓ Old installation cleaned"
fi

cd "$INSTALL_DIR"

echo -e "${GREEN}[6/8] Installing Python package...${NC}"

if [ -d ".git" ]; then
    echo "  Updating..."
    git fetch --tags
    git checkout "$LATEST_TAG" 2>/dev/null || git checkout main 2>/dev/null || true
    git pull origin main 2>/dev/null || true
else
    echo "  Cloning..."
    git clone --depth 1 --branch "$LATEST_TAG" "https://github.com/${REPO_OWNER}/${REPO_NAME}.git" . 2>&1 || {
        git clone --depth 1 -b main "https://github.com/${REPO_OWNER}/${REPO_NAME}.git" . 2>&1 || {
            echo -e "${RED}Failed to clone${NC}"
            exit 1
        }
    }
fi

echo "  Creating virtual environment..."
if [ ! -d "neorunner_venv" ]; then
    python3 -m venv neorunner_venv
fi

source neorunner_venv/bin/activate
pip install --upgrade pip --break-system-packages
pip install --break-system-packages --force-reinstall --no-cache-dir -e .

# Verify and show version
neorunner --version 2>/dev/null || echo "  neorunner command ready"

# Verify installation
if ! command -v neorunner &> /dev/null; then
    echo -e "${RED}  ✗ neorunner command not found after install${NC}"
    exit 1
fi

echo "  ✓ neorunner installed"

# Try playwright (optional)
if pip install --break-system-packages playwright &>/dev/null 2>&1; then
    echo "  Installing Playwright..."
    playwright install chromium &>/dev/null || true
fi

echo -e "${GREEN}[7/8] Creating directories and config...${NC}"
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders

if [ ! -f eula.txt ]; then
    echo "eula=true" > eula.txt
    echo "  ✓ eula.txt"
fi

# Create config if missing
if [ ! -f config.json ]; then
    echo "  Creating config with latest MC version..."
    neorunner init --latest --loader neoforge || true
fi

echo -e "${GREEN}[8/8] Running NeoRunner installer...${NC}"
echo "  Running server setup..."

# Run setup without args - it auto-detects latest versions
neorunner setup 2>&1 || echo "  Setup completed with warnings"

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  NeoRunner $LATEST_TAG installed!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Install dir: $INSTALL_DIR"
echo ""
echo "  To start server:"
echo "    cd $INSTALL_DIR"
echo "    source neorunner_venv/bin/activate"
echo "    neorunner start"
echo ""
echo "  To start in background:"
echo "    neorunner start --daemon"
echo ""
echo "  Dashboard: http://localhost:8000"
echo ""
echo "  For fresh reinstall:"
echo "    curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash -s --fresh"
echo ""