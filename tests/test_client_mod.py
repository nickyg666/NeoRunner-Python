"""Tests for the clickable-link client mod builder."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestClientLinkMod:
    def test_source_files_exist(self):
        from neorunner_pkg.client_mod import _JAVA_SOURCES, MOD_DIR
        assert MOD_DIR.is_dir()
        for src in _JAVA_SOURCES:
            assert src.exists(), src

    def test_mixin_config_and_mods_toml(self):
        from neorunner_pkg.client_mod import MOD_DIR
        assert (MOD_DIR / "resources" / "neorunner-client-link.mixins.json").exists()
        toml = (MOD_DIR / "resources" / "META-INF" / "neoforge.mods.toml").read_text()
        assert "neorunner_client_link" in toml
        assert "[[mixins]]" in toml

    def test_mixin_targets_disconnect_screen(self):
        from neorunner_pkg.client_mod import MOD_DIR
        src = (MOD_DIR / "src" / "neorunner" / "client" / "link" / "mixin" / "DisconnectedScreenMixin.java").read_text()
        assert "net.minecraft.client.gui.screens.DisconnectedScreen" in src
        assert "ClickEvent.OpenUrl" in src
        assert "mouseClicked" in src

    def test_build_skips_without_javac(self, tmp_path, monkeypatch):
        import shutil

        from neorunner_pkg import client_mod
        monkeypatch.setattr(shutil, "which", lambda name: None)
        result = client_mod.build_client_link_mod(tmp_path / "clientonly")
        assert result is None
