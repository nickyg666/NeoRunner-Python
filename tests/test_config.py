"""Tests for config validation and management."""

import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.config import ServerConfig, validate_config, ensure_config
from neorunner_pkg.config import load_cfg, save_cfg, _validate_memory, _get_default_version



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
        from neorunner_pkg.version import get_latest_minecraft_version
        cfg = ServerConfig()
        
        result = ensure_config(cfg)
        
        assert result.mc_version == get_latest_minecraft_version()
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
    
    def test_ensure_config_warns_on_missing_fields(self):
        with pytest.warns(UserWarning, match="using defaults"):
            result = ensure_config(ServerConfig(
                mc_version="", loader="", mods_dir="", clientonly_dir="",
                quarantine_dir="", xmx="", xms="",
            ))
        assert result.mc_version == "1.21.11"

    def test_from_dict(self):
        """Test config deserialization."""
        data = {"mc_version": "1.20.1", "loader": "fabric"}
        
        cfg = ServerConfig.from_dict(data)
        
        assert cfg.mc_version == "1.20.1"
        assert cfg.loader == "fabric"


class TestConfigLoadSave:
    """Test load_cfg / save_cfg / memory validation."""

    def test_load_cfg_missing_file_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neorunner_pkg.config.CWD", tmp_path)
        cfg = load_cfg()
        assert cfg.http_port == 8000

    def test_load_cfg_corrupt_json_returns_default(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("neorunner_pkg.config.CWD", tmp_path)
        (tmp_path / "config.json").write_text("{not valid json")
        cfg = load_cfg()
        assert cfg.http_port == 8000
        assert "Error loading config" in capsys.readouterr().out

    def test_save_cfg_writes_and_validates_memory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neorunner_pkg.config.CWD", tmp_path)
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge")
        cfg.xmx = "http://evil"   # corrupted -> falls back to default
        cfg.xms = None
        save_cfg(cfg)
        written = json.loads((tmp_path / "config.json").read_text())
        assert written["xmx"] == "4G"
        assert written["xms"] == "2G"
        assert written["mc_version"] == "1.21.11"

    def test_save_cfg_tolerates_bat_regeneration_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neorunner_pkg.config.CWD", tmp_path)
        def _boom(cfg):
            raise RuntimeError("no bat")
        monkeypatch.setattr("neorunner_pkg.mod_hosting.generate_bat_script", _boom)
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge")
        save_cfg(cfg)  # must not raise

    def test_validate_memory(self):
        assert _validate_memory(None, "4G") == "4G"
        assert _validate_memory("echo rm -rf", "4G") == "4G"
        assert _validate_memory("dashboard", "4G") == "4G"
        assert _validate_memory("2G", "4G") == "2G"
        assert _validate_memory("512M", "4G") == "512M"
        assert _validate_memory("banana", "4G") == "4G"

    def test_get_default_version_fallback(self, monkeypatch):
        def _boom():
            raise RuntimeError("api down")
        monkeypatch.setattr("neorunner_pkg.version.get_latest_minecraft_version", _boom)
        assert _get_default_version() == "1.21.11"


class TestValidateConfigErrors:
    """Test validate_config error branches and fail_on_error."""

    def _empty(self, **kw):
        defaults = dict(mc_version="1.21.11", loader="neoforge", mods_dir="mods",
                        clientonly_dir="clientonly", quarantine_dir="quarantine",
                        xmx="4G", xms="2G")
        defaults.update(kw)
        return ServerConfig(**defaults)

    def test_missing_loader(self):
        _, errors = validate_config(self._empty(loader=""), fail_on_error=False)
        assert any("loader" in e for e in errors)

    def test_missing_mods_dir(self):
        _, errors = validate_config(self._empty(mods_dir=""), fail_on_error=False)
        assert any("mods_dir" in e for e in errors)

    def test_missing_clientonly_dir(self):
        _, errors = validate_config(self._empty(clientonly_dir=""), fail_on_error=False)
        assert any("clientonly_dir" in e for e in errors)

    def test_missing_quarantine_dir(self):
        _, errors = validate_config(self._empty(quarantine_dir=""), fail_on_error=False)
        assert any("quarantine_dir" in e for e in errors)

    def test_missing_xmx(self):
        _, errors = validate_config(self._empty(xmx=""), fail_on_error=False)
        assert any("xmx" in e for e in errors)

    def test_missing_xms(self):
        _, errors = validate_config(self._empty(xms=""), fail_on_error=False)
        assert any("xms" in e for e in errors)

    def test_fail_on_error_raises(self):
        with pytest.raises(ValueError, match="mc_version is required"):
            validate_config(self._empty(mc_version=""))
