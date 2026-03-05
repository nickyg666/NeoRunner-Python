"""Tests for log management."""

import pytest
import sys
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.log_manager import LogManager
from neorunner.config import ServerConfig


class TestLogManager:
    """Test LogManager cleanup functions."""
    
    def test_cleanup_crash_reports_old(self):
        """Deletes crash reports older than retention period."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crash_dir = Path(tmpdir) / "crash-reports"
            crash_dir.mkdir()
            
            old_file = crash_dir / "crash-2020-01-01.txt"
            old_file.write_text("crash log")
            
            old_time = time.time() - (35 * 24 * 60 * 60)
            os.utime(old_file, (old_time, old_time))
            
            cfg = ServerConfig(crash_report_retention_days=30)
            mgr = LogManager(cfg)
            mgr.crash_reports_dir = crash_dir
            
            deleted = mgr._cleanup_crash_reports()
            
            assert deleted == 1
            assert not old_file.exists()
    
    def test_cleanup_crash_reports_recent(self):
        """Keeps recent crash reports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crash_dir = Path(tmpdir) / "crash-reports"
            crash_dir.mkdir()
            
            recent_file = crash_dir / "crash-recent.txt"
            recent_file.write_text("crash log")
            
            cfg = ServerConfig(crash_report_retention_days=30)
            mgr = LogManager(cfg)
            mgr.crash_reports_dir = crash_dir
            
            deleted = mgr._cleanup_crash_reports()
            
            assert deleted == 0
            assert recent_file.exists()
    
    def test_rotate_live_log_small(self):
        """Doesn't rotate if log is small."""
        with tempfile.TemporaryDirectory() as tmpdir:
            live_log = Path(tmpdir) / "live.log"
            live_log.write_text("small log")
            
            cfg = ServerConfig(live_log_max_size_mb=10)
            mgr = LogManager(cfg)
            mgr.live_log = live_log
            mgr.cwd = Path(tmpdir)
            
            rotated = mgr._rotate_live_log()
            
            assert rotated is False
    
    def test_cleanup_old_logs(self):
        """Deletes old rotated logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            live_log = Path(tmpdir) / "live.log"
            live_log.write_text("current log")
            
            old_log = Path(tmpdir) / "live.log.1"
            old_log.write_text("old log")
            
            old_time = time.time() - (35 * 24 * 60 * 60)
            os.utime(old_log, (old_time, old_time))
            
            cfg = ServerConfig(log_retention_days=30)
            mgr = LogManager(cfg)
            mgr.live_log = live_log
            mgr.cwd = Path(tmpdir)
            
            deleted = mgr._cleanup_old_logs()
            
            assert deleted == 1
            assert not old_log.exists()
