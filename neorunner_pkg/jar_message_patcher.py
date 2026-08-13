"""Patch loader jars so clients are shown the modpack download link.

When a client attempts to connect with a mismatched/vanilla mod loader, the
server disconnects them during the configuration handshake with a translatable
component.  By default the client renders that as "Incompatible client! Please
use NeoForge X" or the vanilla fallback.  We patch the string constants inside
the loader's universal jar so the disconnect message instead points players at
the modpack download page.

How it works
------------
A class file's constant pool stores strings as length-prefixed UTF8 entries.
`Component.translatable(key, args)` only translates *known* keys; an unknown
key is rendered verbatim by the client.  Replacing the constant for a well-known
key (e.g. ``multiplayer.disconnect.incompatible``) with a plain message therefore
changes exactly what the client sees, without touching any bytecode offsets.
"""

import shutil
import struct
from pathlib import Path

from ._clickable_message import CLASS_NAME as CLICKABLE_CLASS_NAME
from ._clickable_message import clickable_message_class
from .config import load_cfg
from .constants import CWD
from .log import log_event
from .mod_hosting import public_download_link

# The text shown before the (clickable) download URL on a mod-mismatch kick.
# The link itself is appended as a separate component with a ClickEvent.OpenUrl.
CLICKABLE_TEXT = "Your client does not match the server's mods. Download the modpack: "

# The class whose bytecode is rewritten to call the clickable-link helper.
SERVER_HANDSHAKE_CLASS = "net/minecraft/server/network/ServerHandshakePacketListenerImpl.class"

# Translation keys / fallback strings that loaders send on a mod mismatch.
# The ``key -> message`` entries replace the constant used as the component key.
# The ``fallback -> message`` entries replace the raw fallback string sent via
# ``Component.translatableWithFallback`` (rendered verbatim by vanilla clients).
NEOFORGE_REPLACEMENTS = {
    # Sent by NetworkRegistry for every modded-payload rejection.
    "multiplayer.disconnect.incompatible": "Your client does not match the server's mods. Download the modpack: {}",
    # Vanilla client joining a NeoForge server.
    "You are trying to connect to a server that is running NeoForge, but you are not. Please install NeoForge Version: %s to connect to this server.": "This server runs a modpack you need first. Download it here: {}",
    # FML handshake version rejection.
    "Incompatible client! Please use %s": "Your client does not match the server's mods. Download the modpack: {}",
}

FORGE_REPLACEMENTS = {
    "multiplayer.disconnect.incompatible": "Your client does not match the server's mods. Download the modpack: {}",
    "Incompatible client! Please use %s": "Your client does not match the server's mods. Download the modpack: {}",
}

FABRIC_REPLACEMENTS = {
    # Fabric uses its own handshake; patch the vanilla key where present.
    "multiplayer.disconnect.incompatible": "Your client does not match the server's mods. Download the modpack: {}",
}


def _download_link(cfg) -> str:
    """Public installer download URL (delegates to the shared mod_hosting helper)."""
    return public_download_link(cfg)


def _loader_replacements(loader: str) -> dict[str, str]:
    table = {
        "neoforge": NEOFORGE_REPLACEMENTS,
        "forge": FORGE_REPLACEMENTS,
        "fabric": FABRIC_REPLACEMENTS,
    }
    return table.get(loader, {})


def _loader_byte_replacements(loader: str, link: str) -> list[tuple[bytes, bytes]]:
    """Version-tolerant replacement table as ``[(old_bytes, new_bytes)]``.

    Loader disconnect strings vary by MC/loader version, so instead of a fixed
    ``dict`` we enumerate candidate old constants and the message they render
    for each, then let the class-file scan pick whichever are actually present.
    """
    out: list[tuple[bytes, bytes]] = []
    for key, fmt in _loader_replacements(loader).items():
        out.append((key.encode("utf-8"), fmt.format(link).encode("utf-8")))
    return out


