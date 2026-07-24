import pytest
import tempfile
import partcad as pc
from pygit2 import GitError
from unittest.mock import MagicMock, mock_open, patch

from partcad.user_config import UserConfig

repo_url = "https://github.com/partcad/partcad"
test_config_import_git = {
    "name": "//part_step",
    "type": "git",
    "url": repo_url,
    "relPath": "examples/produce_part_step",
}

# Simulate failure scenarios, worded the way libgit2 words them
fake_git_errors = [
    # Host resolution problem
    GitError("failed to resolve address for github.com: Name or service not known"),
    # The remote could not be reached
    GitError("failed to connect to github.com: Connection refused"),
    # Timeout, either the remote's own or the one PartCAD imposes
    GitError("could not read from socket: timed out"),
    GitError(f"failed to connect to github.com: Operation timed out"),
    # Partial data transfer issue
    GitError("early EOF"),
    GitError("unexpected disconnect while reading sideband packet"),
    # Broken pipe during data transfer
    GitError("could not write to socket: Broken pipe"),
    # Incomplete negotiation during fetch
    GitError("remote did not send all necessary objects"),
    # The server, or a proxy in front of it, is temporarily unable to answer
    GitError("unexpected http status code: 503"),
    GitError("received HTTP code 407 from proxy after CONNECT"),
    # SSL/TLS handshake failure
    GitError("SSL error: unable to get local issuer certificate"),
]

test_git_retry_config = {"max": 5, "patience": 0.1}


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def user_config(temp_dir):
    config = UserConfig()
    config.internal_state_dir = temp_dir
    config.set("git.clone.retry.max", test_git_retry_config["max"])
    config.set("git.clone.retry.patience", test_git_retry_config["patience"])
    return config


@pytest.mark.parametrize("git_error", fake_git_errors)
def test_project_import_git_clone_retry_failure(git_error: GitError, user_config):
    def side_effect(*args, **kwargs):
        side_effect.counter += 1
        raise git_error

    side_effect.counter = 0

    with (
        patch("partcad.project_factory_git._clone", side_effect=side_effect) as mock_clone,
        pytest.raises(RuntimeError),
    ):

        ctx = pc.Context(user_config=user_config)
        factory = pc.ProjectFactoryGit(ctx, None, test_config_import_git)
        assert factory is not None

    # The number of calls must be initial attempt plus 'max' retries
    assert mock_clone.call_count == test_git_retry_config["max"] + 1


def test_project_import_git_clone_retry_then_success(user_config):
    fail_count = 3

    def side_effect(*args, **kwargs):
        side_effect.counter += 1
        if side_effect.counter <= fail_count:
            raise fake_git_errors[0]
        return MagicMock()

    side_effect.counter = 0

    with (
        patch("partcad.project_factory_git._clone", side_effect=side_effect) as mock_clone,
        patch("builtins.open", mock_open(read_data="")),
    ):

        ctx = pc.Context(user_config=user_config)
        factory = pc.ProjectFactoryGit(ctx, None, test_config_import_git)
        assert factory is not None

    # The call_count must be fail_count plus one(the last successful call)
    assert mock_clone.call_count == fail_count + 1


def test_a_permanent_failure_is_not_retried(user_config):
    """A repository that is gone stays gone; retrying only delays the report."""

    def side_effect(*args, **kwargs):
        side_effect.counter += 1
        raise GitError("unexpected http status code: 404")

    side_effect.counter = 0

    with (
        patch("partcad.project_factory_git._clone", side_effect=side_effect) as mock_clone,
        pytest.raises(RuntimeError),
    ):

        ctx = pc.Context(user_config=user_config)
        pc.ProjectFactoryGit(ctx, None, test_config_import_git)

    # The optimized clone, then the full clone it falls back to, and no retries
    assert mock_clone.call_count == 2
