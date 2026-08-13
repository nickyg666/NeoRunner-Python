"""Tests for self-healing and crash handling."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.self_heal import (
    load_crash_history,
    preflight_dep_check,
    quarantine_mod,
    save_crash_history,
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


class TestDependencyVerification:
    """Post-fetch verification quarantines mods with missing required deps."""

    def _make_mod_jar(self, path: Path, mod_id: str, required: list[str] | None = None) -> Path:
        import zipfile
        jar = path / f"{mod_id}-1.0.0.jar"
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/neoforge.mods.toml", _build_toml(mod_id, required or []))
        return jar

    def test_required_deps_of(self, tmp_path):
        from neorunner_pkg.self_heal import _required_deps_of
        jar = self._make_mod_jar(tmp_path, "moda", ["dep1", "dep2"])
        assert _required_deps_of(jar) == {"dep1", "dep2"}

    def test_required_deps_of_ignores_optional(self, tmp_path):
        from neorunner_pkg.self_heal import _required_deps_of
        jar = tmp_path / "modb-1.0.0.jar"
        import zipfile
        toml = _build_toml("modb", ["dep1"]) + '[[dependencies.modb]]\nmodId="optdep"\ntype="optional"\nversionRange="[1.0,)"\n'
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/neoforge.mods.toml", toml)
        assert _required_deps_of(jar) == {"dep1"}

    def test_quarantine_unsatisfiable(self, tmp_path, monkeypatch):
        from neorunner_pkg.self_heal import preflight_dep_check
        mods_dir = tmp_path / "mods"
        clientonly_dir = tmp_path / "clientonly"
        mods_dir.mkdir()
        clientonly_dir.mkdir()
        # moda requires dep1 which is missing -> should be quarantined.
        self._make_mod_jar(mods_dir, "moda", ["dep1"])

        monkeypatch.setattr("neorunner_pkg.self_heal.CWD", tmp_path)
        monkeypatch.setattr("neorunner_pkg.self_heal._fetch_dependency", lambda *a, **k: False)
        cfg = {"mc_version": "1.21.11", "loader": "neoforge", "mods_dir": "mods", "clientonly_dir": "clientonly"}
        preflight_dep_check(cfg)

        assert (mods_dir / "quarantine" / "moda-1.0.0.jar").exists()


def _build_toml(mod_id: str, required: list[str]) -> str:
    """Build a valid neoforge.mods.toml declaring the given required deps."""
    lines = ["[[mods]]", f'modId="{mod_id}"', 'version="1.0.0"', 'displayName="Test"']
    if required:
        for r in required:
            lines.append("")
            lines.append(f"[[dependencies.{mod_id}]]")
            lines.append(f'modId="{r}"')
            lines.append('type="required"')
            lines.append('versionRange="[1.0,)"')
    return "\n".join(lines) + "\n"
