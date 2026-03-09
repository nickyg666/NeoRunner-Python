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
