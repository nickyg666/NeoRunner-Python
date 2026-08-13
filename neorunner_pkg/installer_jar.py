"""Build and serve the NeoRunner client installer JAR.

The JAR is a self-contained Java program (Java 8+ bytecode) that:
  1. Shows a Swing GUI asking for the .minecraft directory (console fallback)
  2. Downloads + runs the loader client installer from the server (quiet)
  3. Extracts the embedded pack.zip (mods + config + defaultconfigs)
  4. Shows the server address to join

The mods/config are embedded directly in the JAR as ``pack.zip`` so the
client gets everything in a single download. The JAR is built lazily and
cached; it is rebuilt when the Java source, embedded properties, or pack
contents change.
"""

import hashlib
import io
import logging
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .config import ServerConfig
from .constants import CWD
from .mod_hosting import _get_local_ip

logger = logging.getLogger(__name__)

_JAVA_SRC = Path(__file__).parent / "client_installer" / "NeoRunnerInstaller.java"


def _cache_dir() -> Path:
    """Cache directory, resolved from ``CWD`` at call time.

    Resolved lazily (not at import) so tests can monkeypatch ``CWD`` and still
    get an isolated cache instead of polluting the real ``.cache`` directory.
    """
    return CWD / ".cache" / "client_installer"


def build_installer_properties(cfg: ServerConfig, base_url: str | None = None, host: str | None = None,
                               http_port: int | None = None, server_address: str | None = None) -> str:
    """Compose the installer.properties content embedded in the JAR."""
    if not base_url:
        if not host:
            host = getattr(cfg, "hostname", "") or ""
        if not http_port:
            http_port = int(getattr(cfg, "http_port", 8000) or 8000)
        if host:
            base_url = f"https://{host}"
        else:
            base_url = f"http://{_get_local_ip()}:{http_port}"
    if not server_address:
        src_host = host or _get_local_ip()
        mc_port = int(getattr(cfg, "mc_port", 25565) or 25565)
        server_address = f"{src_host}:{mc_port}" if mc_port != 25565 else src_host

    loader_version = ""
    try:
        if cfg.loader == "neoforge":
            lib = CWD / "libraries" / "net" / "neoforged" / "neoforge"
            if lib.exists():
                versions = [d.name for d in lib.iterdir() if d.is_dir()]
                if versions:
                    loader_version = max(versions)
        elif cfg.loader == "fabric":
            lib = CWD / ".fabric" / "loader"
            if lib.exists():
                versions = [d.name for d in lib.iterdir() if d.is_dir()]
                if versions:
                    loader_version = max(versions)
    except Exception:
        pass

    return "\n".join([
        f"baseUrl={base_url}",
        f"serverAddress={server_address}",
        f"loader={cfg.loader}",
        f"mcVersion={cfg.mc_version}",
        f"loaderVersion={loader_version}",
        "",
    ])


def _build_pack_zip(cfg: ServerConfig) -> bytes:
    """Build the embedded pack (mods + config + defaultconfigs) as bytes."""
    from .mod_hosting import build_launcher_zip_bytes
    buf = build_launcher_zip_bytes(cfg)
    if buf is None:
        raise RuntimeError("failed to build launcher pack")
    return buf.getvalue()


def build_installer_jar(cfg: ServerConfig, base_url: str | None = None, host: str | None = None,
                        http_port: int | None = None, server_address: str | None = None,
                        force: bool = False) -> Path:
    """Compile NeoRunnerInstaller.java + embedded properties + pack into a JAR (cached)."""
    if not _JAVA_SRC.exists():
        raise FileNotFoundError(f"Installer source not found: {_JAVA_SRC}")

    properties_text = build_installer_properties(cfg, base_url, host, http_port, server_address)
    pack_bytes = _build_pack_zip(cfg)
    cache_key = hashlib.sha256(
        (_JAVA_SRC.read_text() + "\n---\n" + properties_text
         + "\n---pack---\n" + hashlib.sha256(pack_bytes).hexdigest()).encode("utf-8")
    ).hexdigest()[:12]

    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    jar_path = cache_dir / f"neorunner-installer-{cache_key}.jar"

    if jar_path.exists() and not force:
        return jar_path

    javac = shutil.which("javac")
    if not javac:
        raise RuntimeError("javac not found on PATH - cannot build installer JAR")

    with tempfile.TemporaryDirectory(prefix="nr-installer-") as tmpd:
        tmp = Path(tmpd)
        classes = tmp / "classes"
        classes.mkdir()
        (classes / "installer.properties").write_text(properties_text)

        result = subprocess.run(
            [javac, "-source", "8", "-target", "8", "-d", str(classes), str(_JAVA_SRC)], check=False,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"javac failed: {result.stderr}")

        with zipfile.ZipFile(jar_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(classes.rglob("*")):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(classes)))
            zf.writestr("pack.zip", pack_bytes)
            zf.writestr("META-INF/MANIFEST.MF",
                        "Manifest-Version: 1.0\r\nMain-Class: NeoRunnerInstaller\r\n")

    logger.info("Built installer JAR: %s (%.1f MB)", jar_path.name, jar_path.stat().st_size / 1e6)
    return jar_path


def build_installer_jar_bytes(cfg: ServerConfig, base_url: str | None = None, host: str | None = None,
                              http_port: int | None = None, server_address: str | None = None) -> io.BytesIO:
    """Return the installer JAR as in-memory bytes (for Flask send_file)."""
    jar_path = build_installer_jar(cfg, base_url, host, http_port, server_address)
    buf = io.BytesIO(jar_path.read_bytes())
    buf.seek(0)
    return buf
