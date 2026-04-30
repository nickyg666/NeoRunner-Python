"""Tests for dashboard API endpoints."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDashboardAPIImports:
    """Test dashboard API functions can be imported."""
    
    def test_parse_server_properties_imports(self):
        """parse_server_properties function exists."""
        from neorunner_pkg.dashboard import parse_server_properties
        assert callable(parse_server_properties)
    
    def test_scan_worlds_imports(self):
        """scan_worlds function exists."""
        from neorunner_pkg.dashboard import scan_worlds
        assert callable(scan_worlds)
    
    def test_dashboard_state_imports(self):
        """DashboardState class exists."""
        from neorunner_pkg.dashboard import DashboardState
        state = DashboardState()
        assert hasattr(state, 'add_event')
        assert hasattr(state, 'events')
    
    def test_get_config_path_imports(self):
        """get_config_path function exists."""
        from neorunner_pkg.dashboard import get_config_path
        assert callable(get_config_path)


class TestDashboardAPIRoutes:
    """Test dashboard API routes structure."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from neorunner_pkg.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_api_status_route_returns_json(self, client):
        """Test /api/status returns JSON."""
        response = client.get('/api/status')
        assert response.status_code == 200
        data = response.get_json()
        # Check status key (actual structure may vary)
        assert data is not None
        assert 'running' in data
    
    def test_api_config_get_route(self, client):
        """Test /api/config (GET) returns config."""
        response = client.get('/api/config')
        assert response.status_code == 200
        data = response.get_json()
        assert 'mc_version' in data or 'loader' in data
    
    def test_api_mods_route(self, client):
        """Test /api/mods returns mod list."""
        response = client.get('/api/mods')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
    
    def test_api_server_status_route(self, client):
        """Test /api/server/status returns server status."""
        response = client.get('/api/server/status')
        assert response.status_code == 200
        data = response.get_json()
        assert 'running' in data


class TestDashboardState:
    """Test DashboardState functionality."""
    
    def test_dashboard_state_add_event(self):
        """Test adding events to state."""
        from neorunner_pkg.dashboard import DashboardState
        
        state = DashboardState()
        state.add_event("SERVER_START", "Test message")
        
        assert len(state.events) == 1
        assert state.events[0]['type'] == "SERVER_START"
        assert state.events[0]['message'] == "Test message"
    
    def test_dashboard_state_max_events(self):
        """Test max events limit works."""
        from neorunner_pkg.dashboard import DashboardState
        
        state = DashboardState()
        state.max_events = 5
        
        # Add more than max
        for i in range(10):
            state.add_event("TEST", f"Event {i}")
        
        # Should be capped at max_events
        assert len(state.events) == 5


class TestParseServerProperties:
    """Test parse_server_properties function."""
    
    def test_parse_server_properties_returns_dict(self):
        """Test parsing returns a dict."""
        from neorunner_pkg.dashboard import parse_server_properties
        result = parse_server_properties()
        assert isinstance(result, dict)
