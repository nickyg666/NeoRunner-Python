#!/bin/bash
# NeoRunner Process Manager
# Usage: ./manage.sh [start|stop|restart|status|logs|install-service]

TMUX_SESSION="MC"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

install_service() {
    echo "Installing systemd service..."
    
    # Get the directory where neorunner is installed
    INSTALL_DIR=$(python3 -c "import neorunner; print('/'.join(neorunner.__file__.split('/')[:-1]))")
    
    # Create dynamic service file
    cat > /tmp/neorunner.service << EOF
[Unit]
Description=NeoRunner Minecraft Server Manager
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 -m neorunner.dashboard
Restart=on-failure
RestartSec=10
Environment=PYTHONPATH=$INSTALL_DIR/..

[Install]
WantedBy=multi-user.target
EOF
    
    # Copy service file
    sudo cp /tmp/neorunner.service /etc/systemd/system/
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    # Enable service
    sudo systemctl enable neorunner
    
    echo "Service installed. Use 'systemctl start neorunner' to start."
}

case "$1" in
    stop)
        echo "Stopping NeoRunner..."
        
        # Stop tmux server session
        tmux -S /tmp/tmux-1000/default send-keys -t "$TMUX_SESSION" 'stop' Enter 2>/dev/null
        sleep 3
        tmux -S /tmp/tmux-1000/default kill-session -t "$TMUX_SESSION" 2>/dev/null
        
        # Kill any Python dashboard processes
        pkill -f "neorunner.dashboard" 2>/dev/null
        pkill -f "flask.*8000" 2>/dev/null
        pkill -f "python.*dashboard" 2>/dev/null
        
        echo "Stopped."
        ;;
        
    start)
        echo "Starting NeoRunner..."
        
        # Install module if needed (one-time)
        if ! python3 -c "import neorunner" 2>/dev/null; then
            echo "Installing neorunner module..."
            pip install -e . -q
        fi
        
        # Start dashboard in background
        nohup python3 -m neorunner.dashboard > /tmp/neorunner_dashboard.log 2>&1 &
        echo "Dashboard started (check /tmp/neorunner_dashboard.log)"
        ;;
        
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
        
    status)
        if tmux -S /tmp/tmux-1000/default has-session -t "$TMUX_SESSION" 2>/dev/null; then
            echo "Server: RUNNING"
        else
            echo "Server: STOPPED"
        fi
        
        if pgrep -f "neorunner.dashboard" > /dev/null; then
            echo "Dashboard: RUNNING"
        else
            echo "Dashboard: STOPPED"
        fi
        
        if systemctl is-active --quiet neorunner 2>/dev/null; then
            echo "Systemd: ENABLED"
        fi
        ;;
        
    logs)
        tail -f live.log
        ;;
        
    install-service)
        install_service
        ;;
        
    enable)
        sudo systemctl enable neorunner
        sudo systemctl start neorunner
        ;;
        
    disable)
        sudo systemctl stop neorunner
        sudo systemctl disable neorunner
        ;;
        
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|install-service|enable|disable}"
        exit 1
        ;;
esac
