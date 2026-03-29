#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
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
        echo "  - tmux, curl, wget, rsync, unzip, zip, openjdk-21, python3-venv"
        return 1
    fi
}

SYSTEM_DEPS="tmux curl wget rsync unzip zip python3-venv python3-pip"
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
    
    # Ensure pip is available
    if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
        echo "  Installing pip..."
        install_pkg python3-pip
    fi
else
    echo -e "${RED}  ✗ Python 3 not found. Please install Python 3.9+.${NC}"
    exit 1
fi

# Get latest release tag
echo -e "${GREEN}[4/6] Fetching latest release...${NC}"

REPO_OWNER="nickyg666"
REPO_NAME="NeoRunner-Python"

# Fetch latest release tag
LATEST_TAG=$(curl -s "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
if [ -z "$LATEST_TAG" ]; then
    LATEST_TAG="v2.3.0"
fi
echo "  Latest version: $LATEST_TAG"

# Create install directory
INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
echo "  Install directory: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Clone repository at specific tag (no checkout needed, just extract)
REPO_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"

if [ -d ".git" ]; then
    echo "  Updating to latest..."
    git fetch --tags
    git checkout "$LATEST_TAG" 2>/dev/null || git checkout main 2>/dev/null || true
else
    echo "  Cloning NeoRunner $LATEST_TAG..."
    # Clone at specific tag
    git clone --depth 1 --branch "$LATEST_TAG" "$REPO_URL" . 2>&1 || {
        echo -e "${RED}Failed to clone. Trying main branch...${NC}"
        git clone --depth 1 -b main "$REPO_URL" . 2>&1 || {
            echo -e "${RED}Failed to clone. Check network connection.${NC}"
            exit 1
        }
    }
fi

# Verify critical files exist
if [ ! -f "setup.py" ] && [ ! -f "neorunner_pkg/__init__.py" ]; then
    echo -e "${RED}Repository contents invalid.${NC}"
    exit 1
fi

# Create virtual environment
echo "  Creating Python virtual environment..."
if [ ! -d "neorunner_venv" ]; then
    python3 -m venv neorunner_venv
fi

# Activate and install
echo "  Installing Python dependencies..."
source neorunner_venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install the package
pip install -e .

# Create directories
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders

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
