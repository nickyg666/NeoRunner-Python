"""Tests for world upload validation, staging, archiving and restore."""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def make_java_world(root: Path, name: str = "world") -> Path:
    world = root / name
    (world / "region").mkdir(parents=True, exist_ok=True)
    (world / "level.dat").write_bytes(b"not-really-nbt")
    (world / "region" / "r.0.0.mca").write_bytes(b"chunkdata")
    return world


def make_bedrock_world(root: Path, name: str = "bedrock") -> Path:
    world = root / name
    (world / "db").mkdir(parents=True, exist_ok=True)
    (world / "level.dat").write_bytes(b"little-endian-nbt")
    (world / "levelname.txt").write_text("Bedrock World")
    (world / "db" / "0000000000000000.ldb").write_bytes(b"kval")
    return world


class TestSanitize:
    def test_ok_path(self):
        from neorunner_pkg.world_upload import sanitize_rel_path
        assert sanitize_rel_path("region/r.0.0.mca") == "region/r.0.0.mca"

    def test_backslashes_normalized(self):
        from neorunner_pkg.world_upload import sanitize_rel_path
        assert sanitize_rel_path("region\\r.0.0.mca") == "region/r.0.0.mca"

    @pytest.mark.parametrize("bad", ["../evil", "a/../../evil", "/abs/path", "C:/win", ".."])
    def test_traversal_rejected(self, bad):
        from neorunner_pkg.world_upload import sanitize_rel_path
        with pytest.raises(ValueError):
            sanitize_rel_path(bad)

    def test_world_name_sanitized(self):
        from neorunner_pkg.world_upload import sanitize_world_name
        assert sanitize_world_name("../My||World/") == "MyWorld"
        assert sanitize_world_name("")
        assert len(sanitize_world_name("x" * 200)) <= 64


class TestStaging:
    def test_create_and_abort(self, tmp_path):
        from neorunner_pkg.world_upload import (
            abort_upload,
            create_staging,
            resolve_staging,
        )
        st = create_staging(cwd=tmp_path)
        token = st["token"]
        assert token
        assert resolve_staging(token, tmp_path).is_dir()
        abort_upload(token, tmp_path)
        with pytest.raises(FileNotFoundError):
            resolve_staging(token, tmp_path)

    def test_stage_file_and_meta(self, tmp_path):
        from neorunner_pkg.world_upload import (
            create_staging,
            resolve_staging,
            stage_file,
        )
        token = create_staging(cwd=tmp_path)["token"]
        stage_file(token, "region/r.0.0.mca", b"x" * 10, cwd=tmp_path)
        stage_file(token, "level.dat", b"y" * 20, cwd=tmp_path)
        meta = resolve_staging(token, tmp_path)
        assert (meta / "region" / "r.0.0.mca").exists()
        from neorunner_pkg.world_upload import _read_meta
        m = _read_meta(meta)
        assert m["files"] == 2
        assert m["bytes"] == 30

    def test_caps_enforced(self, tmp_path, monkeypatch):
        from neorunner_pkg import world_upload
        monkeypatch.setattr(world_upload, "_stage_limits", lambda cwd: (20, 2))
        token = world_upload.create_staging(cwd=tmp_path)["token"]
        world_upload.stage_file(token, "a.bin", b"x" * 15, cwd=tmp_path)
        with pytest.raises(ValueError):
            world_upload.stage_file(token, "b.bin", b"y" * 15, cwd=tmp_path)


class TestDetection:
    def test_find_world_root_flat(self, tmp_path):
        from neorunner_pkg.world_upload import find_world_root
        make_java_world(tmp_path, "MyWorld")
        assert find_world_root(tmp_path) == tmp_path / "MyWorld"

    def test_find_world_root_nested(self, tmp_path):
        from neorunner_pkg.world_upload import find_world_root
        make_java_world(tmp_path / "archive", "MyWorld")
        assert find_world_root(tmp_path / "archive") == tmp_path / "archive" / "MyWorld"

    def test_detect_bedrock(self, tmp_path):
        from neorunner_pkg.world_upload import detect_platform
        world = make_bedrock_world(tmp_path, "bed")
        assert detect_platform(world) == "bedrock"

    def test_detect_java(self, tmp_path):
        from neorunner_pkg.world_upload import detect_platform
        world = make_java_world(tmp_path, "java")
        assert detect_platform(world) == "java"

    def test_detect_unknown(self, tmp_path):
        from neorunner_pkg.world_upload import detect_platform
        d = tmp_path / "empty"
        d.mkdir()
        assert detect_platform(d) == "unknown"

    def test_bedrock_by_levelname_marker(self, tmp_path):
        from neorunner_pkg.world_upload import detect_platform
        d = tmp_path / "min"
        d.mkdir()
        (d / "levelname.txt").write_text("x")
        assert detect_platform(d) == "bedrock"


