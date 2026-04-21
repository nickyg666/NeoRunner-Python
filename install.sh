#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

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

echo -e "${GREEN}[1/7] Detecting system...${NC}"
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

echo -e "${GREEN}[2/7] Installing system dependencies...${NC}"
install_pkg $SYSTEM_DEPS

if command -v java &> /dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$JAVA_VERSION" -ge 21 ]; then
        echo -e "  ${GREEN}✓ Java $JAVA_VERSION detected${NC}"
    else
        echo -e "${YELLOW}  ⚠ Java $JAVA_VERSION detected, 21+ recommended${NC}"
    fi
fi

echo -e "${GREEN}[3/7] Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}  ✗ Python 3 not found${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "  Python $PYTHON_VERSION"

echo -e "${GREEN}[4/7] Fetching latest release...${NC}"
REPO_OWNER="nickyg666"
REPO_NAME="NeoRunner-Python"
LATEST_TAG=$(curl -s "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
LATEST_TAG=${LATEST_TAG:-v2.3.0}
echo "  Version: $LATEST_TAG"

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo -e "${GREEN}[5/7] Installing Python package...${NC}"
echo "  Directory: $INSTALL_DIR"

if [ -d ".git" ]; then
    echo "  Updating..."
    git fetch --tags
    git checkout "$LATEST_TAG" 2>/dev/null || git checkout main 2>/dev/null || true
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
echo "  Installing neorunner..."
pip install -e .

# Try playwright (optional)
if pip install playwright &>/dev/null 2>&1; then
    playwright install chromium &>/dev/null || true
fi

echo -e "${GREEN}[6/7] Creating directories...${NC}"
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders

if [ ! -f eula.txt ]; then
    echo "eula=true" > eula.txt
    echo "  ✓ eula.txt"
fi

echo -e "${GREEN}[7/7] Running NeoRunner installer...${NC}"

# Check if config exists, if not create it with latest version
if [ ! -f config.json ]; then
    echo "  Creating config with latest MC version..."
    neorunner init --latest --loader neoforge || true
fi

# Run full installer
echo "  Running server installer..."
neorunner install || {
    echo -e "${YELLOW}  Installer needs interactive mode. Running neorunner setup...${NC}"
    neorunner setup || echo -e "${YELLOW}  Setup incomplete - run 'neorunner install' manually${NC}"
}

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  NeoRunner $LATEST_TAG installed!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  To start:"
echo "    cd $INSTALL_DIR"
echo "    source neorunner_venv/bin/activate"
echo "    neorunner start"
echo ""
echo "  Dashboard: http://localhost:8000"
echo ""