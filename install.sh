#!/bin/bash
#
# NeoRunner - One command install + configure + run
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
#

set -e

B='\033[0;34m'
G='\033[0;32m'
NC='\033[0m'

echo -e "${B}=== NeoRunner Installer ===${NC}"

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
cd "$INSTALL_DIR" 2>/dev/null || mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR"

# Clone or update
if [ ! -d ".git" ]; then
    echo "Cloning..."
    git clone -q -b main --depth 1 https://github.com/nickyg666/NeoRunner-Python.git .
else
    echo "Updating..."
    git -C . pull -q origin main 2>/dev/null || true
fi

# Venv + pip install
[ ! -d "neorunner_venv" ] && python3 -m venv neorunner_venv
source neorunner_venv/bin/activate
pip install -q --break-system-packages --force-reinstall -e .

# Create dirs + eula
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders
[ ! -f eula.txt ] && echo "eula=true" > eula.txt

# Run interactive config (will prompt!)
echo "Running interactive config..."
neorunner config --setup || true

# Run setup to install loader
echo "Installing loader..."
neorunner setup 2>&1 || true

echo -e "${G}=== Ready! ===${NC}"
echo "  cd $INSTALL_DIR"
echo "  source neorunner_venv/bin/activate"
echo "  neorunner start"
echo "  Dashboard: http://localhost:8000"