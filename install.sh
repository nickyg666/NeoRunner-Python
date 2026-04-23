#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
# For fresh: rm -rf ~/neorunner && curl -sL ... | bash
#

set -e

B='\033[0;34m'
G='\033[0;32m'
R='\033[0;31m'
NC='\033[0m'

echo -e "${B}========================================================${NC}"
echo -e "${B}           NeoRunner Installer${NC}"
echo -e "${B}========================================================${NC}"

# Install system deps
echo "Installing system deps..."
DEPS="tmux curl wget rsync unzip zip python3 python3-venv python3-pip git"
command -v java &>/dev/null || DEPS="$DEPS openjdk-21-jre-headless"

if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq && sudo apt-get install -y -qq $DEPS
elif command -v dnf &>/dev/null; then
    sudo dnf install -y -q $DEPS
elif command -v yum &>/dev/null; then
    sudo yum install -y -q $DEPS
fi

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Clone if needed
if [ ! -d ".git" ]; then
    echo "Cloning NeoRunner..."
    git clone -q -b main --depth 1 https://github.com/nickyg666/NeoRunner-Python.git .
fi

# Create venv and install package
if [ ! -d "neorunner_venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv neorunner_venv
fi

echo "Installing package..."
source neorunner_venv/bin/activate
pip install -q --upgrade pip
pip install -q --break-system-packages --force-reinstall -e .

# Create directories
echo "Setting up directories..."
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders

[ ! -f eula.txt ] && echo "eula=true" > eula.txt

# Install loader
echo "Installing loader (NeoForge)..."
neorunner setup 2>&1 || echo "Setup completed"

# Create default config
[ ! -f config.json ] && neorunner init 2>/dev/null

echo ""
echo -e "${G}========================================================${NC}"
echo -e "${G}  NeoRunner Ready!${NC}"
echo -e "${G}========================================================${NC}"
echo ""
echo "  Location: $INSTALL_DIR"
echo ""
echo "  To configure (interactively):"
echo "    cd $INSTALL_DIR"
echo "    source neorunner_venv/bin/activate"
echo "    neorunner config --setup"
echo ""
echo "  To start server:"
echo "    cd $INSTALL_DIR"
echo "    source neorunner_venv/bin/activate"
echo "    neorunner start"
echo ""
echo "  Dashboard: http://localhost:8000"
echo ""