def _find_universal_jars(loader: str) -> list:
    """Locate the loader's jars that carry the incompatible-client disconnect.

    For NeoForge that includes the ``*-universal.jar`` (NetworkRegistry /
    ClientNetworkRegistry constants) *and* the ``minecraft-server-patched`` jar,
    whose ``ServerHandshakePacketListenerImpl`` sends the vanilla
    ``multiplayer.disconnect.incompatible`` key on a modded-handshake rejection.
    """
    if loader == "neoforge":
        jars = []
        base = CWD / "libraries" / "net" / "neoforged" / "neoforge"
        if base.exists():
            for ver in sorted(base.iterdir(), reverse=True):
                if not ver.is_dir():
                    continue
                cand = ver / f"neoforge-{ver.name}-universal.jar"
                if cand.exists():
                    jars.append(cand)
        patched_base = CWD / "libraries" / "net" / "neoforged" / "minecraft-server-patched"
        if patched_base.exists():
            for ver in sorted(patched_base.iterdir(), reverse=True):
                if not ver.is_dir():
                    continue
                cand = ver / f"minecraft-server-patched-{ver.name}.jar"
                if cand.exists():
                    jars.append(cand)
        return jars
    if loader == "forge":
        base = CWD / "libraries" / "net" / "minecraftforge" / "forge"
        jars = []
        if base.exists():
            for ver in sorted(base.iterdir(), reverse=True):
                if not ver.is_dir():
                    continue
                for pat in (f"forge-{ver.name}-universal.jar", f"forge-{ver.name}.jar"):
                    cand = ver / pat
                    if cand.exists():
                        jars.append(cand)
                        break
        return jars
    return []


_SIGNATURE_SUFFIXES = (".SF", ".DSA", ".RSA", ".EC")


def _is_signature_file(name: str) -> bool:
    """True for META-INF signature files that must be dropped after patching."""
    upper = name.upper()
    if not upper.startswith("META-INF/"):
        return False
    base = name.split("/", 1)[1]
    if base == "MANIFEST.MF":
        return False
    return upper.endswith(_SIGNATURE_SUFFIXES) or base.startswith("SIG-")


def has_jar_signatures(names: list[str]) -> bool:
    """True if the jar's entry list contains signature files (i.e. it is signed)."""
    return any(_is_signature_file(n) for n in names)


def _sanitize_manifest(manifest_bytes: bytes) -> bytes:
    """Reduce MANIFEST.MF to its main section.

    Signed jars include one ``Name:``/digest block per entry after a blank line.
    Those per-entry attributes are only meaningful for signature verification;
    once the signature files are dropped they'd trigger a validation error, so
    strip them.
    """
    text = manifest_bytes.decode("latin-1")
    for sep in ("\r\n\r\n", "\n\n"):
        if sep in text:
            return text.split(sep, 1)[0].encode("latin-1") + sep.encode("latin-1")
    return manifest_bytes


def strip_jar_signatures(entries: list[str], manifest_bytes: bytes | None) -> tuple[list[str], bytes | None]:
    """Remove signing from a jar's entry list.

    Args:
        entries: jar entry names (as returned by ``namelist``).
        manifest_bytes: raw ``META-INF/MANIFEST.MF`` bytes, if present.

    Returns:
        ``(filtered_entries, sanitized_manifest_bytes)``. The filtered list drops
        ``META-INF/*.SF/.RSA/.DSA/.EC`` and legacy ``META-INF/SIG-*`` files; the
        returned manifest (``None`` if no manifest was given) keeps only the
        main section, so leftover hashes don't break loading.
    """
    filtered = [n for n in entries if not _is_signature_file(n)]
    if manifest_bytes is None:
        return filtered, None
    return filtered, _sanitize_manifest(manifest_bytes)


