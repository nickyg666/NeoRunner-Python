"""Tests for the ferium binary installer (download from GitHub releases)."""

import sys
from pathlib import Path

import pytest

from neorunner_pkg import ferium

sys.path.insert(0, str(Path(__file__).parent.parent))


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size=-1):
        if size < 0 or size >= len(self._payload):
            data, self._payload = self._payload, b""
        else:
            data, self._payload = self._payload[:size], self._payload[size:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestEnsureFerium:
    def test_reuses_existing_binary(self, tmp_path):
        from neorunner_pkg import ferium
        bin_path = tmp_path / ".local" / "bin" / "ferium"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_bytes(b"ELF-fake")

        assert ferium.ensure_ferium(cwd=tmp_path) == bin_path

    def test_downloads_and_installs(self, tmp_path, monkeypatch):
        import io
        import json
        import urllib.request
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("ferium", b"\x7fELF" + b"x" * 64)
        zip_bytes = buf.getvalue()

        release_payload = json.dumps({
            "assets": [
                {"name": "ferium-linux.zip", "browser_download_url": "https://example.com/ferium-linux.zip"},
            ]
        }).encode()

        def fake_urlopen(req, timeout=30):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "api.github.com" in url:
                return _FakeResp(release_payload)
            return _FakeResp(zip_bytes)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        result = ferium.ensure_ferium(cwd=tmp_path)
        assert result is not None
        assert result.exists()
        assert result.read_bytes().startswith(b"\x7fELF")

    def test_returns_none_on_missing_asset(self, tmp_path, monkeypatch):
        import json
        import urllib.request

        release_payload = json.dumps({"assets": []}).encode()

        def fake_urlopen(req, timeout=30):
            return _FakeResp(release_payload)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert ferium.ensure_ferium(cwd=tmp_path) is None
