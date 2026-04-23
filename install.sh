#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
# Or for fresh reinstall: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash -s --fresh
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
echo "║           NeoRunner v2.3.0 Installer                ║"
echo "║        Minecraft Modded Server Manager              ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

OS=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
fi

echo -e "${GREEN}[1/8] Detecting system...${NC}"
echo "  OS: $OS"

install_pkg() {
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y "$@"
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y "$@"
    elif command -v yum &> /dev/null; then
        sudo yum install -y "$@"
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm "$@"
    else
        echo -e "${RED}Unsupported package manager.${NC}"
        return 1
    fi
}

SYSTEM_DEPS="tmux curl wget rsync unzip zip python3 python3-venv python3-pip git"
if ! command -v java &> /dev/null; then
    SYSTEM_DEPS="$SYSTEM_DEPS openjdk-21-jre-headless"
fi

echo -e "${GREEN}[2/8] Installing system dependencies...${NC}"
install_pkg $SYSTEM_DEPS

if command -v java &> /dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$JAVA_VERSION" -ge 21 ]; then
        echo -e "  ${GREEN}✓ Java $JAVA_VERSION detected${NC}"
    else
        echo -e "${YELLOW}  ⚠ Java $JAVA_VERSION detected, 21+ recommended${NC}"
    fi
fi

echo -e "${GREEN}[3/8] Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}  ✗ Python 3 not found${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "  Python $PYTHON_VERSION"

echo -e "${GREEN}[4/8] Fetching latest release...${NC}"
REPO_OWNER="nickyg666"
REPO_NAME="NeoRunner-Python"
LATEST_TAG=$(curl -s "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
LATEST_TAG=${LATEST_TAG:-v2.3.0}
echo "  Version: $LATEST_TAG"

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"

# Fresh install: remove old installation first
echo -e "${GREEN}[5/8] Preparing installation directory...${NC}"
mkdir -p "$INSTALL_DIR"

if [ "$FORCE_FRESH" = true ] || [ ! -f "$INSTALL_DIR/config.json" ]; then
    echo "  Removing old installation for fresh install..."
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
    
    # Only remove if --fresh flag
    if [ "$FORCE_FRESH" = true ]; then
        rm -rf "$INSTALL_DIR/.cache" 2>/dev/null || true
    fi
    
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
pip install --upgrade pip
pip install --break-system-packages -e .

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
echo "  Running server installer..."

# Try neorunner install, fall back to neorunner setup
if neorunner install 2>&1; then
    echo "  ✓ Installation complete"
elif neorunner setup 2>&1; then
    echo "  ✓ Setup complete"
else
    echo -e "${YELLOW}  ⚠ Installation needs manual setup${NC}"
fi

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