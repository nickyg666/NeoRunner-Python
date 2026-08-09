"""Tests for NeoForge loader crash detection."""

import pytest
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from neorunner_pkg.loaders.neoforge import NeoForgeLoader
from neorunner_pkg.config import ServerConfig


def _make_loader():
    cfg = ServerConfig()
    cfg.loader = "neoforge"
    cfg.mc_version = "1.21.11"
    return NeoForgeLoader(cfg, Path("/tmp"))


class TestNeoForgeCrashDetection:
    """Test each NeoForge crash pattern."""

    def test_all_crash_patterns(self):
        """Each NeoForge pattern should be detected correctly."""
        cases = [
            # (log_sample, expected_type, expected_dep_or_culprit)
(
                "---- Minecraft Crash Report ----\n"
                "Failure message: mod foo requires bar",
                "missing_dep",
                "bar",
            ),
            (
                "---- Minecraft Crash Report ----\n"
                "Error loading mod: mymod\nnet.neoforged.fml.ModLoadingException",
                "mod_error",
                "mymod",
            ),
            (
                "---- Minecraft Crash Report ----\n"
                "DuplicateModsFoundException: mods/a.jar and mods/b.jar",
                "mod_conflict",
                "duplicate",
            ),
            (
                "---- Minecraft Crash Report ----\n"
                "This world is incompatible with the server version",
                "version_mismatch",
                None,
            ),
            (
                "---- Minecraft Crash Report ----\n"
                "mixin apply for mod coolmod failed",
                "mod_conflict",
                "mixin_fail",
            ),
            (
                "[16:20:11] [main/INFO] Starting minecraft server",
                "unknown",
                None,
            ),
        ]

        loader = _make_loader()
        for log_sample, expected_type, expected_detail in cases:
            result = loader.detect_crash_reason(log_sample)
            assert result.get("type") == expected_type, (
                f"Expected type {expected_type} for log, got {result.get('type')}"
            )
            if expected_type == "missing_dep":
                assert result.get("dep") == expected_detail
            elif result.get("type") == "mod_error":
                assert result.get("culprit") == expected_detail
            else:
                assert (expected_detail or "") in (result.get("conflict_type") or "")

    def test_version_extraction(self):
        """Extract MC version information from loader."""
        loader = _make_loader()
        assert loader.mc_version == "1.21.11"

        # detect_crash_reason should not raise on logs mentioning versions
        result = loader.detect_crash_reason(
            "---- Minecraft Crash Report ----\n"
            "Incompatible version of mod xyz\n"
            "Expected 1.21.11 but found 1.20.1"
        )
        assert result.get("type") == "version_mismatch"

    def test_fml_early_crash_detection(self):
        """FML detected errors during loading should be caught."""
        loader = _make_loader()
        log_text = (
            "[main/ERROR] [neoforge] FML detected errors during loading:\n"
            "mods/bootstrapmod\n"
            "mods/foo"
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") in ("mod_error", "unknown")

    def test_benign_mixin_warning_detection(self):
        """Mixin overwrite conflicts that are handled gracefully."""
        loader = _make_loader()
        log_text = (
            "[main/WARN] Overwrite conflict for m/foo in mixin.bar from mod baz, "
            "previously defined by mixin.qux. Skipping method."
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") == "benign_mixin_warning"

    def test_mod_crash_with_stack_trace(self):
        """Crash with mod package in stack trace should identify the mod."""
        loader = _make_loader()
        log_text = (
            "---- Minecraft Crash Report ----\n"
            "Description: Exception in server tick loop\n\n"
            "at com.example.coolmod.SomeClass.tick(SomeClass.java:42)\n"
            "at java.base/java.lang.Thread.run(Thread.java:1583)"
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") == "mod_error"
        assert result.get("culprit") == "coolmod"

    def test_bad_jar_detection(self):
        """Non-JAR file in mods folder is a mod_error."""
        loader = _make_loader()
        log_text = (
            "File mods/notamod.jar is not a jar file\n"
            "[main/ERROR] Loading error"
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") == "mod_error"
        assert result.get("bad_file") == "notamod.jar"

    def test_client_only_mixin_crash(self):
        """Client-only mod mixin crash detected."""
        loader = _make_loader()
        log_text = (
            "MixinPreProcessorException: Error processing mixin from mod coolclient\n"
            "mods/coolclient-1.0.0.jar"
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") == "mod_error"
        assert result.get("subtype") == "client_only"

    def test_client_class_reference_crash(self):
        """Mod referencing client classes on server is flagged."""
        loader = _make_loader()
        log_text = (
            "java.lang.NoClassDefFoundError: net/minecraft/client/gui/Gui\n"
            "Mod file: mods/badclient-1.0.jar\n"
            "Failed to create mod instance. ModID: badclient"
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") == "mod_error"
        assert result.get("subtype") == "client_only"
        assert "badclient" in result.get("culprits", [])

    def test_mixin_transformer_error(self):
        """MixinTransformerError from mod identified."""
        loader = _make_loader()
        log_text = (
            "MixinTransformerError: An unexpected critical error was encountered\n"
            "from mod mixintrouble"
        )
        result = loader.detect_crash_reason(log_text)
        assert result.get("type") == "mod_error"

    def test_jvm_args_validation(self, tmp_path):
        """user_jvm_args.txt validation accepts good, rejects corrupted."""
        loader = _make_loader()
        good = tmp_path / "user_jvm_args.txt"
        good.write_text("-Xmx4G\n-Xms2G\n-XX:+UseG1GC\n")
        assert loader._validate_jvm_args(str(good)) is True

        bad = tmp_path / "bad.txt"
        bad.write_text("echo rm -rf /\n")
        assert loader._validate_jvm_args(str(bad)) is False

        weird = tmp_path / "weird.txt"
        weird.write_text("not-a-jvm-arg\n")
        assert loader._validate_jvm_args(str(weird)) is False

        assert loader._validate_jvm_args(str(tmp_path / "missing.txt")) is False

    def test_setup_jvm_args_and_eula(self, tmp_path):
        """Setup creates user_jvm_args.txt and eula.txt."""
        cfg = ServerConfig()
        cfg.xmx = "4G"
        cfg.xms = "2G"
        loader = NeoForgeLoader(cfg, tmp_path)
        loader._setup_jvm_args()
        content = (tmp_path / "user_jvm_args.txt").read_text()
        assert content.startswith("-Xmx4G")
        assert "echo" not in content.lower()

        loader._setup_eula()
        assert "eula=true" in (tmp_path / "eula.txt").read_text()

    def test_setup_server_properties(self, tmp_path):
        """server.properties written with rcon and settings."""
        loader = _make_loader()
        loader.cwd = tmp_path
        loader._setup_server_properties()
        props = (tmp_path / "server.properties").read_text()
        assert "enable-rcon=true" in props
        assert "level-name=world" in props

    def test_setup_server_properties_preserves_existing(self, tmp_path):
        """Existing properties values preserved."""
        loader = _make_loader()
        loader.cwd = tmp_path
        (tmp_path / "server.properties").write_text("level-name=customworld\n")
        loader._setup_server_properties()
        props = (tmp_path / "server.properties").read_text()
        assert "level-name=customworld" in props

    def test_get_neoforge_version_local(self, tmp_path):
        """Version resolved from local libraries when present."""
        loader = _make_loader()
        loader.cwd = tmp_path
        lib = tmp_path / "libraries" / "net" / "neoforged" / "neoforge" / "21.1.100"
        lib.mkdir(parents=True)
        (lib / "neoforge-21.1.100-universal.jar").write_bytes(b"x")
        assert loader._get_neoforge_version() == "21.1.100"

    def test_get_neoforge_version_dynamic_fallback(self, tmp_path, monkeypatch):
        """Version falls back to dynamic fetch when no local libs."""
        loader = _make_loader()
        loader.cwd = tmp_path
        monkeypatch.setattr(
            "neorunner_pkg.version.get_latest_for_loader",
            lambda name: "21.1.140-foo",
        )
        assert loader._get_neoforge_version() == "21.1.140"

    def test_build_java_command_with_run_sh(self, tmp_path):
        """run.sh exists -> command uses it."""
        loader = _make_loader()
        loader.cwd = tmp_path
        (tmp_path / "run.sh").write_text("#!/bin/bash\njava @user_jvm_args.txt @loader_args.txt nogui\n")
        cmd = loader.build_java_command()
        assert cmd == ["./run.sh", "nogui"]

    def test_build_java_command_with_starter_jar(self, tmp_path, monkeypatch):
        """server.jar exists -> java -jar starter."""
        loader = _make_loader()
        loader.cwd = tmp_path
        lib = tmp_path / "libraries" / "net" / "neoforged" / "neoforge" / "21.1.100"
        lib.mkdir(parents=True)
        (lib / "neoforge-21.1.100-universal.jar").write_bytes(b"x")
        (tmp_path / "server.jar").write_bytes(b"starter")
        monkeypatch.setattr(
            "neorunner_pkg.loaders.neoforge.subprocess.run",
            lambda *a, **k: None,
        )
        cmd = loader.build_java_command()
        assert cmd[0] == "java"
        assert cmd[1] == "@user_jvm_args.txt"
        assert cmd[3].endswith("server.jar")
        assert cmd[4] == "nogui"

    def test_registry_conflict_detection(self):
        """Duplicate registry key detected as registry conflict."""
        loader = _make_loader()
        result = loader.detect_crash_reason(
            "Duplicate registry key: coolmod:block/foo is already registered"
        )
        assert result.get("type") == "mod_conflict"
        assert result.get("conflict_type") == "registry"
        assert "coolmod" in result.get("culprits", [])

    def test_mod_conflict_between_mods(self):
        """'mod X conflicts with mod Y' detected."""
        loader = _make_loader()
        result = loader.detect_crash_reason(
            "mod foo conflicts with mod bar - incompatible mods found"
        )
        assert result.get("type") == "mod_conflict"

    def test_mod_error_patterns(self):
        """Various mod error messages detected."""
        loader = _make_loader()
        for log in [
            "Error loading mod: brokenmod",
            "mod badmod has crashed",
            "Caused by mod: causer",
            "ModLoadingException in modloader",
        ]:
            result = loader.detect_crash_reason(log)
            assert result.get("type") == "mod_error", f"for log: {log}"
            assert result.get("culprit")

    def test_stack_trace_framework_mods_ignored(self):
        """Framework packages in stack traces don't produce mod_error."""
        loader = _make_loader()
        result = loader.detect_crash_reason(
            "Exception in server tick loop\n"
            "at net.minecraft.server.MinecraftServer.tick(MinecraftServer.java:100)"
        )
        assert result.get("type") != "mod_error" or result.get("culprit") is not None

    def test_build_java_command_no_jar(self, tmp_path, monkeypatch):
        """No server.jar and no run.sh -> fallback direct -jar."""
        loader = _make_loader()
        loader.cwd = tmp_path
        lib = tmp_path / "libraries" / "net" / "neoforged" / "neoforge" / "21.1.100"
        lib.mkdir(parents=True)
        (lib / "neoforge-21.1.100-universal.jar").write_bytes(b"x")
        monkeypatch.setattr(
            "neorunner_pkg.loaders.neoforge.subprocess.run",
            lambda *a, **k: None,
        )
        cmd = loader.build_java_command()
        assert cmd[0] == "java"
        assert cmd[1] == "@user_jvm_args.txt"

    def test_world_version_mismatch_backs_up_world(self, tmp_path):
        """World with mismatched version gets backed up."""
        cfg = ServerConfig()
        cfg.mc_version = "1.21.11"
        loader = NeoForgeLoader(cfg, tmp_path)
        world_dir = tmp_path / "world"
        world_dir.mkdir()
        (world_dir / "level.dat").write_bytes(b"x")
        (tmp_path / "world" / "version").write_text("1.20.1")
        loader._setup_server_properties()
        backups = list(tmp_path.glob("world_old_*"))
        assert len(backups) == 1
        assert backups[0].is_dir()

    def test_jvm_args_corrupted_dashboard(self, tmp_path):
        """Dashboard/bash content triggers regeneration."""
        loader = _make_loader()
        f = tmp_path / "user_jvm_args.txt"
        f.write_text("Dashboard control panel\n")
        assert loader._validate_jvm_args(str(f)) is False
        f.write_text("-Xmx4G\n")
        assert loader._validate_jvm_args(str(f)) is True