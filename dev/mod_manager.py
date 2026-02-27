"""Mod management system with Modrinth/CurseForge integration"""
import requests
import json
import os
import subprocess
from typing import List, Dict, Optional
from pathlib import Path


class ModInfo:
    """Mod metadata with dependency tracking"""
    def __init__(self, slug: str, name: str, loader: str, mc_version: str, deps: List[str] = None, source: str = "modrinth"):
        self.slug = slug
        self.name = name
        self.loader = loader
        self.mc_version = mc_version
        self.deps = deps or []
        self.source = source
        
    def to_dict(self):
        return {
            "slug": self.slug,
            "name": self.name,
            "loader": self.loader,
            "mc_version": self.mc_version,
            "deps": self.deps,
            "source": self.source
        }


class ModManager:
    """Orchestrates mod discovery, dependency resolution, and installation"""
    
    def __init__(self, cfg, cwd=None):
        self.cfg = cfg
        self.cwd = cwd or os.environ.get("NEORUNNER_HOME", os.path.dirname(os.path.abspath(__file__)))
        self.loader = cfg.get("loader", "neoforge")
        self.mc_version = cfg.get("mc_version", "1.21.11")
        self.mods_dir = os.path.join(self.cwd, cfg.get("mods_dir", "mods"))
        self.ferium_bin = os.path.join(self.cwd, ".local/bin/ferium")
        self.cache_file = os.path.join(self.cwd, ".mod_cache.json")
        self.mod_inventory = os.path.join(self.cwd, ".mod_inventory.json")
        
        os.makedirs(self.mods_dir, exist_ok=True)
    
    def get_100_mods_modrinth(self) -> List[ModInfo]:
        """Fetch 100+ actual gameplay mods from Modrinth (no libraries/APIs)"""
        print(f"\n[MOD_MANAGER] Fetching 100 {self.loader} mods from Modrinth ({self.mc_version})...")
        
        # Categories to EXCLUDE
        EXCLUDE = {
            "library", "api", "utility", "tool", "debug", "developer",
            "admin", "optimization", "performance", "quality"
        }
        
        # Categories to INCLUDE
        INCLUDE = {
            "adventure", "decoration", "dimension", "equipment", "food",
            "magic", "mob", "ore", "plants", "technology", "transportation",
            "cosmetic", "worldgen", "biome"
        }
        
        mods = {}
        offset = 0
        
        while len(mods) < 150 and offset < 2000:
            try:
                r = requests.get(
                    "https://api.modrinth.com/v2/search",
                    params={
                        "limit": 100,
                        "offset": offset,
                        "sort": "downloads:desc"
                    },
                    timeout=10
                )
                
                if r.status_code != 200:
                    break
                
                data = r.json()
                hits = data.get("hits", [])
                
                if not hits:
                    break
                
                for mod in hits:
                    slug = mod["slug"]
                    if slug in mods:
                        continue
                    
                    # Check loader support
                    if self.loader not in mod.get("loaders", []):
                        continue
                    
                    # Check MC version
                    if self.mc_version not in mod.get("versions", []):
                        continue
                    
                    # Check categories
                    cats = set(mod.get("categories", []))
                    
                    # Skip if library/API
                    if cats & EXCLUDE:
                        continue
                    
                    # Include if gameplay category or uncategorized
                    if cats & INCLUDE or not cats:
                        mod_info = ModInfo(
                            slug=slug,
                            name=mod.get("title", ""),
                            loader=self.loader,
                            mc_version=self.mc_version,
                            source="modrinth"
                        )
                        mods[slug] = mod_info
                
                offset += 100
                
            except Exception as e:
                print(f"  Error at offset {offset}: {e}")
                break
        
        # Sort by downloads (get from last request)
        sorted_mods = sorted(mods.values(), key=lambda x: x.name)[:100]
        
        print(f"  Collected: {len(sorted_mods)} mods from Modrinth")
        return sorted_mods
    
    def get_100_mods_curseforge(self) -> List[ModInfo]:
        """Fetch 100+ NeoForge/Forge mods from CurseForge"""
        print(f"\n[MOD_MANAGER] Fetching 100 {self.loader} mods from CurseForge ({self.mc_version})...")
        
        api_key = None
        keyfile = os.path.join(self.cwd, "curseforgeAPIkey")
        if os.path.exists(keyfile):
            try:
                api_key = open(keyfile).read().strip()
            except:
                pass
        
        if not api_key:
            print("  CurseForge: No API key found, skipping")
            return []
        
        # Map loader names
        loader_map = {
            "neoforge": "NeoForge",
            "forge": "Forge",
            "fabric": "Fabric"
        }
        cf_loader = loader_map.get(self.loader)
        
        headers = {"X-API-Key": api_key}
        mods = {}
        page = 1
        
        while len(mods) < 150 and page <= 10:
            try:
                r = requests.get(
                    "https://api.curseforge.com/v1/mods/search",
                    params={
                        "gameId": 432,
                        "pageSize": 50,
                        "index": (page - 1) * 50,
                        "sortField": 2,  # popularity
                        "gameVersion": self.mc_version
                    },
                    headers=headers,
                    timeout=10
                )
                
                if r.status_code != 200:
                    break
                
                data = r.json()
                results = data.get("data", [])
                
                if not results:
                    break
                
                for mod in results:
                    mod_id = mod["id"]
                    if mod_id in mods:
                        continue
                    
                    # Check loader support
                    files = mod.get("latestFilesIndexes", [])
                    has_loader = any(f.get("modLoader") == cf_loader for f in files)
                    
                    if not has_loader:
                        continue
                    
                    mod_info = ModInfo(
                        slug=mod.get("slug", ""),
                        name=mod.get("name", ""),
                        loader=self.loader,
                        mc_version=self.mc_version,
                        source="curseforge"
                    )
                    mods[mod_id] = mod_info
                
                page += 1
                
            except Exception as e:
                print(f"  CurseForge Error page {page}: {e}")
                break
        
        sorted_mods = list(mods.values())[:100]
        print(f"  Collected: {len(sorted_mods)} mods from CurseForge")
        return sorted_mods
    
    def fetch_dependencies(self, mod_list: List[ModInfo]) -> Dict[str, List[str]]:
        """Fetch dependencies for each mod from Modrinth API"""
        print(f"\n[MOD_MANAGER] Fetching dependencies for {len(mod_list)} mods...")
        
        deps = {}
        
        for i, mod in enumerate(mod_list):
            if mod.source != "modrinth":
                continue  # CurseForge deps require different API
            
            try:
                r = requests.get(
                    f"https://api.modrinth.com/v2/project/{mod.slug}",
                    timeout=10
                )
                
                if r.status_code == 200:
                    details = r.json()
                    mod_deps = []
                    
                    for dep_rel in details.get("dependencies", []):
                        if dep_rel.get("dependency_type") == "required":
                            dep_proj_id = dep_rel.get("project_id")
                            if dep_proj_id:
                                mod_deps.append(dep_proj_id)
                    
                    deps[mod.slug] = mod_deps
                    mod.deps = mod_deps
                
                if (i + 1) % 25 == 0:
                    print(f"  Processed: {i + 1}/{len(mod_list)}")
                    
            except Exception as e:
                print(f"  Error fetching deps for {mod.slug}: {e}")
        
        print(f"  Dependencies fetched: {sum(len(d) for d in deps.values())} total")
        return deps
    
    def install_mods(self, mod_slugs: List[str], resolve_deps: bool = True) -> Dict[str, any]:
        """Install mods via ferium with dependency resolution"""
        print(f"\n[MOD_MANAGER] Installing {len(mod_slugs)} mods ({self.loader}, {self.mc_version})...")
        
        # Create ferium profile
        profile_name = f"{self.loader}-{self.mc_version}"
        
        # Remove and recreate profile
        subprocess.run(
            [self.ferium_bin, "profile", "delete", profile_name, "--yes"],
            capture_output=True
        )
        
        # Create profile
        result = subprocess.run(
            [
                self.ferium_bin, "profile", "create",
                "--name", profile_name,
                "--game-version", self.mc_version,
                "--mod-loader", self._ferium_loader_name(),
                "--output-dir", self.mods_dir
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"  Error creating profile: {result.stderr}")
            return {"status": "error", "message": result.stderr}
        
        # Switch to profile
        subprocess.run(
            [self.ferium_bin, "profile", "switch", profile_name],
            capture_output=True
        )
        
        # Add mods
        added = 0
        failed = []
        
        for i, slug in enumerate(mod_slugs):
            result = subprocess.run(
                [self.ferium_bin, "add", slug],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                added += 1
            else:
                failed.append((slug, result.stderr[:100]))
            
            if (i + 1) % 20 == 0:
                print(f"  Added: {added}/{i+1}")
        
        # Download
        print(f"\n[MOD_MANAGER] Downloading {added} mods...")
        result = subprocess.run(
            [self.ferium_bin, "download"],
            capture_output=True,
            text=True,
            timeout=600
        )
        
        # Count downloads
        downloaded = len([f for f in os.listdir(self.mods_dir) if f.endswith('.jar')])
        
        return {
            "status": "success" if result.returncode == 0 else "partial",
            "added": added,
            "downloaded": downloaded,
            "failed": failed
        }
    
    def _ferium_loader_name(self) -> str:
        """Convert loader name to ferium format"""
        return {
            "neoforge": "neo-forge",
            "forge": "forge",
            "fabric": "fabric"
        }.get(self.loader, self.loader) or self.loader
    
    def check_mod_exists(self, mod_slug: str) -> bool:
        """Check if exact version of mod already exists"""
        for f in os.listdir(self.mods_dir):
            if mod_slug in f.lower() and self.mc_version in f and self.loader in f.lower():
                return True
        return False
    
    def save_inventory(self, mods: List[ModInfo]):
        """Save mod metadata for tracking"""
        inventory = {
            "loader": self.loader,
            "mc_version": self.mc_version,
            "mods": [m.to_dict() for m in mods]
        }
        with open(self.mod_inventory, 'w') as f:
            json.dump(inventory, f, indent=2)
