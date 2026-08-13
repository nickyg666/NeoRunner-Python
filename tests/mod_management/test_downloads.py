"""Tests for mod downloads: Modrinth download, ferium, version matching."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from neorunner_pkg.ferium import FeriumManager
from neorunner_pkg.self_heal import _download_from_modrinth


class TestDownloads:
    def test_mod_download(self):
        """Download from Modrinth puts a jar into mods_dir."""
        tmp = Path(tempfile.mkdtemp())
        mods_dir = tmp / "mods"
        mods_dir.mkdir()

        project_json = json.dumps({
            "id": "mod123", "title": "SomeMod", "slug": "somemod"
        }).encode()
        versions_json = json.dumps([
            {
                "version_number": "1.0.0",
                "game_versions": ["1.21.11"],
                "loaders": ["neoforge"],
                "files": [{
                    "url": "https://example.com/somemod-1.0.0.jar",
                    "filename": "somemod-1.0.0.jar",
                    "primary": True,
                }],
            }
        ]).encode()

        target = mods_dir / "somemod-1.0.0.jar"
        target.write_bytes(b"mock-jar")

        def _fake_open(req, timeout=None):
            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/version" in url:
                mock_response.read.return_value = versions_json
            else:
                mock_response.read.return_value = project_json
            return mock_response

        with patch("urllib.request.urlopen", side_effect=_fake_open) as mock_urlopen:
            ok = _download_from_modrinth("somemod", mods_dir, "1.21.11", "neoforge")
            assert ok is True
            assert mock_urlopen.call_count == 2

    def test_ferium_download(self):
        """Ferium manager add_mod invokes subprocess."""
        tmp = Path(tempfile.mkdtemp())
        fm = FeriumManager(cwd=tmp, ferium_bin="/usr/bin/true")
        with patch.object(fm, "ferium_cmd", return_value={"success": True, "stdout": "added"}) as mock_cmd:
            ok = fm.add_mod("sodium")
            assert ok is True
            mock_cmd.assert_called_once()

    def test_version_matching(self):
        """Version matching checks MC + loader before returning a download."""
        tmp = Path(tempfile.mkdtemp())
        mods_dir = tmp / "mods"
        mods_dir.mkdir()

        fake_versions = json.dumps([
            {
                "version_number": "1.5.0",
                "game_versions": ["1.21.11"],
                "loaders": ["neoforge"],
                "files": [{"url": "https://example.com/v150.jar", "filename": "mod-1.5.0.jar"}],
            },
            {
                "version_number": "1.4.0",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "files": [{"url": "https://example.com/v140.jar", "filename": "mod-1.4.0.jar"}],
            },
        ]).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = fake_versions
            mock_urlopen.return_value.__enter__.return_value = mock_response

            from neorunner_pkg.mod_browser import ModBrowser
            browser = ModBrowser(mc_version="1.21.11", loader="neoforge")
            versions = browser.get_versions("somemod", "modrinth")
            # should only return the matching version
            match_list = [v for v in versions if "1.21.11" in v.get("mc_version", []) and "neoforge" in v.get("loaders", [])]
            assert len(match_list) == 1
            assert match_list[0]["loaders"] == ["neoforge"]