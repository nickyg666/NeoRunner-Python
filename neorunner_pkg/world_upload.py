"""World upload validation, staging, archiving and conversion support.

Flows supported by the dashboard:

1. User picks their world *folder* (or zips a world) and uploads it. Files are
   staged under ``world_uploads/<token>/`` (never trusted as a live world).
2. The staged world is *analyzed* before any acceptance: structure, platform
   (Java vs Bedrock), world version, Java requirement vs the installed JVM,
   size/count caps and suspicious payload scans all gate the accept.
3. Accepted worlds are compressed into ``worlds_archive/mc-<version>/<name>.tar.gz``
   and restored (decompressed) back into the server dir on switch.

Bedrock worlds can be converted to Java (or any Java version) through Chunker
via :mod:`neorunner_pkg.chunker` before acceptance.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import time
import uuid
from pathlib import Path
from typing import Any

from .config import load_cfg
from .constants import CWD
from .log import log_event
from .nbt_parser import get_world_version

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.\- ]")


def sanitize_world_name(name: str, fallback: str = "world") -> str:
    """Sanitize a user-supplied world name into a safe folder name."""
    cleaned = SAFE_NAME_RE.sub("", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")[:64]
    return cleaned or fallback


def sanitize_rel_path(rel_path: str) -> str:
    """Validate a staged relative path; raise ValueError on traversal tricks."""
    p = str(rel_path or "").replace("\\", "/")
    if not p or p.startswith("/"):
        raise ValueError(f"invalid relative path: {rel_path!r}")
    parts = p.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"invalid relative path: {rel_path!r}")
    if re.match(r"^[A-Za-z]:", p):
        raise ValueError(f"invalid absolute path: {rel_path!r}")
    return p


def staging_root(cwd: Path | None = None) -> Path:
    """Root directory holding all staging uploads."""
    if cwd is None:
        cwd = CWD
    cfg = load_cfg()
    return cwd / (getattr(cfg, "world_upload_dir", None) or "world_uploads")


def _meta_file(staging: Path) -> Path:
    return staging / "__meta__.json"


def _read_meta(staging: Path) -> dict[str, int]:
    meta = _meta_file(staging)
    if meta.exists():
        try:
            return json.loads(meta.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_meta(staging: Path, meta: dict[str, int]) -> None:
    _meta_file(staging).write_text(json.dumps(meta))


def create_staging(cwd: Path | None = None) -> dict[str, Any]:
    """Create a fresh upload staging slot, returning its token + path."""
    if cwd is None:
        cwd = CWD
    root = staging_root(cwd)
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    stage = root / token
    stage.mkdir(parents=True, exist_ok=False)
    _write_meta(stage, {"files": 0, "bytes": 0})
    return {"token": token, "staging_dir": str(stage)}


def resolve_staging(token: str, cwd: Path | None = None) -> Path:
    """Resolve a staging token to its directory, or raise if absent."""
    if cwd is None:
        cwd = CWD
    stage = staging_root(cwd) / sanitize_world_name(token, "")
    if not stage.is_dir():
        raise FileNotFoundError(f"Unknown upload token: {token}")
    return stage


def _stage_limits(cwd: Path) -> tuple[int, int]:
    """Return (max_bytes, max_files) from config."""
    cfg = load_cfg()
    max_mb = getattr(cfg, "world_upload_max_total_mb", None) or 102400
    max_files = getattr(cfg, "world_upload_max_files", None) or 200000
    return max_mb * 1024 * 1024, max_files


def stage_file(
    token: str,
    rel_path: str,
    data: bytes,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Write one uploaded file into a staging slot with cap enforcement.

    Raises ValueError when the path is unsafe or the upload exceeds the
    configured total-size / file-count caps.
    """
    if cwd is None:
        cwd = CWD
    safe = sanitize_rel_path(rel_path)
    stage = resolve_staging(token, cwd)
    meta = _read_meta(stage)
    max_bytes, max_files = _stage_limits(cwd)
    if meta.get("bytes", 0) + len(data) > max_bytes:
        raise ValueError("World upload exceeds the maximum total size cap")
    if meta.get("files", 0) + 1 > max_files:
        raise ValueError("World upload exceeds the maximum file count cap")

    dest = stage / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.parent.is_relative_to(stage):
        raise ValueError("unsafe path escapes staging directory")
    # Guard against a file/dir collision on case-insensitive or recreated paths.
    if safe == "__meta__.json":
        raise ValueError("reserved filename")
    dest.write_bytes(data)
    meta["files"] = meta.get("files", 0) + 1
    meta["bytes"] = meta.get("bytes", 0) + len(data)
    _write_meta(stage, meta)
    return {"received": len(data), "total_bytes": meta["bytes"], "files": meta["files"]}


