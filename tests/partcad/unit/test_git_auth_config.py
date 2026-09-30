#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Credentials for private Git remotes come from the user configuration.

PartCAD never prompts: this callback can be running inside the background daemon
or a CI job, where a prompt is a hang rather than a question. So credentials are
configured upfront under ``git.auth``, and a remote that needs one PartCAD does
not have fails with a message naming the setting to add.
"""

import pygit2
import pytest
from pygit2.enums import CredentialType

from partcad.project_factory_git import GitCallbacks


class FakeSection:
    """Stands in for a user_config BaseConfig section."""

    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class FakeUserConfig:
    def __init__(self, auth=None):
        self.git_auth = FakeSection(auth or {})


def test_https_credentials_come_from_the_configured_host_entry():
    callbacks = GitCallbacks(FakeUserConfig({"github.com": {"username": "alice", "password": "ghp_token"}}))

    credential = callbacks.credentials("https://github.com/owner/repo.git", None, CredentialType.USERPASS_PLAINTEXT)

    assert isinstance(credential, pygit2.UserPass)
    assert credential.credential_tuple[:2] == ("alice", "ghp_token")


def test_a_default_entry_answers_for_a_host_that_has_none():
    callbacks = GitCallbacks(FakeUserConfig({"default": {"username": "bob", "password": "token"}}))

    credential = callbacks.credentials(
        "https://gitlab.example.com/owner/repo.git", None, CredentialType.USERPASS_PLAINTEXT
    )

    assert credential.credential_tuple[:2] == ("bob", "token")


def test_a_host_entry_outranks_the_default():
    callbacks = GitCallbacks(
        FakeUserConfig(
            {
                "default": {"username": "bob", "password": "shared"},
                "github.com": {"username": "alice", "password": "specific"},
            }
        )
    )

    credential = callbacks.credentials("https://github.com/owner/repo.git", None, CredentialType.USERPASS_PLAINTEXT)

    assert credential.credential_tuple[:2] == ("alice", "specific")


def test_an_scp_style_ssh_url_resolves_its_host():
    """ "git@github.com:owner/repo" carries no scheme for urlparse to read."""
    callbacks = GitCallbacks(FakeUserConfig({"github.com": {"sshKey": "/keys/id_work"}}))

    assert callbacks._auth_entry("git@github.com:owner/repo.git") == {"sshKey": "/keys/id_work"}


def test_a_configured_ssh_key_is_offered_before_the_ambient_ones():
    """The configured key is the deliberate answer, and may carry a passphrase.

    The agent and the default ~/.ssh keys stay as fallbacks, so a host with no
    entry keeps working exactly as before.
    """
    callbacks = GitCallbacks(FakeUserConfig({"github.com": {"sshKey": "/keys/id_work", "sshKeyPassphrase": "secret"}}))

    credential = callbacks.credentials("git@github.com:owner/repo.git", None, CredentialType.SSH_KEY)

    assert isinstance(credential, pygit2.Keypair)
    username, _public, private, passphrase = credential.credential_tuple
    assert (username, private, passphrase) == ("git", "/keys/id_work", "secret")


def test_https_without_configured_credentials_names_the_setting_to_add():
    """The failure has to be actionable: there is nobody to ask interactively."""
    callbacks = GitCallbacks(FakeUserConfig())

    with pytest.raises(pygit2.GitError) as excinfo:
        callbacks.credentials("https://github.com/owner/private.git", None, CredentialType.USERPASS_PLAINTEXT)

    message = str(excinfo.value)
    assert "git.auth.github.com" in message
    assert "never prompts" in message


def test_ssh_still_falls_back_to_the_agent_when_nothing_is_configured():
    """An unconfigured ssh remote behaves as it did before git.auth existed."""
    callbacks = GitCallbacks(FakeUserConfig())

    credential = callbacks.credentials("git@github.com:owner/repo.git", None, CredentialType.SSH_KEY)

    assert isinstance(credential, pygit2.KeypairFromAgent)
