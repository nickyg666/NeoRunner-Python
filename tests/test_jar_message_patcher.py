"""Tests for the loader jar message patcher."""

import os
import shutil
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg import jar_message_patcher as jmp
from neorunner_pkg.config import ServerConfig


# Minimal valid-looking class bytes: magic + version + a tiny constant pool.
def _fake_class_bytes() -> bytes:
    # cp_count = 3 (indices 1..2 used): one Utf8 and one Class
    utf8 = b"multiplayer.disconnect.incompatible"
    cp = struct.pack(">H", 3)
    cp += b"\x01" + struct.pack(">H", len(utf8)) + utf8
    cp += b"\x07" + struct.pack(">H", 1)  # Class -> index 1
    return b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61) + cp


def _make_handshake_class() -> bytes:
    """Synthetic ``ServerHandshakePacketListenerImpl`` with the incompatible block.

    The constant pool puts a String constant for ``multiplayer.disconnect.incompatible``
    at index 2, and the body carries the exact 21-byte ``beginLogin`` sequence
    (``ldc #2; iconst_1; anewarray #2; dup; iconst_0; invokestatic;
    invokeinterface; aastore; invokestatic; astore_3``) that the clickable
    surgery targets.
    """
    utf8_key = b"multiplayer.disconnect.incompatible"
    cp = struct.pack(">H", 3)  # cp_count = 3 (indices 1 and 2 used)
    cp += b"\x01" + struct.pack(">H", len(utf8_key)) + utf8_key  # 1: Utf8
    cp += b"\x08" + struct.pack(">H", 1)  # 2: String -> 1
    # Class body: access_flags, this, super, ifaces, fields, methods
    header = struct.pack(">HHHHHH", 0x0021, 1, 0, 0, 0, 0)
    block = bytes(
        [
            0x12, 0x02,  # ldc #2 (the incompatible key)
            0x04,  # iconst_1
            0xBD, 0x00, 0x02,  # anewarray #2
            0x59,  # dup
            0x03,  # iconst_0
            0xB8, 0x00, 0x03,  # invokestatic
            0xB9, 0x00, 0x04, 0x01, 0x00,  # invokeinterface
            0x53,  # aastore
            0xB8, 0x00, 0x05,  # invokestatic (translatable)
            0x4E,  # astore_3
        ]
    )
    body = header + block + b"\x00" * 10
    return b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61) + cp + body


def _make_registry_class() -> bytes:
    """Synthetic ``NetworkRegistry`` with a ``Component.translatable`` call site.

    Constant pool: key string (String -> Utf8), a ``Component`` Class, and a
    ``translatable`` InterfaceMethodref.  The body carries ``ldc #2; iconst_1;
    anewarray; dup; iconst_0; invokestatic #8`` — the shape the registry surgery
    targets (``ldc <key>`` followed by ``invokestatic translatable``).
    """
    utf8_key = b"multiplayer.disconnect.incompatible"
    utf8_component = b"net/minecraft/network/chat/Component"
    utf8_translatable = b"translatable"
    utf8_desc = b"(Ljava/lang/String;[Ljava/lang/Object;)Lnet/minecraft/network/chat/MutableComponent;"

    cp = struct.pack(">H", 9)  # indices 1..8
    cp += b"\x01" + struct.pack(">H", len(utf8_key)) + utf8_key  # 1 Utf8 key
    cp += b"\x08" + struct.pack(">H", 1)  # 2 String -> 1
    cp += b"\x01" + struct.pack(">H", len(utf8_component)) + utf8_component  # 3 Utf8
    cp += b"\x07" + struct.pack(">H", 3)  # 4 Class -> 3
    cp += b"\x01" + struct.pack(">H", len(utf8_translatable)) + utf8_translatable  # 5 Utf8
    cp += b"\x01" + struct.pack(">H", len(utf8_desc)) + utf8_desc  # 6 Utf8
    cp += b"\x0C" + struct.pack(">H", 5) + struct.pack(">H", 6)  # 7 NameAndType -> (5, 6)
    cp += b"\x0B" + struct.pack(">H", 4) + struct.pack(">H", 7)  # 8 InterfaceMethodref -> (4, 7)

    header = struct.pack(">HHHHHH", 0x0021, 9, 0, 0, 0, 0)
    block = bytes(
        [
            0x12, 0x02,  # ldc #2 (the incompatible key)
            0x04,  # iconst_1
            0xBD, 0x00, 0x02,  # anewarray #2
            0x59,  # dup
            0x03,  # iconst_0
            0xB8, 0x00, 0x08,  # invokestatic #8 (translatable)
        ]
    )
    body = header + block + b"\x00" * 8
    return b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, 61) + cp + body


