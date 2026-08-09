"""Tests for Forge loader crash detection."""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from neorunner_pkg.loaders.forge import ForgeLoader
from neorunner_pkg.config import ServerConfig


def _make_loader():
    cfg = ServerConfig()
    cfg.loader = "forge"
    cfg.mc_version = "1.21.11"
    return ForgeLoader(cfg, Path("/tmp"))


class TestForgeCrashDetection:
    def test_missing_dependency_detection(self):
        """Forge-style dependency errors."""
        loader = _make_loader()
        for sample in [
            "mod foo requires bar but not found",
            "missing mandatory dependency: gecko",
            "could not find required mod: curios",
        ]:
            result = loader.detect_crash_reason(sample)
            assert result.get("type") == "missing_dep", sample
            assert result.get("dep") in ("bar", "gecko", "curios")

    def test_version_mismatch_detection(self):
        """Version incompatible errors."""
        loader = _make_loader()
        result = loader.detect_crash_reason("incompatible version of mod: expected 1.20, found 1.21")
        assert result.get("type") == "version_mismatch"

    def test_mod_loading_error_detection(self):
        """FML/modloading errors."""
        loader = _make_loader()
        result = loader.detect_crash_reason("fml: error while loading mod")
        assert result.get("type") == "mod_error"

    def test_unknown_log_returns_unknown(self):
        """Clean logs report unknown (no crash)."""
        loader = _make_loader()
        result = loader.detect_crash_reason("[INFO] Starting Minecraft server...")
        assert result.get("type") == "unknown"

    def test_prepare_environment(self, tmp_path):
        """prepare_environment writes jvm args, properties, eula."""
        cfg = ServerConfig()
        cfg.loader = "forge"
        loader = ForgeLoader(cfg, tmp_path)
        loader.prepare_environment()

        jvm = (tmp_path / "user_jvm_args.txt").read_text()
        assert jvm.startswith("-Xmx6G")
        assert "fml.query.verbose" in jvm

        props = (tmp_path / "server.properties").read_text()
        assert "enable-rcon=true" in props
        assert "NeoRunner - Forge Server" in props

        assert "eula=true" in (tmp_path / "eula.txt").read_text()

    def test_setup_server_properties_preserves_existing(self, tmp_path):
        """Existing property values are preserved."""
        loader = _make_loader()
        loader.cwd = tmp_path
        (tmp_path / "server.properties").write_text("online-mode=true\n")
        loader._setup_server_properties()
        props = (tmp_path / "server.properties").read_text()
        assert "online-mode=true" in props

    def test_validate_jvm_args(self, tmp_path):
        """JVM args validation for forge."""
        loader = _make_loader()
        good = tmp_path / "jvm.txt"
        good.write_text("-Xmx6G\n-XX:+UseG1GC\n")
        assert loader._validate_jvm_args(str(good)) is True

        corrupted = tmp_path / "bad.txt"
        corrupted.write_text("#!/bin/bash\necho hi\n")
        assert loader._validate_jvm_args(str(corrupted)) is False

        assert loader._validate_jvm_args(str(tmp_path / "missing.txt")) is False

    def test_setup_jvm_args_removes_corrupted(self, tmp_path):
        """Corrupted jvm args file is replaced."""
        loader = _make_loader()
        loader.cwd = tmp_path
        jvm = tmp_path / "user_jvm_args.txt"
        jvm.write_text("Dashboard broken\n")
        loader._setup_jvm_args()
        content = jvm.read_text()
        assert content.startswith("-Xmx6G")
        assert "Dashboard" not in content

    def test_build_java_command(self, tmp_path, monkeypatch):
        """Build command runs installer then returns java cmd."""
        loader = _make_loader()
        loader.cwd = tmp_path
        (tmp_path / "forge.jar").write_bytes(b"x")
        monkeypatch.setattr(
            "neorunner_pkg.loaders.forge.subprocess.run",
            lambda *a, **k: None,
        )
        cmd = loader.build_java_command()
        assert cmd[0] == "java"
        assert cmd[1] == "@user_jvm_args.txt"
        assert cmd[3].endswith("forge.jar")

    def test_get_loader_display_name(self):
        """Display name for forge."""
        loader = _make_loader()
        assert loader.get_loader_display_name() == "Forge"
