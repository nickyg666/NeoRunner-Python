"""Tests for admin user credential management."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neorunner_pkg import users


class TestUsers:
    def test_add_and_verify(self, tmp_path, monkeypatch):
        monkeypatch.setattr(users, "USERS_FILE", tmp_path / ".neorunner-users.json")
        assert users.add_user("admin", "hunter2") is True
        assert users.verify_credentials("admin", "hunter2") is True
        assert users.verify_credentials("admin", "wrong") is False
        assert users.verify_credentials("nobody", "hunter2") is False

    def test_password_is_hashed_not_plaintext(self, tmp_path, monkeypatch):
        monkeypatch.setattr(users, "USERS_FILE", tmp_path / ".neorunner-users.json")
        users.add_user("admin", "secret-password")
        raw = (tmp_path / ".neorunner-users.json").read_text()
        assert "secret-password" not in raw

    def test_list_and_remove(self, tmp_path, monkeypatch):
        monkeypatch.setattr(users, "USERS_FILE", tmp_path / ".neorunner-users.json")
        users.add_user("alice", "pw1")
        users.add_user("bob", "pw2")
        assert users.list_users() == ["alice", "bob"]
        assert users.remove_user("alice") is True
        assert users.list_users() == ["bob"]
        assert users.remove_user("alice") is False

    def test_set_password(self, tmp_path, monkeypatch):
        monkeypatch.setattr(users, "USERS_FILE", tmp_path / ".neorunner-users.json")
        users.add_user("admin", "old")
        assert users.set_password("admin", "new") is True
        assert users.verify_credentials("admin", "new") is True
        assert users.verify_credentials("admin", "old") is False
        assert users.set_password("ghost", "x") is False

    def test_empty_store_has_no_users(self, tmp_path, monkeypatch):
        monkeypatch.setattr(users, "USERS_FILE", tmp_path / ".neorunner-users.json")
        assert users.has_users() is False
        assert users.list_users() == []
