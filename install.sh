#!/bin/bash
#
# NeoRunner - Self-contained installer
# Usage: curl -sL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/main/install.sh | bash
#

set -e

INSTALL_DIR="${INSTALL_DIR:-$HOME/neorunner}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "=== NeoRunner Installer ==="
echo "Install dir: $INSTALL_DIR"

# Clone if no .git
if [ ! -d ".git" ]; then
    echo "Cloning..."
    git clone -q -b main --depth 1 https://github.com/nickyg666/NeoRunner-Python.git .
fi

# Create venv
[ ! -d "neorunner_venv" ] && python3 -m venv neorunner_venv

# Install package
echo "Installing package..."
source neorunner_venv/bin/activate
pip install -q --break-system-packages --force-reinstall -e .

# Create directories
mkdir -p mods clientonly config backups crash-reports logs world libraries loaders

# Create eula
[ ! -f eula.txt ] && echo "eula=true" > eula.txt

# Force fresh config
rm -f config.json

# Create fresh config
echo "Creating config..."
neorunner init 2>/dev/null || true

# Set proper paths
neorunner config server_ip 192.168.0.150 2>/dev/null || true
neorunner config http_port 8000 2>/dev/null || true
neorunner config xmx 4G 2>/dev/null || true

# Create proper JVM args
echo "-Xmx4G" > user_jvm_args.txt
echo "-Xms2G" >> user_jvm_args.txt
echo "-XX:+UseG1GC" >> user_jvm_args.txt
echo "-XX:MaxGCPauseMillis=200" >> user_jvm_args.txt
echo "-Djava.net.preferIPv4Stack=true" >> user_jvm_args.txt

# Run setup
echo "Installing loader..."
neorunner setup 2>&1 || echo "Setup done"

echo "=== Ready! ==="
echo "Dashboard: http://192.168.0.150:8000"
echo "Start: cd $INSTALL_DIR && source neorunner_venv/bin/activate && neorunner start"