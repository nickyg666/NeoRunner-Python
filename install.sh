#!/bin/bash
#
# NeoRunner Quick Installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
# For fresh reinstall: rm -rf ~/neorunner && curl -sL ... | bash
#

set -e

R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
B='\033[0;34m'
NC='\033[0m'

echo -e "${B}"
echo "========================================================"
echo "           NeoRunner Installer"
echo "========================================================"
echo -e "${NC}"

echo "Checking system..."

OS=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
fi

echo "  OS: $OS"

echo "Installing system deps..."
DEPS="tmux curl wget rsync unzip zip python3 python3-venv python3-pip git"
if ! command -v java &> /dev/null; then
    DEPS="$DEPS openjdk-21-jre-headless"
fi

if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq && sudo apt-get install -y -qq $DEPS
elif command -v dnf &> /dev/null; then
    sudo dnf install -y -q $DEPS
elif command -v yum &> /dev/null; then
    sudo yum install -y -q $DEPS
fi

if ! command -v python3 &> /dev/null; then
    echo "Python 3 not found"
    exit 1
fi

echo "  Python $(python3 --version | cut -d' ' -f2)"

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
mkdir -p "$INSTALL_DIR"

echo "Installing to $INSTALL_DIR..."

cd "$INSTALL_DIR"

if [ ! -d ".git" ]; then
    echo "Cloning NeoRunner..."
    git clone -q -b main --depth 1 https://github.com/nickyg666/NeoRunner-Python.git . || {
        echo "Clone failed"
        exit 1
    }
fi

if [ ! -d "neorunner_venv" ]; then
    echo "Creating venv..."
    python3 -m venv neorunner_venv
fi

echo "Installing package..."
source neorunner_venv/bin/activate
pip install -q --upgrade pip
pip install -q --break-system-packages --force-reinstall --no-cache-dir -e .

echo "Creating directories..."
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders

if [ ! -f eula.txt ]; then
    echo "eula=true" > eula.txt
fi

if [ ! -f config.json ]; then
    echo "Creating config..."
    neorunner init || true
fi

echo ""
echo "========================================================"
echo "  NeoRunner ready!"
echo "========================================================"
echo ""
echo "  To configure interactively:"
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
echo "  NeoRunner ready!"
echo "========================================================"
echo ""
echo "  To start server:"
echo "    cd $INSTALL_DIR"
echo "    source neorunner_venv/bin/activate"
echo "    neorunner start"
echo ""
echo "  Dashboard: http://localhost:8000"
echo ""