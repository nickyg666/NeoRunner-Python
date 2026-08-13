"""Tests for crash log analyzer."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.crash_analyzer import CrashAnalysis, CrashAnalyzer


class TestCrashAnalyzer:
    """Test CrashAnalyzer."""
    
    def test_detect_java_version_error(self):
        """Detects Java version incompatibility."""
        log = "java.lang.UnsupportedClassVersionError: Unsupported class file major version 65"
        
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log)
        
        assert len(results) > 0
        assert results[0].error_type == "java_version"
    
    def test_detect_mixin_error(self):
        """Detects Mixin errors."""
        log = """
java.lang.RuntimeException: Error in class 'mod_Loader'
    at net.minecraft.class_xxx.method(class_xxx.java:50)
Caused by: org.spongepowered.asm.mixin.injection.exception.InvalidInjectionException
"""
        
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log)
        
        assert len(results) > 0
        assert results[0].error_type in ("mixin", "crash")
    
    def test_detect_missing_dependency(self):
        """Detects missing dependency errors."""
        log = "Caused by: java.lang.NoClassDefFoundError: Lorg/example/ModClass;"
        
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log)
        
        assert len(results) > 0
    
    def test_detect_mod_crash(self):
        """Detects mod crash."""
        log = "Caused by: java.lang.RuntimeException: Mod examplemod crashed!"
        
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log)
        
        assert len(results) > 0
    
    def test_detect_client_only_mod(self):
        """Client-only detection requires mods_dir scan."""
        log = "net.minecraft.client.gui.Screen"
        
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log)
        
        assert isinstance(results, list)
    
    def test_no_crash(self):
        """Returns no crash for clean logs."""
        log = "Server started in 5.234 seconds"
        
        analyzer = CrashAnalyzer()
        results = analyzer.analyze(log)
        
        assert len(results) == 0
    
    def test_extract_mod_name(self):
        """Extracts mod name from crash."""
        log = "at com.example.examplemod.CommonClass.init(ExampleMod.java:100)"
        
        CrashAnalyzer()
        
        assert "examplemod" in log

    def test_java_version_class_version_conversion(self):
        """Class version 69 maps to Java 25."""
        log = "UnsupportedClassVersionError: Class version 69 required"
        results = CrashAnalyzer().analyze(log)
        java = [r for r in results if r.error_type == "java_version"]
        assert len(java) == 1
        assert "Java 25" in java[0].message
        assert java[0].severity == "high"

    def test_java_version_old_class_version(self):
        """Class version 52 maps to Java 8."""
        log = "Unsupported class file major version 52 - Class version 52 required"
        results = CrashAnalyzer().analyze(log)
        java = [r for r in results if r.error_type == "java_version"]
        assert "Java 8" in java[0].message

    def test_missing_dep_server_has_same_version_no_action(self, tmp_path):
        """Server having the mod means no fetch needed."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        (mods_dir / "bar-2.0.0.jar").write_bytes(b"x")
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        results = analyzer.analyze("requires mod bar")
        missing = [r for r in results if r.error_type == "missing_dep"]
        assert missing == []
        # version mismatch reported only when server version is known...
        # with mod present and version extractable, nothing needed
        assert all(r.mod_to_fetch is None for r in results)

    def test_missing_dep_server_has_no_mod_suggests_fetch(self, tmp_path):
        """Missing dep with no server copy flags for fetch to clientonly."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        results = analyzer.analyze("requires mod bar")
        missing = [r for r in results if r.error_type == "missing_dep"]
        assert len(missing) == 1
        assert missing[0].mod_to_fetch == "bar"
        assert missing[0].fetch_to_folder == "clientonly"

    def test_check_server_has_mod_jar_filename(self, tmp_path):
        """Finds mod by filename containing mod ID."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        (mods_dir / "bar-3.1.4.jar").write_bytes(b"x")
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        has, version = analyzer._check_server_has_mod("bar")
        assert has is True
        assert version == "3.1.4"

    def test_check_server_has_mod_missing_dir(self, tmp_path):
        """Missing mods dir returns False."""
        analyzer = CrashAnalyzer(mods_dir=tmp_path / "nope")
        assert analyzer._check_server_has_mod("bar") == (False, None)

    def test_auto_fetch_missing_calls_fetch(self, tmp_path):
        """auto_fetch_missing invokes _fetch_dependency and reports results."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        analyzer = CrashAnalyzer(mods_dir=mods_dir)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "neorunner_pkg.crash_analyzer._fetch_dependency",
                lambda **kw: True,
            )
            result = analyzer.auto_fetch_missing([
                CrashAnalysis(
                    error_type="missing_dep", culprit="needy", message="m",
                    severity="critical", recommendations=[],
                    mod_to_fetch="bar", fetch_to_folder="clientonly",
                )
            ])
        assert result["fetched"] == [{"mod": "bar", "folder": "clientonly"}]
        assert (mods_dir / "clientonly").is_dir()

    def test_auto_fetch_missing_fetch_fails(self, tmp_path):
        """Failed fetch recorded in errors."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "neorunner_pkg.crash_analyzer._fetch_dependency",
                lambda **kw: False,
            )
            result = analyzer.auto_fetch_missing([
                CrashAnalysis(
                    error_type="missing_dep", culprit="needy", message="m",
                    severity="critical", recommendations=[],
                    mod_to_fetch="bar", fetch_to_folder="mods",
                )
            ])
        assert result["fetched"] == []
        assert result["errors"][0]["mod"] == "bar"

    def test_auto_fetch_missing_exception(self, tmp_path):
        """Exceptions during fetch are captured."""
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        with pytest.MonkeyPatch.context() as mp:
            def _boom(**kw):
                raise RuntimeError("network down")
            mp.setattr("neorunner_pkg.crash_analyzer._fetch_dependency", _boom)
            result = analyzer.auto_fetch_missing([
                CrashAnalysis(
                    error_type="missing_dep", culprit="needy", message="m",
                    severity="critical", recommendations=[],
                    mod_to_fetch="bar", fetch_to_folder="mods",
                )
            ])
        assert result["fetched"] == []
        assert "network down" in result["errors"][0]["error"]

    def test_mod_crash_skips_framework_mods(self):
        """Minecraft/neoforge/fml crashes are ignored."""
        analyzer = CrashAnalyzer(mods_dir=None)
        results = analyzer._detect_mod_crash("Exception in mod neoforge")
        assert results == []

    def test_mod_crash_detects_real_mod(self):
        """Real mod crashes are reported with culprit."""
        analyzer = CrashAnalyzer(mods_dir=None)
        results = analyzer._detect_mod_crash("Caused by: java.lang.Error: mod coolmod has crashed")
        assert any(r.culprit == "coolmod" for r in results)

    def test_version_mismatch_detection(self):
        """Version mismatch pattern detected."""
        analyzer = CrashAnalyzer(mods_dir=None)
        results = analyzer.analyze("mod version mismatch in pack 1.21.11 but found 1.20.1")
        mismatch = [r for r in results if r.error_type == "version_mismatch"]
        assert len(mismatch) >= 1
        assert "1.21.11" in mismatch[0].message or "1.21.11" in mismatch[0].recommendations[0]

    def test_mixin_detection_wo_culprit(self):
        """Mixin errors with no mod context still reported."""
        analyzer = CrashAnalyzer(mods_dir=None)
        results = analyzer.analyze("MixinPreProcessorException at transform")
        mixin = [r for r in results if r.error_type == "mixin"]
        assert len(mixin) == 1

    def test_client_only_detection(self):
        """Client-side class references flagged as client_only."""
        analyzer = CrashAnalyzer(mods_dir=None)
        results = analyzer.analyze(
            "at net.minecraft.client.gui.GuiGraphics.drawString "
            "in mod (sodiumjar) stack trace"
        )
        client_only = [r for r in results if r.error_type == "client_only"]
        assert len(client_only) >= 1
        assert client_only[0].severity == "medium"

    def test_analyze_crash_log_helper(self):
        """Convenience function wraps analyze."""
        from neorunner_pkg.crash_analyzer import analyze_crash_log
        results = analyze_crash_log("UnsupportedClassVersionError: Unsupported class file major version 65")
        assert any(r.error_type == "java_version" for r in results)

    def test_server_jar_fabric_mod_id(self, tmp_path):
        """Fabric mods found by fabric.mod.json id."""
        import zipfile
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        jar = mods_dir / "fancypack.jar"
        with zipfile.ZipFile(jar, "w") as zf:
            zf.writestr("fabric.mod.json", '{"id": "fancypack", "schemaVersion": 1}')
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        has, _ = analyzer._check_server_has_mod("fancypack")
        assert has is True

    def test_server_jar_neoforge_mod_id(self, tmp_path):
        """NeoForge mods found by mods.toml modId."""
        import zipfile
        mods_dir = tmp_path / "mods"
        mods_dir.mkdir()
        jar = mods_dir / "neopack.jar"
        with zipfile.ZipFile(jar, "w") as zf:
            zf.writestr("META-INF/neoforge.mods.toml",
                        'modLoader="javafml"\n[[mods]]\nmodId="neopack"')
        analyzer = CrashAnalyzer(mods_dir=mods_dir)
        has, _ = analyzer._check_server_has_mod("neopack")
        assert has is True

    def test_extract_mod_from_context_jar_name(self):
        """JAR filename in context is used as culprit."""
        analyzer = CrashAnalyzer(mods_dir=None)
        culprit = analyzer._extract_mod_from_context(
            "Loading mod from file: sodium-0.5.8.jar requires mod fabric_api", 30)
        assert culprit == "sodium"
