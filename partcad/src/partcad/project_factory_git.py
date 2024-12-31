#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

from git import Repo, exc
import hashlib
import re
import os
import time
import pathlib
import threading
import time

from . import project_factory as pf
from . import logging as pc_logging
from .user_config import user_config

global_cache_lock = threading.Lock()
cache_locks = {}

git_error_patterns = [
    # Network issue (RPC failed)
    r"error: RPC failed; curl \d+ .* stream \d+ was not closed cleanly: .* \(err \d+\)",
    # Host resolution problem
    r"fatal: unable to access '(https?://github.com/|git@github.com:)[a-zA-Z0-9./_-]+': Could not resolve host: .+",
    # Partial data transfer issue
    r"error: \d+ bytes of body are still expected",
    # Timeout issue
    r"fatal: unable to access '(https?://github.com/|git@github.com:)[a-zA-Z0-9./_-]+': Operation timed out after \d+ milliseconds with \d+ out of \d+ bytes received",
    # SSL/TLS handshake failure
    r"fatal: unable to access 'https?://github.com/[a-zA-Z0-9./_-]+': SSL certificate problem: .+",
    # Broken pipe during data transfer
    r"error: RPC failed; curl \d+ .*Send failure: Broken pipe",
    # Incomplete negotiation during fetch
    r"error: remote did not send all necessary objects",
    # Proxy-related failure
    r"fatal: unable to access 'https?://github.com/[a-zA-Z0-9./_-]+': Received HTTP code \d+ from proxy after CONNECT",
    # Unexpected EOF
    r"fetch-pack: unexpected disconnect while reading sideband packet",

    # Invalid index-pack output
    r"fatal: early EOF",
    r"fatal: fetch-pack: invalid index-pack output",
]


def get_cache_lock(hash):
    global global_cache_lock
    global_cache_lock.acquire()
    if hash not in cache_locks:
        cache_locks[hash] = threading.Lock()
    lock = cache_locks[hash]
    global_cache_lock.release()
    return lock


class GitImportConfiguration:
    def __init__(self):
        self.import_config_url = self.config_obj.get("url")
        self.import_revision = self.config_obj.get("revision")
        self.import_rel_path = self.config_obj.get("relPath")


