"""Crash log analyzer for diagnosing client-side issues."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
import zipfile

from .config import load_cfg
from .self_heal import _fetch_dependency, log_event


@dataclass
class CrashAnalysis:
    """Result of crash log analysis."""
    error_type: str  # java_version, mixin, missing_dep, crash, client_only, version_mismatch
    culprit: Optional[str]
    message: str
    severity: str  # critical, high, medium
    recommendations: List[str]
    mod_to_fetch: Optional[str] = None  # Mod ID to auto-fetch
    fetch_to_folder: Optional[str] = None  # "clientonly" or "mods"


class CrashAnalyzer:
    """Analyze crash logs to identify issues and recommend fixes."""
    
    # Error patterns
    JAVA_VERSION_PATTERNS = [
        r"Class version (\d+) required",
        r"UnsupportedClassVersionError",
        r"requires Java (\d+)",
        r"Java(\d+) is not supported",
    ]
    
    MIXIN_PATTERNS = [
        r"MixinPreProcessorException",
        r"MixinTransformerError",
        r"mixin.*incompatibility",
        r"Mixin.*failed to transform",
    ]
    
    MISSING_DEP_PATTERNS = [
        r"requires mod ([a-zA-Z0-9_]+)",
        r"mod ([a-zA-Z0-9_]+) not found",
        r"Missing dependency: ([a-zA-Z0-9_]+)",
        r"Could not find mod ([a-zA-Z0-9_]+)",
        r"-- Mod loading issue for: ([a-zA-Z0-9_]+)",
    ]
    
    MOD_CRASH_PATTERNS = [
        r"-- Mod loading issue for: ([a-zA-Z0-9_]+)",
        r"Failure message:.*?\( ([a-zA-Z0-9_]+) \)",
        r"Caused by:?\s+([a-zA-Z0-9_]+\.[a-zA-Z0-9_.]+)",
        r"mod ([a-zA-Z0-9_]+) has crashed",
        r"mod ([a-zA-Z0-9_]+) encountered an error",
        r"Exception in mod ([a-zA-Z0-9_]+)",
    ]
    
    CLIENT_ONLY_PATTERNS = [
        r"net\.minecraft\.client\.",
        r"client\.renderer\.",
        r"client\.gui\.",
        r"com\.mojang\.blaze3d\.",
    ]
    
    VERSION_MISMATCH_PATTERNS = [
        r"mod.*version.*mismatch",
        r"incompatible.*version",
        r"expected.*but found",
    ]
    
    def __init__(self, mods_dir: Optional[Path] = None):
        self.cfg = load_cfg()
        self.mods_dir = mods_dir or Path(self.cfg.mods_dir)
    
    def analyze(self, log_text: str) -> List[CrashAnalysis]:
        """Analyze crash log and return list of issues found."""
        results = []
        
        # Check for Java version issues
        java_result = self._detect_java_version_error(log_text)
        if java_result:
            results.append(java_result)
        
        # Check for mixin errors
        mixin_result = self._detect_mixin_error(log_text)
        if mixin_result:
            results.append(mixin_result)
        
        # Check for missing dependencies
        missing_results = self._detect_missing_dep(log_text)
        results.extend(missing_results)
        
        # Check for mod crashes
        crash_results = self._detect_mod_crash(log_text)
        results.extend(crash_results)
        
        # Check for client-only mods
        client_results = self._detect_client_only_mod(log_text)
        results.extend(client_results)
        
        # Check for version mismatches
        version_results = self._detect_version_mismatch(log_text)
        results.extend(version_results)
        
        return results
    
    def _detect_java_version_error(self, log_text: str) -> Optional[CrashAnalysis]:
        """Detect Java version incompatibility."""
        log_lower = log_text.lower()
        
        for pattern in self.JAVA_VERSION_PATTERNS:
            match = re.search(pattern, log_text, re.IGNORECASE)
            if match:
                # Extract required Java version
                required_java = match.group(1) if match.groups() else "unknown"
                
                # Try to find which mod requires this
                culprit = self._extract_mod_from_context(log_text, match.start())
                
                message = f"Java version incompatibility detected"
                if culprit:
                    message += f" - Mod '{culprit}' requires Java {required_java}"
                else:
                    message += f" - A mod requires Java {required_java}"
                
                return CrashAnalysis(
                    error_type="java_version",
                    culprit=culprit,
                    message=message,
                    severity="high",
                    recommendations=[
                        f"Update Java to version {required_java} or higher",
                        f"Or remove mod '{culprit}' if it cannot be updated"
                    ]
                )
        
        return None
    
    def _detect_mixin_error(self, log_text: str) -> Optional[CrashAnalysis]:
        """Detect mixin incompatibility errors."""
        for pattern in self.MIXIN_PATTERNS:
            match = re.search(pattern, log_text, re.IGNORECASE)
            if match:
                culprit = self._extract_mod_from_context(log_text, match.start())
                
                # Extract mixin class for better diagnosis
                mixin_class = None
                mixin_match = re.search(r"from\s+([a-zA-Z0-9_.]+)\.mixins?", log_text, re.IGNORECASE)
                if mixin_match:
                    mixin_class = mixin_match.group(1)
                
                message = f"Mixin incompatibility detected"
                if culprit:
                    message += f" - Mod '{culprit}' has mixin issues"
                elif mixin_class:
                    message += f" - Issue in {mixin_class}"
                
                return CrashAnalysis(
                    error_type="mixin",
                    culprit=culprit,
                    message=message,
                    severity="high",
                    recommendations=[
                        "Update the mod to a compatible version",
                        "Or update Java (mixin issues often indicate Java version mismatch)"
                    ]
                )
        
        return None
    
    def _detect_missing_dep(self, log_text: str) -> List[CrashAnalysis]:
        """Detect missing dependencies."""
        results = []
        
        for pattern in self.MISSING_DEP_PATTERNS:
            for match in re.finditer(pattern, log_text, re.IGNORECASE):
                dep_id = match.group(1).lower()
                
                # Check if server already has this mod
                server_has, server_version = self._check_server_has_mod(dep_id)
                
                if not server_has:
                    # Need to fetch this mod - put in clientonly folder
                    results.append(CrashAnalysis(
                        error_type="missing_dep",
                        culprit=dep_id,
                        message=f"Missing dependency: {dep_id} - Client has mod that requires this but server doesn't",
                        severity="critical",
                        recommendations=[
                            f"Fetching {dep_id} for client sync",
                            "Mod will be added to clientonly folder"
                        ],
                        mod_to_fetch=dep_id,
                        fetch_to_folder="clientonly"
                    ))
                elif server_version:
                    # Server has different version
                    results.append(CrashAnalysis(
                        error_type="version_mismatch",
                        culprit=dep_id,
                        message=f"Version mismatch: Client has different version of {dep_id} than server",
                        severity="high",
                        recommendations=[
                            f"Server has {dep_id} v{server_version}",
                            "Client should resync to get correct version"
                        ]
                    ))
        
        return results
    
    def _detect_mod_crash(self, log_text: str) -> List[CrashAnalysis]:
        """Detect mods that have crashed."""
        results = []
        
        for pattern in self.MOD_CRASH_PATTERNS:
            for match in re.finditer(pattern, log_text, re.IGNORECASE):
                culprit = match.group(1).lower()
                
                # Skip framework mods
                if culprit in ["minecraft", "neoforge", "forge", "fml", "java"]:
                    continue
                
                results.append(CrashAnalysis(
                    error_type="crash",
                    culprit=culprit,
                    message=f"Mod '{culprit}' has crashed",
                    severity="high",
                    recommendations=[
                        f"Check for update to {culprit}",
                        "Or remove the mod if no update available"
                    ]
                ))
        
        return results
    
    def _detect_client_only_mod(self, log_text: str) -> List[CrashAnalysis]:
        """Detect client-only mods in crash log."""
        results = []
        
        for pattern in self.CLIENT_ONLY_PATTERNS:
            for match in re.finditer(pattern, log_text, re.IGNORECASE):
                # Find the mod name from the stack trace context
                culprit = self._extract_mod_from_context(log_text, match.start())
                
                if culprit:
                    results.append(CrashAnalysis(
                        error_type="client_only",
                        culprit=culprit,
                        message=f"Mod '{culprit}' is a client-only mod (uses client-side classes)",
                        severity="medium",
                        recommendations=[
                            "This is not a server issue",
                            "Ensure client has matching version of this mod",
                            "Remove from server if present - client-only mods don't need to be on server"
                        ]
                    ))
        
        return results
    
    def _detect_version_mismatch(self, log_text: str) -> List[CrashAnalysis]:
        """Detect Minecraft version mismatches."""
        results = []
        
        for pattern in self.VERSION_MISMATCH_PATTERNS:
            for match in re.finditer(pattern, log_text, re.IGNORECASE):
                culprit = self._extract_mod_from_context(log_text, match.start())
                
                # Extract version info
                version_match = re.search(r"(\d+\.\d+\.\d+)", log_text[match.start():match.start()+200])
                found_version = version_match.group(1) if version_match else "unknown"
                
                results.append(CrashAnalysis(
                    error_type="version_mismatch",
                    culprit=culprit,
                    message=f"Version mismatch detected{f' in {culprit}' if culprit else ''}",
                    severity="high",
                    recommendations=[
                        f"Found version: {found_version}",
                        "Ensure mod version matches server Minecraft version",
                        "Client and server must have matching mod versions"
                    ]
                ))
        
        return results
    
    def _extract_mod_from_context(self, log_text: str, pos: int, context_chars: int = 500) -> Optional[str]:
        """Extract mod name from context around the error position."""
        start = max(0, pos - context_chars)
        end = min(len(log_text), pos + context_chars)
        context = log_text[start:end]
        
        # Look for mod ID patterns in JAR filenames or modIds
        # Common patterns: modname.jar, modId=, "modId": "modname"
        
        # Pattern 1: JAR filename
        jar_match = re.search(r"([a-zA-Z0-9_-]+)\.jar", context, re.IGNORECASE)
        if jar_match:
            return jar_match.group(1).lower()
        
        # Pattern 2: from mod X or mod (X)
        mod_from = re.search(r"(?:from|mod)\s+\(?([a-zA-Z0-9_-]+)\)?", context, re.IGNORECASE)
        if mod_from:
            mod_name = mod_from.group(1).lower()
            if mod_name not in ["minecraft", "neoforge", "forge", "fml", "java", "net", "com"]:
                return mod_name
        
        return None
    
    def _check_server_has_mod(self, mod_id: str) -> tuple[bool, Optional[str]]:
        """Check if server has this mod installed."""
        mod_id_lower = mod_id.lower()
        
        if not self.mods_dir.exists():
            return False, None
        
        # Check main mods folder
        for jar_path in self.mods_dir.glob("*.jar"):
            jar_name = jar_path.stem.lower()
            
            # Check if mod ID is in filename
            if mod_id_lower in jar_name:
                # Try to extract version from filename
                version_match = re.search(r"(\d+\.\d+\.\d+)", jar_name)
                version = version_match.group(1) if version_match else None
                return True, version
            
            # Check inside JAR for mod ID
            try:
                with zipfile.ZipFile(jar_path) as zf:
                    names = zf.namelist()
                    
                    # Check neoforge mods.toml
                    if 'META-INF/neoforge.mods.toml' in names:
                        try:
                            import tomllib
                        except ImportError:
                            import tomli as tomllib
                            tomllib = None
                        if tomllib:
                            try:
                                raw = zf.read('META-INF/neoforge.mods.toml').decode('utf-8', errors='ignore')
                                data = tomllib.loads(raw)
                                for mod in data.get("mods", []):
                                    if mod.get("modId", "").lower() == mod_id_lower:
                                        deps = data.get("dependencies", {})
                                        return True, None
                            except:
                                pass
                    
                    # Check fabric.mod.json
                    if 'fabric.mod.json' in names:
                        try:
                            import json
                            data = json.loads(zf.read('fabric.mod.json').decode('utf-8', errors='ignore'))
                            if data.get("id", "").lower() == mod_id_lower:
                                return True, None
                        except:
                            pass
            except:
                continue
        
        return False, None
    
    def auto_fetch_missing(self, analysis_results: List[CrashAnalysis]) -> Dict[str, Any]:
        """Auto-fetch missing mods based on analysis results."""
        fetched = []
        errors = []
        
        cfg = load_cfg()
        mc_version = cfg.mc_version
        loader = cfg.loader
        
        for result in analysis_results:
            if result.mod_to_fetch and result.fetch_to_folder:
                try:
                    # Determine target folder
                    if result.fetch_to_folder == "clientonly":
                        target_dir = self.mods_dir / "clientonly"
                    else:
                        target_dir = self.mods_dir
                    
                    target_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Fetch the mod using existing dependency fetch mechanism
                    success = _fetch_dependency(
                        dep_id=result.mod_to_fetch,
                        mc_version=mc_version,
                        loader_name=loader,
                        mods_dir=target_dir,
                        dependents=[result.culprit] if result.culprit else None
                    )
                    
                    if success:
                        fetched.append({
                            "mod": result.mod_to_fetch,
                            "folder": result.fetch_to_folder
                        })
                        log_event("CRASH_ANALYZER", f"Auto-fetched {result.mod_to_fetch} to {result.fetch_to_folder}")
                    else:
                        errors.append({
                            "mod": result.mod_to_fetch,
                            "error": "Fetch failed"
                        })
                except Exception as e:
                    errors.append({
                        "mod": result.mod_to_fetch,
                        "error": str(e)
                    })
        
        return {
            "fetched": fetched,
            "errors": errors
        }


def analyze_crash_log(log_text: str) -> List[CrashAnalysis]:
    """Convenience function to analyze crash log."""
    analyzer = CrashAnalyzer()
    return analyzer.analyze(log_text)


__all__ = ["CrashAnalyzer", "CrashAnalysis", "analyze_crash_log"]
