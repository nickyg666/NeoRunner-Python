"""Tests for dashboard API endpoints."""

import base64
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _auth_header(user="mc", password="123"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


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
        response = client.get('/api/status', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        # Check status key (actual structure may vary)
        assert data is not None
        assert 'running' in data
    
    def test_api_config_get_route(self, client):
        """Test /api/config (GET) returns config."""
        response = client.get('/api/config', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        assert 'mc_version' in data or 'loader' in data
    
    def test_api_mods_route(self, client):
        """Test /api/mods returns mod list."""
        response = client.get('/api/mods', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
    
    def test_api_server_status_route(self, client):
        """Test /api/server/status returns server status."""
        response = client.get('/api/server/status', headers=_auth_header())
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


class TestHoldingCellRoutes:
    """Test the holding cell (download lobby) API routes.

    These routes touch the real tmux session when invoked, so mock the cell
    manager to keep tests hermetic (no starting/stopping a live room).
    """

    @pytest.fixture
    def client(self):
        from neorunner_pkg.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    @pytest.fixture
    def mock_cell(self):
        cell = MagicMock()
        cell.status.return_value = {
            "running": False,
            "port": 25565,
            "address": "127.0.0.1",
            "modpack_link": "https://W8.mom/dl/mods.zip",
            "modded_server": "127.0.0.1:1234",
            "room_size": 20,
            "started": False,
        }
        cell.is_running.return_value = False
        cell.start.return_value = True
        cell.stop.return_value = True
        with patch("neorunner_pkg.holding_cell.VanillaHoldingCell", return_value=cell):
            yield cell

    def test_room_status_route_exists(self, client, mock_cell):
        """GET /api/room/status returns JSON status payload."""
        response = client.get('/api/room/status', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert "running" in data
        assert "port" in data
        assert "modpack_link" in data

    def test_room_status_requires_auth(self, client):
        """Room status is part of the /api control surface (auth protected)."""
        response = client.get('/api/room/status')
        assert response.status_code == 401

    def test_room_start_accepts_post(self, client, mock_cell):
        """POST /api/room/start is routed (returns ok or already_running)."""
        response = client.post('/api/room/start', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("ok") is True
        mock_cell.start.assert_called_once()

    def test_room_stop_accepts_post(self, client, mock_cell):
        """POST /api/room/stop is routed and stops the cell."""
        response = client.post('/api/room/stop', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("running") is False
        mock_cell.stop.assert_called_once()


class TestDescriptionRoutes:
    """Test the server/waiting-room description (MOTD) API routes."""

    @pytest.fixture
    def client(self):
        from neorunner_pkg.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_descriptions_get_returns_both(self, client):
        """GET /api/descriptions returns both description fields."""
        response = client.get('/api/descriptions', headers=_auth_header())
        assert response.status_code == 200
        data = response.get_json()
        assert "server_description" in data
        assert "holding_cell_description" in data

    def test_descriptions_update_applies(self, client):
        """POST /api/descriptions writes both descriptions and returns config.

        The on-disk MOTD apply helpers are mocked so tests never mutate the
        live server.properties files in the repo checkout.
        """
        with patch("neorunner_pkg.dashboard.apply_main_server_motd", return_value=True), \
             patch("neorunner_pkg.dashboard.apply_room_motd", return_value=True):
            response = client.post('/api/descriptions', headers=_auth_header(),
                                   json={"server_description": "Test Server", "holding_cell_description": "Test Room"})
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("success") is True
        assert data.get("server_description") == "Test Server"
        assert data.get("holding_cell_description") == "Test Room"
