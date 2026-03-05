"""Logging utilities for NeoRunner."""

from datetime import datetime
from pathlib import Path

from .constants import CWD


def log_event(event_type: str, msg: str) -> None:
    """Log an event to live.log.
    
    Args:
        event_type: Type of event (INFO, ERROR, WARNING, etc.)
        msg: Message to log
    """
    log_file = CWD / "live.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} | [{event_type}] {msg}\n"
    
    with open(log_file, "a") as f:
        f.write(log_line)