def _parse_and_rebuild(data: bytes, replacements: dict[bytes, bytes]) -> bytes:
    """Replace constant-pool UTF8 strings and rebuild a class file.

    Args:
        data: raw .class bytes
        replacements: mapping old byte string -> new byte string

    Returns:
        Rebuilt class bytes with the constant pool strings swapped.
    """
    assert data[:4] == b"\xca\xfe\xba\xbe", "not a class file"
    magic = data[:8]
    cp_count = struct.unpack(">H", data[8:10])[0]
    idx = 10
    entries = []
    for _ in range(1, cp_count):
        tag = data[idx]
        start = idx
        if tag == 1:  # Utf8
            ln = struct.unpack(">H", data[idx + 1 : idx + 3])[0]
            val = data[idx + 3 : idx + 3 + ln]
            if val in replacements:
                newval = replacements[val]
                assert len(newval) <= 65535, "replacement too long for constant pool"
                entries.append(b"\x01" + struct.pack(">H", len(newval)) + newval)
            else:
                entries.append(data[start : idx + 3 + ln])
            idx = idx + 3 + ln
        elif tag in (3, 4):  # Int, Float
            entries.append(data[start : start + 5])
            idx += 5
        elif tag in (5, 6):  # Long, Double (two slots)
            entries.append(data[start : start + 9])
            idx += 9
        elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
            entries.append(data[start : start + 3])
            idx += 3
        elif tag in (9, 10, 11, 12, 17, 18):  # refs, NameAndType, Dynamic, InvokeDynamic
            entries.append(data[start : start + 5])
            idx += 5
        elif tag == 15:  # MethodHandle
            entries.append(data[start : start + 4])
            idx += 4
        else:
            raise ValueError(f"unknown constant pool tag {tag} at offset {start}")
    rest = data[idx:]
    out = bytearray(magic + struct.pack(">H", cp_count))
    for e in entries:
        out += e
    out += rest
    return bytes(out)


# -- Clickable-link bytecode surgery --------------------------------------
#
# ``ServerHandshakePacketListenerImpl.beginLogin`` disconnects a mismatched
# client with ``Component.translatable(key, args)``.  A string-only patch can
# change *what* text is shown, but a vanilla client renders an unknown key
# verbatim, so the URL stays a plain, non-clickable string.  To make it a real
# hyperlink we rewrite the bytecode to call ``ClickableMessage.textWithLink``
# instead, and inject that helper class into the jar.
#
# The original block (20 bytes, just before ``astore_3``):
#     ldc #k            ; "multiplayer.disconnect.incompatible" key
#     iconst_1
#     anewarray #2      ; Object[] args
#     dup
#     iconst_0
#     invokestatic      ; SharedConstants.getCurrentVersion()
#     invokeinterface   ; WorldVersion.name()
#     aastore
#     invokestatic      ; Component.translatable(String, Object[])
# is replaced with an equal-length block:
#     ldc #k            ; text (constant rewritten to CLICKABLE_TEXT)
#     ldc_w #url        ; new CONSTANT_String for the link
#     invokestatic #m   ; ClickableMessage.textWithLink(String, String)
#     nop * (padding)
# so every branch offset and stack-map frame stays valid.

def _parse_cp_entries(data: bytes) -> tuple[list, int]:
    """Return ``(entries, body_offset)`` for a class file's constant pool.

    ``entries[i]`` corresponds to constant-pool index ``i + 1`` and is a
    ``(tag, info)`` tuple where ``info`` is the raw bytes following the tag.
    ``body_offset`` is the byte offset where the pool ends and the class body
    (access flags onward) begins.
    """
    assert data[:4] == b"\xca\xfe\xba\xbe", "not a class file"
    cp_count = struct.unpack(">H", data[8:10])[0]
    idx = 10
    entries = []
    for _ in range(1, cp_count):
        tag = data[idx]
        start = idx
        if tag == 1:  # Utf8
            ln = struct.unpack(">H", data[idx + 1 : idx + 3])[0]
            entries.append((1, data[idx + 3 : idx + 3 + ln]))
            idx += 3 + ln
        elif tag in (3, 4):  # Int, Float
            entries.append((tag, data[start + 1 : start + 5]))
            idx += 5
        elif tag in (5, 6):  # Long, Double (two slots)
            entries.append((tag, data[start + 1 : start + 9]))
            idx += 9
        elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
            entries.append((tag, data[start + 1 : start + 3]))
            idx += 3
        elif tag in (9, 10, 11, 12, 17, 18):  # refs, NameAndType, Dynamic, InvokeDynamic
            entries.append((tag, data[start + 1 : start + 5]))
            idx += 5
        elif tag == 15:  # MethodHandle
            entries.append((tag, data[start + 1 : start + 4]))
            idx += 4
        else:
            raise ValueError(f"unknown constant pool tag {tag} at offset {start}")
    return entries, idx


