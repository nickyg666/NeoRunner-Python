"""Tests for loader server.properties wiring (description + port)."""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.config import ServerConfig
from neorunner_pkg.loaders.neoforge import NeoForgeLoader


def _write_props(cfg: ServerConfig, tmp_path: Path) -> str:
    loader = NeoForgeLoader(cfg, cwd=tmp_path)
    loader._setup_server_properties()
    return (tmp_path / "server.properties").read_text()


def test_server_description_becomes_motd(tmp_path):
    cfg = ServerConfig(mc_version="26.1.2", loader="neoforge", server_description="Welcome to my modded realm!")
    props = _write_props(cfg, tmp_path)
    assert "motd=Welcome to my modded realm!" in props


def test_server_description_empty_uses_loader_default(tmp_path):
    cfg = ServerConfig(mc_version="26.1.2", loader="neoforge", server_description="")
    props = _write_props(cfg, tmp_path)
    assert "motd=NeoRunner - NeoForge Server" in props


def test_server_port_follows_mc_port(tmp_path):
    # Legacy (proxy disabled) mode: server.properties follows cfg.mc_port.
    cfg = ServerConfig(mc_version="26.1.2", loader="neoforge", mc_port=25565,
                       proxy_enabled=False)
    props = _write_props(cfg, tmp_path)
    assert "server-port=25565" in props


def test_server_port_can_be_overridden(tmp_path):
    # server_port (if present on the config) takes priority over mc_port, but
    # ServerConfig does not define it, so mc_port wins.
    cfg = ServerConfig(mc_version="26.1.2", loader="neoforge", mc_port=25565,
                       proxy_enabled=False)
    props = _write_props(cfg, tmp_path)
    assert "server-port=25565" in props


def test_proxy_mode_binds_loopback_backend_port(tmp_path):
    # Default (proxy enabled): the real modded server binds a loopback-only
    # backend port while the proxy owns the public cfg.mc_port.
    cfg = ServerConfig(mc_version="26.1.2", loader="neoforge",
                       mc_port=25565, backend_modded_port=25570,
                       proxy_enabled=True)
    props = _write_props(cfg, tmp_path)
    assert "server-port=25570" in props
    assert "server-ip=127.0.0.1" in props
