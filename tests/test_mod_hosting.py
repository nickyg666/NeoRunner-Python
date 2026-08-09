"""Tests for mod hosting functionality."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestModHostingIPDetection:
    """Test mod hosting IP detection."""
    
    def test_is_private_ip_10(self):
        """10.x.x.x is private."""
        from neorunner_pkg.mod_hosting import _is_private_ip
        
        assert _is_private_ip("10.0.0.1") is True
    
    def test_is_private_ip_172(self):
        """172.16-31.x.x is private."""
        from neorunner_pkg.mod_hosting import _is_private_ip
        
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("172.31.0.1") is True
    
    def test_is_private_ip_192_168(self):
        """192.168.x.x is private."""
        from neorunner_pkg.mod_hosting import _is_private_ip
        
        assert _is_private_ip("192.168.0.1") is True
    
    def test_is_private_ip_127(self):
        """127.x.x.x is loopback."""
        from neorunner_pkg.mod_hosting import _is_private_ip
        
        assert _is_private_ip("127.0.0.1") is True
    
    def test_is_private_ip_public(self):
        """Public IPs are not private."""
        from neorunner_pkg.mod_hosting import _is_private_ip
        
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False
    
    def test_is_private_ip_invalid(self):
        """Invalid IPs return False."""
        from neorunner_pkg.mod_hosting import _is_private_ip
        
        assert _is_private_ip("invalid") is False
        assert _is_private_ip("256.0.0.1") is False
        assert _is_private_ip("") is False


class TestModHostingBatScript:
    """Test batch script generation."""
    
    def test_generate_bat_script_neoforge(self):
        """Generate batch script for NeoForge."""
        from neorunner_pkg.mod_hosting import generate_bat_script
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge", http_port=8000)
        script = generate_bat_script(cfg)
        
        assert isinstance(script, str)
        assert len(script) > 0
    
    def test_generate_bat_script_fabric(self):
        """Generate batch script for Fabric."""
        from neorunner_pkg.mod_hosting import generate_bat_script
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(mc_version="1.20.4", loader="fabric", http_port=8000)
        script = generate_bat_script(cfg)
        
        assert isinstance(script, str)
    
    def test_generate_bat_script_contains_curl(self):
        """Batch script contains curl command."""
        from neorunner_pkg.mod_hosting import generate_bat_script
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(http_port=8000)
        script = generate_bat_script(cfg)
        
        assert "curl" in script.lower() or "powershell" in script.lower()


class TestModHostingRateLimiting:
    """Test rate limiting functionality."""
    
    def test_rate_limit_config(self):
        """Rate limit is configurable."""
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(rate_limit_seconds=2)
        
        assert cfg.rate_limit_seconds == 2
    
    def test_rate_limit_default(self):
        """Rate limit has default."""
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        
        assert cfg.rate_limit_seconds > 0


class TestModHostingManifest:
    """Test manifest creation."""
    
    def test_create_mod_zip_function(self):
        """Test create_mod_zip can be imported."""
        from neorunner_pkg.mod_hosting import create_mod_zip
        
        assert callable(create_mod_zip)
    
    def test_conditional_create_mod_zip_function(self):
        """Test conditional_create_mod_zip can be imported."""
        from neorunner_pkg.mod_hosting import conditional_create_mod_zip
        
        assert callable(conditional_create_mod_zip)


class TestGetServerIP:
    """Test server IP detection."""
    
    def test_get_server_ip_returns_string(self):
        """get_server_ip returns a string or None."""
        from neorunner_pkg.mod_hosting import get_server_ip
        
        ip = get_server_ip()
        
        # May be None if no network, but shouldn't raise
        assert ip is None or isinstance(ip, str)
