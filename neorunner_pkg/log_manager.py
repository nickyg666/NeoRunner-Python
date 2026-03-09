"""Log management for NeoRunner - retention, rotation, and cleanup."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .constants import CWD
from .config import ServerConfig
from .log import log_event


class LogManager:
    """Manages log retention, rotation, and cleanup."""
    
    def __init__(self, cfg: Optional[ServerConfig] = None):
        self.cfg = cfg or ServerConfig()
        self.cwd = CWD
        self.live_log = self.cwd / "live.log"
        self.crash_reports_dir = self.cwd / "crash-reports"
    
    def cleanup(self) -> dict:
        """Run all cleanup tasks. Returns summary of actions taken."""
        actions = {
            "crash_reports_deleted": 0,
            "log_rotated": False,
            "old_logs_deleted": 0,
        }
        
        crash_deleted = self._cleanup_crash_reports()
        actions["crash_reports_deleted"] = crash_deleted
        
        log_rotated = self._rotate_live_log()
        actions["log_rotated"] = log_rotated
        
        old_deleted = self._cleanup_old_logs()
        actions["old_logs_deleted"] = old_deleted
        
        log_event("LOG_MANAGE", f"Cleanup complete: {crash_deleted} crash reports, {old_deleted} old logs removed")
        
        return actions
    
    def _cleanup_crash_reports(self) -> int:
        """Delete crash reports older than retention period."""
        if not self.crash_reports_dir.exists():
            return 0
        
        retention_days = getattr(self.cfg, 'crash_report_retention_days', 30)
        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted = 0
        
        for entry in self.crash_reports_dir.iterdir():
            if entry.is_file() and entry.suffix == ".txt":
                mtime = datetime.fromtimestamp(entry.stat().st_mtime)
                if mtime < cutoff:
                    try:
                        entry.unlink()
                        deleted += 1
                    except Exception:
                        pass
        
        return deleted
    
    def _rotate_live_log(self) -> bool:
        """Rotate live.log if it exceeds max size."""
        max_size_mb = getattr(self.cfg, 'live_log_max_size_mb', 10)
        max_size_bytes = max_size_mb * 1024 * 1024
        
        if not self.live_log.exists():
            return False
        
        if self.live_log.stat().st_size < max_size_bytes:
            return False
        
        backup_count = getattr(self.cfg, 'live_log_backup_count', 5)
        
        for i in range(backup_count - 1, 0, -1):
            src = self.live_log.with_suffix(f'.log.{i}')
            dst = self.live_log.with_suffix(f'.log.{i + 1}')
            if dst.exists():
                try:
                    dst.unlink()
                except Exception:
                    pass
            if src.exists():
                try:
                    shutil.move(str(src), str(dst))
                except Exception:
                    pass
        
        backup_1 = self.live_log.with_suffix('.log.1')
        try:
            shutil.move(str(self.live_log), str(backup_1))
        except Exception:
            return False
        
        try:
            self.live_log.touch()
        except Exception:
            pass
        
        log_event("LOG_ROTATE", f"Rotated live.log (exceeded {max_size_mb}MB)")
        
        return True
    
    def _cleanup_old_logs(self) -> int:
        """Delete old rotated log files beyond retention."""
        if not self.live_log.exists():
            return 0
        
        retention_days = getattr(self.cfg, 'log_retention_days', 30)
        cutoff = datetime.now() - timedelta(days=retention_days)
        deleted = 0
        
        for f in self.cwd.glob("live.log.*"):
            if f.is_file():
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    try:
                        f.unlink()
                        deleted += 1
                    except Exception:
                        pass
        
        return deleted


def run_log_cleanup(cfg: Optional[ServerConfig] = None) -> dict:
    """Convenience function to run log cleanup."""
    manager = LogManager(cfg)
    return manager.cleanup()


__all__ = ["LogManager", "run_log_cleanup"]
