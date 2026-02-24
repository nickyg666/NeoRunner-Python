#!/bin/bash
#
# NeoRunner - Fully Automated Minecraft Server Setup
# Installs and configures a complete modded Minecraft server with:
# - NeoForge/Fabric/Forge support
# - Automatic mod management via Ferium
# - Web-based dashboard for administration
# - RCON for server control
# - Automated backups and monitoring
#
# Usage: bash setup.sh
#

set -e

CWD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$CWD/neorunner_env"
PYTHON_BIN="$VENV_DIR/bin/python3"
PIP_BIN="$VENV_DIR/bin/pip"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}NeoRunner - Minecraft Server Setup${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Step 1: Check system dependencies
echo -e "${YELLOW}[1/6]${NC} Checking system dependencies..."
for pkg in tmux curl rsync unzip zip java git; do
    if ! command -v $pkg &> /dev/null; then
        echo -e "${RED}✗${NC} Missing: $pkg"
        echo "Install with: sudo apt-get install -y $pkg"
        exit 1
    fi
done
echo -e "${GREEN}✓${NC} All system dependencies found"

# Step 2: Create Python virtual environment
echo -e "\n${YELLOW}[2/6]${NC} Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} Virtual environment created"
else
    echo -e "${GREEN}✓${NC} Virtual environment already exists"
fi

# Step 3: Install Python dependencies
echo -e "\n${YELLOW}[3/6]${NC} Installing Python dependencies..."
$PIP_BIN install --quiet --upgrade pip setuptools wheel
$PIP_BIN install --quiet \
    selenium \
    requests \
    beautifulsoup4 \
    lxml \
    flask \
    apscheduler

echo -e "${GREEN}✓${NC} Python dependencies installed"

# Step 4: Download and install Ferium
echo -e "\n${YELLOW}[4/6]${NC} Installing Ferium mod manager..."
FERIUM_DIR="$CWD/.local/bin"
mkdir -p "$FERIUM_DIR"

if [ ! -f "$FERIUM_DIR/ferium" ]; then
    echo "  Downloading Ferium v4.7.1..."
    TMP_DIR=$(mktemp -d)
    cd "$TMP_DIR"
    
    # Detect architecture
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        ARCH="x86_64"
    elif [ "$ARCH" = "aarch64" ]; then
        ARCH="arm64"
    else
        echo -e "${RED}✗${NC} Unsupported architecture: $ARCH"
        exit 1
    fi
    
    # Download appropriate binary
    curl -L -o ferium-nogui.zip "https://github.com/gorilla-devs/ferium/releases/download/v4.7.1/ferium-linux-nogui.zip" 2>/dev/null
    unzip -q ferium-nogui.zip
    chmod +x ferium
    mv ferium "$FERIUM_DIR/"
    
    cd "$CWD"
    rm -rf "$TMP_DIR"
    
    echo -e "${GREEN}✓${NC} Ferium installed"
else
    echo -e "${GREEN}✓${NC} Ferium already installed"
fi

# Step 5: Create necessary directories
echo -e "\n${YELLOW}[5/6]${NC} Creating server directories..."
mkdir -p "$CWD/mods"
mkdir -p "$CWD/backups"
mkdir -p "$CWD/cache"
mkdir -p "$CWD/static"
echo -e "${GREEN}✓${NC} Directories created"

# Step 6: Install systemd service
echo -e "\n${YELLOW}[6/6]${NC} Registering with systemd..."
SYSTEMD_SERVICE="/etc/systemd/system/neorunner.service"
if [ ! -f "$SYSTEMD_SERVICE" ]; then
    cat > /tmp/neorunner.service << 'EOF'
[Unit]
Description=NeoRunner Minecraft Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=services
WorkingDirectory=/home/services
ExecStart=/home/services/neorunner_env/bin/python3 /home/services/run.py run
Restart=always
RestartSec=10
StandardOutput=append:/home/services/live.log
StandardError=append:/home/services/live.log
Environment="PATH=/home/services/neorunner_env/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF
    
    echo "  Systemd service file created at: /tmp/neorunner.service"
    echo "  To install as root: sudo cp /tmp/neorunner.service $SYSTEMD_SERVICE"
    echo "  Then: sudo systemctl daemon-reload && sudo systemctl enable neorunner"
else
    echo -e "${GREEN}✓${NC} Systemd service already registered"
fi

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}\n"

echo "Next steps:"
echo "1. Run the server: $PYTHON_BIN $CWD/run.py run"
echo "2. Or start as systemd service: sudo systemctl start neorunner"
echo "3. Access dashboard at: http://localhost:8001"
echo "4. Download mods from: http://localhost:8000"
echo ""
echo "Configuration file: $CWD/config.json"
echo "Server logs: $CWD/live.log"
echo ""
