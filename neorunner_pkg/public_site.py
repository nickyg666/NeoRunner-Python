"""Public download site for mc.w8.mom.

Served by gunicorn on 127.0.0.1:8005, reverse-proxied by Caddy at mc.w8.mom.
Gives unmodded players a painless path onto the modded server:
  1. Launcher zip  - drop into .minecraft/mods (official launcher / any launcher)
  2. CurseForge/Overwolf zip - import directly into the CF app
  3. install-mods.bat / one-liner - automatic sync script
"""

import io
import json
import logging
import socket
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, Response, jsonify, send_file

from .config import load_cfg
from .constants import CWD
from .mod_hosting import create_mod_zip, update_manifest

logger = logging.getLogger(__name__)

app = Flask(__name__)

SERVER_HOST = "w8.mom"


def _public_host() -> str:
    """Public download hostname: prefer config hostname, fall back to SERVER_HOST."""
    try:
        cfg = load_cfg()
        host = getattr(cfg, "hostname", None)
        if host:
            return host
    except Exception:
        pass
    return SERVER_HOST

"""Default MC port for join instructions (server.properties server-port)."""
DEFAULT_SERVER_PORT = 25565

_LOCAL_IP_CACHE: dict = {}


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _loader_label(loader: str) -> str:
    return {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric"}.get(loader, loader.title())


def _server_info() -> dict:
    cfg = load_cfg()
    mc_version = getattr(cfg, "mc_version", None) or "1.21.11"
    loader = getattr(cfg, "loader", "neoforge") or "neoforge"
    mods_dir = CWD / getattr(cfg, "mods_dir", "mods")
    clientonly_dir = CWD / getattr(cfg, "clientonly_dir", "clientonly")

    mod_count = 0
    if mods_dir.exists():
        mod_count += len([f for f in mods_dir.glob("*.jar") if not f.name.endswith(".server.jar")])
    if clientonly_dir.exists():
        mod_count += len([f for f in clientonly_dir.glob("*.jar") if not f.name.endswith(".server.jar")])

    loader_version = None
    lib_path = CWD / "libraries" / "net" / "neoforged" / "neoforge"
    if loader == "neoforge" and lib_path.exists():
        versions = [d.name for d in lib_path.iterdir() if d.is_dir()]
        if versions:
            loader_version = max(versions)

    port = getattr(cfg, "mc_port", DEFAULT_SERVER_PORT) or DEFAULT_SERVER_PORT

    return {
        "mc_version": mc_version,
        "loader": loader,
        "loader_label": _loader_display(loader, loader_version),
        "loader_version": loader_version,
        "mod_count": mod_count,
        "server_address": SERVER_HOST if int(port) == DEFAULT_SERVER_PORT else f"{SERVER_HOST}:{port}",
        "port": int(port),
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _loader_display(loader: str, loader_version: str | None = None) -> str:
    label = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric"}.get(loader, loader.title())
    if loader_version:
        return f"{label} {loader_version}"
    return label


def _collect_jars() -> list:
    """Return list of (arcname, absolute_path) for all installable jars (server + clientonly)."""
    cfg = load_cfg()
    mods_dir = CWD / getattr(cfg, "mods_dir", "mods")
    clientonly_dir = CWD / getattr(cfg, "clientonly_dir", "clientonly")
    jars = []
    for d in (mods_dir, clientonly_dir):
        if d.exists():
            for f in sorted(d.glob("*.jar")):
                if f.name.endswith(".server.jar"):
                    continue
                jars.append((f.name, str(f)))
    return jars


_cf_files_cache: tuple = (None, None)
_CF_ID_MAP_FILE = "data/cf_mod_id_map.json"


def _cf_id_map() -> dict:
    """Map installed jar filename -> {projectID, fileID} using the modpack zip.

    Resolved filenames come from the CurseForge API (cfwidget) and are cached
    on disk so the map only needs one network pass after a modpack install.
    Mods not part of any CF pack (auto-fetched deps, client-only) are absent
    from the map and ship via overrides/mods.
    """
    map_path = CWD / _CF_ID_MAP_FILE
    if map_path.exists():
        try:
            return json.loads(map_path.read_text())
        except Exception:
            pass

    mapping = {}
    entries = _modpack_cf_files()
    if entries:
        from .modpack_installer import resolve_file_name

        for f in entries:
            pid, fid = f.get("projectID"), f.get("fileID")
            if not pid or not fid:
                continue
            try:
                fname = resolve_file_name(pid, fid)
            except Exception:
                fname = None
            if fname:
                mapping[fname] = {"projectID": pid, "fileID": fid}
        try:
            map_path.parent.mkdir(parents=True, exist_ok=True)
            map_path.write_text(json.dumps(mapping, indent=2))
        except Exception:
            pass
    return mapping


def _modpack_cf_files() -> list:
    """Return CurseForge (projectID, fileID) entries from the installed modpack zip.

    ``modpacks/<name>.zip`` is a CurseForge export that lists every mod with its
    numeric CF project/file IDs. ``_build_curseforge_zip`` embeds these so the
    CurseForge app shows a proper mod list ("modpack info") instead of an empty
    file set with mods smuggled into overrides/mods.

    Returns a list of ``{"projectID", "fileID", "required"}``. Empty if no
    modpack zip (or none that matches the current MC version / loader).
    """
    global _cf_files_cache
    cfg = load_cfg()
    cache_key = (getattr(cfg, "mc_version", ""), getattr(cfg, "loader", ""))
    if _cf_files_cache[0] == cache_key:
        return _cf_files_cache[1]

    import zipfile as _zipfile

    entries = []
    modpacks_dir = CWD / "modpacks"
    if modpacks_dir.exists():
        for zp in sorted(modpacks_dir.glob("*.zip"), reverse=True):
            try:
                with _zipfile.ZipFile(zp) as zf:
                    raw = zf.read("manifest.json")
                manifest = json.loads(raw)
                mc = manifest.get("minecraft", {})
                if mc.get("version") and cfg.mc_version and mc["version"] != cfg.mc_version:
                    continue
                loaders = mc.get("modLoaders", [])
                primary = next((l for l in loaders if l.get("primary")), None)
                if primary:
                    lid = primary.get("id", "")
                    if cfg.loader and lid and not lid.startswith(cfg.loader):
                        continue
                entries = [
                    {
                        "projectID": f.get("projectID"),
                        "fileID": f.get("fileID"),
                        "required": f.get("required", True),
                    }
                    for f in manifest.get("files", [])
                    if f.get("projectID") and f.get("fileID")
                ]
                if entries:
                    break
            except Exception:
                continue

    _cf_files_cache = (cache_key, entries)
    return entries


def _extra_folder_entries() -> list:
    """config/, defaultconfigs/, shaderpacks/, resourcepacks/ go into the pack.

    These are the client-facing asset folders a CurseForge modpack's overrides/
    can contain. They ride along in overrides/ so shaders and resource packs are
    shipped to the client, not just mods.
    """
    entries = []
    for folder in ("config", "defaultconfigs", "shaderpacks", "resourcepacks"):
        path = CWD / folder
        if path.exists():
            entries.append((folder, path))
    return entries


def _build_launcher_zip() -> io.BytesIO:
    from .mod_hosting import build_launcher_zip_bytes
    buf = build_launcher_zip_bytes()
    if buf is None:
        return io.BytesIO()
    return buf


def _modpack_meta() -> dict:
    """Return ``{"name", "version"}`` of the installed CurseForge modpack zip.

    Falls back to generic values when no modpack zip matches the current
    MC version / loader.
    """
    cfg = load_cfg()
    modpacks_dir = CWD / "modpacks"
    if modpacks_dir.exists():
        for zp in sorted(modpacks_dir.glob("*.zip"), reverse=True):
            try:
                with zipfile.ZipFile(zp) as zf:
                    raw = zf.read("manifest.json")
                manifest = json.loads(raw)
                mc = manifest.get("minecraft", {})
                if mc.get("version") and cfg.mc_version and mc["version"] != cfg.mc_version:
                    continue
                loaders = mc.get("modLoaders", [])
                primary = next((l for l in loaders if l.get("primary")), None)
                if primary:
                    lid = primary.get("id", "")
                    if cfg.loader and lid and not lid.startswith(cfg.loader):
                        continue
                return {
                    "name": manifest.get("name") or "NeoRunner Server Pack",
                    "version": manifest.get("version") or "1.0.0",
                }
            except Exception:
                continue
    return {"name": "NeoRunner Server Pack", "version": "1.0.0"}


def _non_mod_cf_assets() -> list:
    """Return CF files[] entries that are NOT mods (shaderpacks, worlds, etc.).

    A CurseForge manifest ``files[]`` must only reference mod jars. Anything
    else (shaderpacks, resource packs, world saves) belongs in ``overrides/``
    under its proper subfolder. This resolves each manifest entry back to the
    installed filename (via the cached jar->CF id map) and returns the ones
    that are not jars.
    """
    id_map = _cf_id_map()
    reverse = {}
    for fname, ids in id_map.items():
        reverse[(ids.get("projectID"), ids.get("fileID"))] = fname

    assets = []
    for f in _modpack_cf_files():
        key = (f.get("projectID"), f.get("fileID"))
        fname = reverse.get(key)
        if fname and not fname.lower().endswith(".jar"):
            src = CWD / "mods" / fname
            if src.exists():
                assets.append((fname, src))
    return assets


def _asset_override_arcname(fname: str, src: Path) -> str:
    """Map a non-mod CF asset to its CurseForge overrides/ path."""
    try:
        with zipfile.ZipFile(src) as zf:
            names = zf.namelist()
    except Exception:
        names = []
    # Shaderpack zips contain a shaders/ folder at the top level.
    if any(n.startswith("shaders/") for n in names):
        return f"overrides/shaderpacks/{fname}"
    # World saves contain level.dat.
    if any(n.endswith("level.dat") for n in names):
        world_folder = names[0].split("/")[0]
        return f"overrides/saves/{world_folder}/"
    # Everything else goes straight into overrides/.
    return f"overrides/{fname}"


def _build_curseforge_zip() -> io.BytesIO:
    info = _server_info()
    loader_id = "neoforge-" + (info["loader_version"] or "26.1.0.0")
    if info["loader"] == "fabric":
        loader_id = "fabric-0.19.3"

    meta = _modpack_meta()
    cf_files = _modpack_cf_files()
    non_mod_assets = _non_mod_cf_assets()

    # CurseForge spec: files[] must only contain mod jars. Shaderpacks, worlds
    # and other non-mod content belongs in overrides/ (the manifest "files" are
    # downloaded into mods/ by the launcher).
    known_asset_names = {f[0] for f in non_mod_assets}
    asset_keys = _asset_cf_keys(non_mod_assets)
    mod_files = [
        f for f in cf_files
        if (f.get("projectID"), f.get("fileID")) not in asset_keys
    ]

    manifest = {
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": meta["name"],
        "version": meta["version"],
        "author": "NeoRunner",
        "overrides": "overrides",
        "files": mod_files,
        "minecraft": {
            "version": info["mc_version"],
            "modLoaders": [{"id": loader_id, "primary": True}],
        },
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr(
            "README.txt",
            "Import this zip in the CurseForge/Overwolf launcher:\n"
            "  My Modpacks > Import > select this .zip\n\n"
            "Then launch and join the server at " + info["server_address"] + "\n",
        )
        # Non-mod assets (shaderpacks, world saves) go into overrides/ at their
        # proper subfolder so the launcher places them correctly.
        for fname, src in non_mod_assets:
            arc = _asset_override_arcname(fname, src)
            if arc.endswith("/"):
                with zipfile.ZipFile(src) as zfsrc:
                    for n in zfsrc.namelist():
                        if n.endswith("/"):
                            continue
                        # names[] entries already include the top-level world
                        # folder; drop it since arc already names that folder.
                        stripped = n.split("/", 1)[1] if "/" in n else n
                        zf.writestr(f"{arc}{stripped}", zfsrc.read(n))
            else:
                zf.write(str(src), arcname=arc)
        # Mods the CurseForge app already downloads via the manifest files[]
        # must not be duplicated in overrides/mods. Only mods that were added
        # outside the CF pack (e.g. auto-fetched deps, client-only mods) go into
        # overrides/mods as extra files.
        known = set()
        for f in mod_files:
            known.add((f.get("projectID"), f.get("fileID")))
        extra_jars = []
        seen_names = set()
        for arcname, path in _collect_jars():
            if arcname in known_asset_names:
                continue
            pid, fid = _cf_id_for_jar(arcname)
            if (pid, fid) in known:
                continue
            if arcname in seen_names:
                continue
            seen_names.add(arcname)
            extra_jars.append((arcname, path))
        for arcname, path in extra_jars:
            zf.write(path, arcname=f"overrides/mods/{arcname}")
        for folder, path in _extra_folder_entries():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    zf.write(str(f), arcname=f"overrides/{folder}/{f.relative_to(path)}")
    buf.seek(0)
    return buf


def _asset_cf_keys(assets: list) -> set:
    """Return set of (projectID, fileID) for the given non-mod assets."""
    id_map = _cf_id_map()
    reverse = {}
    for fname, ids in id_map.items():
        reverse[fname] = (ids.get("projectID"), ids.get("fileID"))
    keys = set()
    for fname, _ in assets:
        key = reverse.get(fname)
        if key:
            keys.add(key)
    return keys


def _cf_id_for_jar(filename: str) -> tuple:
    """Best-effort map of an installed jar filename back to CF project/file IDs.

    Uses the cached jar->CF map built from the installed modpack zip. Returns
    ``(None, None)`` when unknown (jar then ships via overrides/mods).
    """
    info = _cf_id_map().get(filename)
    if info:
        return (info.get("projectID"), info.get("fileID"))
    return (None, None)


@app.route("/")
def index():
    """Landing page: download options for players."""
    info = _server_info()
    host = _public_host()
    launcher_url = f"https://{host}/download/launcher.zip"
    cf_url = f"https://{host}/download/curseforge.zip"
    bat_url = f"https://{host}/download/install-mods.bat"
    jar_url = f"https://{host}/download/installer.jar"
    install_bat_url = f"https://{host}/download/install.bat"
    install_sh_url = f"https://{host}/download/install.sh"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Join the modded server — {host}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#0d1117; color:#e6e6e6;
         min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:40px 16px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:14px; max-width:640px;
          width:100%; padding:32px; margin-bottom:20px; }}
  h1 {{ font-size:28px; margin-bottom:6px; }}
  .sub {{ color:#8b949e; font-size:14px; margin-bottom:20px; }}
  .badge {{ display:inline-block; background:#1f6feb; color:#fff; padding:3px 10px; border-radius:999px;
            font-size:12px; margin:2px 4px 2px 0; }}
  .badge.amber {{ background:#d29922; }}
  .btn {{ display:block; width:100%; text-align:left; background:#21262d; border:1px solid #30363d;
         border-radius:10px; padding:16px 18px; margin:10px 0; cursor:pointer; transition:border-color .15s;
         color:#e6d1e6; text-decoration:none; }}
  .btn:hover {{ border-color:#1f6feb; }}
  .btn .t {{ font-size:15px; font-weight:600; }}
  .btn .d {{ font-size:12px; color:#8b949e; margin-top:3px; }}
  .btn .arrow {{ float:right; color:#1f6feb; font-weight:700; font-size:20px; }}
  ol {{ margin-left:20px; font-size:14px; }}
  ol li {{ margin:6px 0; color:#c9d1d9; }}
  code {{ background:#21262d; padding:2px 6px; border-radius:4px; font-size:13px; }}
  .addr {{ font-size:16px; font-weight:700; color:#58a6ff; }}
  .footer {{ color:#484f58; font-size:11px; margin-top:8px; }}
</style>
</head>
<body>
  <div class="card">
    <h1>Join the Neoforge Server</h1>
    <p class="sub">Almost done — grab the modpack, install it, and connect.</p>
    <div><span class="badge">Minecraft {info['mc_version']}</span><span class="badge amber">{info['loader_label']}</span><span class="badge">{info['mod_count']} mods</span></div>
    <p style="color:#8b949e;font-size:13px;margin-top:14px;">Server address:</p>
    <p class="addr">{info['server_address']}</p>
  </div>

  <div class="card">
    <a class="btn" href="{install_bat_url}" style="border-color:#2ea043;">
      <span class="arrow">↗</span>
      <span class="t">One-click installer — Windows</span>
      <span class="d">Downloads the installer + all mods &amp; config. Installs Java automatically if your PC doesn't have it. Detects your .minecraft folder and asks for confirmation.</span>
    </a>
    <a class="btn" href="{install_sh_url}" style="border-color:#2ea043;">
      <span class="arrow">↗</span>
      <span class="t">One-click installer — macOS / Linux</span>
      <span class="d">Downloads the installer + all mods &amp; config. Installs Java automatically if needed. Detects your .minecraft folder and asks for confirmation.</span>
    </a>
    <a class="btn" href="{jar_url}">
      <span class="arrow">↗</span>
      <span class="t">Installer JAR only (you already have Java)</span>
      <span class="d">The raw {info['loader_label']} installer JAR — use this only if Java is already installed.</span>
    </a>
    <a class="btn" href="{launcher_url}">
      <span class="arrow">↗</span>
      <span class="t">The official/minecraft launcher</span>
      <span class="d">Download the folder zip (mods + config). Unzip into .minecraft and in the launcher use {info['loader_label']}"{info['mc_version']}".</span>
    </a>
    <a class="btn" href="{cf_url}">
      <span class="arrow">↗</span>
      <span class="t">CurseForge / Overwolf</span>
      <span class="d">Download the .zip, Import at My Modpacks — done. Launch from the CF app.</span>
    </a>
    <a class="btn" href="{bat_url}">
      <span class="arrow">↗</span>
      <span class="t">Auto-install script (Windows)</span>
      <span class="d">Runs in a cmd window and downloads &amp; syncs your mods automatically.</span>
    </a>
  </div>

  <div class="card">
    <h2 style="font-size:18px;margin-bottom:10px;">How to join</h2>
    <ol>
      <li>Install the <b>{info['loader_label']}</b> loader for Minecraft {info['mc_version']} (the zip download above does this for you).</li>
      <li>Unzip the downloaded modpack into your <code>.minecraft</code> folder (the launcher zip does the whole thing).</li>
      <li>Launch Minecraft with the profile your loader creates, then <b>Multiplayer → Add server</b> and enter <code>{info['server_address']}</code>.</li>
      <li>You're in! If you get an error, re-join after a minute — the server self-heals mods automatically.</li>
    </ol>
    <p style="color:#8b949e;font-size:12px;margin-top:12px;">Your game needs the mods BEFORE connecting - the server checks that you have every mod installed!</p>
  </div>

  <p class="footer">NeoRunner auto-healing modded server · generated {info['generated']}</p>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@app.route("/download/launcher.zip")
def download_launcher_zip():
    buf = _build_launcher_zip()
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"neorunner-launcher-{_server_info()['mc_version']}.zip",
    )


@app.route("/download/curseforge.zip")
def download_curseforge_zip():
    buf = _build_curseforge_zip()
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"neorunner-curseforge-{_server_info()['mc_version']}.zip",
    )


@app.route("/download/installer.jar")
def download_installer_jar():
    """Self-contained Java installer: detects .minecraft dir, installs loader + mods."""
    try:
        cfg = load_cfg()
        from .installer_jar import build_installer_jar_bytes
        info = _server_info()
        server_addr = info.get("server_address") or "127.0.0.1"
        buf = build_installer_jar_bytes(
            cfg, base_url=f"https://{_public_host()}", server_address=server_addr,
        )
        return send_file(
            buf, mimetype="application/java-archive", as_attachment=True,
            download_name=f"neorunner-installer-{cfg.mc_version}.jar",
        )
    except Exception as e:
        logger.exception("installer jar build failed")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download/loader-installer.jar")
def download_loader_installer():
    """Serve the mod loader's own client installer jar (NeoForge/Forge/Fabric)."""
    try:
        cfg = load_cfg()
        candidates = []
        if cfg.loader == "neoforge":
            lib = CWD / "libraries" / "net" / "neoforged" / "neoforge"
            if lib.exists():
                for v in sorted(lib.iterdir(), reverse=True):
                    if v.is_dir():
                        candidates.append(v / f"neoforge-{v.name}-installer.jar")
            candidates.append(CWD / f"neoforge-{cfg.mc_version}-installer.jar")
        elif cfg.loader == "forge":
            candidates.append(CWD / f"forge-{cfg.mc_version}-installer.jar")
        elif cfg.loader == "fabric":
            candidates.append(CWD / "fabric-installer.jar")

        for cand in candidates:
            if cand.exists():
                return send_file(str(cand), mimetype="application/java-archive",
                                 as_attachment=True, download_name=cand.name)

        return jsonify({"success": False, "error": "No loader installer jar available on server"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download/manifest")
def download_manifest():
    cfg = load_cfg()
    mods_dir = CWD / getattr(cfg, "mods_dir", "mods")
    update_manifest(mods_dir, cfg)
    manifest_path = mods_dir / "manifest.json"
    if manifest_path.exists():
        return send_file(manifest_path, mimetype="application/json")
    return jsonify({"files": []})


@app.route("/download/all")
@app.route("/download/mods_latest.zip")
def download_all_zip():
    cfg = load_cfg()
    mods_dir = CWD / getattr(cfg, "mods_dir", "mods")
    zip_path = create_mod_zip(mods_dir, cfg)
    if zip_path and zip_path.exists():
        return send_file(str(zip_path), mimetype="application/zip", as_attachment=True, download_name="neorunner-mods.zip")
    return jsonify({"success": False, "error": "No mods on server yet"}), 404


_BAT_TEMPLATE = r"""@echo off
title NeoRunner Mod Sync - {host}
set "BASE=https://{host}"
echo ============================================
echo   NeoRunner Mod Sync
echo   Downloading manifest from %BASE% ...
echo ============================================
set "MC_DIR=%APPDATA%\.minecraft"
if not exist "%MC_DIR%\mods" mkdir "%MC_DIR%\mods"
if not exist "%MC_DIR%\oldmods" mkdir "%MC_DIR%\oldmods"

curl.exe -sL "%BASE%/download/all" -o "%TEMP%\neorunner_mods.zip" || goto :fail
powershell -NoProfile -Command "Expand-Archive -Force '%TEMP%\neorunner_mods.zip' '%MC_DIR%\mods' -DestinationPath '%MC_DIR%\mods'" 2>nul || (
    echo Extracting with built-in expander...
    cd /d "%MC_DIR%\mods" && tar -xf "%TEMP%\neorunner_mods.zip" 2>nul
)
echo.
echo Move any old mods you want to keep into "oldmods".
echo Recommended: delete everything in mods first, then re-run this if missing mods.
echo.
echo Done! Launch Minecraft with the + %LOADER% loader and join the server.
timeout /t 5

:fail
echo.
echo Failed to download the modpack. Check https://{host}
timeout /t 10 >nul
"""


@app.route("/download/install-mods.bat")
def download_install_bat():
    return Response(_BAT_TEMPLATE.format(host=_public_host()), mimetype="text/plain", headers={
        "Content-Disposition": 'attachment; filename="install-mods.bat"'
    })


@app.route("/api/info")
def api_info():
    return jsonify(_server_info())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8005, debug=False, threaded=True)