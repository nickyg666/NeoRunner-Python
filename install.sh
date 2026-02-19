#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
# NeoRunner — One-File Installer
# Modded Minecraft server manager with web dashboard, dual-source mod
# curation (Modrinth API + CurseForge scraping), crash recovery, RCON
# tellraw broadcasts, and auto-generated client install scripts.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/master/install.sh | sudo bash
#   — or —
#   wget -qO- https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/master/install.sh | sudo bash
#   — or —
#   chmod +x install.sh && sudo ./install.sh
#
# What this does:
#   1. Installs system deps (Java 21, Python 3, pip, git, tmux, xvfb)
#   2. Creates 'services' user if needed
#   3. Clones NeoRunner into /home/services, downloads ferium for mod management
#   4. Sets up Python venv + pip packages (Flask, Playwright, etc.)
#   5. Installs Playwright Chromium (for CurseForge scraping)
#   6. Creates + enables systemd service (auto-start on boot)
#   7. Starts NeoRunner (first run triggers interactive setup wizard)
#
# After install, open http://<your-ip>:8000 for the dashboard.
# ══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }
step()  { echo -e "\n${BOLD}═══ $* ═══${NC}"; }

# ── Root check ───────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root (use sudo)."
fi

REPO="https://github.com/nickyg666/NeoRunner-Python.git"
BRANCH="master"
INSTALL_DIR="/opt/NeoRunner"
SERVICE_USER="ec2user"
SERVICE_NAME="mcserver"
VENV_DIR="$INSTALL_DIR/neorunner_env"
echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           NeoRunner — Modded MC Server Manager          ║"
echo "║                    One-File Installer                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. System packages ──────────────────────────────────────────────
step "1/7  Installing system packages"

export DEBIAN_FRONTEND=noninteractive

# Detect package manager
if command -v apt-get &>/dev/null; then
    PKG="apt"
elif command -v dnf &>/dev/null; then
    PKG="dnf"
elif command -v yum &>/dev/null; then
    PKG="yum"
else
    fail "Unsupported package manager. Need apt, dnf, or yum."
fi

if [[ "$PKG" == "apt" ]]; then
    info "Updating apt cache..."
    apt-get update -qq

    info "Installing Java 21, Python 3, git, tmux..."
    apt-get install -y -qq \
        openjdk-21-jre-headless \
        python3 python3-pip python3-venv \
        git tmux curl wget unzip \
        2>&1 | tail -5

    # Java 21 might not be in default repos on older Ubuntu
    if ! java -version 2>&1 | grep -q "21\|22\|23"; then
        warn "Java 21 not found in default repos, trying Adoptium..."
        apt-get install -y -qq software-properties-common
        add-apt-repository -y ppa:openjdk-r/ppa 2>/dev/null || true
        apt-get update -qq
        apt-get install -y -qq openjdk-21-jre-headless 2>&1 | tail -3
    fi
elif [[ "$PKG" == "dnf" ]] || [[ "$PKG" == "yum" ]]; then
    info "Installing Java 21, Python 3, git, tmux..."
    $PKG install -y --skip-broken \
        java-21-amazon-corretto\
        python3 python3-pip \
        git tmux curl wget unzip \
        2>&1 | tail -5
fi

# Verify critical deps
command -v java    &>/dev/null || fail "Java not installed"
command -v python3 &>/dev/null || fail "Python 3 not installed"
command -v tmux    &>/dev/null || fail "tmux not installed"

JAVA_VER=$(java -version 2>&1 | head -1)
PYTHON_VER=$(python3 --version)
ok "Java:   $JAVA_VER"
ok "Python: $PYTHON_VER"

# ── 2. Create service user ──────────────────────────────────────────
step "2/7  Setting up '$SERVICE_USER' user"

if id "$SERVICE_USER" &>/dev/null; then
    ok "User '$SERVICE_USER' already exists"
else
    info "Creating user '$SERVICE_USER'..."
    useradd -m -s /bin/bash "$SERVICE_USER"
    ok "User '$SERVICE_USER' created"
fi

# ── 3. Clone repos ───────────────────────────────────────────────────
step "3/7  Cloning NeoRunner"


if [[ -d "$INSTALL_DIR" ]] && [[ "$(ls -A $INSTALL_DIR 2>/dev/null)" ]]; then
    # Home dir exists with stuff in it but no git repo
    info "Existing files found in $INSTALL_DIR, cloning into temp and merging..."
    TMPDIR=$(mktemp -d)
    git clone --branch "$BRANCH" "$REPO" "$TMPDIR" 2>&1 | tail -6

    # Copy repo files (don't overwrite existing config/mods)
    cp -rn "$TMPDIR/." "$INSTALL_DIR/" 2>/dev/null || true
    # Make sure .git is there
    cp -r "$TMPDIR/.git" "$INSTALL_DIR/.git"
    rm -rf "$TMPDIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    ok "Repo merged into existing directory"
