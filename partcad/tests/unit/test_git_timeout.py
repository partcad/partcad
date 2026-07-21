#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
import re

from partcad.project_factory_git import (
    _apply_git_timeout,
    _make_git_non_interactive,
    git_error_patterns,
)
from partcad.user_config import UserConfig

STALL_ABORT = (
    "fatal: unable to access 'https://github.com/partcad/partcad.git/': "
    "Operation too slow. Less than 1000 bytes/sec transferred the last 180 seconds"
)


def test_git_clone_timeout_defaults_to_three_minutes():
    assert UserConfig().git_clone_timeout == 180


def test_git_clone_timeout_reads_the_environment(monkeypatch):
    monkeypatch.setenv("PC_GIT_CLONE_TIMEOUT", "45")
    assert UserConfig().git_clone_timeout == 45


def test_git_clone_timeout_rejects_nonsense(monkeypatch):
    """A zero or negative value must not silently disable the bound."""
    monkeypatch.setenv("PC_GIT_CLONE_TIMEOUT", "0")
    assert UserConfig().git_clone_timeout == 180


def test_apply_git_timeout_sets_the_transfer_bound(monkeypatch):
    monkeypatch.delenv("GIT_HTTP_LOW_SPEED_LIMIT", raising=False)
    monkeypatch.delenv("GIT_HTTP_LOW_SPEED_TIME", raising=False)

    _apply_git_timeout(90)

    # git aborts a transfer that stays under the limit for this long. This is
    # used instead of GitPython's kill_after_timeout, which has no effect
    # because clone, fetch and pull all run with as_process=True.
    assert os.environ["GIT_HTTP_LOW_SPEED_TIME"] == "90"
    assert int(os.environ["GIT_HTTP_LOW_SPEED_LIMIT"]) > 0


def test_apply_git_timeout_bounds_ssh_too(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)

    _apply_git_timeout(30)

    ssh = os.environ["GIT_SSH_COMMAND"]
    assert "BatchMode=yes" in ssh
    assert "ConnectTimeout=30" in ssh


def test_apply_git_timeout_keeps_an_explicit_ssh_command(monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /my/key")

    _apply_git_timeout(30)

    assert os.environ["GIT_SSH_COMMAND"] == "ssh -i /my/key"


def test_git_is_never_interactive(monkeypatch):
    """git must fail rather than wait on a credential prompt nobody answers."""
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)

    _make_git_non_interactive()

    assert os.environ["GIT_TERMINAL_PROMPT"] == "0"
    if os.name != "nt":
        assert os.environ["GIT_ASKPASS"] == "/bin/true"


def test_deliberate_askpass_is_preserved(monkeypatch):
    """Someone reaching private repos keeps their helper."""
    monkeypatch.setenv("GIT_ASKPASS", "/usr/local/bin/my-helper")

    _make_git_non_interactive()

    assert os.environ["GIT_ASKPASS"] == "/usr/local/bin/my-helper"
    # ... and still cannot fall back to an interactive prompt
    assert os.environ["GIT_TERMINAL_PROMPT"] == "0"


def test_stall_abort_is_retryable():
    """The timeout must produce an error the existing retry loop acts on."""
    assert any(re.search(p, STALL_ABORT) for p in git_error_patterns)


def test_retry_patterns_do_not_swallow_real_failures():
    for message in (
        "fatal: repository 'https://github.com/partcad/nope.git/' not found",
        "fatal: Authentication failed for 'https://github.com/partcad/private.git/'",
    ):
        assert not any(re.search(p, message) for p in git_error_patterns), message
