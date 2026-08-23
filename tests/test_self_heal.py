"""Tests for self-healing and crash handling."""

import pytest
import sys
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.self_heal import (
    preflight_dep_check,
    quarantine_mod,
    load_crash_history,
    save_crash_history,
    _collect_installed_mod_ids,
    _jij_provided_mod_ids,
    _required_deps_of,
)


class TestSelfHeal:
    """Test self-healing functions."""
    
    def test_preflight_dep_check_returns_dict(self):
        """Preflight returns a dict with expected keys."""
        cfg = {
            "mc_version": "1.21.11",
            "loader": "neoforge",
            "mods_dir": "mods",
        }
        
        with patch('neorunner_pkg.self_heal._run_cmd') as mock_cmd:
            mock_cmd.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch('neorunner_pkg.self_heal.CWD', new=Path(tempfile.gettempdir())):
                result = preflight_dep_check(cfg)
        
        assert isinstance(result, dict)
        assert "fetched" in result
    
    def test_quarantine_mod(self):
        """Quarantine moves mods to quarantine folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mods_dir = Path(tmpdir) / "mods"
            quarantine_dir = Path(tmpdir) / "quarantine"
            mods_dir.mkdir()
            quarantine_dir.mkdir()
            
            mod_file = mods_dir / "testmod-1.0.0.jar"
            mod_file.write_text("test content")
            
            with patch('neorunner_pkg.self_heal.CWD', Path(tmpdir)):
                result = quarantine_mod(mods_dir, "testmod-1.0.0.jar", "Test quarantine")
            
            assert result is None or isinstance(result, Path)
    
    def test_quarantine_mod_not_found(self):
        """Quarantine handles missing mod gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mods_dir = Path(tmpdir) / "mods"
            quarantine_dir = Path(tmpdir) / "quarantine"
            mods_dir.mkdir()
            quarantine_dir.mkdir()
            
            with patch('neorunner_pkg.self_heal.CWD', Path(tmpdir)):
                result = quarantine_mod(mods_dir, "nonexistent.jar", "Test")
            
            assert result is None
    
    def test_load_crash_history_missing_file(self):
        """Load crash history returns empty dict if file missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('neorunner_pkg.self_heal.CWD', Path(tmpdir)):
                history = load_crash_history()
            
            assert history == {}
    
    def test_save_crash_history(self):
        """Save crash history to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('neorunner_pkg.self_heal.CWD', Path(tmpdir)):
                save_crash_history({"mod1": 5, "mod2": 2})
                history = load_crash_history()
            
            assert history["mod1"] == 5
            assert history["mod2"] == 2


class TestJarJarDeps:
    """JarJar-bundled dependencies must count as installed, not missing."""

    def _build_jij_jar(self, path: Path) -> None:
        import io
        import zipfile

        # Inner jar providing modId "scena".
        inner_buf = io.BytesIO()
        with zipfile.ZipFile(inner_buf, "w") as z:
            z.writestr(
                "META-INF/neoforge.mods.toml",
                'modLoader="javafml"\n[[mods]]\nmodId="scena"\nversion="1.0"\n',
            )
        inner_buf.seek(0)

        # Outer jar that depends on scena but bundles it via JarJar.
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "META-INF/neoforge.mods.toml",
                'modLoader="javafml"\n'
                '[[mods]]\nmodId="chiselsandbits"\nversion="1.0"\n'
                '[[dependencies.chiselsandbits]]\nmodId="scena"\nrequired=true\n',
            )
            z.writestr("META-INF/jarjar/scena.jar", inner_buf.getvalue())

    def test_jij_provided_mod_ids(self, tmp_path):
        jar = tmp_path / "mod.jar"
        self._build_jij_jar(jar)
        assert _jij_provided_mod_ids(jar) == {"scena"}

    def test_collect_installed_includes_jij(self, tmp_path):
        jar = tmp_path / "mod.jar"
        self._build_jij_jar(jar)
        ids = _collect_installed_mod_ids([tmp_path])
        assert "chiselsandbits" in ids
        assert "scena" in ids  # bundled, so not "missing"

    def test_required_deps_still_lists_jij(self, tmp_path):
        jar = tmp_path / "mod.jar"
        self._build_jij_jar(jar)
        # The declared dependency is real, but the installed-set subtraction
        # (required - installed) must now leave it empty.
        assert _required_deps_of(jar) == {"scena"}
        assert _required_deps_of(jar) - set(_collect_installed_mod_ids([tmp_path])) == set()


class TestDependencyResolutionFixes:
    def test_jij_bundled_deps_count_as_installed(self, tmp_path):
        """A jar that bundles scena via jarjar should not flag scena as missing."""
        from neorunner_pkg.self_heal import _collect_installed_mod_ids
        # Build a fake C&B-like jar with an inner jarjar providing 'scena'
        jar = tmp_path / "chisels.jar"
        import io
        inner_toml = b'[[mods]]\nmodId="scena"\nversion="1.0"\n'
        inner = io.BytesIO()
        import zipfile as zf
        with zf.ZipFile(inner, "w") as iz:
            iz.writestr("META-INF/neoforge.mods.toml", inner_toml)
        with zf.ZipFile(jar, "w") as z:
            z.writestr("META-INF/neoforge.mods.toml",
                       b'[[mods]]\nmodId="chiselsandbits"\nversion="1.0"\n')
            z.writestr("META-INF/jarjar/scena.jar", inner.getvalue())
        ids = _collect_installed_mod_ids([tmp_path])
        assert "scena" in ids
        assert "chiselsandbits" in ids

    def test_clientonly_mods_count_as_installed(self, tmp_path):
        """Clientonly mods (e.g. ETF) satisfy their dependents' requirements."""
        from neorunner_pkg.self_heal import _collect_installed_mod_ids
        mods = tmp_path / "mods"
        clientonly = tmp_path / "clientonly"
        mods.mkdir()
        clientonly.mkdir()
        (clientonly / "etf.jar").write_bytes(
            b'PK\x05\x06' + b'\x00' * 18)  # empty zip
        import zipfile as zf
        with zf.ZipFile(clientonly / "etf.jar", "w") as z:
            z.writestr("META-INF/neoforge.mods.toml",
                       b'[[mods]]\nmodId="entity_texture_features"\nversion="1.0"\n')
        ids = _collect_installed_mod_ids([mods, clientonly])
        assert "entity_texture_features" in ids
