"""Logging utilities for NeoRunner with rotating file handler."""

import logging
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .constants import CWD

# Configure the rotating file handler for production
LOG_FILE = CWD / "logs" / "neorunner.log"
LOG_FILE.parent.mkdir(exist_ok=True)

# Maximum 10MB per file, keep 5 backup files = 50MB total max
MAX_BYTES = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5

def get_logger(name: str = "neorunner") -> logging.Logger:
    """Get or create a configured logger with rotating file handler."""
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        
        # Rotating file handler
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Log format
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        
        # Also log to console for debugging
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


# Default logger instance
logger = get_logger("neorunner")


def log_event(event_type: str, msg: str) -> None:
    """Log an event to the rotating log file and live.log for compatibility.
    
    Args:
        event_type: Type of event (INFO, ERROR, WARNING, etc.)
        msg: Message to log
    """
    # Map event_type to logging level
    level_map = {
        "INFO": logging.INFO,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "DEBUG": logging.DEBUG,
        "CRITICAL": logging.CRITICAL,
    }
    level = level_map.get(event_type.upper(), logging.INFO)
    
    logger.log(level, f"[{event_type}] {msg}")
    
    # Also write to live.log for backward compatibility
    live_log_file = CWD / "live.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} | [{event_type}] {msg}\n"
    
    with open(live_log_file, "a") as f:
        f.write(log_line)


# For direct use: from log import log_event
logger = get_logger("neorunner")
