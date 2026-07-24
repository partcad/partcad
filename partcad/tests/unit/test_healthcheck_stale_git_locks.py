#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""The StaleGitLocks healthcheck removes leftover git cache lock files that no
process holds, and never touches a lock a process still holds."""

import os

import pytest
from filelock import FileLock

from partcad.user_config import user_config
from partcad.healthcheck.stale_git_locks import StaleGitLocksCheck


@pytest.fixture
def git_cache(tmp_path, monkeypatch):
    """Point the healthcheck at a temporary internal state dir with a git/ dir."""
    git_dir = tmp_path / "git"
    git_dir.mkdir()
    monkeypatch.setattr(user_config, "internal_state_dir", str(tmp_path))
    return git_dir


def test_not_applicable_without_git_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(user_config, "internal_state_dir", str(tmp_path))
    assert StaleGitLocksCheck().is_applicable() is False


def test_stale_lock_is_reported_and_removed(git_cache):
    stale = git_cache / "deadbeef.lock"
    stale.write_text("")

    check = StaleGitLocksCheck()
    assert check.is_applicable() is True

    report = check.test()
    assert any("deadbeef.lock" in finding for finding in report.findings)

    assert check.fix() is True
    assert not stale.exists()


def test_held_lock_is_left_untouched(git_cache):
    held_path = git_cache / "held.lock"
    held = FileLock(str(held_path))
    held.acquire()
    try:
        check = StaleGitLocksCheck()
        report = check.test()
        # A lock a process still holds is not reported as stale...
        assert not any("held.lock" in finding for finding in report.findings)
        # ...and a fix pass leaves it in place.
        check.fix()
        assert held_path.exists()
    finally:
        held.release()


def test_no_locks_is_a_clean_pass(git_cache):
    report = StaleGitLocksCheck().test()
    assert report.findings == []
