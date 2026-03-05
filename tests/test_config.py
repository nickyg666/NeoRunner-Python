"""Tests for config validation and management."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.config import ServerConfig, validate_config, ensure_config


class TestConfigValidation:
    """Test config validation functions."""
    
    def test_validate_config_valid(self):
        """Valid config passes validation."""
        cfg = ServerConfig(
            mc_version="1.21.11",
            loader="neoforge",
            mods_dir="mods",
            clientonly_dir="clientonly",
            quarantine_dir="quarantine",
            xmx="4G",
            xms="2G",
        )
        
        is_valid, errors = validate_config(cfg, fail_on_error=False)
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_config_missing_mc_version(self):
        """Fails on missing mc_version."""
        cfg = ServerConfig(
            mc_version="",
            loader="neoforge",
            mods_dir="mods",
            clientonly_dir="clientonly",
            quarantine_dir="quarantine",
            xmx="4G",
            xms="2G",
        )
        
        is_valid, errors = validate_config(cfg, fail_on_error=False)
        
        assert is_valid is False
        assert any("mc_version" in e for e in errors)
    
    def test_validate_config_invalid_loader(self):
        """Fails on invalid loader."""
        cfg = ServerConfig(
            mc_version="1.21.11",
            loader="invalid_loader",
            mods_dir="mods",
            clientonly_dir="clientonly",
            quarantine_dir="quarantine",
            xmx="4G",
            xms="2G",
        )
        
        is_valid, errors = validate_config(cfg, fail_on_error=False)
        
        assert is_valid is False
        assert any("loader" in e for e in errors)
    
    def test_ensure_config_fills_defaults(self):
        """Ensures config fills in missing fields with defaults."""
        cfg = ServerConfig()
        
        result = ensure_config(cfg)
        
        assert result.mc_version == "1.21.11"
        assert result.loader == "neoforge"
        assert result.mods_dir == "mods"
        assert result.xmx == "6G"
        assert result.log_retention_days == 30
    
    def test_ensure_config_preserves_existing(self):
        """Ensures config preserves existing valid values."""
        cfg = ServerConfig(
            mc_version="1.20.1",
            loader="forge",
            xmx="8G",
        )
        
        result = ensure_config(cfg)
        
        assert result.mc_version == "1.20.1"
        assert result.loader == "forge"
        assert result.xmx == "8G"
        assert result.mods_dir == "mods"


class TestServerConfigDefaults:
    """Test ServerConfig default values."""
    
    def test_default_values(self):
        """Check default config values."""
        cfg = ServerConfig()
        
        assert cfg.http_port == 8000
        assert cfg.mc_port == 1234
        assert cfg.max_download_mb == 600
        assert cfg.rate_limit_seconds == 2
        assert cfg.log_retention_days == 30
        assert cfg.crash_report_retention_days == 30
        assert cfg.live_log_max_size_mb == 10
        assert cfg.live_log_backup_count == 5
    
    def test_to_dict(self):
        """Test config serialization."""
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge")
        
        d = cfg.to_dict()
        
        assert d["mc_version"] == "1.21.11"
        assert d["loader"] == "neoforge"
    
    def test_from_dict(self):
        """Test config deserialization."""
        data = {"mc_version": "1.20.1", "loader": "fabric"}
        
        cfg = ServerConfig.from_dict(data)
        
        assert cfg.mc_version == "1.20.1"
        assert cfg.loader == "fabric"
