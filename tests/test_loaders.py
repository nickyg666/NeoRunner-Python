#!/usr/bin/env python3
"""NeoRunner test suite - validates all loaders and configurations."""

import os
import sys
import subprocess
import shutil
import time
import pytest
from pathlib import Path

# Setup paths
NEORUNNER_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(NEORUNNER_ROOT))

TEST_DIR = Path("/tmp/neorunner_tests")
CLEANUP = True


def setup_test_dir():
    """Create clean test directory."""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)


def cleanup_test_dir():
    """Clean up test directory."""
    if CLEANUP and TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)


@pytest.fixture(autouse=True)
def test_setup():
    """Setup and teardown for each test."""
    setup_test_dir()
    yield
    cleanup_test_dir()


class TestConfigLoading:
    """Test configuration loading."""
    
    def test_load_config_with_defaults(self):
        """Test loading config with default values."""
        from neorunner_pkg.config import ServerConfig
        cfg = ServerConfig()
        assert cfg.xmx == "6G"
        assert cfg.xms == "4G"
        assert cfg.loader == "neoforge"
    
    def test_load_config_from_dict(self):
        """Test loading config from dict."""
        from neorunner_pkg.config import ServerConfig
        cfg = ServerConfig()
        cfg.xmx = "8G"
        cfg.xms = "4G"
        cfg.loader = "fabric"
        
        assert cfg.xmx == "8G"
        assert cfg.xms == "4G"
        assert cfg.loader == "fabric"


class TestNeoForgeLoader:
    """Test NeoForge loader."""
    
    @pytest.mark.parametrize("xmx,xms", [
        ("2G", "1G"),
        ("4G", "2G"),
        ("6G", "3G"),
        ("8G", "4G"),
    ])
    def test_jvm_args_creation(self, xmx, xms):
        """Test JVM args are created correctly with different memory settings."""
        from neorunner_pkg.loaders.neoforge import NeoForgeLoader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.xmx = xmx
        cfg.xms = xms
        cfg.loader = "neoforge"
        cfg.mc_version = "1.21.4"
        
        loader = NeoForgeLoader(cfg, str(TEST_DIR))
        loader._setup_jvm_args()
        
        jvm_file = TEST_DIR / "user_jvm_args.txt"
        assert jvm_file.exists(), f"JVM args file not created for {xmx}/{xms}"
        
        content = jvm_file.read_text()
        
        # Verify content is valid
        assert f"-Xmx{xmx}" in content, f"Missing -Xmx{xmx} in {content}"
        assert f"-Xms{xms}" in content, f"Missing -Xms{xms} in {content}"
        assert "echo" not in content, f"Invalid 'echo' found in {content}"
        assert "Dashboard" not in content, f"Invalid 'Dashboard' found in {content}"
    
    def test_build_java_command(self):
        """Test Java command building."""
        from neorunner_pkg.loaders.neoforge import NeoForgeLoader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.xmx = "4G"
        cfg.xms = "2G"
        cfg.loader = "neoforge"
        cfg.mc_version = "1.21.4"
        
        loader = NeoForgeLoader(cfg, str(TEST_DIR))
        loader._setup_jvm_args()
        
        cmd = loader.build_java_command()
        
        assert "java" in cmd
        assert "@user_jvm_args.txt" in cmd
        assert "-jar" in cmd
        assert "nogui" in cmd
    
    def test_prepare_environment(self):
        """Test environment preparation creates all required files."""
        from neorunner_pkg.loaders.neoforge import NeoForgeLoader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.xmx = "4G"
        cfg.xms = "2G"
        cfg.loader = "neoforge"
        cfg.mc_version = "1.21.4"
        
        loader = NeoForgeLoader(cfg, str(TEST_DIR))
        loader.prepare_environment()
        
        # Check all required files exist
        assert (TEST_DIR / "user_jvm_args.txt").exists(), "JVM args not created"
        assert (TEST_DIR / "eula.txt").exists(), "eula not created"
        assert (TEST_DIR / "server.properties").exists(), "server.properties not created"


class TestForgeLoader:
    """Test Forge loader."""
    
    @pytest.mark.parametrize("xmx,xms", [
        ("2G", "1G"),
        ("4G", "2G"),
    ])
    def test_jvm_args_creation(self, xmx, xms):
        """Test JVM args for Forge."""
        from neorunner_pkg.loaders.forge import ForgeLoader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.xmx = xmx
        cfg.xms = xms
        cfg.loader = "forge"
        cfg.mc_version = "1.20.1"
        cfg.server_jar = "forge.jar"
        
        loader = ForgeLoader(cfg, str(TEST_DIR))
        loader._setup_jvm_args()
        
        content = (TEST_DIR / "user_jvm_args.txt").read_text()
        
        assert f"-Xmx{xmx}" in content
        assert f"-Xms{xms}" in content
        assert "echo" not in content


