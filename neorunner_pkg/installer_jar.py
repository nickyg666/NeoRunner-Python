"""Build and serve the NeoRunner client installer JAR.

The JAR is a self-contained Java program (Java 8+ bytecode) that:
  1. Detects the default .minecraft directory (Windows/Linux/macOS)
  2. Asks the user to confirm or enter a custom path
  3. Downloads + runs the loader client installer from the server
  4. Downloads launcher.zip (mods + config + defaultconfigs) and extracts it
  5. Prints the server address to join

Built lazily on demand and cached; rebuilt when the embedded config changes.
"""

import hashlib
import io
import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .config import ServerConfig, load_cfg
from .constants import CWD

logger = logging.getLogger(__name__)

_JAVA_SRC = Path(__file__).parent / "client_installer" / "NeoRunnerInstaller.java"
_CACHE_DIR = CWD / ".cache" / "client_installer"


def build_installer_properties(cfg: ServerConfig, base_url: str = None, host: str = None,
                               http_port: int = None, server_address: str = None) -> str:
    """Compose the installer.properties content embedded in the JAR."""
    if not base_url:
        if not host:
            host = getattr(cfg, "hostname", "") or "127.0.0.1"
        if not http_port:
            http_port = int(getattr(cfg, "http_port", 8000) or 8000)
        base_url = f"http://{host}:{http_port}"
    if not server_address:
        mc_port = int(getattr(cfg, "mc_port", 25565) or 25565)
        server_address = f"{host}:{mc_port}" if mc_port != 25565 else host

    loader_version = ""
    try:
        if cfg.loader == "neoforge":
            lib = CWD / "libraries" / "net" / "neoforged" / "neoforge"
            if lib.exists():
                versions = [d.name for d in lib.iterdir() if d.is_dir()]
                if versions:
                    loader_version = sorted(versions)[-1]
        elif cfg.loader == "fabric":
            lib = CWD / ".fabric" / "loader"
            if lib.exists():
                versions = [d.name for d in lib.iterdir() if d.is_dir()]
                if versions:
                    loader_version = sorted(versions)[-1]
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


def build_installer_jar(cfg: ServerConfig, base_url: str = None, host: str = None,
                        http_port: int = None, server_address: str = None,
                        force: bool = False) -> Path:
    """Compile NeoRunnerInstaller.java + embedded properties into a JAR (cached)."""
    if not _JAVA_SRC.exists():
        raise FileNotFoundError(f"Installer source not found: {_JAVA_SRC}")

    properties_text = build_installer_properties(cfg, base_url, host, http_port, server_address)
    cache_key = hashlib.sha256(
        (_JAVA_SRC.read_text() + "\n---\n" + properties_text).encode("utf-8")
    ).hexdigest()[:12]

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jar_path = _CACHE_DIR / f"neorunner-installer-{cache_key}.jar"

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
            [javac, "-source", "8", "-target", "8", "-d", str(classes), str(_JAVA_SRC)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"javac failed: {result.stderr}")

        with zipfile.ZipFile(jar_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(classes.rglob("*")):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(classes)))
            zf.writestr("META-INF/MANIFEST.MF",
                        "Manifest-Version: 1.0\r\nMain-Class: NeoRunnerInstaller\r\n")

    logger.info("Built installer JAR: %s", jar_path.name)
    return jar_path


def build_installer_jar_bytes(cfg: ServerConfig, base_url: str = None, host: str = None,
                              http_port: int = None, server_address: str = None) -> io.BytesIO:
    """Return the installer JAR as in-memory bytes (for Flask send_file)."""
    jar_path = build_installer_jar(cfg, base_url, host, http_port, server_address)
    buf = io.BytesIO(jar_path.read_bytes())
    buf.seek(0)
    return buf
