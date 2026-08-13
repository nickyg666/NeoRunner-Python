"""Chunker CLI integration for Minecraft world conversion.

Chunker (https://chunker.app) converts worlds between Java and Bedrock
editions and across versions. The CLI is a pure-Java JAR distributed on the
HiveGamesOSS/Chunker GitHub releases page. NeoRunner downloads it on ``setup``
and wraps conversion here so a Bedrock world uploaded to the dashboard can be
converted to the running Java version (or any user-picked target).

Output formats follow the ``EDITION_X_Y_Z`` scheme, e.g. ``JAVA_1_21_11``.
"""

from __future__ import annotations

import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from .config import load_cfg
from .constants import CWD
from .log import log_event

CHUNKER_DOWNLOAD_URL = (
    "https://github.com/HiveGamesOSS/Chunker/releases/latest/download/chunker-cli.jar"
)
USER_AGENT = "NeoRunner/2.4.0 chunker"
FORMAT_RE = re.compile(r"^(JAVA|BEDROCK)_[\d_]+$")
MIN_JAVA_REQUIRED = 17  # Chunker CLI requires Java 17+


def get_chunker_jar(cfg: Any | None = None) -> Path:
    """Return the configured chunker CLI jar path.

    Uses ``cfg.chunker_jar`` when set (absolute or relative to CWD),
    otherwise the default ``CWD/tools/chunker-cli.jar``.
    """
    if cfg is None:
        cfg = load_cfg()
    jar = getattr(cfg, "chunker_jar", "") or ""
    if jar:
        path = Path(jar)
        return path if path.is_absolute() else CWD / path
    return CWD / "tools" / "chunker-cli.jar"


def _download(url: str, dest: Path) -> None:
    """Stream ``url`` to ``dest`` with a browser-like User-Agent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 512)
            if not chunk:
                break
            f.write(chunk)


def ensure_chunker(cfg: Any | None = None, force: bool = False) -> Path:
    """Ensure the chunker CLI jar is available, downloading it if needed.

    Returns the jar path. Raises ``RuntimeError`` if the jar cannot be
    obtained (download failure or jar too small to be valid).
    """
    jar = get_chunker_jar(cfg)
    if jar.exists() and jar.stat().st_size > 100_000 and not force:
        return jar

    if force and jar.exists():
        jar.unlink()

    log_event("CHUNKER", f"Downloading Chunker CLI from {CHUNKER_DOWNLOAD_URL}")
    try:
        _download(CHUNKER_DOWNLOAD_URL, jar)
    except Exception as e:
        if not jar.exists():
            raise RuntimeError(f"Failed to download chunker-cli.jar: {e}") from e
    if not jar.exists() or jar.stat().st_size < 100_000:
        raise RuntimeError("Downloaded chunker-cli.jar is invalid (too small)")
    log_event("CHUNKER", f"Chunker CLI ready at {jar}")
    return jar


def list_available_formats(chunker_jar: Path | None = None, cfg: Any | None = None) -> list[str]:
    """Return all output formats supported by the installed Chunker CLI.

    Runs ``java -jar chunker.jar -f ?`` and parses the ``EDITION_X_Y_Z``
    tokens from the output. Returns an empty list if the jar is unavailable.
    """
    jar = chunker_jar or get_chunker_jar(cfg)
    if not jar.exists():
        return []
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar), "-f", "?"],
            check=False, capture_output=True, text=True, timeout=120,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except (subprocess.SubprocessError, OSError):
        return []
    formats = sorted({tok for tok in re.findall(r"\b[A-Z]+_\d[\d_]*\b", text) if FORMAT_RE.match(tok)})
    return formats


def java_formats(chunker_jar: Path | None = None, cfg: Any | None = None) -> list[str]:
    """Return only the Java-Edition output formats Chunker supports."""
    return [f for f in list_available_formats(chunker_jar, cfg) if f.startswith("JAVA_")]


def mc_to_chunker_format(mc_version: str) -> str:
    """Map a Minecraft Java version like ``1.21.11`` to ``JAVA_1_21_11``."""
    cleaned = re.sub(r"[^0-9.]", "", str(mc_version)) or "1.21"
    return f"JAVA_{cleaned.replace('.', '_')}"


def convert_world(
    input_dir: str | Path,
    output_format: str,
    output_dir: str | Path,
    xmx: str = "4G",
    timeout: int = 7200,
    cfg: Any | None = None,
    chunker_jar: Path | None = None,
) -> dict[str, Any]:
    """Convert a world with Chunker.

    Args:
        input_dir: World folder to convert (Java or Bedrock).
        output_format: Target format, e.g. ``JAVA_1_21_11``.
        output_dir: Where the converted world is written (created if missing).
        xmx: Max JVM heap for the Chunker process.
        timeout: Max wall-clock seconds for the conversion.
        cfg: Config (for jar path).
        chunker_jar: Explicit jar path (overrides config).

    Returns:
        Dict with ``success``, ``output_dir``, ``error`` (on failure) and
        ``log`` (tail of chunker output).
    """
    jar = chunker_jar or get_chunker_jar(cfg)
    if not jar.exists():
        return {"success": False, "output_dir": str(output_dir), "error": "chunker-cli.jar not installed"}
    fmt = output_format.upper()
    if not FORMAT_RE.match(fmt):
        return {"success": False, "output_dir": str(output_dir), "error": f"invalid output format: {fmt}"}

    out = Path(output_dir)
    if out.exists():
        import shutil
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    log_event("CHUNKER", f"Converting {input_dir} -> {fmt} via Chunker")
    cmd = ["java", f"-Xmx{xmx}", "-jar", str(jar), "-i", str(input_dir), "-f", fmt, "-o", str(out)]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log_event("CHUNKER", f"Conversion timed out after {timeout}s")
        return {"success": False, "output_dir": str(out), "error": f"conversion timed out after {timeout}s"}
    except OSError as e:
        return {"success": False, "output_dir": str(out), "error": str(e)}

    log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    ok = proc.returncode == 0
    if ok:
        log_event("CHUNKER", f"Converted world to {fmt} (Chunker exit 0)")
    else:
        log_event("CHUNKER", f"Chunker conversion failed (exit {proc.returncode})")
    return {
        "success": ok,
        "output_dir": str(out),
        "error": None if ok else (log[-2000:] or f"chunker exited with code {proc.returncode}"),
        "log": log[-4000:],
    }


__all__ = [
    "CHUNKER_DOWNLOAD_URL",
    "MIN_JAVA_REQUIRED",
    "convert_world",
    "ensure_chunker",
    "get_chunker_jar",
    "java_formats",
    "list_available_formats",
    "mc_to_chunker_format",
]