class TestJavaCompat:
    def test_min_java_major_mapping(self):
        from neorunner_pkg.world_upload import min_java_major
        assert min_java_major("1.21.11") == 21
        assert min_java_major("1.20.5") == 21
        assert min_java_major("1.20.4") == 17
        assert min_java_major("1.18.2") == 17
        assert min_java_major("1.17.1") == 16
        assert min_java_major("1.16.5") == 8
        assert min_java_major(None) is None
        assert min_java_major("26.1.2") is None

    def test_java_compatibility(self):
        from neorunner_pkg.world_upload import java_compatibility
        assert java_compatibility("1.21.11", "1.21.11") == "compatible"
        assert java_compatibility("1.21.10", "1.21.11") == "warning"
        assert java_compatibility("1.20.4", "1.21.11") == "incompatible"
        assert java_compatibility(None, "1.21.11") == "na"


class TestAnalyze:
    def test_analyze_java_world(self, tmp_path):
        from neorunner_pkg.world_upload import (
            analyze_upload,
            create_staging,
            stage_file,
        )
        make_java_world(tmp_path, "MyWorld")
        token = create_staging(cwd=tmp_path)["token"]
        for p in ["level.dat", "region/r.0.0.mca"]:
            stage_file(token, p, (tmp_path / "MyWorld" / p).read_bytes(), cwd=tmp_path)
        a = analyze_upload(token, server_mc_version="1.21.11", cwd=tmp_path)
        assert a["valid"] is True
        assert a["platform"] == "java"
        assert a["is_bedrock"] is False

    def test_analyze_bedrock_world(self, tmp_path):
        from neorunner_pkg.world_upload import (
            analyze_upload,
            create_staging,
            stage_file,
        )
        make_bedrock_world(tmp_path, "Bed")
        token = create_staging(cwd=tmp_path)["token"]
        # Upload every file under the bedrock world (skip folder wrapper).
        for p in sorted((tmp_path / "Bed").rglob("*")):
            if p.is_file():
                rel = p.relative_to(tmp_path / "Bed").as_posix()
                stage_file(token, rel, p.read_bytes(), cwd=tmp_path)
        a = analyze_upload(token, server_mc_version="1.21.11", cwd=tmp_path)
        assert a["valid"] is True
        assert a["is_bedrock"] is True

    def test_analyze_not_a_world(self, tmp_path):
        from neorunner_pkg.world_upload import (
            analyze_upload,
            create_staging,
            stage_file,
        )
        token = create_staging(cwd=tmp_path)["token"]
        stage_file(token, "notes.txt", b"not a world", cwd=tmp_path)
        a = analyze_upload(token, server_mc_version="1.21.11", cwd=tmp_path)
        assert a["valid"] is False
        assert a["errors"]

    def test_suspicious_files_flagged(self, tmp_path):
        from neorunner_pkg.world_upload import (
            analyze_upload,
            create_staging,
            stage_file,
        )
        make_java_world(tmp_path, "MyWorld")
        token = create_staging(cwd=tmp_path)["token"]
        for p in ["level.dat", "region/r.0.0.mca"]:
            stage_file(token, p, (tmp_path / "MyWorld" / p).read_bytes(), cwd=tmp_path)
        stage_file(token, "secret.exe", b"MZ", cwd=tmp_path)
        a = analyze_upload(token, server_mc_version="1.21.11", cwd=tmp_path)
        assert "secret.exe" in a["suspicious_files"]


