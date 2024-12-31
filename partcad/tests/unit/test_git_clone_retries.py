from git import Repo
import pytest
import partcad as pc
from git.exc import GitCommandError
from unittest.mock import MagicMock, mock_open, patch

repo_url = "https://github.com/partcad/partcad"
test_config_import_git = {
    "name": "/part_step",
    "type": "git",
    "url": "https://github.com/partcad/partcad",
    "revision": "devel",
    "relPath": "examples/produce_part_step",
}

# Simulate failure scenarios
fake_git_errors = [
    # Network issue (RPC failed)
    GitCommandError(
        """
          error: RPC failed; curl 56 HTTP/2 stream 2 was not closed cleanly: CANCEL (err 0)
          fatal: The remote end hung up unexpectedly
          fatal: early EOF
          fatal: index-pack failed
        """
    ),
    # Host resolution problem
    GitCommandError(
        f"""
          fatal: unable to access '{repo_url}': Could not resolve host: github.com
        """
    ),
    # Partial data transfer issue
    GitCommandError(
        """
          error: 123 bytes of body are still expected
          fatal: fetch-pack: expected to read 2048 bytes but got 2015
          error: unpack failed: partial content received
          error: failed to read data from remote repository
        """
    ),
    # Timeout issue
    GitCommandError(
        f"""
          fatal: unable to access '{repo_url}': Operation timed out after 30000 milliseconds with 0 out of 0 bytes received
          fatal: The operation timed out
        """
    ),
    # Broken pipe during data transfer
    GitCommandError(
        f"""
          error: RPC failed; curl 55 Send failure: Broken pipe
          fatal: The remote end hung up unexpectedly
          error: failed to push some refs to '{repo_url}'
          fatal: The remote end hung up unexpectedly, could not send data

        """
    ),
    # Incomplete negotiation during fetch
    GitCommandError(
        """
          error: remote did not send all necessary objects
          fatal: early EOF
          fatal: index-pack failed
          fatal: fetch-pack: unexpected EOF
          fatal: error: remote did not send all necessary objects
        """
    ),
    # Proxy-related failure
    GitCommandError(
        f"""
          fatal: unable to access '{repo_url}': Received HTTP code 407 from proxy after CONNECT
          fatal: unable to access '{repo_url}': Proxy authentication required
          fatal: unable to access '{repo_url}': Proxy error: 407 Proxy Authentication Required
        """
    ),
]

test_git_retry_config = {"max": 5, "patience": 0.1}

@pytest.mark.parametrize("git_error", fake_git_errors)
def test_project_import_git_clone_retry_failure(git_error: GitCommandError):
    def side_effect(*args, **kwargs):
        side_effect.counter += 1
        raise git_error
    side_effect.counter = 0

    ctx = pc.Context()
    factory = pc.ProjectFactoryGit(ctx, None, test_config_import_git)
    with patch("git.Repo.clone_from", side_effect=side_effect) as mock_clone_from, \
         patch.object(pc.user_config, "git_retry_config", test_git_retry_config), \
         patch("builtins.open", mock_open(read_data="")):
        with pytest.raises(RuntimeError):
            factory._clone_or_update_repo(repo_url, "")

    # The number of calls must be initial attempt plus 'max' retries
    assert mock_clone_from.call_count == test_git_retry_config["max"] + 1


def test_project_import_git_clone_retry_then_success():
    # initial attempt plus two retries
    fail_count = 3
    def side_effect(*args, **kwargs):
        side_effect.counter += 1
        if side_effect.counter <= fail_count:
            raise fake_git_errors[0]
        else:
            return MagicMock()
    side_effect.counter = 0

    ctx = pc.Context()
    factory = pc.ProjectFactoryGit(ctx, None, test_config_import_git)
    with patch("git.Repo.clone_from", side_effect=side_effect) as mock_clone_from, \
         patch.object(pc.user_config, "git_retry_config", test_git_retry_config), \
         patch("builtins.open", mock_open(read_data="")):
        factory._clone_or_update_repo(repo_url, "")

    # The call_count must be fail_count plus one(the last successful call)
    assert mock_clone_from.call_count == fail_count + 1
