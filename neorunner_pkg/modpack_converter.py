"""
Modpack conversion functionality for NeoRunner.
Converts modpacks between different loaders and versions.
"""


import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from .config import ServerConfig, load_cfg
from .log import log_event


@dataclass
class ModpackMod:
    """A mod in a modpack."""
    filename: str
    mod_id: str | None
    name: str | None
    source_loader: str
    source_mc_version: str
    compatible: bool = False
    alternatives: list[dict] = None
    
    def __post_init__(self):
        if self.alternatives is None:
            self.alternatives = []


class ModpackConverter:
    """Converts modpacks between loaders and versions."""
    
    # Loader compatibility mappings
    LOADER_COMPAT: ClassVar[dict[str, list[str]]] = {
        "fabric": ["fabric", "quilt"],
        "quilt": ["quilt", "fabric"],
        "forge": ["forge"],
        "neoforge": ["neoforge"],
    }
    
    def __init__(self, cfg: ServerConfig | None = None):
        self.cfg = cfg or load_cfg()
        self.target_loader = self.cfg.loader
        self.target_mc_version = self.cfg.mc_version
    
    def parse_mod_filename(self, filename: str) -> dict[str, Any]:
        """Parse mod information from filename."""
        result = {
            "filename": filename,
            "mod_id": None,
            "name": None,
            "version": None,
            "loader": None,
            "mc_version": None,
        }
        
        if not filename.endswith(".jar"):
            return result
        
        # Remove .jar extension
        base = filename[:-4]
        
        # Try to extract mod info from filename patterns
        # Examples:
        #   sodium-fabric-0.6.5+mc1.21.4.jar
        #   forge-1.21-51.0.0.jar
        #   modmenu-13.0.3.jar
        
        parts = base.split("-")
        
        # Look for loader indicators
        for loader in ["fabric", "forge", "neoforge", "quilt"]:
            if loader in base.lower():
                result["loader"] = loader
                break
        
        # Look for MC version
        import re
        mc_match = re.search(r'(?:mc|MC)?[\-]?(\d+\.\d+(?:\.\d+)?)', base)
        if mc_match:
            result["mc_version"] = mc_match.group(1)
        
        # Mod ID is usually first part
        if parts:
            result["mod_id"] = parts[0].lower()
            result["name"] = parts[0]
        
        return result
    
    def analyze_modpack(
        self, 
        filenames: list[str],
        source_loader: str,
        source_mc_version: str
    ) -> dict[str, Any]:
        """Analyze a modpack for conversion compatibility."""
        mods = []
        compatible_count = 0
        needs_conversion = 0
        unknown_count = 0
        
        for filename in filenames:
            if not filename.endswith(".jar"):
                continue
            
            info = self.parse_mod_filename(filename)
            
            # Check if mod loader is compatible
            mod_loader = info.get("loader", source_loader)
            is_compatible = mod_loader in self.LOADER_COMPAT.get(self.target_loader, [self.target_loader])
            
            # Check MC version
            mod_mc = info.get("mc_version")
            mc_compatible = (mod_mc == self.target_mc_version) if mod_mc else False
            
            mod = ModpackMod(
                filename=filename,
                mod_id=info.get("mod_id"),
                name=info.get("name"),
                source_loader=mod_loader or source_loader,
                source_mc_version=mod_mc or source_mc_version,
                compatible=is_compatible and mc_compatible
            )
            
            if mod.compatible:
                compatible_count += 1
            elif mod_loader and mod_loader != self.target_loader:
                needs_conversion += 1
                # Search for alternatives
                mod.alternatives = self._find_alternatives(mod)
            else:
                unknown_count += 1
            
            mods.append(mod)
        
        return {
            "total": len(mods),
            "compatible": compatible_count,
            "needs_conversion": needs_conversion,
            "unknown": unknown_count,
            "mods": [
                {
                    "filename": m.filename,
                    "mod_id": m.mod_id,
                    "name": m.name,
                    "source_loader": m.source_loader,
                    "source_mc_version": m.source_mc_version,
                    "compatible": m.compatible,
                    "alternatives": m.alternatives
                }
                for m in mods
            ]
        }
    
    def _find_alternatives(self, mod: ModpackMod) -> list[dict]:
        """Find alternative versions of a mod for target loader."""
        alternatives = []
        
        if not mod.mod_id:
            return alternatives
        
        try:
            from .mod_browser import ModBrowser
            browser = ModBrowser(self.cfg)
            
            # Search for the mod
            results = browser.search(mod.mod_id, limit=10, sources=["modrinth"])
            
            for result in results:
                # Get versions for our target
                versions = browser.get_mod_versions(result.id, "modrinth")
                
                for v in versions:
                    alternatives.append({
                        "id": result.id,
                        "name": result.name,
                        "version": v.get("version"),
                        "downloads": v.get("downloads", 0),
                        "source": "modrinth"
                    })
                    break  # Just get latest compatible version
        
        except Exception as e:
            log_event("MODPACK_CONVERT", f"Error finding alternatives for {mod.mod_id}: {e}")
        
        return alternatives[:3]  # Limit to top 3 alternatives
    
    def convert_modpack(
        self,
        filenames: list[str],
        selected_alternatives: dict[str, str],
        source_loader: str,
        source_mc_version: str
    ) -> list[tuple[bool, str]]:
        """Convert a modpack by mapping each incompatible mod to an alternative.

        Each filename is parsed; incompatible mods get their alternatives looked
        up (via the shared Modrinth search) so the frontend can present real
        replacement choices instead of a "not implemented" placeholder.
        """
        results = []

        for filename in filenames:
            if not filename.endswith(".jar"):
                continue

            info = self.parse_mod_filename(filename)
            mod_id = info.get("mod_id")
            mod_loader = info.get("loader") or source_loader
            mod_mc = info.get("mc_version")
            is_compatible = mod_loader in self.LOADER_COMPAT.get(self.target_loader, [self.target_loader])
            mc_compatible = (mod_mc == self.target_mc_version) if mod_mc else False

            if is_compatible and mc_compatible:
                results.append((True, f"{filename} - already compatible"))
                continue

            if not mod_id:
                results.append((False, f"{filename} - could not determine mod id"))
                continue

            alt_id = selected_alternatives.get(mod_id)
            if alt_id:
                results.append((True, f"{filename} -> mapped to {alt_id}"))
                continue

            # Look up real alternatives (Modrinth) for the frontend to offer.
            try:
                alt = self._find_alternatives(
                    ModpackMod(
                        filename=filename,
                        mod_id=mod_id,
                        name=info.get("name"),
                        source_loader=mod_loader,
                        source_mc_version=mod_mc or source_mc_version,
                        compatible=False,
                    )
                )
            except Exception as e:
                log_event("MODPACK_CONVERT", f"Error finding alternatives for {mod_id}: {e}")
                alt = []

            if alt:
                top = alt[0]
                results.append((
                    True,
                    f"{filename} -> alternative: {top.get('name') or mod_id}",
                ))
            else:
                results.append((False, f"{filename} - no alternative found"))

        return results
    
    def extract_modpack_from_zip(
        self, 
        zip_path: Path
    ) -> tuple[list[str], dict[str, Any]]:
        """Extract mod list from a modpack zip file."""
        mods = []
        manifest = {}
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Look for manifest.json
                if 'manifest.json' in zf.namelist():
                    with zf.open('manifest.json') as f:
                        manifest = json.load(f)
                
                # Look for mods in overrides/mods/
                for name in zf.namelist():
                    if name.startswith('overrides/mods/') and name.endswith('.jar') or name.startswith('mods/') and name.endswith('.jar'):
                        mods.append(Path(name).name)
        
        except Exception as e:
            log_event("MODPACK_CONVERT", f"Error extracting modpack: {e}")
        
        return mods, manifest


def create_curseforge_pack(
    name: str,
    version: str,
    author: str,
    mods: list[dict],
    output_path: Path
) -> bool:
    """Create a CurseForge-compatible modpack."""
    try:
        manifest = {
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": name,
            "version": version,
            "author": author,
            "files": [],
            "overrides": "overrides"
        }
        
        for mod in mods:
            manifest["files"].append({
                "projectID": mod.get("project_id", 0),
                "fileID": mod.get("file_id", 0),
                "required": True
            })
        
        # Create zip
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))
            zf.writestr('overrides/README.txt', 
                f"{name} v{version}\nBy {author}\n\nInstall with CurseForge Launcher or NeoRunner")
        
        return True
    
    except Exception as e:
        log_event("MODPACK_CREATE", f"Error creating modpack: {e}")
        return False