class TestAcceptRestore:
    def test_accept_creates_archive_and_cleans_staging(self, tmp_path):
        from neorunner_pkg.world_upload import (
            accept_upload,
            create_staging,
            list_archived_worlds,
            resolve_staging,
            stage_file,
        )
        make_java_world(tmp_path, "MyWorld")
        token = create_staging(cwd=tmp_path)["token"]
        for p in ["level.dat", "region/r.0.0.mca"]:
            stage_file(token, p, (tmp_path / "MyWorld" / p).read_bytes(), cwd=tmp_path)

        result = accept_upload(token, "MyWorld", mc_version="1.21.11", loader="neoforge", cwd=tmp_path)
        assert result["success"] is True
        assert result["mc_version"] == "1.21.11"
        assert "MyWorld.tar.gz" in result["archive"]
        # staging slot removed
        with pytest.raises(FileNotFoundError):
            resolve_staging(token, tmp_path)
        # listed as a compressed archive
        entries = list_archived_worlds(cwd=tmp_path)
        comp = [e for e in entries if e["name"] == "MyWorld" and e["compressed"]]
        assert comp and comp[0]["mc_version"] == "1.21.11"

    def test_restore_compressed_archive(self, tmp_path):
        from neorunner_pkg.world_upload import (
            accept_upload,
            create_staging,
            restore_archived_world,
            stage_file,
        )
        make_java_world(tmp_path, "MyWorld")
        token = create_staging(cwd=tmp_path)["token"]
        for p in ["level.dat", "region/r.0.0.mca"]:
            stage_file(token, p, (tmp_path / "MyWorld" / p).read_bytes(), cwd=tmp_path)
        accept_upload(token, "MyWorld", mc_version="1.21.11", loader="neoforge", cwd=tmp_path)

        # Remove the copy that was the upload source to prove restore works from the archive.
        import shutil
        shutil.rmtree(tmp_path / "MyWorld")

        ok, msg = restore_archived_world("MyWorld", cwd=tmp_path)
        assert ok, msg
        assert (tmp_path / "MyWorld" / "level.dat").exists()
        assert (tmp_path / "MyWorld" / "region" / "r.0.0.mca").exists()

    def test_duplicate_accept_rejected(self, tmp_path):
        from neorunner_pkg.world_upload import (
            accept_upload,
            create_staging,
            stage_file,
        )
        make_java_world(tmp_path, "MyWorld")
        token = create_staging(cwd=tmp_path)["token"]
        for p in ["level.dat", "region/r.0.0.mca"]:
            stage_file(token, p, (tmp_path / "MyWorld" / p).read_bytes(), cwd=tmp_path)
        accept_upload(token, "MyWorld", mc_version="1.21.11", loader="neoforge", cwd=tmp_path)
        token2 = create_staging(cwd=tmp_path)["token"]
        for p in ["level.dat", "region/r.0.0.mca"]:
            stage_file(token2, p, (tmp_path / "MyWorld" / p).read_bytes(), cwd=tmp_path)
        with pytest.raises(ValueError):
            accept_upload(token2, "MyWorld", mc_version="1.21.11", loader="neoforge", cwd=tmp_path)


class TestArchiveExtract:
    def _zip_world(self, path: Path, name: str) -> Path:
        z = path / f"{name}.zip"
        make_java_world(path, name)
        with zipfile.ZipFile(z, "w") as zf:
            for p in (path / name).rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=f"{name}/{p.relative_to(path / name).as_posix()}")
        return z

    def test_extract_zip_upload(self, tmp_path):
        from neorunner_pkg.world_upload import (
            create_staging,
            extract_archive_upload,
            stage_file,
        )
        z = self._zip_world(tmp_path, "ZipWorld")
        token = create_staging(cwd=tmp_path)["token"]
        stage_file(token, "_upload_ZipWorld.zip", z.read_bytes(), cwd=tmp_path)
        root = extract_archive_upload(token, cwd=tmp_path)
        assert (root / "level.dat").exists()
        assert (root / "region" / "r.0.0.mca").exists()

    def test_extract_archive_traversal_tolerated(self, tmp_path):
        from neorunner_pkg.world_upload import (
            create_staging,
            extract_archive_upload,
            stage_file,
        )
        make_java_world(tmp_path, "MyWorld")
        z = tmp_path / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../evil.txt", "nope")
            zf.writestr("MyWorld/level.dat", "lvl")
            zf.writestr("MyWorld/region/r.0.0.mca", "x")
        token = create_staging(cwd=tmp_path)["token"]
        stage_file(token, "_upload_evil.zip", z.read_bytes(), cwd=tmp_path)
        root = extract_archive_upload(token, cwd=tmp_path)
        # traversal member dropped; world still extracted
        assert (root / "level.dat").exists()
        assert not (tmp_path / "worlds_archive" / ".." / "evil.txt").exists()


class TestConfigDefaults:
    def test_new_fields_have_defaults(self):
        from neorunner_pkg.config import ServerConfig
        cfg = ServerConfig()
        assert cfg.chunker_jar == ""
        assert cfg.world_upload_dir == "world_uploads"
        assert cfg.world_upload_max_total_mb > 0
        assert cfg.world_staging_retention_hours > 0