"""Mod browser for searching and installing mods from various sources."""

from __future__ import annotations

import json
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from pathlib import Path


MODRINTH_LOADER_MAP = {
    "neoforge": "neoforge",
    "forge": "forge",
    "fabric": "fabric",
    "quilt": "quilt",
}


@dataclass
class ModResult:
    """Represents a mod search result."""
    id: str
    name: str
    slug: str
    description: str
    downloads: int
    source: str  # "modrinth" or "curseforge"
    mc_version: str
    loader: str
    url: str
    icon_url: Optional[str] = None


class ModBrowser:
    """Browser for searching mods on Modrinth and CurseForge."""
    
    def __init__(self, mc_version: str = "1.21.11", loader: str = "neoforge"):
        self.mc_version = mc_version
        self.loader = loader.lower()
    
    def search(self, query: str, limit: int = 50, sources: List[str] = None) -> List[ModResult]:
        """Search for mods.
        
        Args:
            query: Search query
            limit: Maximum results
            sources: List of sources to search (["modrinth", "curseforge"])
        
        Returns:
            List of ModResult objects
        """
        if sources is None:
            sources = ["modrinth", "curseforge"]
        
        results = []
        
        if "modrinth" in sources:
            results.extend(self._search_modrinth(query, limit))
        
        # Sort by downloads
        results.sort(key=lambda x: x.downloads, reverse=True)
        return results[:limit]
    
    def _search_modrinth(self, query: str, limit: int) -> List[ModResult]:
        """Search Modrinth API with proper filtering."""
        results = []
        
        loader = MODRINTH_LOADER_MAP.get(self.loader, self.loader)
        
        # Use facets for proper filtering - format as JSON array
        facets_json = json.dumps([
            [f"versions:{self.mc_version}"],
            [f"categories:{loader}"],
            ["project_type:mod"]
        ])
        
        url = (
            f"https://api.modrinth.com/v2/search"
            f"?query={urllib.parse.quote(query)}"
            f"&limit={limit}"
            f"&facets={urllib.parse.quote(facets_json)}"
        )
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                
                for hit in data.get("hits", []):
                    # Filter out libraries and API mods
                    title_lower = hit.get("title", "").lower()
                    slug_lower = hit.get("slug", "").lower()
                    
                    # Skip common library/API patterns
                    skip_patterns = ["library", "api", "core", "lib", "common", "util"]
                    if any(p in title_lower for p in skip_patterns) and hit.get("downloads", 0) < 10000:
                        continue
                    
                    results.append(ModResult(
                        id=hit.get("project_id", ""),
                        name=hit.get("title", ""),
                        slug=hit.get("slug", ""),
                        description=hit.get("description", ""),
                        downloads=hit.get("downloads", 0),
                        source="modrinth",
                        mc_version=self.mc_version,
                        loader=self.loader,
                        url=f"https://modrinth.com/mod/{hit.get('slug', '')}",
                        icon_url=hit.get("icon_url"),
                    ))
        except Exception as e:
            print(f"Modrinth search error: {e}")
        
        return results
    
    def get_versions(self, mod_id: str, source: str) -> List[Dict[str, Any]]:
        """Get available versions for a mod.
        
        Args:
            mod_id: Mod project ID or slug
            source: "modrinth" or "curseforge"
        
        Returns:
            List of version dictionaries
        """
        if source == "modrinth":
            return self._get_modrinth_versions(mod_id)
        return []
    
    def get_mod_details(self, mod_id: str, source: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a mod."""
        if source == "modrinth":
            return self._get_modrinth_details(mod_id)
        return None
    
    def get_mod_versions(self, mod_id: str, source: str) -> List[Dict[str, Any]]:
        """Get available versions for a mod."""
        return self.get_versions(mod_id, source)
    
    def _get_modrinth_details(self, mod_id: str) -> Optional[Dict[str, Any]]:
        """Get mod details from Modrinth."""
        url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(mod_id)}"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                
                return {
                    "id": data.get("id"),
                    "name": data.get("title"),
                    "slug": data.get("slug"),
                    "description": data.get("description"),
                    "downloads": data.get("downloads"),
                    "source": "modrinth",
                    "url": f"https://modrinth.com/mod/{data.get('slug')}",
                    "icon_url": data.get("icon_url"),
                    "latest_versions": self.get_versions(mod_id, "modrinth"),
                }
        except Exception as e:
            print(f"Modrinth details error: {e}")
            return None
    
    def _get_modrinth_versions(self, mod_id: str) -> List[Dict[str, Any]]:
        """Get versions from Modrinth API."""
        url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(mod_id)}/version"
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NeoRunner/2.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                versions = json.loads(response.read().decode())
                
                # Filter by version and loader
                loader = MODRINTH_LOADER_MAP.get(self.loader, self.loader)
                filtered = []
                
                for v in versions:
                    game_versions = v.get("game_versions", [])
                    loaders = [l.lower() for l in v.get("loaders", [])]
                    
                    # Check version match
                    if self.mc_version not in game_versions:
                        continue
                    
                    # Check loader match
                    if loader not in loaders and "neoforge" not in loaders:
                        continue
                    
                    filtered.append({
                        "version": v.get("version_number"),
                        "name": v.get("name"),
                        "mc_version": game_versions,
                        "loaders": loaders,
                        "files": v.get("files", []),
                    })
                
                return filtered
        except Exception as e:
            print(f"Modrinth versions error: {e}")
            return []


__all__ = ["ModBrowser", "ModResult"]
