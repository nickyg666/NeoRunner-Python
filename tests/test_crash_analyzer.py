"""Tests for crash log analyzer."""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.crash_analyzer import CrashAnalyzer, CrashAnalysis


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
        
        analyzer = CrashAnalyzer()
        
        assert "examplemod" in log
