"""Tests for dashboard API endpoints."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.server import stop_server, restart_server, is_server_running


class TestServerAPI:
    """Test server API functions."""
    
    def test_stop_server_without_instance(self):
        """stop_server works without _server_instance (dashboard process)."""
        with patch('neorunner.server.subprocess.run') as mock_run:
            with patch('neorunner.server.load_cfg') as mock_cfg:
                mock_cfg.return_value.mc_version = "1.21.11"
                mock_cfg.return_value.loader = "neoforge"
                mock_cfg.return_value.tmux_socket = "/tmp/test"
                
                mock_run.return_value = MagicMock()
                
                result = stop_server()
                
                assert result is True
                assert mock_run.called
    
    def test_is_server_running_check(self):
        """is_server_running returns bool."""
        with patch('neorunner.server.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            
            result = is_server_running()
            
            assert isinstance(result, bool)
    
    def test_stop_server_with_instance(self):
        """stop_server uses instance when available."""
        with patch('neorunner.server._server_instance') as mock_instance:
            mock_instance.stop.return_value = True
            
            result = stop_server()
            
            assert mock_instance.stop.called


class TestDashboardImports:
    """Test that dashboard modules can be imported."""
    
    def test_dashboard_imports(self):
        """Dashboard can be imported."""
        from neorunner.dashboard import app
        assert app is not None
    
    def test_config_imports(self):
        """Config functions work."""
        from neorunner.config import load_cfg, save_cfg, ensure_config, validate_config, ServerConfig
        cfg = ServerConfig()
        cfg = ensure_config(cfg)  # Fill defaults
        valid, errors = validate_config(cfg, fail_on_error=False)
        assert valid is True  # With defaults, should be valid
    
    def test_server_imports(self):
        """Server functions can be imported."""
        from neorunner.server import (
            run_server, stop_server, restart_server,
            send_command, is_server_running, get_server, get_events
        )
        assert callable(run_server)
        assert callable(stop_server)
        assert callable(restart_server)


class TestModHosting:
    """Test mod hosting functions."""
    
    def test_generate_bat_script(self):
        """Batch script generation works."""
        from neorunner_pkg.mod_hosting import generate_bat_script
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge", http_port=8000)
        script = generate_bat_script(cfg)
        
        assert "curl" in script or "powershell" in script
    
    def test_get_server_ip(self):
        """Server IP detection works."""
        from neorunner_pkg.mod_hosting import get_server_ip
        
        ip = get_server_ip()
        
        assert ip is not None
        assert len(ip.split('.')) == 4  # IPv4 format


class TestManifest:
    """Test manifest creation."""
    
    def test_create_mod_zip_function_exists(self):
        """create_mod_zip function exists."""
        from neorunner.mod_hosting import create_mod_zip
        assert callable(create_mod_zip)
    
    def test_conditional_create_mod_zip_exists(self):
        """conditional_create_mod_zip function exists."""
        from neorunner.mod_hosting import conditional_create_mod_zip
        assert callable(conditional_create_mod_zip)