def _cp_resolve_string(entries: list, index: int) -> str | None:
    """Resolve a 1-based constant-pool index to its UTF8 value if it is a String."""
    if index < 1 or index > len(entries):
        return None
    tag, info = entries[index - 1]
    if tag == 8:  # CONSTANT_String -> Utf8 index
        utf8_idx = struct.unpack(">H", info)[0]
        t2, v2 = entries[utf8_idx - 1]
        if t2 == 1:
            return v2.decode("utf-8")
    return None


def _encode_cp_entry(tag: int, info: bytes) -> bytes:
    """Serialize a single constant-pool entry from ``(tag, info)``."""
    if tag == 1:
        return b"\x01" + struct.pack(">H", len(info)) + info
    return bytes([tag]) + info


def _inject_clickable(data: bytes, link: str, text: str = CLICKABLE_TEXT) -> bytes | None:
    """Rewrite ``beginLogin`` to call ``ClickableMessage.textWithLink``.

    Args:
        data: raw ``ServerHandshakePacketListenerImpl.class`` bytes.
        link: the download URL to make clickable.
        text: the static text shown before the clickable URL.

    Returns:
        New class bytes, or ``None`` if the target call site was not found
        (e.g. already patched, or a different Minecraft version layout).
    """
    entries, body_start = _parse_cp_entries(data)
    old_count = len(entries) + 1
    body = data[body_start:]

    # Locate the block.  The two candidate blocks (outdated_client vs
    # incompatible) are structurally identical, so disambiguate by the string
    # the ``ldc`` operand resolves to.
    block_i = None
    ldc_idx = None
    for i in range(len(body) - 21):
        b = body
        if (
            b[i] == 0x12
            and b[i + 2] == 0x04
            and b[i + 3] == 0xBD
            and b[i + 6] == 0x59
            and b[i + 7] == 0x03
            and b[i + 8] == 0xB8
            and b[i + 11] == 0xB9
            and b[i + 14] == 0x01
            and b[i + 15] == 0x00
            and b[i + 16] == 0x53
            and b[i + 17] == 0xB8
            and b[i + 20] == 0x4E
        ):
            s = _cp_resolve_string(entries, b[i + 1])
            if s == "multiplayer.disconnect.incompatible":
                block_i = i
                ldc_idx = b[i + 1]
                break
    if block_i is None:
        return None

    text_utf8 = text.encode("utf-8")
    link_utf8 = link.encode("utf-8")

    # New constant-pool indices (appended after the existing entries).
    cls_name_idx = old_count + 0
    class_idx = old_count + 1
    mname_idx = old_count + 2
    desc_idx = old_count + 3
    nat_idx = old_count + 4
    mref_idx = old_count + 5
    url_utf8_idx = old_count + 6
    url_str_idx = old_count + 7

    new_entries = [
        (1, b"neorunner_client/ClickableMessage"),
        (7, struct.pack(">H", cls_name_idx)),
        (1, b"textWithLink"),
        (
            1,
            b"(Ljava/lang/String;Ljava/lang/String;)Lnet/minecraft/network/chat/MutableComponent;",
        ),
        (12, struct.pack(">H", mname_idx) + struct.pack(">H", desc_idx)),
        (10, struct.pack(">H", class_idx) + struct.pack(">H", nat_idx)),
        (1, link_utf8),
        (8, struct.pack(">H", url_utf8_idx)),
    ]

    # Rebuild the pool, rewriting the incompatible key to the clickable text.
    out_entries = []
    for tag, info in entries:
        if tag == 1 and info == b"multiplayer.disconnect.incompatible":
            info = text_utf8
        out_entries.append((tag, info))
    out_entries.extend(new_entries)

    cp_bytes = bytearray()
    for tag, info in out_entries:
        cp_bytes += _encode_cp_entry(tag, info)

    new_cp_count = old_count + len(new_entries)
    header = data[:8] + struct.pack(">H", new_cp_count) + bytes(cp_bytes)

    # Build the replacement block (equal length to the original 20 bytes).
    new_block = bytearray()
    new_block += b"\x12" + bytes([ldc_idx])  # ldc (text)
    new_block += b"\x13" + struct.pack(">H", url_str_idx)  # ldc_w (url)
    new_block += b"\xb8" + struct.pack(">H", mref_idx)  # invokestatic helper
    if len(new_block) > 20:
        raise ValueError("clickable replacement block exceeds 20 bytes")
    new_block += b"\x00" * (20 - len(new_block))

    body = body[:block_i] + bytes(new_block) + body[block_i + 20 :]
    return header + body


