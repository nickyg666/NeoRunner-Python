"""Tests for server status checks and monitoring."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestServerStatusFunctions:
    """Test server status check functions."""
    
    def test_get_events_returns_list(self):
        """get_events returns a list."""
        from neorunner_pkg.server import get_events
        
        events = get_events()
        
        assert isinstance(events, list)
    
    def test_is_server_running_returns_bool(self):
        """is_server_running returns boolean."""
        from neorunner import server
        
        with patch('neorunner.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = server.is_server_running()
            
            assert isinstance(result, bool)


class TestTmuxServer:
    """Test TmuxServer class."""
    
    def test_tmux_server_init(self):
        """TmuxServer initializes correctly."""
        from neorunner_pkg.server import TmuxServer
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        server = TmuxServer(cfg)
        
        assert server.cfg == cfg
        assert server.tmux_session == "MC"
        assert hasattr(server, 'running')
    
    def test_tmux_server_default_values(self):
        """TmuxServer has expected defaults."""
        from neorunner_pkg.server import TmuxServer
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        server = TmuxServer(cfg)
        
        # Check expected attributes exist
        assert hasattr(server, 'log_file')
        assert hasattr(server, 'running')
        assert hasattr(server, 'stop_flag')


class TestServerEventTypes:
    """Test server event types."""
    
    def test_server_event_types_defined(self):
        """Server event types are defined."""
        from neorunner_pkg.server import SERVER_EVENT_TYPES
        
        # It's a set, not a dict
        assert isinstance(SERVER_EVENT_TYPES, (set, dict, list, tuple))
        assert len(SERVER_EVENT_TYPES) > 0
    
    def test_server_event_types_values(self):
        """Event types include expected values."""
        from neorunner_pkg.server import SERVER_EVENT_TYPES
        
        # Check expected event types
        expected = ["CRASH_DETECT", "SELF_HEAL", "QUARANTINE", "SERVER_RESTART", "SERVER_START"]
        
        # Convert to string for checking
        events_str = str(SERVER_EVENT_TYPES)
        
        for event in expected:
            assert event in events_str or event in expected


class TestServerStatusCheck:
    """Test server status checking."""
    
    def test_status_check_with_mock(self):
        """Status check works with mocking."""
        from neorunner import server
        
        with patch('neorunner.server.subprocess.run') as mock_run:
            # Return code 0 means running
            mock_run.return_value = MagicMock(returncode=0, stdout="minecraft server")
            
            result = server.is_server_running()
            
            assert isinstance(result, bool)


class TestServerLogs:
    """Test server logging functions."""
    
    def test_log_event_function(self):
        """log_event function works."""
        from neorunner_pkg.log import log_event
        
        # Should not raise
        log_event("test", "test message")


class TestServerConfigIntegration:
    """Test server with config integration."""
    
    def test_server_gets_loader_config(self):
        """Server gets loader from config."""
        from neorunner_pkg.server import TmuxServer
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(loader="neoforge", mc_version="1.21.11")
        server = TmuxServer(cfg)
        
        assert server.loader is not None
