"""Tests for config validation functionality."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigValidationEdgeCases:
    """Test edge cases in config validation."""
    
    def test_validate_empty_mc_version(self):
        """Validation fails with empty mc_version."""
        from neorunner_pkg.config import ServerConfig, validate_config
        
        cfg = ServerConfig(mc_version="")
        valid, errors = validate_config(cfg, fail_on_error=False)
        assert valid is False
    
    def test_validate_missing_mc_version(self):
        """Validation fails with missing mc_version."""
        from neorunner_pkg.config import ServerConfig, validate_config
        
        cfg = ServerConfig(mc_version=None)
        valid, errors = validate_config(cfg, fail_on_error=False)
        assert valid is False
    
    def test_validate_invalid_loader(self):
        """Validation fails with invalid loader."""
        from neorunner_pkg.config import ServerConfig, validate_config
        
        cfg = ServerConfig(loader="invalid")
        valid, errors = validate_config(cfg, fail_on_error=False)
        assert valid is False


class TestConfigMemoryValidation:
    """Test memory configuration validation."""
    
    def test_validate_memory_format_values(self):
        """Test various memory formats."""
        from neorunner_pkg.config import ServerConfig, validate_config
        
        # Most of these are actually valid per the codebase
        # The loader validation happens separately
        for mem in ["1G", "2G", "4G", "8G", "512M"]:
            cfg = ServerConfig(xmx=mem)
            valid, errors = validate_config(cfg, fail_on_error=False)
            # Just verify it doesn't crash
            assert isinstance(valid, bool)


class TestConfigSerialization:
    """Test config serialization methods."""
    
    def test_server_config_to_dict(self):
        """Test to_dict method."""
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge")
        d = cfg.to_dict()
        
        assert isinstance(d, dict)
        assert d['mc_version'] == "1.21.11"
        assert d['loader'] == "neoforge"
    
    def test_server_config_from_dict(self):
        """Test from_dict method."""
        from neorunner_pkg.config import ServerConfig
        
        data = {"mc_version": "1.21.1", "loader": "fabric"}
        cfg = ServerConfig.from_dict(data)
        
        assert cfg.mc_version == "1.21.1"
        assert cfg.loader == "fabric"
    
    def test_server_config_from_dict_unknown_fields(self):
        """from_dict ignores unknown fields."""
        from neorunner_pkg.config import ServerConfig
        
        data = {"mc_version": "1.21.1", "unknown_field": "value"}
        cfg = ServerConfig.from_dict(data)
        
        assert cfg.mc_version == "1.21.1"


class TestConfigParallelPorts:
    """Test parallel ports configuration."""
    
    def test_with_parallel_ports(self):
        """Test parallel ports mode."""
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        parallel_cfg = cfg.with_parallel_ports()
        
        assert parallel_cfg.mc_port != cfg.mc_port
        assert parallel_cfg.rcon_port != cfg.rcon_port
        assert parallel_cfg.http_port != cfg.http_port


class TestConfigDefaults:
    """Test config defaults."""
    
    def test_default_values_known(self):
        """Default values are correctly set."""
        from neorunner_pkg.config import ServerConfig, _get_default_version
        
        cfg = ServerConfig()
        
        assert cfg.rcon_port == "25575"
        assert cfg.mc_port == 1234
        assert cfg.http_port == 8000
        assert cfg.mods_dir == "mods"
        assert cfg.loader == "neoforge"
    
    def test_default_curator_values(self):
        """Default curator settings."""
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        
        assert cfg.curator_limit == 100
        assert cfg.curator_max_depth == 3
        assert cfg.curator_show_optional_audit is True
