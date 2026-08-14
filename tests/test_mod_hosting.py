"""Tests for mod hosting functionality."""

import os
import sys

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
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import generate_bat_script
        
        cfg = ServerConfig(mc_version="1.21.11", loader="neoforge", http_port=8000)
        script = generate_bat_script(cfg)
        
        assert isinstance(script, str)
        assert len(script) > 0
    
    def test_generate_bat_script_fabric(self):
        """Generate batch script for Fabric."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import generate_bat_script
        
        cfg = ServerConfig(mc_version="1.20.4", loader="fabric", http_port=8000)
        script = generate_bat_script(cfg)
        
        assert isinstance(script, str)
    
    def test_generate_bat_script_contains_curl(self):
        """Batch script contains curl command."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import generate_bat_script
        
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


class TestModHostingManifestFunctions:
    """Test manifest and zip generation."""

    def test_update_manifest_includes_clientonly(self, tmp_path, monkeypatch):
        """Manifest includes server + clientonly mods with types."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import update_manifest

        mods_dir = tmp_path / "mods"
        clientonly = tmp_path / "clientonly"
        mods_dir.mkdir()
        clientonly.mkdir()
        (mods_dir / "servermod.jar").write_bytes(b"x")
        (mods_dir / "servermod.server.jar").write_bytes(b"x")  # excluded
        (clientonly / "clientmod.jar").write_bytes(b"x")

        cfg = ServerConfig(clientonly_dir=str(clientonly))
        assert update_manifest(mods_dir, cfg) is True

        import json
        data = json.loads((mods_dir / "manifest.json").read_text())
        files = {f["path"]: f["type"] for f in data["files"]}
        assert files["servermod.jar"] == "server"
        assert files["clientmod.jar"] == "clientonly"
        assert "servermod.server.jar" not in files

    def test_update_manifest_relative_clientonly(self, tmp_path, monkeypatch):
        """Relative clientonly dir resolved against CWD."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import update_manifest

        mods_dir = tmp_path / "mods"
        clientonly = tmp_path / "clientonly"
        mods_dir.mkdir()
        clientonly.mkdir()
        (clientonly / "relmod.jar").write_bytes(b"x")

        monkeypatch.setattr("neorunner_pkg.mod_hosting.CWD", tmp_path)
        cfg = ServerConfig(clientonly_dir="clientonly")
        assert update_manifest(mods_dir, cfg) is True

        import json
        data = json.loads((mods_dir / "manifest.json").read_text())
        assert any(f["path"] == "relmod.jar" for f in data["files"])

    def test_create_mod_zip(self, tmp_path):
        """create_mod_zip bundles mods and clientonly."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import create_mod_zip

        mods_dir = tmp_path / "mods"
        clientonly = tmp_path / "clientonly"
        mods_dir.mkdir()
        clientonly.mkdir()
        (mods_dir / "a.jar").write_bytes(b"a")
        (clientonly / "b.jar").write_bytes(b"b")

        cfg = ServerConfig(clientonly_dir=str(clientonly))
        zip_path = create_mod_zip(mods_dir, cfg)
        assert zip_path is not None
        assert zip_path.name == "mods_latest.zip"

        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        assert {"a.jar", "b.jar"} <= names

    def test_create_mod_zip_error_returns_none(self, tmp_path, monkeypatch):
        """Error during zip creation returns None."""
        from neorunner_pkg.mod_hosting import create_mod_zip

        monkeypatch.setattr(
            "neorunner_pkg.mod_hosting.update_manifest",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert create_mod_zip(tmp_path / "mods") is None

    def test_conditional_create_mod_zip_throttle(self, tmp_path, monkeypatch):
        """Zip not recreated within 5 minutes."""
        import time

        import neorunner_pkg.mod_hosting as mh
        from neorunner_pkg.mod_hosting import conditional_create_mod_zip

        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        (mods_dir / "a.jar").write_bytes(b"a")

        # recent creation -> throttled (returns None, no zip made)
        monkeypatch.setattr(mh, "_last_zip_time", time.time() - 10)
        assert conditional_create_mod_zip(mods_dir) is None

        # stale creation -> creates zip
        monkeypatch.setattr(mh, "_last_zip_time", time.time() - 600)
        assert conditional_create_mod_zip(mods_dir) is not None

    def test_generate_powershell_script(self):
        """PowerShell script contains manifest download URL."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import generate_powershell_script

        cfg = ServerConfig(http_port=8000)
        script = generate_powershell_script(cfg)
        assert "/download/manifest" in script
        assert "Expand-Archive" in script
        # ensure no duplicated block (regression)
        assert script.count("All mods up to date!") == 1

    def test_generate_bash_script(self):
        """Bash script contains manifest URL."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.mod_hosting import generate_bash_script

        cfg = ServerConfig(http_port=8000)
        script = generate_bash_script(cfg)
        assert "/download/manifest" in script
        assert "curl" in script

    def test_get_server_ip_config_override(self, monkeypatch):
        """Config server_ip is used when set."""
        from neorunner_pkg.mod_hosting import get_server_ip

        class FakeCfg:
            server_ip = "203.0.113.5"

        monkeypatch.setattr("neorunner_pkg.config.load_cfg", lambda: FakeCfg())
        assert get_server_ip() == "203.0.113.5"

    def test_get_server_ip_fallback(self, monkeypatch):
        """Falls back to local IP detection."""
        from neorunner_pkg.mod_hosting import get_server_ip

        monkeypatch.setattr("neorunner_pkg.config.load_cfg", lambda: None)
        monkeypatch.setattr(
            "neorunner_pkg.mod_hosting._get_local_ip", lambda: "192.168.1.10")
        assert get_server_ip() == "192.168.1.10"


class TestJavaBootstrap:
    """Native Java-installer bootstrap scripts (ensure Java, run installer)."""

    def _cfg(self):
        from neorunner_pkg.config import ServerConfig
        return ServerConfig(hostname="mc.example.com", http_port=8000)

    def test_adoptium_url(self):
        from neorunner_pkg.mod_hosting import adoptium_jre_url
        u = adoptium_jre_url("windows", "x64", 21)
        assert u.startswith("https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse")

    def test_bash_bootstrap_checks_java(self):
        from neorunner_pkg.mod_hosting import generate_java_bootstrap_sh
        s = generate_java_bootstrap_sh(self._cfg())
        assert "#!/bin/bash" in s
        assert "command -v java" in s
        assert "adoptium.net" in s
        assert 'BASE_URL="https://mc.example.com"' in s
        assert "/download/installer.jar" in s
        assert "-jar" in s

    def test_bat_bootstrap_checks_java(self):
        from neorunner_pkg.mod_hosting import generate_java_bootstrap_bat
        s = generate_java_bootstrap_bat(self._cfg())
        assert "@echo off" in s
        assert "where java" in s
        assert "adoptium.net" in s
        assert 'BASE_URL=https://mc.example.com' in s
        assert "/download/installer.jar" in s
        assert "-jar" in s

    def test_bash_uses_local_ip_when_no_hostname(self):
        from neorunner_pkg.mod_hosting import generate_java_bootstrap_sh
        from neorunner_pkg.config import ServerConfig
        s = generate_java_bootstrap_sh(ServerConfig(hostname="", http_port=8000))
        assert "/download/installer.jar" in s
