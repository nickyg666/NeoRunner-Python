"""CurseForge modpack (.zip) installer.

Installs a CurseForge-format modpack export: parses ``manifest.json``,
resolves each (projectID, fileID) entry to a direct CDN download via the
cfwidget lookup API, downloads the jars into the server's ``mods/`` folder,
and applies ``overrides/`` (config files) into the server directory.

The module is deliberately free of Flask/web dependencies so it can be used
from the dashboard API, CLI, or tests.
"""

import json
import logging
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CFWIDGET_BASE = "https://api.cfwidget.com"
CDN_BASES = (
    "https://edge.forgecdn.net",
    "https://mediafilez.forgecdn.net",
)
USER_AGENT = "NeoRunner/2.0"

ProgressCallback = Callable[[str, int, int], None]


@dataclass
class InstallResult:
    """Result of installing one modpack zip."""

    pack_name: str = ""
    pack_version: str = ""
    mc_version: str = ""
    loader: str = ""
    total: int = 0
    installed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.total > 0


def _cf_download_path(file_id: int) -> str:
    """Build the CDN path prefix for a file id.

    CDN layout: /files/{file_id // 1000}/{file_id % 1000}/{filename}
    """
    return f"/files/{file_id // 1000}/{file_id % 1000}"


def _cf_download_url(file_id: int, filename: str) -> str:
    return f"{_cf_download_path(file_id)}/{filename}"


