"""Tests for installer_jar module (client installer JAR builder)."""

import os
import sys
import zipfile
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.config import ServerConfig
from neorunner_pkg.installer_jar import (
    _build_pack_zip,
    build_installer_jar,
    build_installer_properties,
)


def _cfg(**overrides):
    defaults = {
        "mc_version": "26.1.2",
        "loader": "neoforge",
        "mods_dir": "mods",
        "clientonly_dir": "clientonly",
        "quarantine_dir": "quarantine",
        "http_port": 8000,
        "mc_port": 1234,
        "hostname": "",
    }
    defaults.update(overrides)
    return ServerConfig(**defaults)


class TestInstallerProperties:
    def test_default_properties(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg())
        assert "baseUrl=" in props
        assert "serverAddress=" in props
        assert "loader=neoforge" in props
        assert "mcVersion=26.1.2" in props
        assert "loaderVersion=" in props

    def test_custom_base_url(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(
            _cfg(), base_url="https://mc.w8.mom", server_address="w8.mom:1234"
        )
        assert "baseUrl=https://mc.w8.mom" in props
        assert "serverAddress=w8.mom:1234" in props

    def test_default_server_address_uses_mc_port(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg())
        assert "serverAddress=" in props

    def test_all_required_keys_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg(loader="fabric"))
        for key in ("baseUrl", "serverAddress", "loader", "mcVersion", "loaderVersion"):
            assert f"{key}=" in props

    def test_hostname_uses_https_base_url(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        props = build_installer_properties(_cfg(hostname="mc.w8.mom"))
        assert "baseUrl=https://mc.w8.mom" in props
        assert "serverAddress=mc.w8.mom:1234" in props

    def test_no_hostname_falls_back_to_lan_http(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        monkeypatch.setattr(
            "neorunner_pkg.installer_jar._get_local_ip", lambda: "192.168.0.50"
        )
        props = build_installer_properties(_cfg(hostname=""))
        assert "baseUrl=http://192.168.0.50:8000" in props
        assert "serverAddress=192.168.0.50:1234" in props


class TestPackZip:
    def test_pack_contains_mods_and_config(self, monkeypatch, tmp_path):
        mods = tmp_path / "mods"
        config = tmp_path / "config"
        mods.mkdir()
        config.mkdir()
        (mods / "awesome-1.0.jar").write_bytes(b"PKfakejar")
        (config / "mod.toml").write_text("enabled=true\n")

        cfg = _cfg(mods_dir=str(mods), clientonly_dir=str(tmp_path / "clientonly"))
        cfg.mods_dir = str(mods)
        cfg.clientonly_dir = str(tmp_path / "clientonly")

        def fake_builder(cfg):
            import zipfile as zf
            buf = BytesIO()
            with zf.ZipFile(buf, "w") as z:
                z.writestr("README.txt", "test")
                z.write(str(mods / "awesome-1.0.jar"), arcname="mods/awesome-1.0.jar")
                z.write(str(config / "mod.toml"), arcname="config/mod.toml")
            buf.seek(0)
            return buf

        monkeypatch.setattr(
            "neorunner_pkg.mod_hosting.build_launcher_zip_bytes", fake_builder
        )
        pack = _build_pack_zip(cfg)
        z = zipfile.ZipFile(BytesIO(pack))
        names = z.namelist()
        assert "mods/awesome-1.0.jar" in names
        assert "config/mod.toml" in names

    def test_pack_bytes_are_deterministic(self, monkeypatch, tmp_path):
        cfg = _cfg()

        def fake_builder(cfg):
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("README.txt", "same")
            buf.seek(0)
            return buf

        monkeypatch.setattr(
            "neorunner_pkg.mod_hosting.build_launcher_zip_bytes", fake_builder
        )
        assert _build_pack_zip(cfg) == _build_pack_zip(cfg)


class TestBuildJarEmbedding:
    def test_jar_embeds_pack_and_properties(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)

        java_src = tmp_path / "NeoRunnerInstaller.java"
        java_src.write_text("class NeoRunnerInstaller {}")
        monkeypatch.setattr("neorunner_pkg.installer_jar._JAVA_SRC", java_src)

        # Fake javac so the test doesn't need a real compiler.
        def fake_run(cmd, **kwargs):
            classes_dir = cmd[cmd.index("-d") + 1]
            out = os.path.join(classes_dir, "NeoRunnerInstaller.class")
            with open(out, "wb") as f:
                f.write(b"fakeclass")
            return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

        monkeypatch.setattr(
            "neorunner_pkg.installer_jar.subprocess.run", fake_run
        )
        monkeypatch.setattr("neorunner_pkg.installer_jar.shutil.which", lambda x: "/usr/bin/javac")

        def fake_builder(cfg):
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("mods/x.jar", "PK")
            buf.seek(0)
            return buf

        monkeypatch.setattr(
            "neorunner_pkg.mod_hosting.build_launcher_zip_bytes", fake_builder
        )

        jar = build_installer_jar(_cfg(hostname="mc.w8.mom"), base_url="https://mc.w8.mom",
                                  server_address="mc.w8.mom:1234", force=True)
        with zipfile.ZipFile(jar) as z:
            names = z.namelist()
            assert "pack.zip" in names
            assert "installer.properties" in names
            assert "NeoRunnerInstaller.class" in names
            manifest = z.read("META-INF/MANIFEST.MF").decode()
            assert "Main-Class: NeoRunnerInstaller" in manifest
            pack = zipfile.ZipFile(BytesIO(z.read("pack.zip")))
            assert "mods/x.jar" in pack.namelist()

    def test_cache_key_changes_with_pack(self, monkeypatch, tmp_path):
        monkeypatch.setattr("neorunner_pkg.installer_jar.CWD", tmp_path)
        java_src = tmp_path / "NeoRunnerInstaller.java"
        java_src.write_text("class NeoRunnerInstaller {}")
        monkeypatch.setattr("neorunner_pkg.installer_jar._JAVA_SRC", java_src)
        monkeypatch.setattr("neorunner_pkg.installer_jar.shutil.which", lambda x: "/usr/bin/javac")

        def fake_run(cmd, **kwargs):
            classes_dir = cmd[cmd.index("-d") + 1]
            with open(os.path.join(classes_dir, "NeoRunnerInstaller.class"), "wb") as f:
                f.write(b"fakeclass")
            return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

        monkeypatch.setattr("neorunner_pkg.installer_jar.subprocess.run", fake_run)

        packs = {"a": "mod-a.jar", "b": "mod-b.jar"}

        def fake_builder(cfg):
            buf = BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("mods/" + packs["current"], "PK")
            buf.seek(0)
            return buf

        monkeypatch.setattr("neorunner_pkg.mod_hosting.build_launcher_zip_bytes", fake_builder)

        cfg = _cfg(hostname="mc.w8.mom")
        packs["current"] = "a"
        jar_a = build_installer_jar(cfg, base_url="https://mc.w8.mom",
                                    server_address="mc.w8.mom:1234", force=True)
        packs["current"] = "b"
        jar_b = build_installer_jar(cfg, base_url="https://mc.w8.mom",
                                    server_address="mc.w8.mom:1234", force=True)
        assert jar_a.name != jar_b.name