"""Tests for log management."""

import pytest
import sys
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.log_manager import LogManager
from neorunner_pkg.config import ServerConfig


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

    def test_cleanup_crash_reports_dir_missing(self):
        """Returns 0 when crash-reports dir doesn't exist."""
        cfg = ServerConfig(crash_report_retention_days=30)
        mgr = LogManager(cfg)
        mgr.crash_reports_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        assert mgr._cleanup_crash_reports() == 0

    def test_rotate_live_log_missing(self):
        """Returns False when live.log doesn't exist."""
        cfg = ServerConfig(live_log_max_size_mb=10)
        mgr = LogManager(cfg)
        mgr.live_log = Path(tempfile.mkdtemp()) / "nope.log"
        assert mgr._rotate_live_log() is False

    def test_cleanup_old_logs_missing_live_log(self):
        """Returns 0 when live.log doesn't exist."""
        mgr = LogManager(ServerConfig())
        mgr.live_log = Path(tempfile.mkdtemp()) / "nope.log"
        assert mgr._cleanup_old_logs() == 0

    def test_rotate_live_log_full_rotation(self):
        """Rotates existing backups up the chain and creates fresh log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            live_log = tmp / "live.log"
            live_log.write_text("x" * (11 * 1024 * 1024))  # 11MB > 10MB max

            for i in (1, 2):
                (tmp / f"live.log.{i}").write_text(f"backup {i}")

            cfg = ServerConfig(live_log_max_size_mb=10, live_log_backup_count=3)
            mgr = LogManager(cfg)
            mgr.live_log = live_log
            mgr.cwd = tmp

            rotated = mgr._rotate_live_log()

            assert rotated is True
            assert (tmp / "live.log.1").exists()
            assert (tmp / "live.log.2").exists()
            assert (tmp / "live.log.3").exists()
            assert live_log.exists()  # re-created empty
            assert live_log.stat().st_size == 0

    def test_cleanup(self):
        """cleanup() returns summary dict and handles missing dirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            crash_dir = tmp / "crash-reports"
            crash_dir.mkdir()
            old_crash = crash_dir / "old.txt"
            old_crash.write_text("old")
            old_time = time.time() - (35 * 24 * 60 * 60)
            os.utime(old_crash, (old_time, old_time))

            live_log = tmp / "live.log"
            live_log.write_text("current")
            cfg = ServerConfig(crash_report_retention_days=30, log_retention_days=30,
                               live_log_max_size_mb=10)
            mgr = LogManager(cfg)
            mgr.cwd = tmp
            mgr.live_log = live_log
            mgr.crash_reports_dir = crash_dir

            summary = mgr.cleanup()

            assert summary["crash_reports_deleted"] == 1
            assert summary["log_rotated"] is False
            assert summary["old_logs_deleted"] == 0
            assert not old_crash.exists()

    def test_cleanup_tolerates_permission_errors(self, monkeypatch):
        """Cleanup tolerates permission errors during unlink/move."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            crash_dir = tmp / "crash-reports"
            crash_dir.mkdir()
            old_crash = crash_dir / "old.txt"
            old_crash.write_text("old")
            old_time = time.time() - (35 * 24 * 60 * 60)
            os.utime(old_crash, (old_time, old_time))

            live_log = tmp / "live.log"
            live_log.write_text("x" * (11 * 1024 * 1024))
            (tmp / "live.log.1").write_text("backup")
            (tmp / "live.log.5").write_text("existing dst")
            old_time = time.time() - (35 * 24 * 60 * 60)
            os.utime(tmp / "live.log.1", (old_time, old_time))

            cfg = ServerConfig(crash_report_retention_days=30, live_log_max_size_mb=10,
                               live_log_backup_count=5)
            mgr = LogManager(cfg)
            mgr.cwd = tmp
            mgr.live_log = live_log
            mgr.crash_reports_dir = crash_dir

            def _deny(*args, **kwargs):
                raise PermissionError("denied")

            monkeypatch.setattr(mgr, "live_log", live_log)
            with monkeypatch.context() as m:
                m.setattr("pathlib.Path.unlink", _deny)
                m.setattr("shutil.move", _deny)
                summary = mgr.cleanup()
            assert summary["log_rotated"] is False  # move failed -> returns False
            assert summary["crash_reports_deleted"] == 0

    def test_rotate_tolerates_touch_failure(self, monkeypatch):
        """Rotation succeeds even if recreating live.log fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            live_log = tmp / "live.log"
            live_log.write_text("x" * (11 * 1024 * 1024))

            cfg = ServerConfig(live_log_max_size_mb=10, live_log_backup_count=5)
            mgr = LogManager(cfg)
            mgr.cwd = tmp
            mgr.live_log = live_log

            def _deny(*args, **kwargs):
                raise PermissionError("denied")

            with monkeypatch.context() as m:
                m.setattr("pathlib.Path.touch", _deny)
                assert mgr._rotate_live_log() is True
            assert (tmp / "live.log.1").exists()
