#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""When a clone fails, PartCAD retries it once with the ambient git config
(the user's ~/.gitconfig and the system config) ignored, so a 'url.*.insteadOf'
rewrite there cannot break an otherwise anonymous clone. These tests drive that
fallback without touching the network by making the fake clone succeed only when
the ambient config search path has been cleared."""

import tempfile

import pytest
import pygit2
from pygit2 import GitError
from pygit2.enums import ConfigLevel
from unittest.mock import MagicMock, patch

import partcad as pc
from partcad.user_config import UserConfig

repo_url = "https://github.com/partcad/partcad"
test_config_import_git = {
    "name": "//part_step",
    "type": "git",
    "url": repo_url,
    "relPath": "examples/produce_part_step",
}

# What GitCallbacks raises when an insteadOf-rewritten URL needs credentials
# that are not available. It is deliberately not a retryable error, so it drops
# straight to the ambient-config fallback.
auth_error = GitError("Authentication is required for 'ssh://git@github.com/partcad/partcad' and no credentials")


@pytest.fixture
def user_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = UserConfig()
        config.internal_state_dir = tmpdir
        config.set("git.clone.retry.max", 2)
        config.set("git.clone.retry.patience", 0.01)
        yield config


def _ambient_config_ignored() -> bool:
    """Whether the fallback has cleared the config search path for this call."""
    return pygit2.settings.search_path[ConfigLevel.GLOBAL] == ""


def test_clone_falls_back_to_ignoring_ambient_config(user_config, mocked_git_open):
    """A clone that fails while honoring the ambient config succeeds once it is
    ignored, and the search path is restored afterwards."""

    def side_effect(*args, **kwargs):
        side_effect.counter += 1
        if _ambient_config_ignored():
            return MagicMock()
        raise auth_error

    side_effect.counter = 0
    saved = pygit2.settings.search_path[ConfigLevel.GLOBAL]

    with (
        patch("partcad.project_factory_git._clone", side_effect=side_effect),
        mocked_git_open(),
    ):
        ctx = pc.Context(user_config=user_config)
        factory = pc.ProjectFactoryGit(ctx, None, test_config_import_git)
        assert factory is not None

    # Honored the ambient config first (and failed), then ignored it (and won).
    assert side_effect.counter >= 2
    # The process-wide search path is left exactly as it was found.
    assert pygit2.settings.search_path[ConfigLevel.GLOBAL] == saved


def test_search_path_restored_when_fallback_also_fails(user_config):
    """Even if ignoring the ambient config does not help, the search path is
    restored and the failure is reported as a clean RuntimeError."""

    def side_effect(*args, **kwargs):
        raise auth_error

    saved = pygit2.settings.search_path[ConfigLevel.GLOBAL]

    with (
        patch("partcad.project_factory_git._clone", side_effect=side_effect),
        pytest.raises(RuntimeError),
    ):
        ctx = pc.Context(user_config=user_config)
        pc.ProjectFactoryGit(ctx, None, test_config_import_git)

    assert pygit2.settings.search_path[ConfigLevel.GLOBAL] == saved


def test_successful_clone_never_touches_the_search_path(user_config, mocked_git_open):
    """The happy path honors the ambient config and never clears the search
    path, so a clone always sees the user's configuration when it works."""

    seen = []

    def side_effect(*args, **kwargs):
        seen.append(_ambient_config_ignored())
        return MagicMock()

    with (
        patch("partcad.project_factory_git._clone", side_effect=side_effect),
        mocked_git_open(),
    ):
        ctx = pc.Context(user_config=user_config)
        pc.ProjectFactoryGit(ctx, None, test_config_import_git)

    assert seen  # the clone ran
    assert not any(seen)  # and always honored the ambient config