def _http_get_json(url: str, timeout: int = 20) -> Any:
    """Fetch a URL and parse the JSON response (stdlib only)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_file_name(project_id: int, file_id: int) -> str | None:
    """Resolve a CF file id to its filename via the cfwidget lookup API."""
    try:
        data = _http_get_json(f"{CFWIDGET_BASE}/{project_id}")
        for f in data.get("files", []):
            if f.get("id") == file_id:
                return f.get("name")
    except Exception as e:
        log.warning("cfwidget lookup failed for %s/%s: %s", project_id, file_id, e)
    return None


def download_cf_mod(
    project_id: int,
    file_id: int,
    dest_dir: Path,
    filename: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str]:
    """Download a CurseForge mod file into ``dest_dir``.

    Returns ``(ok, filename_or_error)``.
    """
    if filename is None:
        filename = resolve_file_name(project_id, file_id)
    if not filename:
        return False, f"could not resolve file id {file_id} for project {project_id}"

    # Guard against path traversal from the CF API's filename field.
    safe_name = Path(filename).name
    if on_progress:
        on_progress(f"Downloading {safe_name}...", 0, 0)

    errors = []
    for cdn_base in CDN_BASES:
        url = f"{cdn_base}{_cf_download_path(file_id)}/{urllib.parse.quote(safe_name)}"
        try:
            dest = dest_dir / safe_name
            total = 0
            written = 0
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                with open(dest, "wb") as fh:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fh.write(chunk)
                        written += len(chunk)
                        if on_progress:
                            on_progress(safe_name, written, total)
            return True, safe_name
        except Exception as e:
            errors.append(f"{url}: {e}")
            log.warning("CF download failed via %s: %s", cdn_base, e)
    return False, "; ".join(errors)


def parse_manifest(zip_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract the CurseForge manifest from a modpack zip.

    Returns ``(manifest, files)`` where files is the manifest's file list.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        raw = zf.read("manifest.json")
    manifest = json.loads(raw)
    files = manifest.get("files", [])
    files = [f for f in files if f.get("fileID")]
    return manifest, files


def extract_overrides(zip_path: Path, dest: Path) -> int:
    """Extract the ``overrides/`` folder from a modpack zip into ``dest``.

    Returns the number of files extracted. Paths are sanitized so no file
    can escape ``dest``.
    """
    extracted = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            rel = name[10:] if name.startswith("overrides/") else None
            if rel is None:
                continue
            target = (dest / rel).resolve()
            if not str(target).startswith(str(dest.resolve())):
                continue
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as fh:
                shutil.copyfileobj(src, fh)
            extracted += 1
    return extracted


def install_curseforge_pack(
    zip_path: Path,
    mods_dir: Path,
    overrides_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallResult:
    """Install a CurseForge modpack zip.

    Args:
        zip_path: Path to the modpack zip.
        mods_dir: Directory the downloaded jars are placed in.
        overrides_dir: Directory overrides/ is extracted into. If None the
            archive's overrides are skipped.
        on_progress: Optional ``(message, done, total)`` callback.

    Returns:
        An :class:`InstallResult` describing what happened.
    """
    result = InstallResult()
    try:
        manifest, files = parse_manifest(zip_path)
    except Exception as e:
        log.error("Invalid modpack zip %s: %s", zip_path, e)
        result.errors.append(f"invalid modpack archive: {e}")
        return result

    result.pack_name = manifest.get("name", zip_path.stem)
    result.pack_version = str(manifest.get("version", ""))
    mc = manifest.get("minecraft", {})
    result.mc_version = mc.get("version", "")
    loaders = mc.get("modLoaders", [])
    primary = next((loader for loader in loaders if loader.get("primary")), loaders[0] if loaders else {})
    result.loader = primary.get("id", "")

    mods_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in mods_dir.iterdir() if p.is_file()}
    result.total = len(files)
    seen_names = set()

    for i, entry in enumerate(files, start=1):
        pid, fid = entry.get("projectID"), entry.get("fileID")
        if on_progress:
            on_progress(f"[{i}/{len(files)}] project {pid}...", i - 1, len(files))

        # Reuse an already-downloaded jar by pid-fid if present.
        already = next(
            (n for n in existing if n.startswith(f"{pid}-{fid}.")),
            None,
        )
        if already:
            result.skipped += 1
            result.files.append({"projectID": pid, "fileID": fid, "file": already, "status": "skipped"})
            continue

        if on_progress:
            on_progress(f"[{i}/{len(files)}] project {pid}...", i - 1, len(files))

        # Resolve the filename up-front so duplicates are skipped without a
        # redundant download (and a later entry can't overwrite an already
        # installed file with the same name).
        fname = resolve_file_name(pid, fid)
        if fname in seen_names:
            result.skipped += 1
            result.files.append({"projectID": pid, "fileID": fid, "file": fname, "status": "duplicate"})
            continue
        if fname in existing:
            result.skipped += 1
            result.files.append({"projectID": pid, "fileID": fid, "file": fname, "status": "already-present"})
            continue

        ok, info = download_cf_mod(pid, fid, mods_dir, filename=fname, on_progress=on_progress)

        if not ok and not any(p for p in mods_dir.glob(f"{pid}-{fid}*")):
            # Retry once with a fresh filename resolution (API drift).
            ok, info = download_cf_mod(pid, fid, mods_dir, on_progress=on_progress)

        if ok:
            result.installed += 1
            seen_names.add(info)
            result.files.append({"projectID": pid, "fileID": fid, "file": info, "status": "installed"})
        else:
            result.failed += 1
            result.errors.append(f"{pid}/{fid}: {info}")
            result.files.append({"projectID": pid, "fileID": fid, "file": None, "status": "failed", "error": info})

    if overrides_dir is not None:
        try:
            n = extract_overrides(zip_path, overrides_dir)
            result.files.append({"file": f"overrides/ ({n} files)", "status": "extracted"})
            if n == 0:
                result.errors.append("modpack has no overrides/ folder")
        except Exception as e:
            result.errors.append(f"overrides extraction failed: {e}")

    result.skipped = result.total - result.installed - result.failed
    if on_progress:
        on_progress(f"Done: {result.installed} installed, {result.failed} failed", result.total, result.total)
    return result


__all__ = [
    "CDN_BASES",
    "CFWIDGET_BASE",
    "InstallResult",
    "download_cf_mod",
    "extract_overrides",
    "install_curseforge_pack",
    "parse_manifest",
    "resolve_file_name",
]
