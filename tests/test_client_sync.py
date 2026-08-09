"""Tests for client sync: manifest, auto-fetch, resync, PS1 script."""

import sys
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.mod_hosting import update_manifest, generate_powershell_script
from neorunner_pkg.crash_analyzer import CrashAnalyzer, CrashAnalysis
from neorunner_pkg.config import ServerConfig


class TestClientSync:
    def _setup(self):
        tmp = Path(tempfile.mkdtemp())
        mods = tmp / "mods"
        clientonly = tmp / "clientonly"
        mods.mkdir(parents=True)
        (mods / "servermod.jar").write_bytes(b"mock")
        clientonly.mkdir(parents=True)
        (clientonly / "clientmod.jar").write_bytes(b"mock")
        cfg = ServerConfig()
        cfg.mods_dir = str(mods)
        cfg.clientonly_dir = str(clientonly)
        return tmp, mods, clientonly, cfg

    def test_manifest_includes_clientonly(self):
        """clientonly folder contents appear in manifest with type=clientonly."""
        tmp, mods, clientonly, cfg = self._setup()
        ok = update_manifest(mods, cfg)
        assert ok is True
        manifest = json.loads((mods / "manifest.json").read_text())
        files = manifest["files"]
        paths = [f["path"] for f in files]
        assert "servermod.jar" in paths
        assert "clientmod.jar" in paths
        client_entry = next(f for f in files if f["path"] == "clientmod.jar")
        assert client_entry["type"] == "clientonly"
        server_entry = next(f for f in files if f["path"] == "servermod.jar")
        assert server_entry["type"] == "server"

    def test_auto_fetch_missing_dep(self):
        """Crash analyzer schedules missing deps into clientonly folder."""
        with patch("neorunner_pkg.crash_analyzer.load_cfg") as mock_cfg:
            mock_cfg.return_value = ServerConfig()
            analyzer = CrashAnalyzer()
            analysis = CrashAnalysis(
                error_type="missing_dep",
                culprit="Missing",
                message="missing dependency",
                severity="high",
                recommendations=["fetch"],
                mod_to_fetch="examplemod",
                fetch_to_folder="clientonly",
            )
            with patch("neorunner_pkg.crash_analyzer._fetch_dependency", return_value=True) as mock_fetch:
                result = analyzer.auto_fetch_missing([analysis])
                assert result["fetched"] == [{"mod": "examplemod", "folder": "clientonly"}]
                mock_fetch.assert_called_once()

    def test_resync_when_server_has_mod(self):
        """When server has a different mod version, analysis flags version mismatch."""
        with patch("neorunner_pkg.crash_analyzer.load_cfg") as mock_cfg:
            mock_cfg.return_value = ServerConfig()
            analyzer = CrashAnalyzer()
            with patch.object(analyzer, "_check_server_has_mod", return_value=(True, "1.0.0")):
                results = analyzer.analyze("client coolmod requires mod somedep")
                mismatch = [r for r in results if r.error_type == "version_mismatch"]
                assert mismatch, "Expected version mismatch result"
                assert mismatch[0].mod_to_fetch is None

    def test_ps1_fetches_latest_manifest(self):
        """Generated PS1 script must fetch from /download/manifest URL."""
        tmp, mods, clientonly, cfg = self._setup()
        script = generate_powershell_script(cfg)
        assert "/download/manifest" in script
        assert "manifest" in script.lower()
        assert "mods" in script.lower()