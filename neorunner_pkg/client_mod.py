"""Build the tiny ``neorunner-client-link`` client mod.

The server can only send a click event on the disconnect message; the vanilla
client's ``DisconnectedScreen`` never routes component clicks, so the URL shows
as plain text. This client-side mod (a Mixin into ``DisconnectedScreen``) makes
any ``ClickEvent.OpenUrl`` in the kick reason open the browser.

It is compiled against the *server* jar (the shared ``net.minecraft.network.chat``
classes) plus the Mixin annotations and the FML ``@Mod`` annotation -- the mixin
targets the client class by string name, so the client jar is not needed at
build time. The resulting jar is dropped into ``clientonly/`` so it ships with
the modpack.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .constants import CWD
from .log import log_event

MOD_DIR = Path(__file__).parent / "client_mod"
MOD_ID = "neorunner_client_link"
MOD_FILENAME = "neorunner-client-link-1.0.0.jar"

_JAVA_SOURCES = [
    MOD_DIR / "src" / "neorunner" / "client" / "link" / "NeoRunnerClientLink.java",
    MOD_DIR / "src" / "neorunner" / "client" / "link" / "mixin" / "DisconnectedScreenMixin.java",
]
_RESOURCES = MOD_DIR / "resources"


def _locate_library(*globs: str) -> Path | None:
    """Find the newest matching library jar under ``libraries/``."""
    for pattern in globs:
        candidates = sorted(CWD.glob(pattern), reverse=True)
        for c in candidates:
            if c.is_file():
                return c
    return None


def _classpath() -> list[str]:
    """Assemble the compile classpath from the installed server + loader libs."""
    parts: list[str] = []
    server_patched = _locate_library(
        "libraries/net/neoforged/minecraft-server-patched/*/minecraft-server-patched-*.jar",
    )
    universal = _locate_library(
        "libraries/net/neoforged/neoforge/*/neoforge-*-universal.jar",
    )
    mixin = _locate_library(
        "libraries/net/fabricmc/sponge-mixin/*/sponge-mixin-*.jar",
    )
    loader = _locate_library(
        "libraries/net/neoforged/fancymodloader/loader/*/loader-*.jar",
    )
    for p in (server_patched, universal, mixin, loader):
        if p:
            parts.append(str(p))

    # Transitive runtime deps (brigadier, etc.) come from the loader's args file.
    for unix_args in sorted(CWD.glob("libraries/net/neoforged/neoforge/*/unix_args.txt")):
        try:
            for tok in unix_args.read_text().split():
                if tok.endswith(".jar"):
                    p = Path(tok)
                    parts.append(str(p if p.is_absolute() else CWD / p))
        except Exception:
            continue
    return parts


def build_client_link_mod(clientonly_dir: Path | None = None) -> Path | None:
    """Compile and package the client-link mod into ``clientonly/`` (cached)."""
    javac = shutil.which("javac")
    if javac is None:
        log_event("CLIENT_MOD", "javac not found - skipping client-link mod build")
        return None
    if not _JAVA_SOURCES[0].exists():
        log_event("CLIENT_MOD", "client-link mod source missing")
        return None

    if clientonly_dir is None:
        clientonly_dir = CWD / "clientonly"
    clientonly_dir.mkdir(parents=True, exist_ok=True)
    out_jar = clientonly_dir / MOD_FILENAME

    cp = ":".join(_classpath())
    if not cp:
        log_event("CLIENT_MOD", "no library classpath found - skipping client-link mod build")
        return None

    with tempfile.TemporaryDirectory(prefix="nr-clientmod-") as tmpd:
        tmp = Path(tmpd)
        classes = tmp / "classes"
        classes.mkdir()
        result = subprocess.run(
            [javac, "--release", "21", "-nowarn", "-cp", cp, "-d", str(classes)]
            + [str(s) for s in _JAVA_SOURCES],
            check=False, capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            log_event("CLIENT_MOD", f"client-link mod compile failed: {result.stderr[:400]}")
            return None

        with zipfile.ZipFile(str(out_jar) + ".tmp", "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(classes.rglob("*.class")):
                zf.write(f, arcname=str(f.relative_to(classes)))
            for f in sorted(_RESOURCES.rglob("*")):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(_RESOURCES)))
        shutil.move(str(out_jar) + ".tmp", str(out_jar))

    log_event("CLIENT_MOD", f"Built {out_jar.name} (clickable disconnect link)")
    return out_jar


__all__ = ["MOD_FILENAME", "MOD_ID", "build_client_link_mod"]
