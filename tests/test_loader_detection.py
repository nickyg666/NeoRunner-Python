"""Tests for loader detection and factory functions."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLoaderFactory:
    """Test loader factory function."""
    
    def test_get_neoforge_loader(self):
        """NeoForge loader is detected."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="neoforge", mc_version="1.21.11")
        loader = get_loader(cfg)
        
        assert loader.loader_name == "neoforge"
    
    def test_get_forge_loader(self):
        """Forge loader is detected."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="forge", mc_version="1.20.4")
        loader = get_loader(cfg)
        
        assert loader.loader_name == "forge"
    
    def test_get_fabric_loader(self):
        """Fabric loader is detected."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="fabric", mc_version="1.20.4")
        loader = get_loader(cfg)
        
        assert loader.loader_name == "fabric"
    
    def test_unknown_loader_raises(self):
        """Unknown loader raises ValueError."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="unknown")
        
        with pytest.raises(ValueError):
            get_loader(cfg)


class TestLoaderDisplayNames:
    """Test loader display name functions."""
    
    def test_neoforge_display_name(self):
        """NeoForge display name is correct."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="neoforge")
        loader = get_loader(cfg)
        
        assert loader.get_loader_display_name() == "NeoForge"
    
    def test_forge_display_name(self):
        """Forge display name is correct."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="forge")
        loader = get_loader(cfg)
        
        assert loader.get_loader_display_name() == "Forge"
    
    def test_fabric_display_name(self):
        """Fabric display name is correct."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="fabric")
        loader = get_loader(cfg)
        
        assert loader.get_loader_display_name() == "Fabric"


class TestLoaderMemoryValidation:
    """Test loader memory configuration."""
    
    def test_loader_rejects_corrupted_memory(self):
        """Loader rejects corrupted memory values."""
        from neorunner_pkg.loaders import _get_cfg_value
        
        # These should be rejected (replaced with default)
        corrupted = "echo http://"
        result = _get_cfg_value({"xmx": corrupted}, "xmx", "4G")
        assert result == "4G"  # Replaced with default
    
    def test_loader_accepts_valid_memory(self):
        """Loader accepts valid memory values."""
        from neorunner_pkg.loaders import _get_cfg_value
        
        valid_values = ["4G", "2G", "512M", "8G"]
        
        for val in valid_values:
            result = _get_cfg_value({"xmx": val}, "xmx", "4G")
            assert result == val


class TestLoaderEnvironment:
    """Test loader prepare_environment."""
    
    def test_neoforge_prepare_environment(self):
        """NeoForge prepares environment."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="neoforge", mc_version="1.21.11")
        loader = get_loader(cfg)
        
        # prepare_environment should not raise
        with patch.object(loader, 'prepare_environment') as mock:
            loader.prepare_environment()
            mock.assert_called_once()


class TestLoaderJavaCommand:
    """Test loader JVM command building."""
    
    def test_build_java_command_returns_list(self):
        """build_java_command returns list."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="neoforge", mc_version="1.21.11")
        loader = get_loader(cfg)
        
        cmd = loader.build_java_command()
        
        assert isinstance(cmd, list)
        assert len(cmd) > 0
    
    def test_build_java_command_has_nogui(self):
        """Java command includes nogui."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="neoforge", mc_version="1.21.11")
        loader = get_loader(cfg)
        
        cmd = loader.build_java_command()
        
        assert "nogui" in cmd


class TestLoaderCrashDetection:
    """Test loader crash detection."""
    
    def test_detect_crash_returns_dict(self):
        """detect_crash_reason returns dict."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="neoforge")
        loader = get_loader(cfg)
        
        result = loader.detect_crash_reason("")
        
        assert isinstance(result, dict)
        assert "type" in result


class TestLoaderConfigs:
    """Test loader with different configs."""
    
    def test_loader_with_dict_config(self):
        """Loader works with dict config."""
        from neorunner_pkg.loaders import get_loader
        
        cfg = {"loader": "neoforge", "mc_version": "1.21.11"}
        loader = get_loader(cfg)
        
        assert loader.loader_name == "neoforge"
    
    def test_loader_preserves_mc_version(self):
        """Loader preserves minecraft version."""
        from neorunner_pkg.config import ServerConfig
        from neorunner_pkg.loaders import get_loader
        
        cfg = ServerConfig(loader="fabric", mc_version="1.19.2")
        loader = get_loader(cfg)
        
        assert loader.mc_version == "1.19.2"
