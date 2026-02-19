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
#   1. Installs system deps (Java 21, Python 3, pip, git, tmux)
#   2. Creates service user if needed
#   3. Clones NeoRunner, downloads ferium for mod management
#   4. Sets up Python venv + pip packages (Flask, Playwright, etc.)
#   5. Installs Playwright Chromium (for CurseForge scraping)
#   6. Creates systemd service (auto-start on boot)
#   7. Runs NeoRunner (prompts for loader, installs it, starts server)
#
# The loader (NeoForge/Fabric/Forge) is installed on first run based on
# user selection. Run again anytime to update.
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

# ── Determine install directory ──────────────────────────────────────
# Use SUDO_USER's home if available, otherwise /opt/NeoRunner
if [[ -n "${SUDO_USER:-}" ]]; then
    SUDO_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    INSTALL_DIR="${SUDO_HOME}/NeoRunner"
    SERVICE_USER="$SUDO_USER"
else
    INSTALL_DIR="/opt/NeoRunner"
    SERVICE_USER="neorunner"
fi

SERVICE_NAME="mcserver"
VENV_DIR="$INSTALL_DIR/neorunner_env"
FERIUM_DIR="$INSTALL_DIR/.local/bin"

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           NeoRunner — Modded MC Server Manager          ║"
echo "║                    One-File Installer                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

info "Installing to: $INSTALL_DIR"
info "Service user: $SERVICE_USER"

# ── 1. System packages ──────────────────────────────────────────────
step "1/6  Installing system packages"

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
        python3 python3-pip python3-venv \
        git tmux curl wget unzip \
        2>&1 | tail -5

    # Try multiple Java 21 providers (openjdk, temurin, corretto)
    if ! java -version 2>&1 | grep -qE "21|22|23"; then
        info "Installing Java 21..."
        apt-get install -y -qq openjdk-21-jre-headless 2>&1 | tail -3 || \
            { info "Trying Eclipse Temurin..."; apt-get install -y -qq temurin-21-jre 2>&1 | tail -3; } || \
            { info "Trying Amazon Corretto..."; apt-get install -y -qq java-21-amazon-corretto-jre 2>&1 | tail -3; } || \
            warn "Could not auto-install Java 21, please install manually"
    fi
elif [[ "$PKG" == "dnf" ]] || [[ "$PKG" == "yum" ]]; then
    info "Installing Java 21, Python 3, git, tmux..."
    $PKG install -y --skip-broken \
        python3 python3-pip \
        git tmux curl wget unzip \
        2>&1 | tail -5

    # Try multiple Java 21 providers for RHEL/Amazon Linux
    if ! java -version 2>&1 | grep -qE "21|22|23"; then
        info "Installing Java 21..."
        $PKG install -y --skip-broken java-21-openjdk-headless 2>&1 | tail -3 || \
            $PKG install -y --skip-broken java-21-amazon-corretto 2>&1 | tail -3 || \
            $PKG install -y --skip-broken java-21-temurin 2>&1 | tail -3 || \
            warn "Could not auto-install Java 21, please install manually"
    fi
fi

# Verify critical deps
command -v java    &>/dev/null || fail "Java not installed - please install Java 21+ manually"
command -v python3 &>/dev/null || fail "Python 3 not installed"
command -v tmux    &>/dev/null || fail "tmux not installed"

# Verify Java version (accept any 21+)
JAVA_VER=$(java -version 2>&1 | head -1)
if ! echo "$JAVA_VER" | grep -qE "21|22|23|24"; then
    warn "Java version may be too old: $JAVA_VER"
    warn "NeoRunner requires Java 21+. Server may fail to start."
fi

PYTHON_VER=$(python3 --version)
ok "Java:   $JAVA_VER"
ok "Python: $PYTHON_VER"

# ── 2. Create service user ──────────────────────────────────────────
step "2/6  Setting up '$SERVICE_USER' user"

if id "$SERVICE_USER" &>/dev/null; then
    ok "User '$SERVICE_USER' already exists"
else
    info "Creating user '$SERVICE_USER'..."
    useradd -m -s /bin/bash "$SERVICE_USER"
    ok "User '$SERVICE_USER' created"
fi

# ── 3. Clone repo ───────────────────────────────────────────────────
step "3/6  Cloning NeoRunner"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Existing repo found, pulling latest..."
    su - "$SERVICE_USER" -c "cd $INSTALL_DIR && git pull origin $BRANCH" 2>&1 | tail -3
    ok "Repository updated"
else
    if [[ -d "$INSTALL_DIR" ]] && [[ "$(ls -A $INSTALL_DIR 2>/dev/null)" ]]; then
        # Home dir exists with stuff in it but no git repo
        info "Existing files found in $INSTALL_DIR, cloning into temp and merging..."
        TMPDIR=$(mktemp -d)
        git clone --branch "$BRANCH" "$REPO" "$TMPDIR" 2>&1 | tail -3
        # Copy repo files (don't overwrite existing config/mods)
        cp -rn "$TMPDIR/." "$INSTALL_DIR/" 2>/dev/null || true
        # Make sure .git is there
        cp -r "$TMPDIR/.git" "$INSTALL_DIR/.git"
        rm -rf "$TMPDIR"
        chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
        ok "Repo merged into existing directory"
    else
        info "Cloning fresh..."
        git clone --branch "$BRANCH" "$REPO" "$INSTALL_DIR" 2>&1 | tail -3
        chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
        ok "Repository cloned to $INSTALL_DIR"
    fi