class TestParseAndRebuild:
    def test_roundtrip_noop(self):
        data = _fake_class_bytes()
        assert jmp._parse_and_rebuild(data, {}) == data

    def test_replace_constant(self):
        data = _fake_class_bytes()
        newval = b"Your client does not match. Download: https://x/download/installer.jar"
        out = jmp._parse_and_rebuild(data, {utf8: newval for utf8 in [b"multiplayer.disconnect.incompatible"]})
        assert newval in out
        assert b"multiplayer.disconnect.incompatible" not in out
        # Rebuild is stable / still parseable
        assert jmp._parse_and_rebuild(out, {}) == out

    def test_rejects_non_class(self):
        with pytest.raises(AssertionError):
            jmp._parse_and_rebuild(b"not a class", {})


class TestDownloadLink:
    def test_uses_hostname_from_cfg(self, monkeypatch):
        cfg = ServerConfig(hostname="play.example.com")
        assert jmp._download_link(cfg) == "https://play.example.com/dl/mods.zip"

    def test_default_host(self, monkeypatch):
        cfg = ServerConfig(hostname="")
        assert jmp._download_link(cfg) == "https://mc.w8.mom/dl/mods.zip"


class TestPatchJar:
    def test_patch_and_restore_real_jar(self, tmp_path, monkeypatch):
        """Patch a copy of a jar-like archive with a NetworkRegistry class."""
        jar = tmp_path / "neoforge.jar"
        fake_class = _make_registry_class()
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
            z.writestr("net/neoforged/neoforge/network/registration/NetworkRegistry.class", fake_class)
            z.writestr("net/neoforged/neoforge/client/network/registration/ClientNetworkRegistry.class", _fake_class_bytes())
            z.writestr("README.txt", "hello")

        monkeypatch.setattr(jmp, "CWD", tmp_path.parent)
        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="mc.w8.mom"))
        monkeypatch.setattr(jmp, "_find_universal_jars", lambda loader: [jar])

        assert jmp.patch_loader_messages("neoforge") is True
        # Backup created
        assert jar.with_suffix(".jar.orig").exists()

        with zipfile.ZipFile(jar) as z:
            data = z.read("net/neoforged/neoforge/network/registration/NetworkRegistry.class")
        assert b"Download the modpack" in data
        assert b"multiplayer.disconnect.incompatible" not in data

        # Idempotent: second patch also reports True but stays valid
        assert jmp.loader_is_patched("neoforge") is True

        assert jmp.restore_loader_messages("neoforge") is True
        with zipfile.ZipFile(jar) as z:
            data = z.read("net/neoforged/neoforge/network/registration/NetworkRegistry.class")
        assert b"multiplayer.disconnect.incompatible" in data

    def test_stale_link_repatch(self, tmp_path, monkeypatch):
        """Re-patching after a hostname change restores the backup and bakes the new link."""
        jar = tmp_path / "neoforge.jar"
        fake_class = _make_registry_class()
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
            z.writestr("net/neoforged/neoforge/network/registration/NetworkRegistry.class", fake_class)
            z.writestr("net/neoforged/neoforge/client/network/registration/ClientNetworkRegistry.class", _fake_class_bytes())

        monkeypatch.setattr(jmp, "CWD", tmp_path.parent)
        monkeypatch.setattr(jmp, "_find_universal_jars", lambda loader: [jar])
        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="old.example.com"))

        assert jmp.patch_loader_messages("neoforge") is True

        # Hostname changed since the jar was patched -> re-patch must re-bake the link.
        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="new.example.com"))
        assert jmp.patch_loader_messages("neoforge") is True

        with zipfile.ZipFile(jar) as z:
            data = z.read("net/neoforged/neoforge/network/registration/NetworkRegistry.class")
        assert b"https://new.example.com/dl/mods.zip" in data
        assert b"https://old.example.com/dl/mods.zip" not in data
        assert jmp.loader_is_patched("neoforge") is True

    def test_no_jars_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(jmp, "_find_universal_jars", lambda loader: [])
        assert jmp.patch_loader_messages("neoforge") is False

    def test_signed_jar_strips_signatures(self, tmp_path, monkeypatch):
        """Patching a signed jar drops .SF/.RSA files and sanitizes the manifest."""
        jar = tmp_path / "signed.jar"
        fake_class = _make_registry_class()
        manifest = (
            "Manifest-Version: 1.0\r\n"
            "Created-By: 1.8.0 (Oracle Corporation)\r\n"
            "\r\n"
            "Name: net/neoforged/neoforge/network/registration/NetworkRegistry.class\r\n"
            "SHA-256-Digest: abc123\r\n"
            "\r\n"
        )
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", manifest)
            z.writestr("META-INF/NEORUNNER.SF", "Signature-Version: 1.0\r\n")
            z.writestr("META-INF/NEORUNNER.RSA", b"\x30\x82fake-signature")
            z.writestr("net/neoforged/neoforge/network/registration/NetworkRegistry.class", fake_class)
            z.writestr("net/neoforged/neoforge/client/network/registration/ClientNetworkRegistry.class", _fake_class_bytes())

        monkeypatch.setattr(jmp, "CWD", tmp_path.parent)
        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="mc.w8.mom"))
        monkeypatch.setattr(jmp, "_find_universal_jars", lambda loader: [jar])

        assert jmp.has_jar_signatures(zipfile.ZipFile(jar).namelist()) is True
        assert jmp.patch_loader_messages("neoforge") is True

        with zipfile.ZipFile(jar) as z:
            names = z.namelist()
            data = z.read("net/neoforged/neoforge/network/registration/NetworkRegistry.class")
            manifest_out = z.read("META-INF/MANIFEST.MF")
        assert b"Download the modpack" in data
        assert "META-INF/NEORUNNER.SF" not in names
        assert "META-INF/NEORUNNER.RSA" not in names
        # Per-entry digest section stripped, main section kept
        assert b"SHA-256-Digest: abc123" not in manifest_out
        assert b"Manifest-Version: 1.0" in manifest_out


