"""
WebSocket support for NeoRunner dashboard.
Provides real-time log streaming and server status updates.
"""

from __future__ import annotations

import os
import json
import threading
import time
from pathlib import Path
from typing import Set, Dict, Any

try:
    from flask_socketio import SocketIO, emit
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

from .config import load_cfg
from .constants import CWD
from .log import log_event

# Global socketio instance
socketio = None


def init_socketio(app):
    """Initialize SocketIO with the Flask app."""
    global socketio
    
    if not SOCKETIO_AVAILABLE:
        log_event("WEBSOCKET", "flask-socketio not available, skipping WebSocket support")
        return None
    
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
    
    # Register event handlers
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        emit('connected', {'status': 'connected', 'time': time.time()})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        pass
    
    @socketio.on('subscribe_logs')
    def handle_subscribe_logs():
        """Subscribe to real-time log updates."""
        emit('subscribed', {'channel': 'logs'})
    
    @socketio.on('unsubscribe_logs')
    def handle_unsubscribe_logs():
        """Unsubscribe from log updates."""
        emit('unsubscribed', {'channel': 'logs'})
    
    @socketio.on('subscribe_status')
    def handle_subscribe_status():
        """Subscribe to server status updates."""
        emit('subscribed', {'channel': 'status'})
    
    return socketio


class LogTailer:
    """Tails the log file and broadcasts updates via WebSocket."""
    
    def __init__(self, log_file: Path, socketio_instance):
        self.log_file = log_file
        self.socketio = socketio_instance
        self.running = False
        self.thread = None
        self.last_position = 0
    
    def start(self):
        """Start tailing the log file."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._tail, daemon=True)
        self.thread.start()
        log_event("WEBSOCKET", "Log tailer started")
    
    def stop(self):
        """Stop tailing the log file."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        log_event("WEBSOCKET", "Log tailer stopped")
    
    def _tail(self):
        """Tail the log file and emit updates."""
        # Get initial file size
        if self.log_file.exists():
            self.last_position = self.log_file.stat().st_size
        
        while self.running:
            try:
                if not self.log_file.exists():
                    time.sleep(1)
                    continue
                
                current_size = self.log_file.stat().st_size
                
                if current_size > self.last_position:
                    with open(self.log_file, 'r') as f:
                        f.seek(self.last_position)
                        new_lines = f.readlines()
                        self.last_position = f.tell()
                    
                    if new_lines and self.socketio:
                        self.socketio.emit('log_update', {
                            'lines': new_lines,
                            'timestamp': time.time()
                        }, namespace='/')
                
                elif current_size < self.last_position:
                    # File was truncated
                    self.last_position = 0
                
                time.sleep(0.5)  # Check every 500ms
            
            except Exception as e:
                log_event("WEBSOCKET_ERROR", f"Log tail error: {e}")
                time.sleep(1)


class StatusBroadcaster:
    """Broadcasts server status updates via WebSocket."""
    
    def __init__(self, socketio_instance, interval: int = 5):
        self.socketio = socketio_instance
        self.interval = interval
        self.running = False
        self.thread = None
    
    def start(self):
        """Start broadcasting status."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._broadcast, daemon=True)
        self.thread.start()
        log_event("WEBSOCKET", "Status broadcaster started")
    
    def stop(self):
        """Stop broadcasting status."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        log_event("WEBSOCKET", "Status broadcaster stopped")
    
    def _broadcast(self):
        """Broadcast status updates."""
        while self.running:
            try:
                if self.socketio:
                    from .server import is_server_running
                    cfg = load_cfg()
                    
                    status = {
                        'running': is_server_running(),
                        'loader': cfg.loader,
                        'mc_version': cfg.mc_version,
                        'timestamp': time.time()
                    }
                    
                    self.socketio.emit('status_update', status, namespace='/')
                
                time.sleep(self.interval)
            
            except Exception as e:
                log_event("WEBSOCKET_ERROR", f"Status broadcast error: {e}")
                time.sleep(self.interval)


# Global instances
log_tailer = None
status_broadcaster = None


def start_websocket_services(app):
    """Start WebSocket services if available."""
    global log_tailer, status_broadcaster, socketio
    
    if not SOCKETIO_AVAILABLE:
        return
    
    # Initialize socketio if not already done
    if socketio is None:
        socketio = init_socketio(app)
    
    if socketio is None:
        return
    
    # Start log tailer
    log_file = CWD / "live.log"
    log_tailer = LogTailer(log_file, socketio)
    log_tailer.start()
    
    # Start status broadcaster
    status_broadcaster = StatusBroadcaster(socketio)
    status_broadcaster.start()


def stop_websocket_services():
    """Stop WebSocket services."""
    global log_tailer, status_broadcaster
    
    if log_tailer:
        log_tailer.stop()
    
    if status_broadcaster:
        status_broadcaster.stop()


def emit_event(event_type: str, data: Dict[str, Any]):
    """Emit an event to all connected clients."""
    global socketio
    
    if socketio:
        socketio.emit(event_type, data, namespace='/')
