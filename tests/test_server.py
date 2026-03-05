"""Tests for server management."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.server import (
    get_server,
    is_server_running,
    send_command,
    get_events,
    _add_event,
)


class TestServer:
    """Test server functions."""
    
    def test_get_server_returns_tmuxserver(self):
        """get_server returns a TmuxServer instance."""
        with patch('neorunner.server.TmuxServer') as mock:
            mock_instance = MagicMock()
            mock.return_value = mock_instance
            
            server = get_server()
            
            assert mock.called
    
    def test_is_server_running(self):
        """is_server_running returns bool."""
        with patch('neorunner.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            result = is_server_running()
            
            assert isinstance(result, bool)
    
    def test_send_command_returns_bool(self):
        """send_command returns bool."""
        with patch('neorunner.server._server_instance') as mock_instance:
            mock_instance.send_command.return_value = True
            
            result = send_command("test")
            
            assert result is True or result is False
    
    def test_send_command_returns_false_when_not_running(self):
        """send_command returns False when server not running."""
        with patch('neorunner.server._server_instance', None):
            result = send_command("test")
            
            assert result is False
    
    def test_get_events_returns_list(self):
        """get_events returns a list."""
        events = get_events()
        
        assert isinstance(events, list)
    
    def test_add_event(self):
        """_add_event adds event to in-memory store."""
        initial_count = len(get_events())
        
        _add_event("TEST", "Test message")
        
        events = get_events()
        assert len(events) > initial_count
    
    def test_get_events_max_limit(self):
        """get_events respects max limit."""
        for i in range(250):
            _add_event("TEST", f"Message {i}")
        
        events = get_events()
        
        assert len(events) <= 200