_URL_RE = None


def _baked_link(jar: Path) -> str | None:
    """Return the download link currently baked into a patched jar, if any."""
    import re

    global _URL_RE
    if _URL_RE is None:
        _URL_RE = re.compile(rb"https?://[A-Za-z0-9.\-]+/download/installer\.jar")
    try:
        import zipfile

        with zipfile.ZipFile(jar) as z:
            for name in z.namelist():
                if not name.endswith(".class"):
                    continue
                m = _URL_RE.search(z.read(name))
                if m:
                    return m.group(0).decode("utf-8")
    except Exception:
        return None
    return None


def _jar_is_clickable(jar: Path) -> bool:
    """True if the jar's handshake class actually calls the clickable-link helper.

    The helper class's presence alone is not enough: it must also be referenced
    from ``ServerHandshakePacketListenerImpl`` (i.e. the bytecode surgery landed).
    """
    import zipfile

    try:
        with zipfile.ZipFile(jar) as z:
            names = z.namelist()
            if CLICKABLE_CLASS_NAME not in names:
                return False
            if SERVER_HANDSHAKE_CLASS not in names:
                return False
            return b"textWithLink" in z.read(SERVER_HANDSHAKE_CLASS)
    except Exception:
        return False


def _patch_jar(jar: Path, loader: str) -> bool:
    """Patch a single universal jar in place. Returns True if anything changed."""
    import tempfile
    import zipfile

    link = _download_link(load_cfg())
    backup = jar.with_suffix(".jar.orig")

    # NeoForge's ``minecraft-server-patched`` jar sends the vanilla
    # ``multiplayer.disconnect.incompatible`` key from
    # ``ServerHandshakePacketListenerImpl``; we make its URL clickable there.
    with zipfile.ZipFile(jar, "r") as zin:
        names = zin.namelist()
        is_server_patched = SERVER_HANDSHAKE_CLASS in names
    do_clickable = loader == "neoforge" and is_server_patched

    # Restore the pristine backup before re-patching if the jar already carries
    # a *different* link (hostname changed), or if it was string-patched before
    # the clickable feature existed and still needs the clickable upgrade.
    baked = _baked_link(jar)
    clickable = _jar_is_clickable(jar)
    stale = baked is not None and (
        baked != link or (do_clickable and not clickable)
    )
    if stale and backup.exists():
        shutil.copy2(backup, jar)

    # Version-tolerant byte map: only constants actually present in this jar's
    # classes will match, so the same table works across loader versions.
    mapping = dict(_loader_byte_replacements(loader, link))
    if not mapping:
        return False

    # Backup untouched jar once (per jar path).
    if not backup.exists():
        shutil.copy2(jar, backup)

    changed = False
    with zipfile.ZipFile(jar, "r") as zin:
        names = zin.namelist()
        # Signed jars: patching class bytes invalidates the digest, so drop the
        # signature files and sanitize MANIFEST.MF before rewriting.
        signed = has_jar_signatures(names)
        manifest_name = "META-INF/MANIFEST.MF"
        manifest_bytes = zin.read(manifest_name) if manifest_name in names else None
        write_names, clean_manifest = (
            strip_jar_signatures(names, manifest_bytes) if signed else (names, manifest_bytes)
        )
        has_clickable = CLICKABLE_CLASS_NAME in names
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for name in names:
                if not name.endswith(".class"):
                    continue
                data = zin.read(name)
                out_data = None
                if do_clickable and name == SERVER_HANDSHAKE_CLASS:
                    # Clickable-link bytecode surgery rewrites the same
                    # ``multiplayer.disconnect.incompatible`` key to the
                    # text-only message (plus a separate URL constant), so it
                    # must run on the pristine bytes, not the string-patched ones.
                    out_data = _inject_clickable(data, link)
                else:
                    # String replacement (loader keys -> modpack message).
                    if any(k in data for k in mapping):
                        patched = _parse_and_rebuild(data, mapping)
                        if patched != data:
                            out_data = patched
                if out_data is not None:
                    out = tmp / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(out_data)
                    changed = True
            if do_clickable and not has_clickable:
                out = tmp / CLICKABLE_CLASS_NAME
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(clickable_message_class())
                changed = True
            if not changed:
                return False
            # Rewrite the jar with patched classes (all entries, preserving order).
            with zipfile.ZipFile(str(jar) + ".tmp", "w", zipfile.ZIP_DEFLATED) as zout:
                for name in write_names:
                    if name == manifest_name and clean_manifest is not None:
                        zout.writestr(name, clean_manifest)
                        continue
                    patched_path = tmp / name
                    if name.endswith(".class") and patched_path.is_file():
                        zout.writestr(name, patched_path.read_bytes())
                    else:
                        zout.writestr(name, zin.read(name))
                if do_clickable and not has_clickable:
                    zout.writestr(CLICKABLE_CLASS_NAME, clickable_message_class())
    shutil.move(str(jar) + ".tmp", jar)
    return changed


