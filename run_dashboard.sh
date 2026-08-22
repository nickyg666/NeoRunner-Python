#!/bin/bash
#
# NeoRunner Dashboard Startup Script
# Production-ready with proper logging and error handling
#

set -euo pipefail

NEORUNNER_DIR="/home/host/neorunner"
VENV_DIR="$NEORUNNER_DIR/venv_314"
LOG_DIR="$NEORUNNER_DIR/logs"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

cd "$NEORUNNER_DIR"

echo "============================================"
echo "NeoRunner Dashboard Starting"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

# Check virtual environment
if [ ! -f "$VENV_DIR/bin/gunicorn" ]; then
    echo "ERROR: Virtual environment not found at $VENV_DIR"
    echo "Please run: python3 -m venv $VENV_DIR && $VENV_DIR/bin/pip install flask gunicorn"
    exit 1
fi

# Export environment
export PATH="$VENV_DIR/bin:$PATH"
export VIRTUAL_ENV="$VENV_DIR"
export PYTHONPATH="$NEORUNNER_DIR"

# Start gunicorn with production settings
# Import from neorunner_pkg (properly structured package)
exec "$VENV_DIR/bin/gunicorn" \
    --bind 127.0.0.1:8000 \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile "$LOG_DIR/access.log" \
    --error-logfile "$LOG_DIR/error.log" \
    --capture-output \
    --enable-stdio-inheritance \
    --daemon \
    --pid "$LOG_DIR/dashboard.pid" \
    "neorunner_pkg.dashboard:app"

echo "Dashboard started successfully"
echo "Access at: http://localhost:8000"
echo "PID stored in: $LOG_DIR/dashboard.pid"
