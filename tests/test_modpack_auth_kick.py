"""Tests for dashboard Basic Auth and modpack endpoints."""

import base64
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg.config import ServerConfig

AUTH = "Basic " + base64.b64encode(b"mc:123").decode()


def _auth_header(user="mc", password="123"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


class TestBasicAuth:
    @pytest.fixture
    def app(self):
        from neorunner_pkg.dashboard import app
        app.config["TESTING"] = True
        return app

    def test_no_credentials_rejected(self, app):
        with app.test_client() as c:
            r = c.get("/admin")
            assert r.status_code == 401
            assert "Basic" in r.headers.get("WWW-Authenticate", "")

    def test_wrong_password_rejected(self, app):
        with app.test_client() as c:
            r = c.get("/api/status", headers=_auth_header(password="nope"))
            assert r.status_code == 401

    def test_mc_credentials_accepted(self, app):
        with app.test_client() as c:
            r = c.get("/api/status", headers=_auth_header())
            assert r.status_code == 200

    def test_download_routes_exempt(self, app):
        with app.test_client() as c:
            r = c.get("/download/manifest")
            assert r.status_code == 200
            assert "files" in r.json

    def test_websocket_exempt(self, app):
        with app.test_client() as c:
            r = c.get("/socket.io")
            assert r.status_code != 401


class TestModpackEndpoints:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from neorunner_pkg import dashboard
        monkeypatch.setattr(dashboard, "MODPACK_UPLOAD_DIR", tmp_path / "modpacks")
        dashboard.app.config["TESTING"] = True
        with dashboard.app.test_client() as c:
            yield c

    def _make_zip(self, path, name="default", version="0.1.0"):
        manifest = {
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": name,
            "version": version,
            "files": [
                {"projectID": 1, "fileID": 100, "required": True},
            ],
            "minecraft": {
                "version": "26.1.2",
                "modLoaders": [{"id": "neoforge-26.1.2.87", "primary": True}],
            },
            "overrides": "overrides",
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        buf.seek(0)
        return buf

    def test_list_empty(self, client):
        r = client.get("/api/modpacks", headers=_auth_header())
        assert r.status_code == 200
        assert r.json["packs"] == []

    def test_upload_requires_auth(self, client):
        r = client.post("/api/modpack/upload", data={})
        assert r.status_code == 401

    def test_upload_and_list(self, client):
        buf = self._make_zip(None)
        name = "default-0.1.0.zip"
        data = {"file": (buf, name)}
        r = client.post("/api/modpack/upload", data=data, headers=_auth_header(), content_type="multipart/form-data")
        assert r.status_code == 200
        body = r.json
        assert body["success"] is True
        assert body["manifest"]["mod_count"] == 1
        assert body["manifest"]["mc_version"] == "26.1.2"

        r = client.get("/api/modpacks", headers=_auth_header())
        assert r.status_code == 200
        assert any(p["filename"] == name for p in r.json["packs"])

    def test_upload_rejects_non_zip(self, client):
        data = {"file": (io.BytesIO(b"not a zip"), "evil.txt")}
        r = client.post("/api/modpack/upload", data=data, headers=_auth_header(), content_type="multipart/form-data")
        assert r.status_code == 400

    def test_install_missing_pack_404(self, client):
        r = client.post("/api/modpack/install", json={"filename": "nonexistent.zip"}, headers=_auth_header())
        assert r.status_code == 404

    def test_install_endpoint_runs(self, client, monkeypatch):
        buf = self._make_zip(None)
        name = "default-0.1.0.zip"
        r = client.post("/api/modpack/upload", data={"file": (buf, name)}, headers=_auth_header(), content_type="multipart/form-data")
        assert r.status_code == 200

        from neorunner_pkg.modpack_installer import InstallResult

        def fake_install(zip_path, mods_dir, overrides_dir=None):
            result = InstallResult(
                pack_name="default", pack_version="0.1.0",
                mc_version="26.1.2", loader="neoforge-26.1.2.87",
                total=1, installed=1,
            )
            result.files.append({"projectID": 1, "fileID": 100, "file": "mod.jar", "status": "installed"})
            return result

        monkeypatch.setattr("neorunner_pkg.modpack_installer.install_curseforge_pack", fake_install)
        monkeypatch.setattr("neorunner_pkg.dashboard.load_cfg", lambda: ServerConfig())

        r = client.post("/api/modpack/install", json={"filename": name}, headers=_auth_header())
        assert r.status_code == 200
        assert r.json["success"] is True
        assert r.json["result"]["installed"] == 1
        assert r.json["result"]["pack"] == "default"

    def test_delete_uploaded_pack(self, client):
        buf = self._make_zip(None)
        name = "default-0.1.0.zip"
        client.post("/api/modpack/upload", data={"file": (buf, name)}, headers=_auth_header(), content_type="multipart/form-data")
        r = client.post("/api/modpack/delete", json={"filename": name}, headers=_auth_header())
        assert r.status_code == 200
        assert r.json["success"] is True
        r = client.get("/api/modpacks", headers=_auth_header())
        assert r.json["packs"] == []


class TestKickEndpoint:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from neorunner_pkg import dashboard
        from neorunner_pkg.config import ServerConfig

        def fake_cfg():
            return ServerConfig(hostname="mc.w8.mom", http_port=8000, mc_port=1234)

        monkeypatch.setattr("neorunner_pkg.dashboard.load_cfg", fake_cfg)
        dashboard.app.config["TESTING"] = True
        with dashboard.app.test_client() as c:
            yield c

    def test_manual_kick_endpoint_removed(self, client):
        """Manual kick was removed - mismatched clients are auto-prompted at
        connect time via the patched loader jar instead."""
        r = client.post("/api/kick", json={"player": "Steve"}, headers=_auth_header())
        assert r.status_code == 404

    def test_broadcast_mods_includes_link(self, client, monkeypatch):
        sent = []
        monkeypatch.setattr("neorunner_pkg.server.send_command", lambda cmd: sent.append(cmd) or True)
        r = client.post("/api/broadcast-mods", headers=_auth_header())
        assert r.status_code == 200
        assert len(sent) == 1
        assert "mc.w8.mom/download/installer.jar" in sent[0]