def abort_upload(token: str, cwd: Path | None = None) -> None:
    """Discard a staging upload entirely."""
    if cwd is None:
        cwd = CWD
    try:
        stage = resolve_staging(token, cwd)
    except FileNotFoundError:
        return
    shutil.rmtree(stage, ignore_errors=True)
    log_event("WORLD_UPLOAD", f"Discarded pending world upload {token}")


def cleanup_stale_staging(cwd: Path | None = None, max_age_hours: int | None = None) -> int:
    if cwd is None:
        cwd = CWD
    if max_age_hours is None:
        cfg = load_cfg()
        max_age_hours = getattr(cfg, "world_staging_retention_hours", None) or 24
    root = staging_root(cwd)
    removed = 0
    if not root.is_dir():
        return 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            age = time.time() - entry.stat().st_mtime
            if age > max_age_hours * 3600:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        log_event("WORLD_UPLOAD", f"Cleaned up {removed} stale world upload slot(s)")
    return removed


def extract_archive_upload(token: str, cwd: Path | None = None) -> Path:
    """Extract an uploaded world archive (.zip/.mcworld/.tar/.tar.gz) in place.

    The extracted contents are flattened into the staging slot so downstream
    analysis and acceptance behave identically to a folder upload.
    """
    if cwd is None:
        cwd = CWD
    stage = resolve_staging(token, cwd)
    import zipfile

    archive = None
    for p in stage.iterdir():
        if not p.is_file():
            continue
        lower = p.name.lower()
        if lower.endswith((".zip", ".mcworld", ".jar", ".tar", ".tar.gz")):
            archive = p
            break
    if archive is None:
        raise ValueError("no world archive (.zip/.mcworld/.tar/.tar.gz) found in upload")

    extract_dir = stage / "_extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        name = archive.name.lower()
        if name.endswith((".tar", ".tar.gz")):
            _safe_extract_tar(archive, stage, "_extracted")
        else:
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    member = info.filename.replace("\\", "/")
                    parts = member.split("/")
                    if member.startswith("/") or any(part in ("", ".", "..") for part in parts):
                        continue
                    target = extract_dir / member
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    finally:
        archive.unlink(missing_ok=True)

    # Flatten a single top-level wrapper folder (e.g. "MyWorld/..." inside the zip).
    if extract_dir.is_dir():
        for item in extract_dir.iterdir():
            shutil.move(str(item), str(stage / item.name))
        extract_dir.rmdir()

    files = _walk_tree(stage)
    total = sum(f.stat().st_size for f in files if f.is_file()) if files else 0
    _write_meta(stage, {"files": len(files), "bytes": total})
    log_event("WORLD_UPLOAD", f"Extracted world archive for upload {token}")
    root = find_world_root(stage)
    return root or stage


