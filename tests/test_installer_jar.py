"""Tests for installer_jar module (client installer JAR builder)."""

import sys
import os
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.installer_jar import build_installer_properties
from neorunner_pkg.config import ServerConfig


def _cfg(**overrides):
    defaults = dict(
        mc_version="26.1.2",
        loader="neoforge",
        mods_dir="mods",
        clientonly_dir="clientonly",
        quarantine_dir="quarantine",
        http_port=8000,
        mc_port=1234,
        hostname="",
    )
    defaults.update(overrides)
    return ServerConfig(**defaults)


class TestInstallerProperties:
    def test_default_properties(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg())
        assert "baseUrl=" in props
        assert "serverAddress=" in props
        assert "loader=neoforge" in props
        assert "mcVersion=26.1.2" in props
        assert "loaderVersion=" in props

    def test_custom_base_url(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(
            _cfg(), base_url="https://mc.w8.mom", server_address="w8.mom:1234"
        )
        assert "baseUrl=https://mc.w8.mom" in props
        assert "serverAddress=w8.mom:1234" in props

    def test_default_server_address_uses_mc_port(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg())
        assert "serverAddress=" in props

    def test_all_required_keys_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg(loader="fabric"))
        for key in ("baseUrl", "serverAddress", "loader", "mcVersion", "loaderVersion"):
            assert f"{key}=" in props

    def test_hostname_uses_https_base_url(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg(hostname="mc.w8.mom"))
        assert "baseUrl=https://mc.w8.mom" in props
        assert "serverAddress=mc.w8.mom:1234" in props

    def test_no_hostname_falls_back_to_lan_http(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        monkeypatch.setattr(
            "neorunner_pkg.installer_jar._get_local_ip", lambda: "192.168.0.50"
        )
        props = build_installer_properties(_cfg(hostname=""))
        assert "baseUrl=http://192.168.0.50:8000" in props
        assert "serverAddress=192.168.0.50:1234" in props