"""User / admin credential management for NeoRunner.

Credentials are stored in ``.neorunner-users.json`` next to ``config.json``,
as PBKDF2-SHA256 hashes (salted, never plaintext). The dashboard's HTTP Basic
Auth checks against this store; the ``neorunner users`` CLI manages it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets

from .constants import CWD

USERS_FILE = CWD / ".neorunner-users.json"

_PBKDF2_ITERATIONS = 200_000


def _load_store() -> dict:
    if not USERS_FILE.exists():
        return {"users": {}}
    try:
        data = json.loads(USERS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"users": {}}
    if not isinstance(data.get("users"), dict):
        return {"users": {}}
    return data


def _save_store(data: dict) -> None:
    tmp = USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, USERS_FILE)
    try:
        os.chmod(USERS_FILE, 0o600)
    except OSError:
        pass


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return ``iterations$salt_hex$hash_hex`` for a password."""
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        iters, salt_hex, hash_hex = stored.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    try:
        iters_int = int(iters)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters_int)
    return hmac.compare_digest(dk, expected)


def verify_credentials(username: str, password: str) -> bool:
    """Return True if username/password match a stored user."""
    store = _load_store()
    stored = store["users"].get(username)
    if not stored:
        return False
    return _verify_password(password, stored)


def has_users() -> bool:
    return bool(_load_store()["users"])


def list_users() -> list[str]:
    return sorted(_load_store()["users"].keys())


def add_user(username: str, password: str) -> bool:
    """Add (or reset) a user's password. Returns False on invalid input."""
    username = (username or "").strip()
    if not username or not password:
        return False
    store = _load_store()
    store["users"][username] = _hash_password(password)
    _save_store(store)
    return True


def remove_user(username: str) -> bool:
    store = _load_store()
    if username not in store["users"]:
        return False
    del store["users"][username]
    _save_store(store)
    return True


def set_password(username: str, password: str) -> bool:
    """Set a password for an existing user; False if the user does not exist."""
    store = _load_store()
    if username not in store["users"]:
        return False
    store["users"][username] = _hash_password(password)
    _save_store(store)
    return True


__all__ = [
    "add_user",
    "has_users",
    "list_users",
    "remove_user",
    "set_password",
    "verify_credentials",
]
