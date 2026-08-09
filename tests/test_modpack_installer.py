"""Tests for modpack_installer module (CurseForge modpack zip installer)."""

import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg.modpack_installer import (
    _cf_download_path,
    extract_overrides,
    install_curseforge_pack,
    parse_manifest,
)


def _make_pack_zip(path, files=None, name="MyPack", version="0.1.0"):
    """Create a CurseForge-format modpack zip."""
    files = files or [
        {"projectID": 111, "fileID": 222, "required": True},
        {"projectID": 333, "fileID": 444, "required": True},
    ]
    manifest = {
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": name,
        "version": version,
        "author": "tester",
        "files": files,
        "overrides": "overrides",
        "minecraft": {
            "version": "26.1.2",
            "modLoaders": [{"id": "neoforge-26.1.2.87", "primary": True}],
        },
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("overrides/config/toml.toml", "setting = true")
        zf.writestr("overrides/config/nested/dir.txt", "hi")


class TestParseManifest:
    def test_parses_valid_pack(self, tmp_path):
        path = tmp_path / "pack.zip"
        _make_pack_zip(path)
        manifest, files = parse_manifest(path)
        assert manifest["name"] == "MyPack"
        assert manifest["minecraft"]["version"] == "26.1.2"
        assert len(files) == 2
        assert files[0] == {"projectID": 111, "fileID": 222, "required": True}

    def test_skips_entries_without_fileid(self, tmp_path):
        path = tmp_path / "pack.zip"
        _make_pack_zip(path, files=[
            {"projectID": 1, "fileID": 100, "required": True},
            {"projectID": 2, "fileID": None, "required": True},
            {"projectID": 3, "required": True},
        ])
        _, files = parse_manifest(path)
        assert len(files) == 1
        assert files[0]["fileID"] == 100

    def test_missing_manifest_raises(self, tmp_path):
        path = tmp_path / "bad.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("readme.txt", "no manifest here")
        with pytest.raises(KeyError):
            parse_manifest(path)


class TestCdnPath:
    def test_cdn_path_layout(self):
        assert _cf_download_path(8050253) == "/files/8050/253"
        assert _cf_download_path(123) == "/files/0/123"

    def test_install_on_invalid_zip(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("junk.txt", "hello")
        result = install_curseforge_pack(bad, tmp_path / "mods")
        assert result.failed == 0
        assert result.total == 0
        assert result.errors
        assert not result.success


class TestExtractOverrides:
    def test_extracts_overrides_sanitized(self, tmp_path):
        pack = tmp_path / "pack.zip"
        _make_pack_zip(pack)
        dest = tmp_path / "server"
        n = extract_overrides(pack, dest)
        assert n == 2
        assert (dest / "config" / "toml.toml").exists()
        assert (dest / "config" / "nested" / "dir.txt").exists()

    def test_path_traversal_blocked(self, tmp_path):
        pack = tmp_path / "evil.zip"
        with zipfile.ZipFile(pack, "w") as zf:
            zf.writestr("overrides/../escape.txt", "boom")
            zf.writestr("manifest.json", json.dumps({"files": []}))
        dest = tmp_path / "server"
        n = extract_overrides(pack, dest)
        assert n == 0
        assert not (tmp_path / "escape.txt").exists()


class TestDownloadDedupe:
    def test_duplicate_filenames_skipped(self, tmp_path, monkeypatch):
        pack = tmp_path / "pack.zip"
        _make_pack_zip(pack, files=[
            {"projectID": 1, "fileID": 100, "required": True},
            {"projectID": 2, "fileID": 200, "required": True},
        ])
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        def fake_resolve(pid, fid):
            return "shared-name.jar"

        def fake_download(pid, fid, dest, filename=None, on_progress=None):
            (dest / filename).write_bytes(b"jar")
            return True, filename

        monkeypatch.setattr("neorunner_pkg.modpack_installer.resolve_file_name", fake_resolve)
        monkeypatch.setattr("neorunner_pkg.modpack_installer.download_cf_mod", fake_download)
        monkeypatch.setattr("neorunner_pkg.modpack_installer.extract_overrides", lambda *a, **k: 0)

        result = install_curseforge_pack(pack, mods_dir)
        assert result.installed == 1
        assert result.skipped == 1
        statuses = [f["status"] for f in result.files]
        assert "installed" in statuses
        assert "duplicate" in statuses

    def test_install_report_fields(self, tmp_path, monkeypatch):
        pack = tmp_path / "pack.zip"
        _make_pack_zip(pack, files=[{"projectID": 1, "fileID": 100, "required": True}])
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()

        monkeypatch.setattr(
            "neorunner_pkg.modpack_installer.resolve_file_name",
            lambda pid, fid: "mod.jar",
        )
        monkeypatch.setattr(
            "neorunner_pkg.modpack_installer.download_cf_mod",
            lambda pid, fid, dest, filename=None, on_progress=None: (True, "mod.jar"),
        )
        monkeypatch.setattr("neorunner_pkg.modpack_installer.extract_overrides", lambda *a, **k: 0)

        result = install_curseforge_pack(pack, mods_dir)
        assert result.pack_name == "MyPack"
        assert result.pack_version == "0.1.0"
        assert result.mc_version == "26.1.2"
        assert "neoforge" in result.loader
        assert result.total == 1
        assert result.installed == 1
        assert result.success
