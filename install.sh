#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
# NeoRunner — Ultimate Installer
# One-File Installer for all dependencies and configurations
# 
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/master/install.sh | sudo bash
#   — or —
#   wget -qO- https://raw.githubusercontent.com/nickyg666/NeoRunner-Python/master/install.sh | sudo bash
#   — or —
#   chmod +x install.sh && sudo ./install.sh
# 
# What this does:
#   1. System dependencies (Java 21, Python 3, pip, git, tmux, etc)
#   2. Creates service user if needed
#   3. Downloads and configures NeoRunner
#   4. Sets up Python venv + pip packages (Flask, Playwright, etc)
#   5. Installs Playwright Chromium (for CurseForge scraping)
#   6. Creates systemd service (auto-start on boot)
#   7. Runs NeoRunner (prompts for loader, installs it, starts server)
#   8. Sets up complete environment with all features
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

# ── Configuration ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="NeoRunner"
PROJECT_DIR="/opt/${PROJECT_NAME,,}"
USER_NAME="${PROJECT_NAME,,}"

# ── System Detection ──────────────────────────────────────────────
DETECT_OS() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$NAME
        OS_VERSION=$VERSION_ID
        OS_ID=$ID
    else
        fail "Cannot detect operating system"
    fi
    
    case $OS_ID in
        ubuntu|debian)
            PACKAGE_MANAGER="apt"
            PACKAGE_INSTALL="apt-get install -y"
            SYSTEM_PKGS="git python3 python3-pip python3-venv tmux default-jre-headless curl wget"
            PYTHON="python3"
            PIP="pip3"
            ;;
        fedora|centos|rhel)
            PACKAGE_MANAGER="dnf"
            PACKAGE_INSTALL="dnf install -y"
            SYSTEM_PKGS="git python3 python3-pip python3-virtualenv tmux java-17-openjdk-headless curl wget"
            PYTHON="python3"
            PIP="pip3"
            ;;
        amazonlinux)
            PACKAGE_MANAGER="yum"
            PACKAGE_INSTALL="yum install -y"
            SYSTEM_PKGS="git python3 python3-pip python3-venv tmux java-17-amazon-corretto-headless curl wget"
            PYTHON="python3"
            PIP="pip3"
            ;;
        arch)
            PACKAGE_MANAGER="pacman"
            PACKAGE_INSTALL="pacman -S --noconfirm"
            SYSTEM_PKGS="git python python-pip python-virtualenv tmux jre-openjdk-headless curl wget"
            PYTHON="python"
            PIP="pip"
            ;;
        *)
            fail "Unsupported operating system: $OS_ID"
            ;;
    esac
}

# ── System Update ──────────────────────────────────────────────────
UPDATE_SYSTEM() {
    step "Updating system packages"
    case $PACKAGE_MANAGER in
        apt)
            apt-get update && apt-get upgrade -y
            ;;
        dnf)
            dnf update -y
            ;;
        yum)
            yum update -y
            ;;
        pacman)
            pacman -Syu --noconfirm
            ;;
    esac
}

# ── Install System Dependencies ─────────────────────────────────
INSTALL_SYSTEM_DEPS() {
    step "Installing system dependencies"
    $PACKAGE_INSTALL $SYSTEM_PKGS
    
    # Check Java version
    if ! command -v java &> /dev/null; then
        fail "Java installation failed"
    fi
    
    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2)
    if [[ ! $JAVA_VERSION =~ ^21.* ]] && [[ ! $JAVA_VERSION =~ ^17.* ]]; then
        warn "Recommended Java 21 or 17, found: $JAVA_VERSION"
    fi
}

# ── Create User ───────────────────────────────────────────────────
CREATE_USER() {
    step "Creating service user"
    if ! id "$USER_NAME" &>/dev/null; then
        useradd -r -s /bin/false -d "$PROJECT_DIR" "$USER_NAME"
        mkdir -p "$PROJECT_DIR"
        chown -R "$USER_NAME:$USER_NAME" "$PROJECT_DIR"
        ok "User $USER_NAME created"
    else
        ok "User $USER_NAME already exists"
    fi
}

# ── Clone Project ────────────────────────────────────────────────
CLONE_PROJECT() {
    step "Cloning NeoRunner project"
    if [[ ! -d "$PROJECT_DIR" ]]; then
        git clone https://github.com/nickyg666/NeoRunner-Python.git "$PROJECT_DIR"
        chown -R "$USER_NAME:$USER_NAME" "$PROJECT_DIR"
        ok "Project cloned to $PROJECT_DIR"
    else
        warn "Project directory already exists"
        cd "$PROJECT_DIR"
        git pull
        ok "Project updated"
    fi
}

# ── Setup Python Virtual Environment ─────────────────────────────
SETUP_PYTHON_ENV() {
    step "Setting up Python virtual environment"
    cd "$PROJECT_DIR"
    
    if [[ ! -d "neorunner_env" ]]; then
        $PYTHON -m venv neorunner_env
        chown -R "$USER_NAME:$USER_NAME" neorunner_env
        ok "Virtual environment created"
    else
        ok "Virtual environment already exists"
    fi
    
    # Activate and install dependencies
    source neorunner_env/bin/activate
    
    # Upgrade pip
    $PIP install --upgrade pip
    
    # Install requirements
    $PIP install -r requirements.txt
    
    # Install Playwright with stealth
    $PIP install playwright playwright-stealth
    
    # Install Playwright browsers
    playwright install chromium
    
    ok "Python environment setup complete"
}