class TestClickableInjection:
    LINK = "https://w8.mom/dl/mods.zip"

    def test_inject_rewrites_call_site(self):
        data = _make_handshake_class()
        out = jmp._inject_clickable(data, self.LINK)
        assert out is not None
        # Text-only message + separate link constant + helper reference baked in.
        assert b"Your client does not match the server's mods. Download the modpack: " in out
        assert self.LINK.encode() in out
        assert b"textWithLink" in out
        assert b"multiplayer.disconnect.incompatible" not in out
        # Result is still a structurally valid class file.
        entries, _ = jmp._parse_cp_entries(out)
        assert len(entries) == 10  # 2 original + 8 appended

    def test_inject_returns_none_when_block_absent(self):
        data = _fake_class_bytes()  # has the key constant but no beginLogin block
        assert jmp._inject_clickable(data, self.LINK) is None

    def test_embedded_helper_class_is_valid(self):
        from neorunner_pkg._clickable_message import clickable_message_class

        data = clickable_message_class()
        assert data[:4] == b"\xca\xfe\xba\xbe"
        major = struct.unpack(">H", data[6:8])[0]
        assert major <= 65  # Java 21 or older so it loads everywhere NeoForge runs
        assert b"textWithLink" in data
        assert b"open_url" in data or b"OpenUrl" in data

    def test_registry_inject_rewrites_call_site(self):
        data = _make_registry_class()
        out = jmp._inject_clickable_registry(data, self.LINK)
        assert out is not None
        # Text-only message + separate link constant + helper reference baked in.
        assert b"Your client does not match the server's mods. Download the modpack: " in out
        assert self.LINK.encode() in out
        assert b"textWithLink" in out
        assert b"multiplayer.disconnect.incompatible" not in out
        entries, _ = jmp._parse_cp_entries(out)
        assert len(entries) == 16  # 8 original + 8 appended

    def test_registry_inject_returns_none_when_absent(self):
        assert jmp._inject_clickable_registry(_fake_class_bytes(), self.LINK) is None

    def test_patch_jar_injects_registry_clickable(self, tmp_path, monkeypatch):
        """Patching a universal jar rewrites NetworkRegistry + injects its own helper."""
        jar = tmp_path / "neoforge-26.1.2.87-universal.jar"
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
            z.writestr("net/neoforged/neoforge/network/registration/NetworkRegistry.class", _make_registry_class())

        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="mc.w8.mom"))
        monkeypatch.setattr(jmp, "_download_link", lambda cfg: self.LINK)

        assert jmp._patch_jar(jar, "neoforge") is True
        assert jmp._jar_registry_clickable(jar) is True
        with zipfile.ZipFile(jar) as z:
            names = z.namelist()
            # The universal jar hosts its own helper under a distinct package
            # (no cross-module reference, no split package).
            assert "neorunner_neoforge/ClickableMessage.class" in names
            assert "neorunner_client/ClickableMessage.class" not in names
            data = z.read("net/neoforged/neoforge/network/registration/NetworkRegistry.class")
        assert b"textWithLink" in data
        assert b"neorunner_neoforge/ClickableMessage" in data
        # Idempotent: second patch reports no change.
        assert jmp._patch_jar(jar, "neoforge") is False

    def test_patch_jar_injects_clickable(self, tmp_path, monkeypatch):
        """Patching a server-patched jar injects the helper and rewrites the call."""
        jar = tmp_path / "minecraft-server-patched-26.1.2.87.jar"
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
            z.writestr("net/minecraft/server/network/ServerHandshakePacketListenerImpl.class", _make_handshake_class())

        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="mc.w8.mom"))
        monkeypatch.setattr(jmp, "_download_link", lambda cfg: self.LINK)

        assert jmp._patch_jar(jar, "neoforge") is True
        assert jmp._jar_is_clickable(jar) is True
        with zipfile.ZipFile(jar) as z:
            names = z.namelist()
            assert "neorunner_client/ClickableMessage.class" in names
            data = z.read("net/minecraft/server/network/ServerHandshakePacketListenerImpl.class")
        assert b"textWithLink" in data

        # Idempotent: a second patch reports no change.
        assert jmp._patch_jar(jar, "neoforge") is False

    def test_upgrade_from_string_only_patch(self, tmp_path, monkeypatch):
        """A jar string-patched before the clickable feature is upgraded in place."""
        jar = tmp_path / "minecraft-server-patched-26.1.2.87.jar"
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
            z.writestr("net/minecraft/server/network/ServerHandshakePacketListenerImpl.class", _make_handshake_class())

        monkeypatch.setattr(jmp, "load_cfg", lambda: ServerConfig(hostname="mc.w8.mom"))
        monkeypatch.setattr(jmp, "_download_link", lambda cfg: self.LINK)

        # First: simulate the old string-only patch (no clickable helper).
        # The real patcher backs up the pristine jar before its first patch.
        backup = jar.with_suffix(".jar.orig")
        shutil.copy2(jar, backup)
        old_mapping = dict(jmp._loader_byte_replacements("neoforge", self.LINK))
        import tempfile
        from pathlib import Path

        with zipfile.ZipFile(jar) as zin:
            names = zin.namelist()
            with tempfile.TemporaryDirectory() as td:
                t = Path(td)
                for n in names:
                    if not n.endswith(".class"):
                        continue
                    d = zin.read(n)
                    if any(k in d for k in old_mapping):
                        p = jmp._parse_and_rebuild(d, old_mapping)
                        (t / n).parent.mkdir(parents=True, exist_ok=True)
                        (t / n).write_bytes(p)
                with zipfile.ZipFile(str(jar) + ".tmp", "w") as zo:
                    for n in names:
                        pp = t / n
                        zo.writestr(n, pp.read_bytes() if pp.is_file() else zin.read(n))
        os.replace(str(jar) + ".tmp", jar)

        assert jmp._jar_is_clickable(jar) is False
        assert jmp._baked_link(jar) == self.LINK

        # Now the clickable patch must restore from backup and upgrade.
        assert jmp._patch_jar(jar, "neoforge") is True
        assert jmp._jar_is_clickable(jar) is True

    def test_jar_is_clickable_requires_surgery(self, tmp_path):
        jar = tmp_path / "partial.jar"
        from neorunner_pkg._clickable_message import clickable_message_class

        # Helper present but the handshake class still uses the plain string ->
        # must not be reported as clickable.
        with zipfile.ZipFile(jar, "w") as z:
            z.writestr("neorunner_client/ClickableMessage.class", clickable_message_class())
            z.writestr("net/minecraft/server/network/ServerHandshakePacketListenerImpl.class", _make_handshake_class())
        assert jmp._jar_is_clickable(jar) is False


