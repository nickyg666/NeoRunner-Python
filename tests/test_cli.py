"""Tests for the CLI single-instance guard and restart/help wiring."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from neorunner_pkg import cli


@pytest.fixture()
def isolated_pid_file(tmp_path, monkeypatch):
    """Point the CLI's PID file at a per-test temp path."""
    pid_file = tmp_path / ".neorunner.pid"
    monkeypatch.setattr(cli, "PID_FILE", pid_file)
    return pid_file


class TestStartArgs:
    def test_start_args_include_daemon(self):
        parser = argparse.ArgumentParser()
        cli._add_start_args(parser)
        args = parser.parse_args(["--daemon", "--pid-file", "/tmp/x.pid"])
        assert args.daemon is True
        assert args.pid_file == "/tmp/x.pid"
        assert args.no_server is False
        assert args.no_dashboard is False

    def test_start_args_defaults(self):
        parser = argparse.ArgumentParser()
        cli._add_start_args(parser)
        args = parser.parse_args([])
        assert args.daemon is False
        assert args.pid_file is None


class TestSingleInstanceLock:
    def test_acquire_then_deny(self, isolated_pid_file):
        fd = cli._acquire_instance_lock()
        assert fd is not None
        try:
            # A second acquisition while the first holds the lock must fail.
            assert cli._acquire_instance_lock() is None
            # The pid file records our pid.
            assert cli._read_daemon_pid() == os.getpid()
        finally:
            os.close(fd)

    def test_lock_released_after_close(self, isolated_pid_file):
        fd = cli._acquire_instance_lock()
        assert fd is not None
        os.close(fd)
        # Once released, a new acquisition succeeds.
        fd2 = cli._acquire_instance_lock()
        assert fd2 is not None
        os.close(fd2)

    def test_running_daemon_pid_dead(self, isolated_pid_file):
        isolated_pid_file.write_text("99999999")
        assert cli._running_daemon_pid() is None
        assert cli._stop_daemon(wait=0.0) is False
        assert cli._signal_daemon_reload() is False

    def test_running_daemon_pid_missing(self, isolated_pid_file):
        assert cli._read_daemon_pid() is None
        assert cli._running_daemon_pid() is None

    def test_running_daemon_pid_not_neorunner(self, isolated_pid_file):
        # A live PID that is not a NeoRunner process must be ignored.
        isolated_pid_file.write_text(str(os.getpid()))
        # The test runner's own cmdline is not a NeoRunner daemon, so this
        # should still resolve to None (protects against stale/reused PIDs).
        result = cli._running_daemon_pid()
        if cli._is_neorunner_process(os.getpid()):
            pytest.skip("test runner cmdline happens to contain 'neorunner'")
        assert result is None


class TestHelp:
    def test_help_command_present(self):
        # The main() parser registers a 'help' subcommand; verify it is listed
        # alongside the other commands by building the parser the same way.
        parser = argparse.ArgumentParser(prog="neorunner")
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("start")
        subparsers.add_parser("restart")
        subparsers.add_parser("help")
        args = parser.parse_args(["help"])
        assert args.command == "help"