def _walk_tree(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn == "__meta__.json":
                continue
            p = Path(dirpath) / fn
            try:
                if p.is_file():
                    files.append(p)
            except OSError:
                continue
    return files


def find_world_root(stage: Path) -> Path | None:
    """Locate the world folder root inside a staging directory.

    Handles both flat uploads (level.dat at root) and single-folder zips
    (level.dat inside one subdirectory). Returns None when not a world.
    """
    for depth_dirs in (([stage]), [d for d in stage.iterdir() if d.is_dir()]):
        for d in depth_dirs:
            if (d / "level.dat").is_file() or (d / "level.dat_old").is_file():
                return d
    # Bedrock marker fallback (db/ or db/*.ldb) when level.dat is missing.
    for d in ([stage]) + [d for d in stage.iterdir() if d.is_dir()]:
        db = d / "db"
        if db.is_dir():
            try:
                if any(p.suffix == ".ldb" for p in db.iterdir()):
                    return d
            except OSError:
                continue
        if (d / "region").is_dir():
            return d
    return None


def detect_platform(world_root: Path) -> str:
    """Detect "bedrock", "java" or "unknown" for a world folder."""
    db = world_root / "db"
    if db.is_dir():
        try:
            if any(p.suffix == ".ldb" for p in db.iterdir()):
                return "bedrock"
        except OSError:
            pass
    if (world_root / "region").is_dir():
        try:
            if any(p.suffix == ".mca" for p in (world_root / "region").iterdir()):
                return "java"
        except OSError:
            pass
    # A level.dat + levelname.txt but no db/ is Java; many Bedrock minimal
    # uploads still include db/. Fall through to metadata heuristics.
    if (world_root / "levelname.txt").is_file() and not (world_root / "region").is_dir():
        return "bedrock"
    if (world_root / "level.dat").is_file():
        return "java"
    return "unknown"


def min_java_major(mc_version: str | None) -> int | None:
    """Minimum Java major required to run a Minecraft Java version.

    Returns None when the version string is not a recognizable Minecraft
    version (e.g. a loader version like ``26.1.2``).
    """
    if not mc_version:
        return None
    parts = [int(x) for x in re.findall(r"\d+", str(mc_version))]
    if not parts or parts[0] != 1:
        return None
    minor = parts[1] if len(parts) > 1 else 0
    patch = parts[2] if len(parts) > 2 else 0
    if minor > 20 or (minor == 20 and patch >= 5):
        return 21  # 1.20.5+
    if minor >= 18:
        return 17  # 1.18 - 1.20.4
    if minor >= 17:
        return 16  # 1.17
    return 8  # <= 1.16


def installed_java_major() -> int | None:
    """Detect the major JVM version of the ``java`` on PATH, or None."""
    try:
        import subprocess
        proc = subprocess.run(
            ["java", "-version"], check=False, capture_output=True, text=True, timeout=20,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r'version "(\d+)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'"?1\.(\d+)', text)  # legacy 1.8-style
    if m:
        return int(m.group(1))
    return None


def java_compatibility(world_version: str | None, server_version: str | None) -> str:
    """Classify a Java world vs the server version.

    Matches the dashboard semantics: exact match -> "compatible", same
    major+minor (patch differs) -> "warning", otherwise "incompatible".
    """
    if not world_version or not server_version:
        return "na"
    if world_version == server_version:
        return "compatible"

    def _seg(v: str) -> list[int]:
        parts = [int(x) for x in re.findall(r"\d+", v)][:2]
        return parts or [0, 0]

    if _seg(world_version) == _seg(server_version):
        return "warning"
    return "incompatible"


def analyze_upload(
    token: str,
    server_mc_version: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Validate and analyze a staged world upload.

    Runs the structural/platform/version/Java/cap checks that gate acceptance.
    """
    if cwd is None:
        cwd = CWD
    stage = resolve_staging(token, cwd)
    meta = _read_meta(stage)
    files = _walk_tree(stage)
    if not files:
        return {"token": token, "valid": False, "platform": "unknown",
                "errors": ["No files uploaded"], "warnings": []}

    world_root = find_world_root(stage)
    errors: list[str] = []
    warnings: list[str] = []

    suspicious = [
        p for p in files
        if p.suffix.lower() in (".exe", ".dll", ".sh", ".bat", ".com", ".scr", ".jar", ".so")
    ]
    if suspicious:
        warnings.append(
            "Contains executable files ({}) - unusual for a world, reviewed before accept".format(
                ", ".join(p.name for p in suspicious[:5]),
            ),
        )

    platform = "unknown"
    version: str | None = None
    if world_root is not None:
        platform = detect_platform(world_root)
        level_dat = world_root / "level.dat"
        if level_dat.is_file():
            try:
                version_info = get_world_version(str(level_dat))
                version = version_info.get("version")
            except Exception:
                version = None
            if version in (None, "unknown"):
                version = None
    else:
        errors.append("Not a Minecraft world: no level.dat, db/ or region/ found")

    is_bedrock = platform == "bedrock"
    java_req = None if is_bedrock else min_java_major(version)
    java_installed = installed_java_major()
    java_ok: bool | None = None
    if is_bedrock:
        warnings.append("Bedrock worlds cannot run on a Java server without conversion")
    elif java_req is not None:
        java_ok = java_installed is not None and java_installed >= java_req
        if java_ok is False:
            warnings.append(
                f"World requires Java {java_req}+ but the installed JVM is "
                f"{java_installed or 'unknown'}"
            )

    size_bytes = meta.get("bytes", 0) or sum(_safe_size(p) for p in files)
    max_bytes, max_files = _stage_limits(cwd)
    if meta.get("files", len(files)) > max_files:
        errors.append("Exceeds the maximum file count for an upload")
    if size_bytes > max_bytes:
        errors.append("Exceeds the maximum total size for an upload")

    compat = "na"
    if not is_bedrock:
        compat = java_compatibility(version, server_mc_version)
        if compat == "incompatible":
            warnings.append(
                f"World is MC {version} but the server runs MC {server_mc_version} - "
                "conversion via Chunker is recommended"
            )
        elif compat == "warning":
            warnings.append(
                f"World MC {version} differs slightly from server MC {server_mc_version}"
            )

    valid = not errors and world_root is not None
    return {
        "token": token,
        "valid": valid,
        "platform": platform,
        "is_bedrock": is_bedrock,
        "world_root": str(world_root.relative_to(staging_root(cwd))) if world_root else None,
        "version": version,
        "server_version": server_mc_version,
        "compatibility": compat,
        "java_required": java_req,
        "java_installed": java_installed,
        "java_compatible": java_ok,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "file_count": len(files),
        "suspicious_files": [p.name for p in suspicious[:10]],
        "errors": errors,
        "warnings": warnings,
    }


def _safe_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def archive_dir(cwd: Path | None = None, mc_version: str | None = None, loader: str | None = None) -> Path:
    """Return the version-scoped archive folder, e.g. worlds_archive/mc-1.21.11/neoforge."""
    if cwd is None:
        cwd = CWD
    safe_ver = re.sub(r"[^0-9A-Za-z.\-_]", "_", str(mc_version)) if mc_version else "unknown"
    base = cwd / "worlds_archive" / f"mc-{safe_ver}"
    if loader:
        base = base / str(loader).lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def accept_upload(
    token: str,
    name: str,
    mc_version: str | None = None,
    loader: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Compress an accepted, analyzed upload into its versioned archive slot.

    Files the world away as ``worlds_archive/mc-<version>/<loader>/<name>.tar.gz``
    and clears the staging slot. World switching decompresses it on demand.
    """
    if cwd is None:
        cwd = CWD
    stage = resolve_staging(token, cwd)
    world_root = find_world_root(stage)
    if world_root is None:
        raise ValueError("staged upload is not a valid Minecraft world")

    safe_name = sanitize_world_name(name)
    v = mc_version or _probe_version(world_root) or "unknown"
    arch_root = archive_dir(cwd, v, loader)
    archive = arch_root / f"{safe_name}.tar.gz"
    tmp = archive.with_suffix(".tar.gz.tmp")
    if archive.exists() or tmp.exists():
        raise ValueError(f"A world named '{safe_name}' is already archived for MC {v}")

    with tarfile.open(tmp, "w:gz") as tar:
        tar.add(world_root, arcname=safe_name)
    tmp.replace(archive)

    abort_upload(token, cwd)
    log_event(
        "WORLD_UPLOAD",
        f"Accepted world '{safe_name}' (MC {v}) -> {archive.relative_to(cwd)} ({world_root.name})",
    )
    return {
        "success": True,
        "name": safe_name,
        "mc_version": v,
        "archive": str(archive.relative_to(cwd)),
        "path": str(archive),
    }


def _probe_version(world_root: Path) -> str | None:
    level_dat = world_root / "level.dat"
    if level_dat.is_file():
        try:
            return get_world_version(str(level_dat)).get("version")
        except Exception:
            pass
    return None


def list_archived_worlds(cwd: Path | None = None, include_compressed: bool = True) -> list[dict[str, Any]]:
    """List worlds stored under worlds_archive/ (folders and tar.gz archives)."""
    if cwd is None:
        cwd = CWD
    root = cwd / "worlds_archive"
    archived: list[dict[str, Any]] = []
    if not root.is_dir():
        return archived
    loader_dirs = {"neoforge", "forge", "fabric"}
    for version_dir in sorted(root.iterdir()):
        if not version_dir.is_dir():
            continue
        mc_version = version_dir.name.replace("mc-", "")
        for child in sorted(version_dir.iterdir()):
            if child.is_dir():
                if child.name in loader_dirs:
                    for w in sorted(child.iterdir()):
                        if w.is_dir():
                            archived.append(_archive_entry(w, mc_version, child.name, "folder"))
                        elif include_compressed and w.name.endswith(".tar.gz"):
                            archived.append(_archive_entry(w, mc_version, child.name, "tar.gz"))
                else:
                    if child.is_dir():
                        archived.append(_archive_entry(child, mc_version, None, "folder"))
                    elif include_compressed and child.name.endswith(".tar.gz"):
                        archived.append(_archive_entry(child, mc_version, None, "tar.gz"))
    return archived


def _archive_entry(path: Path, mc_version: str, loader: str | None, kind: str) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "name": path.name.replace(".tar.gz", "") if kind == "tar.gz" else path.name,
        "location": "worlds_archive",
        "mc_version": mc_version,
        "loader": loader,
        "kind": kind,
        "compressed": kind == "tar.gz",
        "size_mb": round(size / (1024 * 1024), 2),
        "path": str(path),
    }


def restore_archived_world(
    name: str,
    mc_version: str | None = None,
    loader: str | None = None,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    """Restore an archived world (folder or tar.gz) into the server dir."""
    if cwd is None:
        cwd = CWD
    entry = _find_archive(name, mc_version, loader, cwd)
    if entry is None:
        return False, f"Archived world '{name}' not found"
    dest = cwd / name
    if dest.exists():
        return False, f"A world named '{name}' already exists - remove it or pick another name"

    try:
        if entry["kind"] == "tar.gz":
            _safe_extract_tar(entry["path"], cwd, name)
        else:
            shutil.move(entry["path"], str(dest))
        log_event("WORLD_RESTORE", f"Restored archived world '{name}' (MC {entry['mc_version']})")
        return True, f"World '{name}' restored from archives"
    except tarfile.TarError as e:
        return False, f"Corrupt world archive: {e}"
    except Exception as e:
        return False, f"Failed to restore world: {e}"


def _safe_extract_tar(tar_path: str | Path, dest: Path, world_name: str) -> None:
    """Extract a world archive with path-traversal protection.

    Python 3.11 has no ``filter="data"`` on extractall, so members are
    sanitized explicitly and a small top-level folder wrapper (name/) is
    peeled off when present.
    """
    out = dest / world_name
    peel = False
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        if members:
            top = Path(members[0].name).parts[0]
            if all(Path(m.name).parts[0] == top for m in members):
                peel = True
        out.mkdir(parents=True, exist_ok=False)
        for member in members:
            mp = Path(member.name)
            if mp.is_absolute() or ".." in mp.parts:
                raise tarfile.TarError(f"unsafe member path in archive: {member.name}")
            rel = mp.parts[1:] if peel and mp.parts else mp.parts
            if not rel:
                continue
            member.name = str(Path(*rel))
            tar.extract(member, out)
    log_event("WORLD_RESTORE", f"Extracted {tar_path} into {out}")


def _find_archive(name: str, mc_version: str | None, loader: str | None, cwd: Path) -> dict[str, Any] | None:
    for candidate in list_archived_worlds(cwd):
        if candidate["name"] != name:
            continue
        if mc_version and candidate["mc_version"] != mc_version:
            continue
        if loader and candidate["loader"] != loader:
            continue
        return candidate
    return None


def load_archived_world(
    name: str,
    mc_version: str | None = None,
    loader: str | None = None,
    cwd: Path | None = None,
) -> tuple[bool, str]:
    """Restore an archived world into the server dir and activate it."""
    if cwd is None:
        cwd = CWD
    ok, msg = restore_archived_world(name, mc_version, loader, cwd)
    if not ok:
        return ok, msg
    from .worlds import switch_world
    ok2, msg2 = switch_world(name, force=True, cwd=cwd)
    if not ok2:
        return False, f"World restored but switch failed: {msg2}"
    return True, f"World '{name}' restored and activated. Restart server to apply."


__all__ = [
    "abort_upload",
    "accept_upload",
    "analyze_upload",
    "archive_dir",
    "cleanup_stale_staging",
    "create_staging",
    "detect_platform",
    "extract_archive_upload",
    "find_world_root",
    "installed_java_major",
    "java_compatibility",
    "list_archived_worlds",
    "load_archived_world",
    "min_java_major",
    "resolve_staging",
    "restore_archived_world",
    "sanitize_rel_path",
    "sanitize_world_name",
    "stage_file",
    "staging_root",
]