class TestFindUniversalJars:
    def test_neoforge_includes_server_patched(self, tmp_path, monkeypatch):
        """NeoForge jar discovery must also return the minecraft-server-patched jar,
        since that is where the vanilla incompatible-client disconnect is sent from."""
        cwd = tmp_path / "home"
        univ = cwd / "libraries/net/neoforged/neoforge/26.1.2.87/neoforge-26.1.2.87-universal.jar"
        patched = cwd / "libraries/net/neoforged/minecraft-server-patched/26.1.2.87/minecraft-server-patched-26.1.2.87.jar"
        univ.parent.mkdir(parents=True)
        patched.parent.mkdir(parents=True)
        univ.write_bytes(b"")
        patched.write_bytes(b"")

        monkeypatch.setattr(jmp, "CWD", cwd)
        jars = jmp._find_universal_jars("neoforge")
        names = [j.name for j in jars]
        assert "neoforge-26.1.2.87-universal.jar" in names
        assert "minecraft-server-patched-26.1.2.87.jar" in names


class TestStripJarSignatures:
    def test_is_signature_file(self):
        assert jmp._is_signature_file("META-INF/FOO.SF")
        assert jmp._is_signature_file("META-INF/FOO.RSA")
        assert jmp._is_signature_file("META-INF/FOO.DSA")
        assert jmp._is_signature_file("META-INF/FOO.EC")
        assert jmp._is_signature_file("META-INF/SIG-FOO")
        assert not jmp._is_signature_file("META-INF/MANIFEST.MF")
        assert not jmp._is_signature_file("net/example/Foo.class")

    def test_strip_filters_and_sanitizes(self):
        entries = [
            "META-INF/MANIFEST.MF",
            "META-INF/FOO.SF",
            "META-INF/FOO.RSA",
            "net/example/Foo.class",
        ]
        manifest = b"Manifest-Version: 1.0\r\n\r\nName: net/example/Foo.class\r\nSHA-256-Digest: xyz\r\n"
        filtered, clean = jmp.strip_jar_signatures(entries, manifest)
        assert filtered == ["META-INF/MANIFEST.MF", "net/example/Foo.class"]
        assert clean == b"Manifest-Version: 1.0\r\n\r\n"
        assert b"SHA-256-Digest" not in clean

    def test_strip_no_manifest(self):
        filtered, clean = jmp.strip_jar_signatures(["net/example/Foo.class"], None)
        assert filtered == ["net/example/Foo.class"]
        assert clean is None
