"""Tests for CurseForge modpack zip structure (public_site._build_curseforge_zip)."""

import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg import public_site


@pytest.fixture
def build_env(monkeypatch, tmp_path):
    """Isolated server layout: 19 mod jars + shaderpack + world zip in mods/."""
    mods = tmp_path / "mods"
    mods.mkdir()
    for i in range(19):
        jar = mods / f"mod{i}.jar"
        jar.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    shader = mods / "MakeUp-UltraFast-9.5c.zip"
    with zipfile.ZipFile(shader, "w") as zf:
        zf.writestr("shaders/README.txt", "shader")

    world = mods / "Lucky OneBlock 26.1.X (v1.1).zip"
    with zipfile.ZipFile(world, "w") as zf:
        zf.writestr("Lucky OneBlock 26.1.X (v1.1)/level.dat", "data")

    clientonly = tmp_path / "clientonly"
    clientonly.mkdir()
    (clientonly / "sodium-neoforge-0.9.2.jar").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (clientonly / "iris-neoforge-1.11.3.jar").write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    def fake_server_info():
        return {
            "mc_version": "26.1.2",
            "loader": "neoforge",
            "loader_version": "26.1.2.87",
            "server_address": "mc.w8.mom",
        }

    def fake_modpack_meta():
        return {"name": "default", "version": "0.1.0"}

    def fake_cf_files():
        # 19 mod jars + shaderpack (431203) + world (872580) + iris (client-only)
        entries = []
        for i in range(19):
            entries.append({"projectID": 1000 + i, "fileID": 2000 + i, "required": True})
        entries.append({"projectID": 431203, "fileID": 5001, "required": True})
        entries.append({"projectID": 872580, "fileID": 5002, "required": True})
        entries.append({"projectID": 455508, "fileID": 5003, "required": True})  # iris
        return entries

    def fake_cf_id_map():
        m = {}
        for i in range(19):
            m[f"mod{i}.jar"] = {"projectID": 1000 + i, "fileID": 2000 + i}
        m["MakeUp-UltraFast-9.5c.zip"] = {"projectID": 431203, "fileID": 5001}
        m["Lucky OneBlock 26.1.X (v1.1).zip"] = {"projectID": 872580, "fileID": 5002}
        m["iris-neoforge-1.11.3.jar"] = {"projectID": 455508, "fileID": 5003}
        return m

    def fake_collect_jars():
        jars = []
        for f in sorted((tmp_path / "mods").glob("*.jar")):
            jars.append((f.name, str(f)))
        for f in sorted((tmp_path / "clientonly").glob("*.jar")):
            jars.append((f.name, str(f)))
        return jars

    monkeypatch.setattr(public_site, "_server_info", fake_server_info)
    monkeypatch.setattr(public_site, "_modpack_meta", fake_modpack_meta)
    monkeypatch.setattr(public_site, "_modpack_cf_files", fake_cf_files)
    monkeypatch.setattr(public_site, "_cf_id_map", fake_cf_id_map)
    monkeypatch.setattr(public_site, "_collect_jars", fake_collect_jars)
    monkeypatch.setattr(public_site, "CWD", tmp_path)
    monkeypatch.setattr(public_site, "load_cfg", lambda: None)
    return tmp_path


class TestCurseforgeZip:
    def test_manifest_type_casing(self, build_env):
        buf = public_site._build_curseforge_zip()
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["manifestType"] == "minecraftModpack"
        assert manifest["manifestVersion"] == 1

    def test_meta_from_pack(self, build_env):
        buf = public_site._build_curseforge_zip()
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["name"] == "default"
        assert manifest["version"] == "0.1.0"

    def test_files_only_mod_jars(self, build_env):
        buf = public_site._build_curseforge_zip()
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        files = manifest["files"]
        # 19 server mod jars + iris (client-only jar the client still needs);
        # shaderpack + world zip are NOT mod jars and must not be in files[].
        assert len(files) == 20
        pids = {f["projectID"] for f in files}
        assert 431203 not in pids
        assert 872580 not in pids
        assert 455508 in pids

    def test_non_mod_assets_in_overrides(self, build_env):
        buf = public_site._build_curseforge_zip()
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        assert "overrides/shaderpacks/MakeUp-UltraFast-9.5c.zip" in names
        # World save: level.dat must sit directly under the world folder
        assert "overrides/saves/Lucky OneBlock 26.1.X (v1.1)/level.dat" in names

    def test_clientonly_jars_in_overrides_mods(self, build_env):
        buf = public_site._build_curseforge_zip()
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        # sodium isn't part of any CF pack -> goes into overrides/mods.
        # iris is referenced in manifest files[] -> downloaded by launcher,
        # NOT duplicated into overrides/mods.
        assert "overrides/mods/sodium-neoforge-0.9.2.jar" in names
        assert "overrides/mods/iris-neoforge-1.11.3.jar" not in names

    def test_roundtrip_readable(self, build_env):
        buf = public_site._build_curseforge_zip()
        buf.seek(0)
        data = buf.read()
        assert data.startswith(b"PK")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
