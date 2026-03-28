#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/neorunner/neorunner/main/install.sh | bash
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║           NeoRunner v2.3.0 Installer                      ║"
echo "║        Minecraft Modded Server Manager                      ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Detect OS
OS=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
fi

echo -e "${GREEN}[1/6] Detecting system...${NC}"
echo "  OS: $OS"

# Install system dependencies
echo -e "${GREEN}[2/6] Installing system dependencies...${NC}"

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
        echo -e "${RED}Unsupported package manager. Please install manually:${NC}"
        echo "  - tmux, curl, wget, rsync, unzip, zip, openjdk-21"
        return 1
    fi
}

SYSTEM_DEPS="tmux curl wget rsync unzip zip"
if ! command -v java &> /dev/null; then
    SYSTEM_DEPS="$SYSTEM_DEPS openjdk-21-jre-headless"
fi
install_pkg $SYSTEM_DEPS

# Check Java
if command -v java &> /dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$JAVA_VERSION" -ge 21 ]; then
        echo -e "  ${GREEN}✓ Java 21+ detected${NC}"
    else
        echo -e "${YELLOW}  ⚠ Java $JAVA_VERSION detected, Java 21 recommended${NC}"
    fi
fi

# Check Python
echo -e "${GREEN}[3/6] Checking Python...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
    echo "  Python $PYTHON_VERSION detected"
else
    echo -e "${RED}  ✗ Python 3 not found. Please install Python 3.9+.${NC}"
    exit 1
fi

# Create virtual environment
echo -e "${GREEN}[4/6] Setting up...${NC}"

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
echo "  Install directory: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Clone repository
REPO_URL="https://github.com/neorunner/neorunner.git"
if [ -d .git ]; then
    echo "  Updating..."
    git pull origin main 2>/dev/null || true
else
    echo "  Cloning..."
    git clone --depth 1 "$REPO_URL" . 2>/dev/null || {
        echo -e "${RED}Failed to clone. Check network connection.${NC}"
        exit 1
    }
fi

# Create virtual environment
if [ ! -d "neorunner_venv" ]; then
    python3 -m venv neorunner_venv
fi

source neorunner_venv/bin/activate
pip install --upgrade pip -q
pip install -e . -q

# Create directories
mkdir -p mods clientonly config backups crash-reports logs world

# Generate config
echo -e "${GREEN}[5/6] Configuration...${NC}"

if [ ! -f config.json ]; then
    cat > config.json << 'EOF'
{
  "mc_version": "1.21.11",
  "loader": "neoforge",
  "mc_port": 25565,
  "http_port": 8000,
  "rcon_port": 25576,
  "xmx": "4G",
  "xms": "2G"
}
EOF
    echo "  ✓ Created config.json"
fi

if [ ! -f eula.txt ]; then
    echo "eula=true" > eula.txt
    echo "  ✓ Created eula.txt"
fi

echo -e "${GREEN}[6/6] Complete!${NC}"

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  NeoRunner v2.3.0 installed!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  To start:"
echo "    cd $INSTALL_DIR"
echo "    source neorunner_venv/bin/activate"
echo "    neorunner start"
echo ""
echo "  Dashboard: http://localhost:8000"
echo ""
