"""Tests for the Chunker CLI wrapper (world conversion)."""

import sys
from pathlib import Path

import pytest

from neorunner_pkg.config import ServerConfig

sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeProc:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestFormatMapping:
    def test_full_version_mapping(self):
        from neorunner_pkg.chunker import mc_to_chunker_format
        assert mc_to_chunker_format("1.21.11") == "JAVA_1_21_11"

    def test_short_version_mapping(self):
        from neorunner_pkg.chunker import mc_to_chunker_format
        assert mc_to_chunker_format("1.21") == "JAVA_1_21"

    def test_dirty_version_cleaned(self):
        from neorunner_pkg.chunker import mc_to_chunker_format
        assert mc_to_chunker_format(" 1.20.5-beta ") == "JAVA_1_20_5"

    def test_junk_has_fallback(self):
        from neorunner_pkg.chunker import mc_to_chunker_format
        assert mc_to_chunker_format("garbage") == "JAVA_1_21"


class TestEnsureChunker:
    def test_downloads_when_missing(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = tmp_path / "tools" / "chunker-cli.jar"
        cfg = ServerConfig(chunker_jar=str(jar))

        def fake_download(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * 200_000)

        monkeypatch.setattr(chunker, "_download", fake_download)
        monkeypatch.setattr(chunker, "_latest_cli_asset_url", lambda: "https://example.com/chunker-cli.jar")
        result = chunker.ensure_chunker(cfg)
        assert result == jar
        assert jar.exists()

    def test_reuses_existing_jar(self, tmp_path):
        from neorunner_pkg import chunker
        jar = tmp_path / "chunker-cli.jar"
        jar.write_bytes(b"y" * 200_000)
        cfg = ServerConfig(chunker_jar=str(jar))
        assert chunker.ensure_chunker(cfg) == jar

    def test_raises_on_too_small_download(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = tmp_path / "chunker-cli.jar"
        cfg = ServerConfig(chunker_jar=str(jar))

        def tiny_download(url, dest):
            dest.write_bytes(b"tiny")

        monkeypatch.setattr(chunker, "_download", tiny_download)
        monkeypatch.setattr(chunker, "_latest_cli_asset_url", lambda: "https://example.com/chunker-cli.jar")
        with pytest.raises(RuntimeError):
            chunker.ensure_chunker(cfg)


class TestFormats:
    def test_list_parse(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = tmp_path / "chunker-cli.jar"
        jar.write_bytes(b"z" * 200_000)

        def fake_run(cmd, **kw):
            return FakeProc(stdout="JAVA_1_21_11  JAVA_1_20_5\nBEDROCK_1_21_0\nnot_a_format\n")

        monkeypatch.setattr(chunker.subprocess, "run", fake_run)
        fmts = chunker.list_available_formats(jar)
        assert "JAVA_1_21_11" in fmts
        assert "BEDROCK_1_21_0" in fmts
        assert "not_a_format" not in fmts

    def test_java_formats_filter(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = tmp_path / "chunker-cli.jar"
        jar.write_bytes(b"z" * 200_000)

        def fake_run(cmd, **kw):
            return FakeProc(stdout="JAVA_1_21_11\nJAVA_1_20\nBEDROCK_1_21_0\n")

        monkeypatch.setattr(chunker.subprocess, "run", fake_run)
        fmts = chunker.java_formats(jar)
        assert set(fmts) == {"JAVA_1_21_11", "JAVA_1_20"}


class TestConvertWorld:
    def _jar(self, tmp_path) -> Path:
        jar = tmp_path / "chunker-cli.jar"
        jar.write_bytes(b"z" * 200_000)
        return jar

    def test_successful_conversion(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = self._jar(tmp_path)
        src = tmp_path / "input"
        (src / "region").mkdir(parents=True, exist_ok=True)
        (src / "level.dat").write_bytes(b"x")
        out = tmp_path / "output"

        def fake_run(cmd, **kw):
            assert cmd[0] == "java"
            assert f"-Xmx{xmx}" in cmd
            assert str(jar) in cmd
            return FakeProc()

        xmx = "4G"
        monkeypatch.setattr(chunker.subprocess, "run", fake_run)
        result = chunker.convert_world(src, "JAVA_1_21_11", out, xmx=xmx, chunker_jar=jar)
        assert result["success"] is True
        assert Path(result["output_dir"]).is_dir()

    def test_rejects_invalid_format(self, tmp_path):
        from neorunner_pkg import chunker
        jar = self._jar(tmp_path)
        result = chunker.convert_world(tmp_path, "JAVA", tmp_path / "o", chunker_jar=jar)
        assert result["success"] is False
        assert "invalid" in result["error"]

    def test_missing_jar(self, tmp_path):
        from neorunner_pkg import chunker
        result = chunker.convert_world(tmp_path, "JAVA_1_21_11", tmp_path / "o",
                                        chunker_jar=tmp_path / "nope.jar")
        assert result["success"] is False
        assert "not installed" in result["error"]

    def test_failure_reports_error(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = self._jar(tmp_path)

        def fail_run(cmd, **kw):
            return FakeProc(returncode=1, stderr="boom")

        monkeypatch.setattr(chunker.subprocess, "run", fail_run)
        result = chunker.convert_world(tmp_path, "JAVA_1_21_11", tmp_path / "o", chunker_jar=jar)
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_ensures_output_dir_created(self, tmp_path, monkeypatch):
        from neorunner_pkg import chunker
        jar = self._jar(tmp_path)
        out = tmp_path / "brand_new_out"

        def fake_run(cmd, **kw):
            return FakeProc()

        monkeypatch.setattr(chunker.subprocess, "run", fake_run)
        result = chunker.convert_world(tmp_path, "JAVA_1_21_11", out, chunker_jar=jar)
        assert result["success"] is True
        assert out.is_dir()