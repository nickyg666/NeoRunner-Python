"""Test fixtures for neorunner tests."""

import pytest
import sys
import os

# Add the parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This allows relative imports to work
import neorunner_pkg
sys.modules['neorunner_pkg'] = neorunner_pkg


@pytest.fixture(autouse=True)
def _isolate_user_store(tmp_path, monkeypatch):
    """Point the credential store at an empty temp file for every test.

    The dashboard's Basic Auth falls back to bootstrap credentials
    (``mc``/``123``) only when no real users exist. Tests must not depend on
    whatever ``.neorunner-users.json`` happens to exist in the repo checkout,
    so isolate the store to an empty file so ``has_users()`` is deterministic.
    Tests that exercise the user store directly (``test_users.py``) monkeypatch
    ``USERS_FILE`` themselves, which overrides this.
    """
    from neorunner_pkg import users
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / ".neorunner-users.json")
    yield


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Point the config module's CWD at a temp dir so tests never read/write the
    live ``config.json``.

    Dashboard config-update routes call ``save_cfg`` (which writes the repo's
    ``config.json``) and description routes write ``server.properties``. Pointing
    ``config_mod.CWD`` at an empty temp dir keeps tests hermetic and prevents
    mutating the running server's settings.
    """
    from neorunner_pkg import config as config_mod
    monkeypatch.setattr(config_mod, "CWD", tmp_path)
    yield