else
    info "Cloning fresh..."
    git clone --branch "$BRANCH" "$REPO" "$INSTALL_DIR" 2>&1 | tail -6
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    if
        ok "Repository cloned to $INSTALL_DIR"
    fi
fi
#download UNZIP AND move FERIUM
wget https://github.com/gorilla-devs/ferium/releases/download/v4.7.1/ferium-linux-nogui.zip
unzip ferium*.zip
mv ferium/ferium .

# ── 4. Python venv + packages ───────────────────────────────────────
step "4/7  Setting up Python environment"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    su - "$SERVICE_USER" -c "python3 -m venv $VENV_DIR"
fi

info "Installing Python packages..."
su - "$SERVICE_USER" -c "$VENV_DIR/bin/pip install --upgrade pip -q"
su - "$SERVICE_USER" -c "$VENV_DIR/bin/pip install -q -r $INSTALL_DIR/requirements.txt"
ok "Python packages installed"

# Also install to system Python so systemd can use either
info "Installing core packages to system Python (fallback)..."
pip3 install --break-system-packages -q Flask requests playwright playwright-stealth 2>/dev/null || \
    pip3 install -q Flask requests playwright playwright-stealth 2>/dev/null || \
    warn "System pip install failed (non-fatal, venv will be used)"

# ── 5. Playwright browser ───────────────────────────────────────────
step "5/7  Installing Playwright Chromium"

info "This downloads ~150 MB of Chromium for headless CurseForge scraping..."
su - "$SERVICE_USER" -c "$VENV_DIR/bin/python3 -m playwright install chromium" 2>&1 | tail -5
# Install system deps for Playwright
$VENV_DIR/bin/python3 -m playwright install-deps 2>&1 | tail -5 || \
    warn "Playwright deps install had issues (may still work)"
ok "Playwright Chromium installed"

# ── 6. Systemd service ──────────────────────────────────────────────
step "6/7  Creating systemd service"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" << SERVICEEOF
[Unit]
Description=NeoRunner Minecraft Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/run.py run
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/live.log
StandardError=append:$INSTALL_DIR/live.log
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$INSTALL_DIR"

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" 2>/dev/null
ok "Service '$SERVICE_NAME' created and enabled"

# ── 7. Create mods directory ────────────────────────────────────────
step "7/7  Final setup"

su - "$SERVICE_USER" -c "mkdir -p $INSTALL_DIR/mods/clientonly"
su - "$SERVICE_USER" -c "mkdir -p $INSTALL_DIR/backups"

# Fix ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── Accept EULA (required for MC server to start) ───────────────────
if [[ ! -f "$INSTALL_DIR/eula.txt" ]]; then
    info "Pre-accepting Minecraft EULA..."
    su - "$SERVICE_USER" -c "echo 'eula=true' > $INSTALL_DIR/eula.txt"
fi

ok "Directory structure ready"

# ── Start it ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║${NC}  ${GREEN}Installation complete!${NC}                                  ${BOLD}║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}Start the server:${NC}                                       ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    sudo systemctl start $SERVICE_NAME                       ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}View logs:${NC}                                              ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    tail -f $INSTALL_DIR/live.log                  ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}Dashboard:${NC}                                              ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    http://<your-ip>:8000                                 ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}Minecraft server:${NC}                                       ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    <your-ip>:25565 (default, configurable)               ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${YELLOW}First run will prompt for server setup (loader,${NC}         ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${YELLOW}MC version, RCON password, etc).${NC}                       ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}Useful commands:${NC}                                        ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    sudo systemctl status $SERVICE_NAME                     ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    sudo systemctl restart $SERVICE_NAME                    ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    sudo systemctl stop $SERVICE_NAME                       ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

read -rp "Start NeoRunner now? [Y/n] " START_NOW
START_NOW=${START_NOW:-Y}
if [[ "${START_NOW,,}" == "y" ]]; then
    info "Starting $SERVICE_NAME..."
    systemctl start "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "NeoRunner is running!"
        info "Dashboard: http://$(hostname -I | awk '{print $1}'):8000"
        info "Logs: tail -f $INSTALL_DIR/live.log"
    else
        warn "Service started but may still be initializing."
        warn "Check: sudo systemctl status $SERVICE_NAME"
        warn "Logs:  tail -f $INSTALL_DIR/live.log"
    fi
else
    info "Run 'sudo systemctl start $SERVICE_NAME' when ready."
fi
