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
import shutil
import time
import threading

from . import project_factory as pf
from . import logging as pc_logging
from shlex import quote
from . import telemetry


def _make_git_non_interactive() -> None:
    """Stop git from ever blocking on a credential prompt.

    A repository that has been deleted, made private or renamed answers with an
    authentication challenge rather than an error. Left to itself git then waits
    on a prompt that nothing will ever answer, so the whole process hangs
    instead of failing. GitPython has no parameter for this, so the environment
    is set once here, when the git support is first imported.

    setdefault rather than plain assignment: anyone who has deliberately
    configured an askpass helper to reach private repositories keeps it, and
    they still get GIT_TERMINAL_PROMPT below to stop the interactive fallback.
    """
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    if os.name != "nt":
        # No portable equivalent of /bin/true on Windows. GIT_TERMINAL_PROMPT
        # alone already blocks the console prompt there.
        os.environ.setdefault("GIT_ASKPASS", "/bin/true")
        os.environ.setdefault("SSH_ASKPASS", "/bin/true")


def _apply_git_timeout(seconds: int) -> None:
    """Bound git network operations to 'seconds'.

    Note that GitPython's kill_after_timeout cannot be used for this. Repo's
    clone, fetch and pull all run the git command with as_process=True, and
    kill_after_timeout is documented to have no effect in that case, so passing
    it looks like protection while doing nothing at all. It is also unsupported
    on Windows regardless.

    git's own transfer abort is used instead: a transfer that stays below
    lowSpeedLimit bytes/s for lowSpeedTime seconds is terminated. curl enforces
    it inside git, so it works on every platform and applies to clone, fetch and
    pull alike. It bounds how long a transfer may make no progress, which is
    what actually needs bounding here; a large but healthy clone is still
    allowed to take as long as it needs.
    """
    os.environ["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"
    os.environ["GIT_HTTP_LOW_SPEED_TIME"] = str(seconds)
    # Bound the SSH side too, otherwise git+ssh remotes can still hang on a
    # connection that never completes.
    if "GIT_SSH_COMMAND" not in os.environ:
        os.environ["GIT_SSH_COMMAND"] = (
            "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
            f"-o ConnectTimeout={min(seconds, 60)} -o ServerAliveInterval=15"
        )


_make_git_non_interactive()

global_cache_lock = threading.Lock()
cache_locks = {}

git_error_patterns = [
    # Network issue (RPC failed)
    r"error: RPC failed; curl \d+ .* stream \d+ was not closed cleanly: .* \(err \d+\)",
    # Host resolution problem
    r"fatal: unable to access 'https?://github.com/[a-zA-Z0-9./_-]+': Could not resolve host: .+",
    r"fatal: Could not resolve host: .+",
    r"fatal: Could not read from remote repository.",
    # Partial data transfer issue
    r"error: \d+ bytes of body are still expected",
    # Timeout issue
    r"fatal: unable to access '(https?://github.com/|git@github.com:)[a-zA-Z0-9./_-]+': Operation timed out after \d+ milliseconds with \d+ out of \d+ bytes received",
    # Transfer stalled and was aborted by http.lowSpeedLimit/http.lowSpeedTime.
    # A stall is transient, so it belongs with the other retryable errors:
    # without this the abort would end the run on the first hiccup, where it
    # used to hang forever instead.
    r"fatal: unable to access '.+': Operation too slow\. Less than \d+ bytes/sec transferred the last \d+ seconds",
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


# A commit id, whole or abbreviated. Anything else is treated as a branch or
# tag name. Ambiguity is resolved towards "this is a commit id", because that
# choice merely costs a slightly larger clone, whereas guessing "branch" for a
# commit id makes "git clone --branch" fail outright.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def looks_like_commit_id(revision: str) -> bool:
    return bool(_SHA_RE.match(revision.strip()))


def get_clone_options(revision) -> list[str]:
    """Pick the cheapest clone that can still reach 'revision'.

    A full clone downloads every version of every file that ever existed, while
    only one tree is ever read. The public index costs about 780MB that way, and
    the slower the link, the more likely that turns into a stalled transfer.

    Three cases:
      - no revision: one commit of the default branch is all that is needed.
      - a branch or tag: same, but ask the server for that ref directly.
      - a commit id: --branch does not accept one, and a shallow clone would
        not contain it. Keep the whole commit graph so any commit can be
        checked out, and leave historical file contents on the server; blobs
        for the checked out tree are fetched on demand.
    """
    if revision is None:
        return ["--depth 1", "--single-branch", "--no-tags"]
    if looks_like_commit_id(revision):
        return ["--filter=blob:none"]
    return ["--depth 1", "--single-branch", "--no-tags", "--branch %s" % revision]


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

        self._apply_import_overrides()

    def _apply_import_overrides(self):
        # applying url overrides
        url_override = self.ctx.user_config.get("dependencies.overrides.url")
        if url_override:
            for key, value in url_override.items():
                if value in self.import_config_url:
                    self.import_config_url = self.import_config_url.replace(value, key)

    def _git_config_options(self) -> list[str]:
        params = []
        for key, value in self.ctx.user_config.git_config.items():
            if key.find("url") != -1 and key.find("insteadOf") != -1:
                continue

            # Use shlex.quote to properly escape shell arguments
            params.append(f"-c {quote(key)}={quote(str(value))}")
        return params


@telemetry.instrument()
class ProjectFactoryGit(pf.ProjectFactory, GitImportConfiguration):
    def __init__(self, ctx, parent, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        GitImportConfiguration.__init__(self)

        self.git_config_options: list[str] = self._git_config_options()
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
            cache_dir = os.path.join(self.ctx.user_config.internal_state_dir, "git")

        # Generate a unique identifier for the repository based on its URL.
        repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()[:16]
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
            # Bound every network operation below. Without this a stalled
            # remote hangs forever, and the retry loop never helps because a
            # hang raises nothing for it to catch.
            _apply_git_timeout(self.ctx.user_config.git_clone_timeout)
            max_retries = self.ctx.user_config.get_int("git.clone.retry.max")
            patience = self.ctx.user_config.get_float("git.clone.retry.patience")
            while attempt <= max_retries and self.ctx.is_connected():
                # Check if the repository is already cached.
                if os.path.exists(cache_path):
                    # Update the repository if it is already cached.
                    try:
                        before = None
                        now = time.time()

                        # Try to open the existing repository and update it.
                        if self.import_revision is None:
                            # Import the default branch
                            if self.ctx.user_config.force_update or (now - os.path.getmtime(guard_path) > 24 * 3600):
                                repo = Repo(cache_path)
                                origin = repo.remote("origin")
                                before = repo.active_branch.commit

                                # If there is more than 1 remote branch, we have to
                                # explicitly specify the branch to pull.
                                remote_head = origin.refs.HEAD
                                branch_name = remote_head.reference.name
                                short_branch_name = branch_name[branch_name.find("/") + 1 :]
                                pc_logging.debug("Refreshing the GIT branch: %s" % short_branch_name)
                                with telemetry.start_as_current_span(
                                    "*ProjectFactoryGit._clone_or_update_repo.{Repo.pull}"
                                ):
                                    origin.pull(short_branch_name)
                                self.ctx.stats_git_ops += 1
                                os.utime(guard_path, (now, now))
                        else:
                            # Import a specific revision
                            if self.ctx.user_config.force_update:
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
                                with telemetry.start_as_current_span(
                                    "*ProjectFactoryGit._clone_or_update_repo.{Repo.pull}-{Repo.fetch}"
                                ):
                                    origin.fetch()
                                    repo.git.checkout(self.import_revision, force=True)
                                    origin.pull(force=True, rebase=True)
                                self.ctx.stats_git_ops += 1
                                os.utime(guard_path, (now, now))
                            else:
                                # No update was performed
                                before = None

                        if not before is None:
                            # Update was performed
                            after = repo.active_branch.commit
                            if before != after:
                                pc_logging.info("Updated the GIT repo: %s" % self.import_config_url)
                            if before != after or self.ctx.user_config.force_update:
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
                            pc_logging.error(
                                "Failed to update repo %s after %d retries: %s",
                                self.import_config_url,
                                attempt,
                                str(e),
                            )
                            # Fall back to using the previous copy
                else:
                    # Clone the repository if it's not cached yet.
                    try:
                        pc_logging.info("Cloning the GIT repo: %s" % self.import_config_url)
                        clone_options = get_clone_options(self.import_revision)
                        with telemetry.start_as_current_span(
                            "*ProjectFactoryGit._clone_or_update_repo.{Repo.clone_from}"
                        ):
                            try:
                                repo = Repo.clone_from(
                                    repo_url,
                                    cache_path,
                                    multi_options=self.git_config_options + clone_options,
                                    allow_unsafe_options=True,
                                )
                            except exc.GitCommandError as e:
                                # The cheaper clone can be refused for reasons
                                # that say nothing about reachability: a server
                                # with uploadpack.allowFilter disabled, or a
                                # revision that turned out not to be a ref after
                                # all. None of that should stop the import, so
                                # take the slow path rather than give up.
                                if any(re.search(pattern, str(e)) for pattern in git_error_patterns):
                                    raise  # a real network failure, let the retry loop see it
                                pc_logging.warning(
                                    "Optimized clone of %s failed (%s), retrying with a full clone",
                                    self.import_config_url,
                                    str(e).splitlines()[-1] if str(e) else e,
                                )
                                shutil.rmtree(cache_path, ignore_errors=True)
                                repo = Repo.clone_from(
                                    repo_url,
                                    cache_path,
                                    multi_options=self.git_config_options,
                                    allow_unsafe_options=True,
                                )
                        self.ctx.stats_git_ops += 1
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
                            pc_logging.error(
                                "Failed to clone repo %s after %d retries", self.import_config_url, attempt
                            )
                            raise RuntimeError(f"Failed to clone repo: {e}") from e
                attempt += 1
        if not self.import_rel_path is None:
            cache_path = os.path.join(cache_path, self.import_rel_path)

        return cache_path
