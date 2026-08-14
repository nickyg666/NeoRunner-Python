"""Tests for mod deduplication (no two versions of the same mod)."""

import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.mods import (
    _extract_mod_id_version,
    _version_rank,
    dedupe_mod_versions,
)


def _toml(mod_id: str, version: str) -> str:
    return (
        "[[mods]]\n"
        f'modId="{mod_id}"\n'
        f'version="{version}"\n'
        'displayName="Test"\n'
    )


def _jar(path: Path, mod_id: str, version: str) -> Path:
    jar = path / f"{mod_id}-{version}.jar"
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("META-INF/neoforge.mods.toml", _toml(mod_id, version))
    return jar


class TestVersionRank:
    def test_stable_outranks_prerelease(self):
        assert _version_rank("0.9.1") > _version_rank("0.9.2-alpha.4")

    def test_higher_numeric_outranks_lower(self):
        assert _version_rank("0.9.2") > _version_rank("0.9.1")

    def test_stable_between_stable(self):
        assert _version_rank("1.2.0") > _version_rank("1.1.9")

    def test_prerelease_markers(self):
        for v in ("1.0.0-alpha", "1.0.0-beta.2", "1.0.0-rc1", "1.0.0b1", "1.0.0-snapshot"):
            assert _version_rank(v)[0] == 0


class TestExtract:
    def test_neoforge_toml(self, tmp_path):
        jar = _jar(tmp_path, "sodium", "0.9.1")
        assert _extract_mod_id_version(jar) == ("sodium", "0.9.1")

    def test_returns_none_for_junk(self, tmp_path):
        junk = tmp_path / "not-a-mod.jar"
        junk.write_bytes(b"not a zip")
        assert _extract_mod_id_version(junk) is None


class TestDedupe:
    def test_removes_prerelease_duplicate(self, tmp_path):
        mods = tmp_path / "mods"
        clientonly = tmp_path / "clientonly"
        mods.mkdir()
        clientonly.mkdir()
        _jar(clientonly, "sodium", "0.9.1")
        _jar(clientonly, "sodium", "0.9.2-alpha.4")

        result = dedupe_mod_versions(mods, clientonly)
        removed = [r["version"] for r in result["removed"]]
        assert "0.9.2-alpha.4" in removed
        # stable kept in clientonly
        remaining = [p.name for p in clientonly.glob("*.jar")]
        assert "sodium-0.9.1.jar" in remaining
        assert "sodium-0.9.2-alpha.4.jar" not in remaining
        # duplicate moved to quarantine
        assert (mods / "quarantine" / "sodium-0.9.2-alpha.4.jar").exists()

    def test_keeps_higher_stable(self, tmp_path):
        mods = tmp_path / "mods"
        mods.mkdir()
        _jar(mods, "somecore", "1.0.0")
        _jar(mods, "somecore", "2.0.0")
        result = dedupe_mod_versions(mods)
        assert [r["version"] for r in result["removed"]] == ["1.0.0"]
        remaining = [p.name for p in mods.glob("*.jar")]
        assert "somecore-2.0.0.jar" in remaining

    def test_leaves_distinct_mods_alone(self, tmp_path):
        mods = tmp_path / "mods"
        mods.mkdir()
        _jar(mods, "moda", "1.0.0")
        _jar(mods, "modb", "1.0.0")
        result = dedupe_mod_versions(mods)
        assert result["removed"] == []
        assert len(list(mods.glob("*.jar"))) == 2
