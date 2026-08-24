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
import os
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
        # Join address must be a domain that actually carries raw TCP game
        # traffic: ``cfg.game_address`` (e.g. w8.mom, the join domain kept
        # current by ip-updater.service) or ``cfg.hostname`` when it is not
        # Cloudflare-proxied. NEVER an IP.
        from .mod_hosting import game_join_address
        server_address = game_join_address(cfg)

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


def _pack_fingerprint(cfg: ServerConfig) -> str:
    """Cheap fingerprint of everything that goes into the launcher pack.

    Rebuilding the pack to compute its hash on every request is the bottleneck
    behind a slow ``/dl/mods.zip`` (a ~300MB in-memory zip per hit).  Instead we
    hash the *inputs* (name + size + mtime) so unchanged folders hit the disk
    cache without rebuilding anything.
    """
    from .mod_hosting import _loader_installer_path

    def stat_tuple(p: Path) -> tuple:
        try:
            st = p.stat()
        except OSError:
            return (p.name, 0, 0)
        return (p.name, st.st_size, int(st.st_mtime))

    parts: list[tuple] = []
    installer = _loader_installer_path(cfg)
    if installer is not None:
        parts.append(("installer",) + stat_tuple(installer))

    mods_dir = Path(cfg.mods_dir)
    if not mods_dir.is_absolute():
        mods_dir = CWD / mods_dir
    clientonly_dir = Path(cfg.clientonly_dir)
    if not clientonly_dir.is_absolute():
        clientonly_dir = CWD / clientonly_dir

    for d, prefix in ((mods_dir, "mods"), (clientonly_dir, "clientonly")):
        if d.exists():
            for f in sorted(d.glob("*.jar")):
                if f.name.endswith(".server.jar"):
                    continue
                parts.append((prefix,) + stat_tuple(f))

    for folder in ("config", "defaultconfigs", "shaderpacks", "resourcepacks"):
        path = CWD / folder
        if path.exists():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    parts.append((folder,) + stat_tuple(f))

    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]


def _build_pack_zip(cfg: ServerConfig) -> bytes:
    """Build the embedded pack (mods + config + defaultconfigs) as bytes.

    Cached to disk keyed by the input fingerprint, so a pack with unchanged
    contents is returned without re-compressing ~300MB of mods on every hit.
    """
    from .mod_hosting import build_launcher_zip_bytes

    fp = _pack_fingerprint(cfg)
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"pack-{fp}.zip"
    if cached.exists() and cached.stat().st_size > 0:
        return cached.read_bytes()

    buf = build_launcher_zip_bytes(cfg)
    if buf is None:
        raise RuntimeError("failed to build launcher pack")
    data = buf.getvalue()
    # Unique temp name: concurrent builders (warm-up thread + HTTP request)
    # would otherwise collide on the same .zip.tmp and one would fail with
    # "No such file or directory" after the other renamed it away.
    import uuid
    tmp = cached.with_name(f"{cached.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(str(tmp), str(cached))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return data


def build_installer_jar(cfg: ServerConfig, base_url: str | None = None, host: str | None = None,
                        http_port: int | None = None, server_address: str | None = None,
                        force: bool = False) -> Path:
    """Compile NeoRunnerInstaller.java + embedded properties + pack into a JAR (cached)."""
    if not _JAVA_SRC.exists():
        raise FileNotFoundError(f"Installer source not found: {_JAVA_SRC}")

    # Ensure the clickable-link client mod is built and present in clientonly/
    # so it ships inside the embedded pack.
    try:
        from .client_mod import build_client_link_mod
        build_client_link_mod()
    except Exception as e:
        logger.warning("client-link mod build skipped: %s", e)

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