class ProjectFactoryGit(pf.ProjectFactory, GitImportConfiguration):
    def __init__(self, ctx, parent, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        GitImportConfiguration.__init__(self)

        self.path = self._clone_or_update_repo(self.import_config_url)

        # Complement the config object here if necessary
        self._create(config)

        # TODO(clairbee): actually fill in the self.project object here

        self._save()

    def _clone_or_update_repo(self, repo_url, cache_dir=None):
        """
        Clones a Git repository to a local directory and keeps it up-to-date.

        Args:
          repo_url: URL of the Git repository to clone.
          cache_dir: Directory to store the cached copies of repositories (defaults to ".cache").

        Returns:
          Local path to the cloned repository.
        """

        if cache_dir is None:
            cache_dir = os.path.join(user_config.internal_state_dir, "git")

        # Generate a unique identifier for the repository based on its URL.
        repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()
        if self.import_revision is not None:
            # Append the revision to the hash instead of using it as an input
            # to the hash function. This way we can navigate in the cache
            # a lot easier when there are multiple revisions of the same repo.
            display_rev = self.import_revision
            display_rev = display_rev.replace("/", "-slash-")
            if os.name == "nt":
                # On Windows, we need to replace backslashes as well.
                display_rev = display_rev.replace(os.path.sep, "-sep-")
            repo_hash += "-" + display_rev
        cache_path = os.path.join(cache_dir, repo_hash)
        cache_lock = get_cache_lock(repo_hash)

        guard_path = os.path.join(cache_path, ".partcad.git.cloned")

        with cache_lock:
            attempt = 0
            max_retries = user_config.git_retry_config.get("max", 1)
            patience = user_config.git_retry_config.get("patience", 1)
            while attempt <= max_retries:
                # Check if the repository is already cached.
                if os.path.exists(cache_path):
                    # Update the repository if it is already cached.
                    try:
                        before = None
                        now = time.time()

                        # Try to open the existing repository and update it.
                        if self.import_revision is None:
                            # Import the default branch
                            if user_config.force_update or (now - os.path.getmtime(guard_path) > 24 * 3600):
                                repo = Repo(cache_path)
                                origin = repo.remote("origin")
                                before = repo.active_branch.commit

                                # If there is more than 1 remote branch, we have to
                                # explicitly specify the branch to pull.
                                remote_head = origin.refs.HEAD
                                branch_name = remote_head.reference.name
                                short_branch_name = branch_name[branch_name.find("/") + 1 :]
                                pc_logging.debug("Refreshing the GIT branch: %s" % short_branch_name)
                                origin.pull(short_branch_name)
                                os.utime(guard_path, (now, now))
                        else:
                            # Import a specific revision
                            if user_config.force_update:
                                # Ensure "before" doesn't match the desired revision
                                before = ""
                            else:
                                # Read the revision name from the guard file
                                with open(guard_path, "r") as f:
                                    before = f.read()

                            if before != self.import_revision or (now - os.path.getmtime(guard_path) > 24 * 3600):
                                repo = Repo(cache_path)
                                before = repo.active_branch.commit
                                origin = repo.remote("origin")
                                # Need to check for updates
                                origin.fetch()
                                repo.git.checkout(self.import_revision, force=True)
                                origin.pull(force=True, rebase=True)
                                os.utime(guard_path, (now, now))
                            else:
                                # No update was performed
                                before = None

                        if not before is None:
                            # Update was performed
                            after = repo.active_branch.commit
                            if before != after:
                                pc_logging.info("Updated the GIT repo: %s" % self.import_config_url)
                            if before != after or user_config.force_update:
                                with open(guard_path, "w") as f:
                                    if self.import_revision is None:
                                        f.write(str(after))
                                    else:
                                        f.write(self.import_revision)
                        break
                    except exc.GitCommandError as e:
                        # Check if the error message matches any of the patterns
                        if any(re.search(pattern, str(e)) for pattern in git_error_patterns) and attempt < max_retries:
                            pc_logging.warning(
                                "Failed to update repo. Retrying (%d/%d) in %d secs...",
                                attempt + 1,
                                max_retries,
                                patience,
                            )
                            time.sleep(patience)
                        else:
                            pc_logging.error("Failed to update repo after %s retries" % attempt)
                    except Exception as e:
                        pc_logging.error("Failed to update repo\n%s" % e)
                    # Fall back to using the previous copy
                else:
                    # Clone the repository if it's not cached yet.
                    try:
                        pc_logging.info("Cloning the GIT repo: %s" % self.import_config_url)
                        repo = Repo.clone_from(repo_url, cache_path)
                        if not self.import_revision is None:
                            repo.git.checkout(self.import_revision, force=True)
                            after = self.import_revision
                        else:
                            after = repo.active_branch.commit

                        with open(guard_path, "w") as f:
                            f.write(str(after))
                        break
                    except exc.GitCommandError as e:
                        # Check if the error message matches any of the patterns
                        if any(re.search(pattern, str(e)) for pattern in git_error_patterns) and attempt < max_retries:
                            pc_logging.warning(
                                "Failed to clone repo. Retrying (%d/%d) in %d secs...",
                                attempt + 1,
                                max_retries,
                                patience,
                            )
                            time.sleep(patience)
                        else:
                            pc_logging.error("Failed to clone repo after %d retries", attempt)
                            raise RuntimeError("Failed to clone repo: %s" % e)
                    except Exception as e:
                        raise RuntimeError("Failed to clone repo: %s" % e)
                attempt += 1
        if not self.import_rel_path is None:
            cache_path = os.path.join(cache_path, self.import_rel_path)

        return cache_path
