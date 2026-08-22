"""Tests for mod browser."""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner.mod_browser import ModBrowser, ModResult


class TestModBrowser:
    """Test ModBrowser class."""
    
    def test_mod_browser_init_defaults(self):
        """Test ModBrowser initializes with defaults."""
        browser = ModBrowser()
        
        assert browser.mc_version == "1.21.11"
        assert browser.loader == "neoforge"
    
    def test_mod_browser_init_custom(self):
        """Test ModBrowser initializes with custom values."""
        browser = ModBrowser(mc_version="1.20.1", loader="fabric")
        
        assert browser.mc_version == "1.20.1"
        assert browser.loader == "fabric"
    
    def test_mod_result_dataclass(self):
        """Test ModResult dataclass."""
        result = ModResult(
            id="testmod",
            name="Test Mod",
            slug="test-mod",
            description="A test mod",
            downloads=1000,
            source="modrinth",
            mc_version="1.21.11",
            loader="neoforge",
            url="https://modrinth.com/mod/testmod"
        )
        
        assert result.id == "testmod"
        assert result.name == "Test Mod"
        assert result.source == "modrinth"
    
    def test_search_returns_list(self):
        """Test search returns a list."""
        browser = ModBrowser()
        
        with patch.object(browser, '_search_modrinth', return_value=[]):
            results = browser.search("test")
            
        assert isinstance(results, list)
    
    def test_search_with_limit(self):
        """Test search respects limit parameter."""
        browser = ModBrowser()
        
        with patch.object(browser, '_search_modrinth', return_value=[]) as mock_search:
            browser.search("test", limit=10)
            mock_search.assert_called_once_with("test", 10)
    
    def test_get_versions(self):
        """Test get_versions method."""
        browser = ModBrowser()
        
        with patch.object(browser, '_get_modrinth_versions', return_value=[]):
            versions = browser.get_versions("testmod", "modrinth")
            
        assert isinstance(versions, list)
    
    def test_get_mod_details(self):
        """Test get_mod_details method."""
        browser = ModBrowser()
        
        with patch.object(browser, '_get_modrinth_details', return_value=None):
            details = browser.get_mod_details("testmod", "modrinth")
            
        assert details is None or isinstance(details, dict)
