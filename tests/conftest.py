"""Test fixtures for neorunner tests."""

import os
import sys

# Add the parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This allows relative imports to work
import neorunner_pkg

sys.modules['neorunner_pkg'] = neorunner_pkg

import pytest


@pytest.fixture(autouse=True)
def _isolate_users_store(request, tmp_path, monkeypatch):
    """Point the admin user store at a temp file seeded with the bootstrap
    credentials (mc:123) so auth tests never touch the real credential file.

    test_users.py manages its own store, so this fixture skips there.
    """
    if request.node.fspath.basename == "test_users.py":
        yield
        return

    from neorunner_pkg import users

    store = tmp_path / ".neorunner-users.json"
    monkeypatch.setattr(users, "USERS_FILE", store)
    users.add_user("mc", "123")
    yield
