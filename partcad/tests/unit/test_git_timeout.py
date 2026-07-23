#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import re

import pygit2
import pytest
from pygit2.enums import CredentialType

from partcad.project_factory_git import (
    GitCallbacks,
    _apply_git_timeout,
    git_error_patterns,
    is_retryable,
)
from partcad.user_config import UserConfig

# What libgit2 says when server_timeout expires on a transfer that stopped
# making progress. Verified against a server that accepts the connection and
# then never answers.
STALL_ABORT = "could not read from socket: timed out"
CONNECT_ABORT = "failed to connect to 10.255.255.1: Operation timed out"


def test_git_clone_timeout_defaults_to_three_minutes():
    assert UserConfig().git_clone_timeout == 180


def test_git_clone_timeout_reads_the_environment(monkeypatch):
    monkeypatch.setenv("PC_GIT_CLONE_TIMEOUT", "45")
    assert UserConfig().git_clone_timeout == 45


def test_git_clone_timeout_rejects_nonsense(monkeypatch):
    """A zero or negative value must not silently disable the bound."""
    monkeypatch.setenv("PC_GIT_CLONE_TIMEOUT", "0")
    assert UserConfig().git_clone_timeout == 180


def test_apply_git_timeout_bounds_the_transfer():
    # libgit2 gives up on a read that takes longer than this, which is what
    # bounds a remote that accepts the connection and then stops answering.
    _apply_git_timeout(90)

    assert pygit2.settings.server_timeout == 90 * 1000
    assert pygit2.settings.server_connect_timeout > 0


def test_apply_git_timeout_bounds_reaching_the_remote_too():
    _apply_git_timeout(30)

    assert pygit2.settings.server_connect_timeout == 30 * 1000


def test_a_long_timeout_still_connects_promptly():
    """Waiting an hour to find out a host is unreachable helps nobody."""
    _apply_git_timeout(3600)

    assert pygit2.settings.server_connect_timeout <= 60 * 1000
    assert pygit2.settings.server_timeout == 3600 * 1000


def test_git_is_never_interactive():
    """git must fail rather than wait on a credential prompt nobody answers."""
    with pytest.raises(pygit2.GitError):
        GitCallbacks().credentials(
            "https://github.com/partcad/private.git",
            None,
            CredentialType.USERPASS_PLAINTEXT,
        )


def test_ssh_remotes_are_reached_through_the_agent():
    """What the git command line did, and what imports over ssh rely on."""
    callbacks = GitCallbacks()

    assert isinstance(
        callbacks.credentials("git@github.com:partcad/partcad.git", "git", CredentialType.USERNAME),
        pygit2.Username,
    )
    assert isinstance(
        callbacks.credentials("git@github.com:partcad/partcad.git", "git", CredentialType.SSH_KEY),
        pygit2.KeypairFromAgent,
    )


def test_the_default_ssh_key_files_are_offered_too(tmp_path, monkeypatch):
    """ssh reads them without an agent, so a key on disk has to work here."""
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_ed25519").write_text("private")
    (ssh_dir / "id_ed25519.pub").write_text("public")
    monkeypatch.setenv("HOME", str(tmp_path))

    callbacks = GitCallbacks()
    offered = [
        callbacks.credentials("git@github.com:partcad/partcad.git", "git", CredentialType.SSH_KEY),
        callbacks.credentials("git@github.com:partcad/partcad.git", "git", CredentialType.SSH_KEY),
    ]

    assert isinstance(offered[0], pygit2.KeypairFromAgent)
    assert isinstance(offered[1], pygit2.Keypair)


def test_a_rejected_key_is_not_offered_forever(tmp_path, monkeypatch):
    """Being asked again means the key was refused, so stop rather than loop."""
    monkeypatch.setenv("HOME", str(tmp_path))  # nothing on disk to offer
    callbacks = GitCallbacks()
    callbacks.credentials("git@github.com:partcad/partcad.git", "git", CredentialType.SSH_KEY)

    with pytest.raises(pygit2.GitError):
        callbacks.credentials("git@github.com:partcad/partcad.git", "git", CredentialType.SSH_KEY)


@pytest.mark.parametrize("message", [STALL_ABORT, CONNECT_ABORT])
def test_timeouts_are_retryable(message):
    """The timeout must produce an error the existing retry loop acts on."""
    assert is_retryable(pygit2.GitError(message))


@pytest.mark.parametrize(
    "message",
    [
        "failed to resolve address for github.com: Name or service not known",
        "failed to connect to github.com: Connection refused",
        "unexpected disconnect while reading sideband packet",
        "early EOF",
        "unexpected http status code: 503",
        "SSL error: syscall failure",
    ],
)
def test_transient_network_failures_are_retryable(message):
    assert is_retryable(pygit2.GitError(message))


@pytest.mark.parametrize(
    "message",
    [
        "unexpected http status code: 404",
        "remote authentication required but no callback set",
        "Authentication is required for 'https://github.com/partcad/private.git' and no credentials are available",
        "cannot fetch a specific object from the remote repository",
        "reference 'refs/remotes/origin/nosuch' not found",
    ],
)
def test_retry_patterns_do_not_swallow_real_failures(message):
    assert not is_retryable(pygit2.GitError(message)), message


def test_every_pattern_is_a_usable_regex():
    for pattern in git_error_patterns:
        re.compile(pattern)