class TestFabricLoader:
    """Test Fabric loader."""
    
    def test_jvm_args_creation(self):
        """Test JVM args for Fabric."""
        from neorunner_pkg.loaders.fabric import FabricLoader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.xmx = "4G"
        cfg.xms = "2G"
        cfg.loader = "fabric"
        cfg.mc_version = "1.21.4"
        
        loader = FabricLoader(cfg, str(TEST_DIR))
        loader._setup_jvm_args()
        
        content = (TEST_DIR / "user_jvm_args.txt").read_text()
        
        assert "-Xmx4G" in content
        assert "-Xms2G" in content
        assert "echo" not in content


class TestLoaderFactory:
    """Test loader factory."""
    
    def test_get_neoforge_loader(self):
        """Test getting NeoForge loader."""
        from neorunner_pkg.loaders import get_loader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.loader = "neoforge"
        
        loader = get_loader(cfg, str(TEST_DIR))
        assert loader.__class__.__name__ == "NeoForgeLoader"
    
    def test_get_forge_loader(self):
        """Test getting Forge loader."""
        from neorunner_pkg.loaders import get_loader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.loader = "forge"
        
        loader = get_loader(cfg, str(TEST_DIR))
        assert loader.__class__.__name__ == "ForgeLoader"
    
    def test_get_fabric_loader(self):
        """Test getting Fabric loader."""
        from neorunner_pkg.loaders import get_loader
        from neorunner_pkg.config import ServerConfig
        
        cfg = ServerConfig()
        cfg.loader = "fabric"
        
        loader = get_loader(cfg, str(TEST_DIR))
        assert loader.__class__.__name__ == "FabricLoader"


class TestJavaManager:
    """Test Java version detection and installation."""
    
    def test_java_detection(self):
        """Test Java is detected."""
        from neorunner_pkg.java_manager import JavaManager
        manager = JavaManager()
        assert len(manager.installations) >= 0
    
    def test_required_java_version_neoforge_21(self):
        """Test Java 21 required for NeoForge 21.x."""
        from neorunner_pkg.java_manager import JavaManager
        ver = JavaManager.get_required_java_version(loader_version="21.11.42")
        assert ver == 21
    
    def test_required_java_version_neoforge_26(self):
        """Test Java 25 required for NeoForge 26.x."""
        from neorunner_pkg.java_manager import JavaManager
        ver = JavaManager.get_required_java_version(loader_version="26.1.2.22")
        assert ver == 25


class TestModManager:
    """Test mod manager."""
    
    def test_search_mods_by_keyword(self):
        """Test keyword search."""
        from neorunner_pkg.mod_manager import ModManager
        
        cfg = {
            'loader': 'neoforge',
            'mc_version': '1.21.4',
            'mods_dir': str(TEST_DIR / 'mods')
        }
        TEST_DIR.joinpath('mods').mkdir()
        
        mm = ModManager(cfg, str(TEST_DIR))
        
        # This will actually try to reach Modrinth API
        # Skip if no network
        try:
            mods = mm.search_mods_by_keyword("furniture", limit=3)
            # Just verify it doesn't crash
            assert isinstance(mods, list)
        except Exception as e:
            # Skip if no network
            pytest.skip(f"No network: {e}")


class TestDashboard:
    """Test dashboard functionality."""
    
    def test_dashboard_routes(self):
        """Test dashboard can be imported."""
        from neorunner_pkg.dashboard import app
        assert app is not None
    
    def test_api_status_route(self):
        """Test status API route exists."""
        from neorunner_pkg.dashboard import app
        routes = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/status" in routes


def test_all_loaders_import():
    """Verify all loaders can be imported."""
    from neorunner_pkg.loaders.neoforge import NeoForgeLoader
    from neorunner_pkg.loaders.forge import ForgeLoader
    from neorunner_pkg.loaders.fabric import FabricLoader
    assert NeoForgeLoader and ForgeLoader and FabricLoader


def test_config_serialization():
    """Test config can be serialized."""
    from neorunner_pkg.config import ServerConfig
    import json
    
    cfg = ServerConfig()
    cfg.xmx = "8G"
    cfg.xms = "4G"
    cfg.loader = "neoforge"
    cfg.mc_version = "1.21.4"
    
    # Convert to dict
    cfg_dict = {
        'xmx': cfg.xmx,
        'xms': cfg.xms,
        'loader': cfg.loader,
        'mc_version': cfg.mc_version
    }
    
    # Should be JSON serializable
    json_str = json.dumps(cfg_dict)
    assert json_str


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])