# ── Setup Ferium ────────────────────────────────────────────────
SETUP_FERIUM() {
    step "Setting up Ferium mod manager"
    cd "$PROJECT_DIR"
    
    # Create .local directory
    mkdir -p .local/bin
    
    # Download Ferium
    if [[ ! -f ".local/bin/ferium" ]]; then
        FERIUM_URL="https://github.com/Altare4/ferium/releases/latest/download/ferium-linux-x86_64"
        curl -L -o .local/bin/ferium $FERIUM_URL
        chmod +x .local/bin/ferium
        chown -R "$USER_NAME:$USER_NAME" .local
        ok "Ferium downloaded"
    else
        ok "Ferium already installed"
    fi
    
    # Initialize Ferium profile
    if [[ ! -d "$HOME/.config/ferium" ]]; then
        .local/bin/ferium --help > /dev/null 2>&1 || true
        ok "Ferium profile initialized"
    fi
}

# ── Create Systemd Service ──────────────────────────────────────
CREATE_SYSTEMD_SERVICE() {
    step "Creating systemd service"
    SERVICE_FILE="/etc/systemd/system/${PROJECT_NAME,,}.service"
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=${PROJECT_NAME} Minecraft Server Manager
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/neorunner_env/bin/python $PROJECT_DIR/run.py run
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${PROJECT_NAME,,}.service
    ok "Systemd service created and enabled"
}

# ── Configure Project ────────────────────────────────────────────
CONFIGURE_PROJECT() {
    step "Configuring project"
    cd "$PROJECT_DIR"
    
    # Create config.json if it doesn't exist
    if [[ ! -f "config.json" ]]; then
        cat > config.json << EOF
{
  "server_jar": "neo.jar",
  "rcon_pass": "1",
  "rcon_port": "25575",
  "rcon_host": "127.0.0.1",
  "http_port": "8000",
  "mods_dir": "mods",
  "clientonly_dir": "mods/clientonly",
  "autostart": "yes",
  "loader": "neoforge",
  "mc_version": "1.21.11",
  "max_download_mb": 600,
  "rate_limit_seconds": 2,
  "run_curator_on_startup": true,
  "curator_limit": 250,
  "curator_show_optional_audit": true,
  "curator_max_depth": 3,
  "hostname": "127.0.0.1",
  "broadcast_enabled": true,
  "broadcast_auto_on_install": true,
  "nag_show_mod_list_on_join": false,
  "nag_first_visit_modal": false,
  "motd_show_download_url": false,
  "install_script_types": "ps1",
  "curator_sort": "downloads",
  "ferium_update_interval_hours": 24,
  "ferium_weekly_update_day": "mon",
  "ferium_weekly_update_hour": 2
}
EOF
        chown "$USER_NAME:$USER_NAME" config.json
        ok "config.json created"
    else
        ok "config.json already exists"
    fi
    
    # Create necessary directories
    mkdir -p mods mods/clientonly mixins patches manifests logs
    chown -R "$USER_NAME:$USER_NAME" mods patches manifests logs
    
    ok "Project configured"
}

# ── Start Service ───────────────────────────────────────────────
START_SERVICE() {
    step "Starting ${PROJECT_NAME} service"
    systemctl start ${PROJECT_NAME,,}
    
    # Wait for service to start
    sleep 5
    
    if systemctl is-active --quiet ${PROJECT_NAME,,}; then
        ok "${PROJECT_NAME} service is running"
        info "Dashboard available at: http://$(hostname -I | cut -d' ' -f1):8000"
        info "Server port: 1234"
        info "RCON port: 25575"
    else
        fail "Failed to start ${PROJECT_NAME} service"
    fi
}

# ── Display Summary ─────────────────────────────────────────────
DISPLAY_SUMMARY() {
    step "Installation complete!"
    echo -e "${GREEN}✓ Installation successful!${NC}"
    echo ""
    echo "${BOLD}Project:${NC}       ${PROJECT_NAME}"
    echo "${BOLD}Directory:${NC}      $PROJECT_DIR"
    echo "${BOLD}Service:${NC}        ${PROJECT_NAME,,}"
    echo "${BOLD}Dashboard:${NC}      http://$(hostname -I | cut -d' ' -f1):8000"
    echo "${BOLD}Server Port:${NC}    1234"
    echo "${BOLD}RCON Port:${NC}     25575"
    echo ""
    echo "${BOLD}Commands:${NC}"
    echo "  Start service:    systemctl start ${PROJECT_NAME,,}"
    echo "  Stop service:     systemctl stop ${PROJECT_NAME,,}"
    echo "  View logs:        journalctl -u ${PROJECT_NAME,,} -f"
    echo "  Access dashboard: http://$(hostname -I | cut -d' ' -f1):8000"
    echo ""
    echo "${BOLD}First run:${NC} The system will prompt you to select a Minecraft loader (NeoForge/Fabric/Forge)"
    echo "and install the server. This may take several minutes depending on your internet connection."
}

# ────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ────────────────────────────────────────────────────────────────

main() {
    step "Starting ${PROJECT_NAME} installation"
    
    info "Detected OS: $OS $OS_VERSION"
    info "Package manager: $PACKAGE_MANAGER"
    
    UPDATE_SYSTEM
    INSTALL_SYSTEM_DEPS
    CREATE_USER
    CLONE_PROJECT
    SETUP_PYTHON_ENV
    SETUP_FERIUM
    CONFIGURE_PROJECT
    CREATE_SYSTEMD_SERVICE
    START_SERVICE
    DISPLAY_SUMMARY
}

# ────────────────────────────────────────────────────────────────
trap 'fail "Installation interrupted"' INT TERM EXIT
main
exit 0