fi

# ── 3.5. Download Ferium ─────────────────────────────────────────────
info "Downloading Ferium mod manager..."

mkdir -p "$FERIUM_DIR"

if [[ -x "$FERIUM_DIR/ferium" ]]; then
    ok "Ferium already installed at $FERIUM_DIR/ferium"
else
    FERIUM_TMP=$(mktemp -d)
    cd "$FERIUM_TMP"
    
    # Detect architecture
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  FERIUM_ZIP="ferium-linux-nogui.zip" ;;
        aarch64) FERIUM_ZIP="ferium-linux-armv7-nogui.zip" ;;
        armv7l)  FERIUM_ZIP="ferium-linux-armv7-nogui.zip" ;;
        *)       warn "Unknown arch $ARCH, trying x86_64"; FERIUM_ZIP="ferium-linux-nogui.zip" ;;
    esac
    
    info "Downloading $FERIUM_ZIP for $ARCH..."
    wget -q "https://github.com/gorilla-devs/ferium/releases/download/v4.7.1/$FERIUM_ZIP" -O ferium.zip
    unzip -q ferium.zip
    
    # Find the ferium binary (might be in a subdirectory)
    FERIUM_BIN=$(find . -name "ferium" -type f 2>/dev/null | head -1)
    if [[ -n "$FERIUM_BIN" ]]; then
        mv "$FERIUM_BIN" "$FERIUM_DIR/ferium"
        chmod +x "$FERIUM_DIR/ferium"
        chown "$SERVICE_USER:$SERVICE_USER" "$FERIUM_DIR/ferium"
        ok "Ferium installed to $FERIUM_DIR/ferium"
    else
        warn "Could not find ferium binary in downloaded zip"
    fi
    
    cd "$INSTALL_DIR"
    rm -rf "$FERIUM_TMP"
fi

# ── 4. Python venv + packages ───────────────────────────────────────
step "4/6  Setting up Python environment"

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
step "5/6  Installing Playwright Chromium"

info "This downloads ~150 MB of Chromium for headless CurseForge scraping..."
su - "$SERVICE_USER" -c "$VENV_DIR/bin/python3 -m playwright install chromium" 2>&1 | tail -5
# Install system deps for Playwright
$VENV_DIR/bin/python3 -m playwright install-deps 2>&1 | tail -5 || \
    warn "Playwright deps install had issues (may still work)"
ok "Playwright Chromium installed"

# ── 6. Systemd service ──────────────────────────────────────────────
step "6/6  Creating systemd service"

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
Environment="NEORUNNER_HOME=$INSTALL_DIR"

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" 2>/dev/null
ok "Service '$SERVICE_NAME' created and enabled"

# ── Create directories ──────────────────────────────────────────────
su - "$SERVICE_USER" -c "mkdir -p $INSTALL_DIR/mods/clientonly"
su - "$SERVICE_USER" -c "mkdir -p $INSTALL_DIR/backups"

# ── Accept EULA (required for MC server to start) ───────────────────
if [[ ! -f "$INSTALL_DIR/eula.txt" ]]; then
    info "Pre-accepting Minecraft EULA..."
    su - "$SERVICE_USER" -c "echo 'eula=true' > $INSTALL_DIR/eula.txt"
fi

# Fix ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

ok "System ready"

# ── Run NeoRunner ───────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║${NC}  ${GREEN}System prep complete!${NC}                                   ${BOLD}║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  NeoRunner will now:                                     ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    • Ask you to pick a loader (NeoForge/Fabric/Forge)   ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    • Download and install it                             ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    • Start the Minecraft server in tmux                  ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}After startup:${NC}                                          ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    Dashboard: http://<your-ip>:8000                      ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    MC Server: <your-ip>:25565                            ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    Logs:      tail -f $INSTALL_DIR/live.log       ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}    MC Console: tmux attach -t MC                        ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}                                                          ${BOLD}║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

read -rp "Start NeoRunner now? [Y/n] " START_NOW
START_NOW=${START_NOW:-Y}
if [[ "${START_NOW,,}" == "y" ]]; then
    info "Starting NeoRunner..."
    cd "$INSTALL_DIR"
    
    # Run interactively so user can select loader
    su - "$SERVICE_USER" -c "cd '$INSTALL_DIR' && NEORUNNER_HOME='$INSTALL_DIR' $VENV_DIR/bin/python3 run.py run"
    
    cd - > /dev/null
else
    info "Start manually with:"
    info "  cd $INSTALL_DIR && $VENV_DIR/bin/python3 run.py run"
    info ""
    info "Or use systemd (non-interactive, uses saved config):"
    info "  sudo systemctl start $SERVICE_NAME"
fi
