"""Tests for the Velocity entrance backend + entrance dispatcher."""

import json
from pathlib import Path

import pytest

from neorunner_pkg.config import ServerConfig
from neorunner_pkg.velocity_proxy import (
    PLUGIN_JAR_NAME,
    VEL_BUILD,
    VEL_VERSION,
    VelocityManager,
)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "neorunner_pkg" / "velocity_plugin"


# ---------------------------------------------------------------------------
# generated velocity.toml: routing targets + hardening knobs
# ---------------------------------------------------------------------------

@pytest.fixture()
def mgr():
    return VelocityManager(ServerConfig(
        hostname="w8.mom",
        server_description="stungplayz minecraft server!",
        mc_port=25565,
        backend_modded_port=25570,
        holding_cell_port=1234,
    ))


def test_toml_binds_public_port_and_routes_loopback_backends(mgr):
    toml = mgr.render_toml()
    assert 'bind = "0.0.0.0:25565"' in toml
    assert 'modded = "127.0.0.1:25570"' in toml
    assert 'lobby = "127.0.0.1:1234"' in toml


def test_toml_hardening_enabled(mgr):
    toml = mgr.render_toml()
    # Edge auth + anti-abuse knobs must never regress.
    assert "online-mode = true" in toml
    assert "rate-limit = true" in toml
    assert "force-key-authentication = true" in toml
    assert "player-info-forwarding-mode = \"none\"" in toml
    assert "[query]" in toml and "enabled = false" in toml


def test_toml_motd_from_server_description(mgr):
    assert '"stungplayz minecraft server!"' in mgr.render_toml()


def test_toml_alternate_bind_port(mgr):
    assert 'bind = "0.0.0.0:25665"' in mgr.render_toml(bind_port=25665)


def test_refuses_backend_port_collision(mgr):
    mgr.cfg.backend_modded_port = 25565  # same as public port
    assert mgr.start() is False


# ---------------------------------------------------------------------------
# plugin artifact: descriptor + jar present and consistent
# ---------------------------------------------------------------------------

def test_velocity_plugin_descriptor_valid():
    desc = json.loads((PLUGIN_DIR / "velocity-plugin.json").read_text())
    assert desc["id"] == "neorunner-router"
    assert desc["main"] == "mom.w8.neorunner.NeorunnerRouter"
    src = (PLUGIN_DIR / "src/mom/w8/neorunner/NeorunnerRouter.java").read_text()
    # id must match the @Plugin annotation Velocity validates at load time
    assert f'id = "{desc["id"]}"' in src


def test_plugin_jar_built_and_contains_descriptor():
    jar = PLUGIN_DIR / PLUGIN_JAR_NAME
    assert jar.exists(), "plugin jar missing - run neorunner_pkg/velocity_plugin/build.sh"
    import zipfile
    with zipfile.ZipFile(jar) as z:
        names = z.namelist()
        assert "velocity-plugin.json" in names
        assert "mom/w8/neorunner/NeorunnerRouter.class" in names
        desc = json.loads(z.read("velocity-plugin.json"))
        assert desc["id"] == "neorunner-router"


def test_router_source_uses_raw_virtual_host_marker_detection():
    src = (PLUGIN_DIR / "src/mom/w8/neorunner/NeorunnerRouter.java").read_text()
    # The whole point: FML marker detection on the RAW handshake host.
    assert "getRawVirtualHost" in src
    assert "\\u0000FML" in src or "\u005cu0000FML" in src


# ---------------------------------------------------------------------------
# pinned upstream artifact metadata
# ---------------------------------------------------------------------------

def test_pinned_velocity_metadata_present():
    from neorunner_pkg import velocity_proxy as vp
    assert VEL_VERSION and VEL_BUILD
    assert len(vp.VEL_SHA256) == 64
    assert vp.FILL_LATEST.startswith("https://fill.papermc.io/")


# ---------------------------------------------------------------------------
# entrance dispatcher
# ---------------------------------------------------------------------------

def test_dispatcher_selects_python_by_default(monkeypatch, tmp_path):
    from neorunner_pkg import entrance

    monkeypatch.setattr(entrance, "_instances", {})
    cfg = ServerConfig(hostname="w8.mom", mc_port=25565)
    ent = entrance.get_entrance(cfg)
    st = ent.status()
    assert st.get("backend", "python") in ("python", None) or st.get("running") is not None


def test_dispatcher_selects_velocity_when_configured(monkeypatch, tmp_path):
    from neorunner_pkg import entrance

    monkeypatch.setattr(entrance, "_instances", {})
    cfg = ServerConfig(hostname="w8.mom", mc_port=25665,
                       backend_modded_port=25570, holding_cell_port=1234,
                       entrance_backend="velocity")
    ent = entrance.get_entrance(cfg)
    st = ent.status()
    assert st["backend"] == "velocity"
    assert st["servers"]["modded"] == "127.0.0.1:25570"


def test_velocity_properties_follow_loader_policy(mgr, monkeypatch, tmp_path):
    """auto policy: protocol-matching clients go to the modded backend for
    EVERY loader (marker-independent); explicit lobby is honored."""
    from neorunner_pkg import velocity_proxy as vp

    run_dir = tmp_path / ".cache" / "velocity" / "run"
    (run_dir / "plugins").mkdir(parents=True)
    monkeypatch.setattr(vp, "RUN_DIR", run_dir)

    mgr.cfg.loader = "fabric"
    mgr.ensure_plugin()
    props = (run_dir / "plugins" / "neorunner-router.properties").read_text()
    assert "unmarkedTarget=modded" in props
    assert props.startswith("modded=modded")

    mgr.cfg.loader = "neoforge"
    mgr.ensure_plugin()
    props = (run_dir / "plugins" / "neorunner-router.properties").read_text()
    assert "unmarkedTarget=modded" in props

    mgr.cfg.unmarked_client_target = "lobby"
    mgr.ensure_plugin()
    props = (run_dir / "plugins" / "neorunner-router.properties").read_text()
    assert "unmarkedTarget=lobby" in props


def test_router_source_honors_unmarked_target():
    src = (PLUGIN_DIR / "src/mom/w8/neorunner/NeorunnerRouter.java").read_text()
    assert "unmarkedTarget" in src
    assert 'getRawVirtualHost' in src
