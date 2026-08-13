"""Tests for mod curation: client-only detection, quarantine workflow."""

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from neorunner_pkg.client_only_detector import (
    analyze_mod,
    fix_server_mods,
    patch_mixin_config,
    process_mod,
    strip_client_classes,
)
from neorunner_pkg.self_heal import quarantine_mod


def _make_jar(path: Path, mod_id: str = "examplemod", include_client_class: bool = False):
    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr("META-INF/mods.toml", f'modId="{mod_id}"\n')
        zf.writestr("examplemod/ExampleClass.class", b"\xca\xfe\xba\xbe")
        if include_client_class:
            zf.writestr("net/minecraft/client/renderer/RenderClass.class", b"\xca\xfe\xba\xbe")


class TestCuration:
    def test_curation_process(self):
        """Full curation workflow: analyze -> classify action."""
        tmp = Path(tempfile.mkdtemp())
        safe_jar = tmp / "safe.jar"
        _make_jar(safe_jar, mod_id="safemod")

        analysis = analyze_mod(safe_jar)
        assert analysis.action in ("keep", "move", "strip", "patch")
        assert analysis.mod_id == "safemod"
        assert not analysis.has_client_classes

    def test_client_only_detection(self):
        """Client class files in a mod JAR are detected."""
        tmp = Path(tempfile.mkdtemp())
        client_jar = tmp / "clientmod.jar"
        _make_jar(client_jar, mod_id="clientmod", include_client_class=True)

        analysis = analyze_mod(client_jar)
        assert analysis.has_client_classes is True
        assert analysis.action in ("strip", "patch", "move")
        assert any("net.minecraft.client" in f or "RenderClass" in f for f in analysis.client_files)

    def test_known_client_only_detection(self):
        """Known client-only mods get action=move."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "sodium.jar"
        _make_jar(jar, mod_id="sodium")

        analysis = analyze_mod(jar)
        assert analysis.action == "move"
        assert "client-only" in analysis.description.lower()

    def test_quarantine_workflow(self):
        """Quarantine moves mod to quarantine dir with reason."""
        tmp = Path(tempfile.mkdtemp())
        mods_dir = tmp / "mods"
        mods_dir.mkdir()
        jar = mods_dir / "badmod-1.0.jar"
        _make_jar(jar, mod_id="badmod")

        dest = quarantine_mod(mods_dir, "badmod", "crashes server")
        assert dest is not None
        assert dest.parent.name == "quarantine"
        assert not jar.exists()
        assert (mods_dir / "quarantine" / "badmod-1.0.jar").exists()

    def test_strip_client_classes(self):
        """Strip client classes from a mod jar."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "mixed.jar"
        _make_jar(jar, mod_id="mixedmod", include_client_class=True)

        ok = strip_client_classes(jar, backup=False)
        assert ok is True
        with zipfile.ZipFile(str(jar)) as zf:
            names = zf.namelist()
        assert not any("net/minecraft/client" in n for n in names)

    def test_strip_creates_backup(self):
        """Strip creates .backup.jar by default."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "mixed.jar"
        _make_jar(jar, mod_id="mixedmod", include_client_class=True)

        ok = strip_client_classes(jar)
        assert ok is True
        assert (tmp / "mixed.backup.jar").exists()

    def test_strip_tolerates_bad_zip(self):
        """Corrupt jar doesn't raise, returns False."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "broken.jar"
        jar.write_bytes(b"not a zip file")
        assert strip_client_classes(jar, backup=False) is False

    def test_patch_mixin_config_removes_client_targets(self):
        """Mixin JSON with client targets gets patched."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "mixinmod.jar"
        with zipfile.ZipFile(str(jar), "w") as zf:
            zf.writestr("META-INF/mods.toml", 'modId="mixinmod"\n')
            zf.writestr("mixinmod.mixins.json", json.dumps({
                "package": "mixinmod.mixins",
                "mixins": [
                    {"target": "net.minecraft.client.gui.Screen", "name": "GuiMixin"},
                    {"target": "net.minecraft.server.MinecraftServer", "name": "ServerMixin"},
                ],
                "plugin": "mixinmod.plugin",
            }))

        analysis = analyze_mod(jar)
        assert analysis.has_client_mixins is True

        ok = patch_mixin_config(jar)
        assert ok is True
        with zipfile.ZipFile(str(jar)) as zf:
            data = json.loads(zf.read("mixinmod.mixins.json").decode())
        targets = [m["target"] for m in data["mixins"] if isinstance(m, dict)]
        assert all("client" not in t for t in targets)
        assert any("MinecraftServer" in t for t in targets)

    def test_patch_mixin_config_no_changes(self):
        """Jar without client mixin targets is untouched (still returns True)."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "cleancm.jar"
        _make_jar(jar, mod_id="cleancm")
        assert patch_mixin_config(jar) is True

    def test_process_mod_move(self):
        """process_mod moves file to clientonly dir."""
        tmp = Path(tempfile.mkdtemp())
        mods_dir = tmp / "mods"
        clientonly_dir = tmp / "clientonly"
        mods_dir.mkdir()
        jar = mods_dir / "sodium.jar"
        _make_jar(jar, mod_id="sodium")

        analysis = analyze_mod(jar)
        assert analysis.action == "move"
        assert process_mod(analysis, mods_dir, clientonly_dir) is True
        assert (clientonly_dir / "sodium.jar").exists()
        assert not jar.exists()

    def test_fix_server_mods_full_scan(self):
        """fix_server_mods scans dir and classifies all mods."""
        tmp = Path(tempfile.mkdtemp())
        mods_dir = tmp / "mods"
        mods_dir.mkdir()
        clientonly_dir = tmp / "clientonly"

        _make_jar(mods_dir / "safe.jar", mod_id="safemod")
        _make_jar(mods_dir / "sodium.jar", mod_id="sodium")
        _make_jar(mods_dir / "mixed.jar", mod_id="mixedmod", include_client_class=True)
        _make_jar(mods_dir / "patchmod.jar", mod_id="patchmod")

        results = fix_server_mods(mods_dir, clientonly_dir, verbose=False)

        assert results["scanned"] == 4
        assert "sodium.jar" in results["moved"]
        assert "mixed.jar" in results["stripped"]
        assert results["failed"] == []

    def test_patch_mixin_removes_refmap_targets(self):
        """Mixin entries with client refmaps are removed."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "refmapmod.jar"
        with zipfile.ZipFile(str(jar), "w") as zf:
            zf.writestr("META-INF/mods.toml", 'modId="refmapmod"\n')
            zf.writestr("refmapmod.mixins.json", json.dumps({
                "package": "refmapmod.mixins",
                "mixins": [
                    {"refmap": "net/minecraft/client/gui/Screen", "name": "ClientMixin"},
                    {"target": "net.minecraft.server.MinecraftServer", "name": "ServerMixin"},
                ],
            }))

        assert patch_mixin_config(jar) is True
        with zipfile.ZipFile(str(jar)) as zf:
            data = json.loads(zf.read("refmapmod.mixins.json").decode())
        names = [m["name"] for m in data["mixins"] if isinstance(m, dict)]
        assert names == ["ServerMixin"]

    def test_patch_mixin_removes_client_plugin(self):
        """Client plugin entry removed from mixin config."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "pluginmod.jar"
        with zipfile.ZipFile(str(jar), "w") as zf:
            zf.writestr("META-INF/mods.toml", 'modId="pluginmod"\n')
            zf.writestr("pluginmod.mixins.json", json.dumps({
                "package": "pluginmod.mixins",
                "plugin": "net.minecraft.client.plugin.ClientPlugin",
                "mixins": [],
            }))

        assert patch_mixin_config(jar) is True
        with zipfile.ZipFile(str(jar)) as zf:
            data = json.loads(zf.read("pluginmod.mixins.json").decode())
        assert "plugin" not in data

    def test_patch_mixin_corrupt_json_ignored(self):
        """Invalid JSON in mixin file is skipped without failure."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "corruptmix.jar"
        with zipfile.ZipFile(str(jar), "w") as zf:
            zf.writestr("META-INF/mods.toml", 'modId="corruptmix"\n')
            zf.writestr("corruptmix.mixins.json", "{not valid json")

        assert patch_mixin_config(jar) is True
        with zipfile.ZipFile(str(jar)) as zf:
            assert zf.read("corruptmix.mixins.json").decode() == "{not valid json"

    def test_analyze_mod_corrupt_jar(self):
        """Corrupt jar analyzed without raising."""
        tmp = Path(tempfile.mkdtemp())
        jar = tmp / "broken.jar"
        jar.write_bytes(b"not a zip")
        analysis = analyze_mod(jar)
        assert "Error" in analysis.description

    def test_process_mod_keep_returns_true(self):
        """Keep action is a no-op returning True."""
        tmp = Path(tempfile.mkdtemp())
        mods_dir = tmp / "mods"
        mods_dir.mkdir()
        _make_jar(mods_dir / "safe.jar", mod_id="safemod")
        analysis = analyze_mod(mods_dir / "safe.jar")
        assert analysis.action == "keep"
        assert process_mod(analysis, mods_dir, tmp / "clientonly") is True
        assert (mods_dir / "safe.jar").exists()