"""Tests for constants and utility functions."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConstants:
    """Test constants module."""
    
    def test_cwd_is_path(self):
        """CWD is a Path."""
        from neorunner_pkg.constants import CWD
        
        assert CWD is not None
    
    def test_max_restart_attempts(self):
        """MAX_RESTART_ATTEMPTS is defined."""
        from neorunner_pkg.constants import MAX_RESTART_ATTEMPTS
        
        assert isinstance(MAX_RESTART_ATTEMPTS, int)
        assert MAX_RESTART_ATTEMPTS > 0
    
    def test_max_total_restarts(self):
        """MAX_TOTAL_RESTARTS is defined."""
        from neorunner_pkg.constants import MAX_TOTAL_RESTARTS
        
        assert isinstance(MAX_TOTAL_RESTARTS, int)
    
    def test_crash_cooldown(self):
        """CRASH_COOLDOWN_SECONDS is defined."""
        from neorunner_pkg.constants import CRASH_COOLDOWN_SECONDS
        
        assert CRASH_COOLDOWN_SECONDS > 0
    
    def test_parallel_ports(self):
        """PARALLEL_PORTS is defined."""
        from neorunner_pkg.constants import PARALLEL_PORTS
        
        assert isinstance(PARALLEL_PORTS, dict)
        assert "rcon" in PARALLEL_PORTS
        assert "http" in PARALLEL_PORTS
        assert "minecraft" in PARALLEL_PORTS
    
    def test_mod_loaders_defined(self):
        """MOD_LOADERS is defined."""
        from neorunner_pkg.constants import MOD_LOADERS
        
        assert isinstance(MOD_LOADERS, (list, tuple))
        assert "neoforge" in MOD_LOADERS or "forge" in MOD_LOADERS


class TestVersionFunctions:
    """Test version functions."""
    
    def test_get_latest_minecraft_version(self):
        """get_latest_minecraft_version returns string."""
        from neorunner_pkg.version import get_latest_minecraft_version
        
        version = get_latest_minecraft_version()
        
        assert isinstance(version, str)
        assert len(version) > 0
    
    def test_get_all_minecraft_versions(self):
        """get_all_minecraft_versions returns list."""
        from neorunner_pkg.version import get_all_minecraft_versions
        
        versions = get_all_minecraft_versions()
        
        assert isinstance(versions, list)
        assert len(versions) > 0


class TestLogManager:
    """Test log manager functions."""
    
    def test_log_manager_imports(self):
        """Log manager imports work."""
        from neorunner_pkg import log_manager
        
        # Just import the module
        assert log_manager is not None
    
    def test_run_log_cleanup_returns_dict(self):
        """run_log_cleanup returns dict."""
        from neorunner_pkg.log_manager import run_log_cleanup
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        
        result = run_log_cleanup(cfg)
        
        assert isinstance(result, dict)


class TestSelfHeal:
    """Test self-heal functions."""
    
    def test_self_heal_imports(self):
        """Self heal module imports."""
        from neorunner_pkg import self_heal
        
        assert self_heal is not None


class TestMods:
    """Test mods module functions."""
    
    def test_mods_imports(self):
        """Mods module imports."""
        from neorunner_pkg import mods
        
        # Just verify module can be imported
        assert mods is not None


class TestLogEvent:
    """Test log_event function."""
    
    def test_log_event_basic(self):
        """log_event basic functionality."""
        from neorunner_pkg.log import log_event
        
        # Should not raise
        log_event("TEST", "Test message")
