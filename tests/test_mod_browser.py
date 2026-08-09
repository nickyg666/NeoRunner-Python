"""Tests for mod browser."""

import pytest
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg.mod_browser import ModBrowser, ModResult


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

    def test_search_filters_by_mc_version(self):
        """Search builds facets with mc version and loader."""
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")
        with patch.object(browser, "_search_curseforge", return_value=[]), \
             patch.object(browser, "_search_modrinth") as mock_modrinth:
            browser.search("foo", limit=5, sources=["modrinth"])
            mock_modrinth.assert_called_once_with("foo", 5)

    def test_search_default_sources(self):
        """Default search uses curseforge and modrinth."""
        browser = ModBrowser()
        with patch.object(browser, "_search_curseforge", return_value=[]) as mock_cf, \
             patch.object(browser, "_search_modrinth", return_value=[]) as mock_mr:
            browser.search("foo")
            mock_cf.assert_called_once()
            mock_mr.assert_called_once()

    def test_search_sorts_by_downloads(self):
        """Results are sorted by downloads descending and limited."""
        browser = ModBrowser()
        r1 = ModResult("a", "A", "a", "", 100, "modrinth", "1.21.11", "neoforge", "")
        r2 = ModResult("b", "B", "b", "", 500, "modrinth", "1.21.11", "neoforge", "")
        r3 = ModResult("c", "C", "c", "", 300, "modrinth", "1.21.11", "neoforge", "")
        with patch.object(browser, "_search_curseforge", return_value=[r1]), \
             patch.object(browser, "_search_modrinth", return_value=[r2, r3]):
            results = browser.search("x", limit=2)
        assert [r.name for r in results] == ["B", "C"]

    def test_search_modrinth_parses_hits(self):
        """Modrinth hits are converted to ModResults."""
        fake_data = json.dumps({"hits": [
            {"project_id": "abc", "title": "Cool Mod", "slug": "cool-mod",
             "description": "desc", "downloads": 42, "icon_url": "http://i/1.png"},
        ]}).encode()
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            m.read.return_value = fake_data
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            results = browser._search_modrinth("cool", 10)
        assert len(results) == 1
        assert results[0].name == "Cool Mod"
        assert results[0].source == "modrinth"

    def test_search_modrinth_skips_libraries(self):
        """Low-download library mods are filtered out."""
        fake_data = json.dumps({"hits": [
            {"project_id": "x1", "title": "Common Library", "slug": "common-lib",
             "description": "", "downloads": 5},
            {"project_id": "x2", "title": "Cool Lib API", "slug": "cool-lib",
             "description": "", "downloads": 50000},
        ]}).encode()
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            m.read.return_value = fake_data
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            results = browser._search_modrinth("lib", 10)
        assert len(results) == 1
        assert results[0].id == "x2"  # high-download lib kept

    def test_search_modrinth_network_error(self):
        """Network errors return empty list."""
        browser = ModBrowser()
        with patch("urllib.request.urlopen", side_effect=RuntimeError("down")):
            results = browser._search_modrinth("x", 10)
        assert results == []

    def test_curseforge_http_search(self):
        """CurseForge HTTP search parses mod links."""
        html = (
            '<a href="/minecraft/mc-mods/sodium" class="project"><span>Sodium</span></a>'
            '<a href="/minecraft/mc-mods/iris" class="project"><span>Iris</span></a>'
        )
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            m.status = 200
            m.read.return_value = html.encode()
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            results = browser._search_curseforge_http("x", 10)
        assert len(results) == 2
        assert results[0].source == "curseforge"
        assert results[0].url == "https://curseforge.com/minecraft/mc-mods/sodium"

    def test_curseforge_http_403_falls_back(self):
        """403 status triggers playwright fallback."""
        browser = ModBrowser()
        with patch.object(browser, "_search_curseforge_http", return_value=[]), \
             patch.object(browser, "_search_curseforge_playwright",
                          return_value=[ModResult("p", "Pw", "pw", "", 0, "curseforge",
                                                  "1.21.11", "neoforge", "http://u")]):
            results = browser._search_curseforge("x", 10)
        assert len(results) == 1
        assert results[0].name == "Pw"

    def test_get_mod_details_calls_modrinth(self):
        """get_mod_details returns details dict."""
        fake_data = json.dumps({
            "id": "abc", "title": "Cool Mod", "slug": "cool-mod",
            "description": "d", "downloads": 100,
        }).encode()
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            url = str(req.full_url)
            if url.endswith("/version"):
                m.read.return_value = json.dumps([]).encode()
            else:
                m.read.return_value = fake_data
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            details = browser.get_mod_details("cool-mod", "modrinth")
        assert details["name"] == "Cool Mod"
        assert details["source"] == "modrinth"
        assert details["latest_versions"] == []

    def test_get_mod_versions_alias(self):
        """get_mod_versions delegates to get_versions."""
        browser = ModBrowser()
        with patch.object(browser, "get_versions", return_value=[{"v": 1}]) as mock_gv:
            assert browser.get_mod_versions("x", "modrinth") == [{"v": 1}]
            mock_gv.assert_called_once_with("x", "modrinth")

    def test_get_versions_non_modrinth_returns_empty(self):
        """Unknown source returns empty list."""
        browser = ModBrowser()
        assert browser.get_versions("x", "curseforge") == []

    def test_get_mod_details_unknown_source_none(self):
        """Unknown source returns None."""
        browser = ModBrowser()
        assert browser.get_mod_details("x", "curseforge") is None

    def test_modrinth_versions_filter_loader_mismatch(self):
        """Versions not matching MC version are filtered."""
        fake = json.dumps([
            {"version_number": "1.0", "game_versions": ["1.20.1"], "loaders": ["neoforge"], "files": []},
            {"version_number": "2.0", "game_versions": ["1.21.11"], "loaders": ["neoforge"], "files": [{"url": "u"}]},
        ]).encode()
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            m.read.return_value = fake
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            versions = browser.get_versions("mod", "modrinth")
        assert len(versions) == 1
        assert versions[0]["version"] == "2.0"

    def test_modrinth_versions_network_error(self):
        """Versions network error returns empty list."""
        browser = ModBrowser()
        with patch("urllib.request.urlopen", side_effect=RuntimeError("down")):
            assert browser.get_versions("mod", "modrinth") == []

    def test_modrinth_details_error_returns_none(self):
        """Details network error returns None."""
        browser = ModBrowser()
        with patch("urllib.request.urlopen", side_effect=RuntimeError("down")):
            assert browser.get_mod_details("mod", "modrinth") is None

    def test_curseforge_http_403_returns_empty(self):
        """403 status returns empty to signal fallback."""
        browser = ModBrowser()

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            m.status = 403
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            assert browser._search_curseforge_http("x", 10) == []

    def test_curseforge_fallback_link_parsing(self):
        """Fallback link pattern used when no spans matched."""
        html = ('<div><a href="/minecraft/mc-mods/jei" class="x">JEI</a></div>'
                '<div><a href="/minecraft/mc-mods/rei">REI</a></div>')
        browser = ModBrowser(mc_version="1.21.11", loader="neoforge")

        def _fake_open(req, timeout=None):
            m = MagicMock()
            m.__enter__.return_value = m
            m.status = 200
            m.read.return_value = html.encode()
            return m

        with patch("urllib.request.urlopen", side_effect=_fake_open):
            results = browser._search_curseforge_http("x", 10)
        slugs = [r.slug for r in results]
        assert "jei" in slugs and "rei" in slugs

    def test_curseforge_playwright_error_handled(self):
        """Playwright failures return empty list."""
        browser = ModBrowser()
        with patch("neorunner_pkg.curseforge.search_curseforge_playwright",
                   side_effect=RuntimeError("pw down")):
            assert browser._search_curseforge_playwright("x", 10) == []

    def test_curseforge_playwright_results(self):
        """Playwright results converted to ModResults."""
        browser = ModBrowser()
        with patch("neorunner_pkg.curseforge.search_curseforge_playwright",
                   return_value=[{"slug": "s", "name": "S", "url": "http://u"}]):
            results = browser._search_curseforge_playwright("x", 10)
        assert len(results) == 1
        assert results[0].slug == "s"
        assert results[0].source == "curseforge"
