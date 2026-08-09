#!/bin/bash
#
# NeoRunner launch script
#
#   - Port 8000  : Admin dashboard (LAN) - http://IP:8000/admin
#   - Port 8005  : Public download site (local only) - via Cloudflare Tunnel at mc.w8.mom
#
# Production-ready with proper logging and error handling
#

set -euo pipefail

NEORUNNER_DIR="/home/host/neorunner"
VENV_DIR="$NEORUNNER_DIR/venv_314"
LOG_DIR="$NEORUNNER_DIR/logs"
PID_DASH="$LOG_DIR/dashboard.pid"
PID_PUBLIC="$LOG_DIR/public_site.pid"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

cd "$NEORUNNER_DIR"

echo "============================================"
echo "NeoRunner Services Starting"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

# Check virtual environment
if [ ! -f "$VENV_DIR/bin/gunicorn" ]; then
    echo "ERROR: Virtual environment not found at $VENV_DIR"
    echo "Please run: python3 -m venv $VENV_DIR && $VENV_DIR/bin/pip install flask gunicorn"
    exit 1
fi

export PATH="$VENV_DIR/bin:$PATH"
export VIRTUAL_ENV="$VENV_DIR"
export PYTHONPATH="$NEORUNNER_DIR"

# Stop any existing instances
for pid_file in "$PID_DASH" "$PID_PUBLIC"; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi
done

# Start the admin dashboard (LAN only - 0.0.0.0:8000, admin at /admin)
"$VENV_DIR/bin/gunicorn" \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile "$LOG_DIR/access.log" \
    --error-logfile "$LOG_DIR/error.log" \
    --capture-output \
    --daemon \
    --pid "$PID_DASH" \
    "neorunner_pkg.dashboard:app"

# Start the public download site (proxied by caddy from mc.w8.mom)
"$VENV_DIR/bin/gunicorn" \
    --bind 127.0.0.1:8005 \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --access-logfile "$LOG_DIR/public_access.log" \
    --error-logfile "$LOG_DIR/error.log" \
    --capture-output \
    --daemon \
    --pid "$PID_PUBLIC" \
    "neorunner_pkg.public_site:app"

sleep 2

echo "Admin dashboard:  http://localhost:8000/admin"
echo "Public site:      http://localhost:8005 (via Cloudflare Tunnel -> mc.w8.mom)"
echo "PIDs stored in:   $LOG_DIR/dashboard.pid, $LOG_DIR/public_site.pid"