def patch_loader_messages(loader: str | None = None) -> bool:
    """Patch installed loader jars with modpack download messages.

    Args:
        loader: loader to patch; defaults to the configured loader.

    Returns:
        True if at least one jar was patched (or already patched).
    """
    if loader is None:
        loader = load_cfg().loader
    jars = _find_universal_jars(loader)
    if not jars:
        log_event("PATCH", f"No {loader} universal jar found to patch")
        return False
    patched_any = False
    for jar in jars:
        try:
            if _patch_jar(jar, loader):
                log_event("PATCH", f"Patched {jar.name} with modpack download message")
                patched_any = True
        except Exception as e:
            log_event("ERROR", f"Failed to patch {jar.name}: {e}")
    return patched_any


def restore_loader_messages(loader: str | None = None) -> bool:
    """Restore loader jars from their .orig backups. Returns True if restored."""
    if loader is None:
        loader = load_cfg().loader
    jars = _find_universal_jars(loader)
    restored = False
    for jar in jars:
        backup = jar.with_suffix(".jar.orig")
        if backup.exists():
            shutil.copy2(backup, jar)
            log_event("PATCH", f"Restored {jar.name} from backup")
            restored = True
    return restored


def loader_is_patched(loader: str | None = None) -> bool:
    """Return True when the loader jars fully carry our download message.

    For NeoForge this means both the string marker (in the universal jar) and,
    on the ``minecraft-server-patched`` jar, the clickable-link bytecode surgery.
    """
    if loader is None:
        loader = load_cfg().loader
    link = _download_link(load_cfg())
    jars = _find_universal_jars(loader)
    if not jars:
        return False
    marker = f"Download the modpack: {link}".encode()
    import zipfile

    has_string_marker = False
    clickable_ok = True
    for jar in jars:
        try:
            with zipfile.ZipFile(jar) as z:
                names = z.namelist()
                if SERVER_HANDSHAKE_CLASS in names:
                    # The clickable jar carries the text and URL as separate
                    # constants, so check the surgery directly, not the marker.
                    if not _jar_is_clickable(jar):
                        clickable_ok = False
                    continue
                for name in names:
                    if not name.endswith(".class"):
                        continue
                    if marker in z.read(name):
                        has_string_marker = True
                        break
        except Exception as e:
            log_event("WARN", f"Could not inspect {jar.name}: {e}")
            continue
    return has_string_marker and clickable_ok


__all__ = [
    "loader_is_patched",
    "patch_loader_messages",
    "restore_loader_messages",
]
