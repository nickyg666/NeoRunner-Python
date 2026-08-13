"""Tests for external access configuration (Caddy/Cloudflare/ddclient/systemd)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg import external_access as ea
from neorunner_pkg.config import ServerConfig


@pytest.fixture(autouse=True)
def _fake_root(monkeypatch):
    """Pretend we run as root so _write/_sudo don't need real sudo."""
    monkeypatch.setattr(ea, "_euid", lambda: 0)


class TestCaddyConfig:
    def test_basic_proxy(self):
        cfg = ServerConfig(http_port=8000)
        text = ea.caddy_config(cfg, "play.example.com")
        assert "play.example.com {" in text
        assert "reverse_proxy 0.0.0.0:8000" in text

    def test_with_mc_port(self):
        cfg = ServerConfig(http_port=8000, mc_port=1234)
        text = ea.caddy_config(cfg, "play.example.com", mc_port=25565)
        assert "play.example.com:25565 {" in text
        assert "reverse_proxy 0.0.0.0:1234" in text


class TestCloudflaredConfig:
    def test_ingress(self):
        cfg = ServerConfig(http_port=8000, mc_port=1234)
        text = ea.cloudflared_config(cfg, "play.example.com")
        assert "tunnel: play.example.com" in text
        assert "hostname: play.example.com" in text
        assert "service: http://0.0.0.0:8000" in text
        assert "hostname: mc.play.example.com" in text
        assert "service: tcp://0.0.0.0:1234" in text


class TestSetupCaddy:
    def test_raises_without_domain(self):
        with pytest.raises(ea.ExternalAccessError):
            ea.setup_caddy(ServerConfig(), "")

    def test_installs_and_writes(self, monkeypatch, tmp_path):
        calls = []
        have_state = {"installed": False}

        def fake_have(binary):
            return have_state["installed"]

        def fake_install_apt(package):
            calls.append(["apt-get", "install", "-y", package])
            have_state["installed"] = True

        def fake_run(cmd, timeout=60):
            calls.append(cmd)
            return ""  # success

        monkeypatch.setattr(ea, "_have", fake_have)
        monkeypatch.setattr(ea, "_install_apt", fake_install_apt)
        monkeypatch.setattr(ea, "_run", fake_run)
        monkeypatch.setattr(ea, "_write", lambda path, content: None)
        monkeypatch.setattr(ea, "_sudo", lambda cmd: calls.append(cmd))

        result = ea.setup_caddy(ServerConfig(), "play.example.com")
        assert result["ok"] is True
        assert any("apt-get" in c and "caddy" in c for c in calls)
        assert any("systemctl" in c for c in calls)


class TestSetupCloudflare:
    def test_raises_without_token(self):
        with pytest.raises(ea.ExternalAccessError):
            ea.setup_cloudflare(ServerConfig(), "play.example.com", "")

    def test_installs_and_creates_tunnel(self, monkeypatch):
        calls = []
        have_state = {"installed": False}

        def fake_have(binary):
            return have_state["installed"]

        def fake_run(cmd, timeout=60):
            calls.append(cmd)
            if isinstance(cmd, list) and cmd and cmd[0] == "bash":
                have_state["installed"] = True
            return ""

        monkeypatch.setattr(ea, "_have", fake_have)
        monkeypatch.setattr(ea, "_run", fake_run)
        monkeypatch.setattr(ea, "_write", lambda path, content: None)
        monkeypatch.setattr(ea, "_sudo", lambda cmd: calls.append(cmd))

        result = ea.setup_cloudflare(ServerConfig(), "play.example.com", "tok123")
        assert result["ok"] is True
        assert any("tunnel" in c and "login" in c for c in calls)
        assert any("tunnel" in c and "create" in c for c in calls)


class TestDdclient:
    def test_config(self):
        text = ea.ddclient_config("play.example.com", login="user", password="pass")
        assert "protocol=dyndns2" in text
        assert "login=user" in text
        assert "password=pass" in text
        assert text.rstrip().endswith("play.example.com")

    def test_raises_without_domain(self):
        with pytest.raises(ea.ExternalAccessError):
            ea.setup_ddclient("")


class TestSystemd:
    def test_unit_content(self):
        cfg = ServerConfig()
        text = ea.systemd_unit_content(cfg, "/usr/bin/python3", "/opt/neorunner")
        assert "ExecStart=/usr/bin/python3 -m neorunner_pkg start" in text
        assert "WorkingDirectory=/opt/neorunner" in text
        assert "WantedBy=multi-user.target" in text


class TestSetupExternalAccess:
    def test_raises_without_domain(self):
        with pytest.raises(ea.ExternalAccessError):
            ea.setup_external_access(ServerConfig(), {"external_access": "caddy"})

    def test_raises_unknown_provider(self):
        with pytest.raises(ea.ExternalAccessError):
            ea.setup_external_access(ServerConfig(), {
                "domain": "x.example.com", "external_access": "nginx",
            })

    def test_sets_hostname_in_cfg(self, monkeypatch):
        saved = {}

        def fake_caddy(cfg, domain, mc_port=None):
            return {"ok": True}

        def fake_save(cfg):
            saved["hostname"] = cfg.hostname

        monkeypatch.setattr(ea, "setup_caddy", fake_caddy)
        monkeypatch.setattr(ea, "save_cfg", fake_save)

        cfg = ServerConfig(hostname="")
        result = ea.setup_external_access(cfg, {
            "domain": "play.example.com", "external_access": "caddy",
        })
        assert result["ok"] is True
        assert saved["hostname"] == "play.example.com"
