"""Tests for dashboard API endpoints."""

import pytest
import sys
import os
import json
from unittest.mock import patch, MagicMock
from flask import Flask
from neorunner_pkg.config import ServerConfig

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


class TestLoaderSwitch:
    """Test loader switch snapshot/archive flow."""

    @pytest.fixture
    def client(self):
        from neorunner_pkg.dashboard import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client

    def test_loaders_archives_returns_json(self, client):
        """Archives endpoint returns JSON."""
        response = client.get('/api/loaders/archives')
        assert response.status_code == 200
        assert 'archives' in response.get_json()

    def test_loaders_snapshots_returns_json(self, client):
        """Snapshots endpoint returns JSON."""
        response = client.get('/api/loaders/snapshots')
        assert response.status_code == 200
        assert 'snapshots' in response.get_json()

    def test_loaders_switch_invalid_loader(self, client):
        """Unknown loader rejected."""
        response = client.post('/api/loaders/switch', json={"loader": "badloader"})
        assert response.status_code == 400
        assert 'error' in response.get_json()

    def test_loaders_switch_keeps_mods(self, client, monkeypatch, tmp_path):
        """keep_mods=True preserves existing mod jars."""
        import neorunner_pkg.dashboard as dash

        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        (mods_dir / "mymod.jar").write_bytes(b"x")

        monkeypatch.setattr(dash, "CWD", tmp_path)
        monkeypatch.setattr(dash, "load_cfg", lambda: ServerConfig(
            mc_version="1.21.11", loader="neoforge", mods_dir="mods",
            clientonly_dir="clientonly", quarantine_dir="quarantine",
        ))

        class _CfgSaver:
            def __init__(self):
                self.saved = None
            def __call__(self, cfg):
                self.saved = cfg

        saver = _CfgSaver()
        monkeypatch.setattr(dash, "save_cfg", saver)
        monkeypatch.setattr("neorunner_pkg.server.is_server_running", lambda: False)
        monkeypatch.setattr("neorunner_pkg.server.stop_server", lambda: None)
        monkeypatch.setattr("neorunner_pkg.installer.install_loader", lambda cfg: True)
        monkeypatch.setattr(dash, "scan_worlds", lambda: [])

        response = client.post('/api/loaders/switch', json={
            "loader": "fabric", "mc_version": "1.20.1", "keep_mods": True
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["archived_mods"] == 0
        assert (mods_dir / "mymod.jar").exists()

    def test_loaders_switch_archives_mods(self, client, monkeypatch, tmp_path):
        """keep_mods=False archives loader mods."""
        import neorunner_pkg.dashboard as dash

        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        (mods_dir / "neoforgemod.jar").write_bytes(b"x")

        monkeypatch.setattr(dash, "CWD", tmp_path)
        monkeypatch.setattr(dash, "load_cfg", lambda: ServerConfig(
            mc_version="1.21.11", loader="neoforge", mods_dir="mods",
            clientonly_dir="clientonly", quarantine_dir="quarantine",
        ))
        monkeypatch.setattr(dash, "save_cfg", lambda cfg: None)
        monkeypatch.setattr("neorunner_pkg.server.is_server_running", lambda: False)
        monkeypatch.setattr("neorunner_pkg.server.stop_server", lambda: None)
        monkeypatch.setattr("neorunner_pkg.installer.install_loader", lambda cfg: True)
        monkeypatch.setattr(dash, "scan_worlds", lambda: [])

        response = client.post('/api/loaders/switch', json={
            "loader": "fabric", "mc_version": "1.20.1"
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data["archived_mods"] >= 1
        assert not (mods_dir / "neoforgemod.jar").exists()
        archive = tmp_path / "loader_archive" / "neoforge" / "1.21.11" / "1.20.1" / "neoforgemod.jar"
        assert archive.exists()

    def test_loaders_restore_mods(self, client, monkeypatch, tmp_path):
        """Restore archived mods back to mods folder."""
        import neorunner_pkg.dashboard as dash

        archive = tmp_path / "loader_archive" / "neoforge" / "1.21.11" / "1.20.1"
        archive.mkdir(parents=True)
        (archive / "oldmod.jar").write_bytes(b"x")

        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        monkeypatch.setattr(dash, "CWD", tmp_path)
        monkeypatch.setattr(dash, "load_cfg", lambda: ServerConfig(
            mc_version="1.20.1", loader="fabric", mods_dir="mods",
            clientonly_dir="clientonly", quarantine_dir="quarantine",
        ))

        response = client.post('/api/loaders/restore-mods', json={
            "loader": "neoforge", "version": "1.21.11", "mc_version": "1.20.1"
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["message"].startswith("Restored 1")
        assert (mods_dir / "oldmod.jar").exists()

    def test_loaders_restore_snapshot(self, client, monkeypatch, tmp_path):
        """Restore snapshot extracts config back."""
        import neorunner_pkg.dashboard as dash
        import tarfile

        snap_dir = tmp_path / "snapshots"
        snap_dir.mkdir()
        snap = snap_dir / "pre_fabric_switch_test.tar.gz"
        (tmp_path / "config.json").write_text(json.dumps({"loader": "old"}))
        with tarfile.open(str(snap), "w:gz") as tar:
            tar.add(tmp_path / "config.json", arcname="config.json")

        monkeypatch.setattr(dash, "CWD", tmp_path)
        response = client.post('/api/loaders/restore', json={"snapshot": snap.name})
        assert response.status_code == 200
        assert json.loads((tmp_path / "config.json").read_text())["loader"] == "old"

    def test_loaders_restore_snapshot_invalid_name(self, client, monkeypatch, tmp_path):
        """Path traversal in snapshot name rejected."""
        import neorunner_pkg.dashboard as dash
        monkeypatch.setattr(dash, "CWD", tmp_path)
        response = client.post('/api/loaders/restore', json={"snapshot": "../evil"})
        assert response.status_code == 400
