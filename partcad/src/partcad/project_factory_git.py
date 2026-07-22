#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import hashlib
import re
import os
import shutil
import time
import threading
from dataclasses import dataclass
from urllib.parse import urlparse

import pygit2
from pygit2.enums import CheckoutStrategy, CredentialType, ReferenceType, ResetMode

from .project_local import ProjectLocal
from . import project_factory as pf
from . import logging as pc_logging
from . import telemetry


class GitCallbacks(pygit2.RemoteCallbacks):
    """Answer what a remote asks for, without ever waiting on a prompt.

    A repository that has been deleted, made private or renamed answers with an
    authentication challenge rather than an error. The git command line used to
    wait there on a credential prompt that nothing would ever answer, so the
    whole process hung instead of failing. libgit2 asks this callback instead,
    so the same situation ends in an exception as long as this callback never
    tries to reach a terminal, which it does not.

    ssh remotes are the one case worth answering: the git command line reached
    them through ssh, which offers the running agent's keys and the key files
    it keeps by default, so the same is offered here. Each is offered once,
    because libgit2 asks again for every credential a remote refuses and an
    offer that is never withdrawn would loop forever.
    """

    # What ssh would reach for on its own. A key that needs a passphrase only
    # works through the agent, since asking for one is the thing that must
    # never happen here.
    _ssh_key_files = ("id_ed25519", "id_ecdsa", "id_rsa")

    def __init__(self):
        super().__init__()
        self._ssh_credentials = None

    def credentials(self, url, username_from_url, allowed_types):
        username = username_from_url or "git"
        if allowed_types & CredentialType.USERNAME:
            return pygit2.Username(username)
        if allowed_types & CredentialType.SSH_KEY:
            if self._ssh_credentials is None:
                self._ssh_credentials = self._ssh_candidates(username)
            if self._ssh_credentials:
                return self._ssh_credentials.pop(0)
        raise pygit2.GitError("Authentication is required for '%s' and no credentials are available" % url)

    def _ssh_candidates(self, username) -> list:
        candidates = [pygit2.KeypairFromAgent(username)]

        ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
        for name in self._ssh_key_files:
            private_key = os.path.join(ssh_dir, name)
            if not os.path.exists(private_key):
                continue
            public_key = private_key + ".pub"
            candidates.append(
                pygit2.Keypair(username, public_key if os.path.exists(public_key) else "", private_key, "")
            )

        return candidates


def _apply_git_timeout(seconds: int) -> None:
    """Bound git network operations to 'seconds'.

    libgit2 speaks the transport protocols itself, so the bound is a property of
    the library rather than of the environment: server_connect_timeout bounds
    reaching the remote at all, and server_timeout bounds every read and write
    afterwards. Together they bound how long an operation may make no progress,
    which is what actually needs bounding here; a large but healthy clone is
    still allowed to take as long as it needs.

    Both are process-wide libgit2 settings rather than per-call arguments, which
    costs nothing here because every caller below wants the same bound.
    """
    pygit2.settings.server_connect_timeout = min(seconds, 60) * 1000
    pygit2.settings.server_timeout = seconds * 1000


global_cache_lock = threading.Lock()
cache_locks = {}

# libgit2 reports failures as free-form text, so a retryable one is recognized
# by its wording, the way the git command line's output used to be. Everything
# here is a transient network condition. A definitive answer (a 404, an
# authentication challenge, a ref that does not exist) must not match: retrying
# it only delays reporting a repository that is genuinely unusable.
git_error_patterns = [
    # Host resolution problem
    r"failed to resolve address for .+",
    r"could not resolve (host|address)",
    # The remote could not be reached at all
    r"failed to connect to .+",
    r"connection (refused|reset|timed out)",
    # Timeout, either the remote's own or the one _apply_git_timeout sets
    r"timed out",
    r"timeout was reached",
    # The transfer started and then stopped short
    r"broken pipe",
    r"early EOF",
    r"unexpected disconnect while reading sideband packet",
    r"remote did not send all necessary objects",
    r"RPC failed",
    r"failed to (send|receive) (request|response)",
    # The server is temporarily unable to answer. Other 4xx codes are
    # deliberately excluded: those are answers about the repository, not hiccups.
    r"unexpected http status code: (5\d\d|429)",
    # A proxy in the way, which says nothing about the repository whatever code
    # it returns, so any of them is worth another attempt.
    r"received http code \d+ from proxy",
    # SSL/TLS failure
    r"ssl (error|certificate problem)",
]

# libgit2 reports a missing reference as a KeyError rather than as a GitError,
# and an unusable revision as an InvalidSpecError, so every git operation below
# can end in any of the three.
GIT_ERRORS = (pygit2.GitError, pygit2.InvalidSpecError, KeyError)


def is_retryable(error: Exception) -> bool:
    """Whether 'error' is a hiccup worth another attempt rather than an answer."""
    message = str(error)
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in git_error_patterns)


# A commit id, whole or abbreviated. Anything else is treated as a branch or
# tag name. Ambiguity is resolved towards "this is a commit id", because that
# choice merely costs a slightly larger clone, whereas guessing "branch" for a
# commit id makes the clone ask the server for a branch that does not exist.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# "git@github.com:org/repo", the scp-like spelling of an ssh url. It has no
# scheme, so urlparse cannot tell it apart from a local path.
_SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9_.-]+:")


def looks_like_commit_id(revision: str) -> bool:
    return bool(_SHA_RE.match(revision.strip()))


@dataclass(frozen=True)
class CloneOptions:
    """How much of a repository has to be downloaded to reach a revision."""

    # What to ask the server for. None means "whatever the default branch is",
    # which is the one request that needs no revision to be named.
    revision: str | None
    # How many commits to ask for. 0 means the whole history, which is only
    # needed where a single commit cannot be requested by name.
    depth: int
    # Whether every branch has to come down rather than just the one that gets
    # used. Only a commit id needs this: it names no branch, so the one it
    # belongs to is unknown until the commit is in hand.
    all_branches: bool = False

    @property
    def single_commit(self) -> bool:
        """Whether the request names a commit id, which not every server serves."""
        return self.revision is not None and looks_like_commit_id(self.revision)


def get_clone_options(revision) -> CloneOptions:
    """Pick the cheapest download that can still reach 'revision'.

    A full clone downloads every version of every file that ever existed, while
    only one tree is ever read. The public index costs about 780MB that way, and
    the slower the link, the more likely that turns into a stalled transfer.

    Three cases:
      - no revision: one commit of the default branch is all that is needed.
      - a branch or tag: same, but ask the server for that ref directly.
      - a commit id: a clone cannot check one out by name and a shallow clone of
        a branch would not contain it, so the commit is requested by id.
        clone_single_commit does that and only falls back to the whole history
        when the server will not serve a commit id by name.
    """
    if revision is None:
        return CloneOptions(revision=None, depth=1)
    return CloneOptions(revision=revision, depth=1)


def get_fallback_clone_options(revision) -> CloneOptions:
    """What to ask for when the cheapest request was refused.

    A branch or a tag can still be asked for by name. Only the depth has to go,
    because a server that will not serve a shallow request will serve the same
    ref whole.

    A commit id is the harder case: nothing identifies it to a server that will
    not serve it by name, so the only way to reach it is to take the commit
    graph whole and look the commit up locally. The git command line paired
    that with --filter=blob:none, which left historical file contents on the
    server; libgit2 has no partial clone, so this does download them. It stays
    a fallback for exactly that reason: it is only reached against a server
    still speaking protocol v0 with uploadpack.allowReachableSHA1InWant off.
    """
    if revision is not None and looks_like_commit_id(revision):
        return CloneOptions(revision=None, depth=0, all_branches=True)
    return CloneOptions(revision=revision, depth=0)


def _supports_shallow(repo_url: str) -> bool:
    """Whether the transport serving 'repo_url' can answer a shallow request.

    libgit2 refuses a depth on the local transport ("shallow fetch is not
    supported by the local transport") where the git command line merely
    ignored it, so a local path has to be asked for the whole history.
    """
    if _SCP_LIKE_RE.match(repo_url):
        return True
    return urlparse(repo_url).scheme in ("http", "https", "ssh", "git")


def _apply_git_config(repo: pygit2.Repository, git_config) -> None:
    """Write the user's git settings into the repository.

    They have to be in place before anything touches the network, because this
    is where libgit2 reads the settings that shape the transfer itself, http
    proxies among them.
    """
    for key, value in dict(git_config).items():
        repo.config[key] = str(value)


def _repository_factory(git_config):
    """Create the repository a clone fills in, configured before it is filled."""

    def create(path, bare):
        repo = pygit2.init_repository(path, bare=bare)
        _apply_git_config(repo, git_config)
        return repo

    return create


def _tracking_refspecs(revision: str) -> list[str]:
    """The refspecs naming 'revision' and nothing else.

    This is how --single-branch is expressed here: the remote tracks the one
    ref that was asked for instead of the wildcard a clone would configure by
    default, so nothing else is ever downloaded, now or on a later refresh.

    A revision can be a branch or a tag and the import configuration does not
    say which, so both spellings are configured. The one that matches nothing
    on the remote is simply never used.
    """
    return [
        "+refs/heads/{rev}:refs/remotes/origin/{rev}".format(rev=revision),
        "+refs/tags/{rev}:refs/tags/{rev}".format(rev=revision),
    ]


def _create_origin(repo: pygit2.Repository, repo_url: str, revision) -> None:
    """Point the repository at 'repo_url', tracking as little as will do.

    A commit id names no ref, so there is nothing to narrow to and the default
    wildcard stays; every fetch of a commit id asks for it by id anyway.
    """
    if revision is None or looks_like_commit_id(revision):
        repo.remotes.create("origin", repo_url)
        return

    refspecs = _tracking_refspecs(revision)
    repo.remotes.create("origin", repo_url, refspecs[0])
    for refspec in refspecs[1:]:
        repo.remotes.add_fetch("origin", refspec)


def _single_branch_remote():
    """Configure a clone's remote to follow the default branch alone.

    A clone left to itself configures "+refs/heads/*:refs/remotes/origin/*",
    and with a depth that still means a complete snapshot of every branch the
    remote has rather than of the one that gets used. git spells the cure
    --single-branch; libgit2 spells it as the refspec the remote is created
    with, which is what this does.

    Which branch that is only the remote knows, so it is asked: the ref
    advertisement carries HEAD and what it points at. That costs one round trip
    against a server that has just been reached anyway, and saves downloading
    every other branch in full.
    """

    def create(repo, name, url):
        head = None
        for ref in repo.remotes.create_anonymous(url).ls_remotes(callbacks=GitCallbacks(), proxy=True):
            if ref["name"] == "HEAD":
                head = ref.get("symref_target")
                break

        if not head:
            # A remote that does not say which branch is its default. Take
            # everything, as a clone would have anyway.
            return repo.remotes.create(name, url)

        return repo.remotes.create(
            name,
            url,
            "+{ref}:refs/remotes/origin/{short}".format(ref=head, short=head.removeprefix("refs/heads/")),
        )

    return create


def _clone(repo_url, cache_path, git_config, options: CloneOptions) -> pygit2.Repository:
    """Clone 'repo_url' into 'cache_path', taking as few branches as will do."""
    return pygit2.clone_repository(
        repo_url,
        cache_path,
        depth=options.depth if _supports_shallow(repo_url) else 0,
        callbacks=GitCallbacks(),
        repository=_repository_factory(git_config),
        # A commit id can be on any branch, so that search needs the wildcard
        # refspec a clone configures by default.
        remote=None if options.all_branches else _single_branch_remote(),
        # Honour http.proxy from the config written above and the http_proxy
        # environment, the way the git command line did through curl. Without
        # this libgit2 ignores both and talks to the remote directly.
        proxy=True,
    )


def _fetch(repo: pygit2.Repository, revision: str, depth: int = 1) -> pygit2.Oid:
    """Fetch 'revision' from origin, returning the commit it resolved to."""
    remote = repo.remotes["origin"]
    remote.fetch(
        [revision],
        depth=depth if _supports_shallow(remote.url) else 0,
        callbacks=GitCallbacks(),
        proxy=True,
    )
    return _fetched_commit(repo, revision)


def _fetched_commit(repo: pygit2.Repository, revision: str) -> pygit2.Oid:
    """The commit the last fetch resolved 'revision' to.

    FETCH_HEAD is whatever that fetch just resolved, which is right for a
    branch, a tag and a commit id alike. Matching the revision against the
    repository's own references cannot work: a branch lands under
    "origin/<branch>", a tag under its own name and a commit id under no name
    at all, so a single lookup would miss and silently use whatever stale
    reference it found instead of what was just fetched.

    FETCH_HEAD is read as a file rather than looked up as a reference because
    it is not quite one: a fetch that brings several refs down writes a line
    each, which no reference lookup can resolve.

    It is also emptied by a fetch that had nothing to bring down, which is the
    ordinary outcome of refreshing a tag that has not moved. That says the
    local copy of the revision is what the remote has, so the revision is
    resolved locally there. Only a revision that is neither in the file nor
    already downloaded is one the remote does not have.
    """
    entries = []
    fetch_head = os.path.join(repo.path, "FETCH_HEAD")
    if os.path.exists(fetch_head):
        with open(fetch_head, "r") as f:
            entries = [line.split("\t") for line in f.read().splitlines() if line.strip()]

    for fields in entries:
        # The requested ref is the one written to be merged. Anything the
        # server volunteered alongside it is marked "not-for-merge".
        if len(fields) < 2 or not fields[1].strip():
            # An annotated tag resolves to the tag object, not to a commit.
            return repo.get(fields[0].strip()).peel(pygit2.Commit).id

    local = _local_commit(repo, revision)
    if local is not None:
        return local

    raise pygit2.GitError("Revision '%s' was not found on the remote" % revision)


def _local_commit(repo: pygit2.Repository, revision: str):
    """Where 'revision' points in what has already been downloaded, if anywhere.

    Each kind of revision lands somewhere else: a tag under its own name, a
    branch under the remote it came from, and a commit id under no name at all.
    A single lookup of the bare revision finds none of them.
    """
    for candidate in ("refs/tags/%s" % revision, "refs/remotes/origin/%s" % revision, revision):
        try:
            obj = repo.revparse_single(candidate)
        except (KeyError, ValueError):
            continue
        if obj is not None:
            return obj.peel(pygit2.Commit).id
    return None


def _checkout(repo: pygit2.Repository, revision) -> pygit2.Oid:
    """Check 'revision' out, discarding whatever is in the working tree.

    HEAD is left detached. A commit id or a tag leaves it detached anyway, and
    nothing here reads the branch: the refresh path resets HEAD to what it just
    fetched, which works the same either way.
    """
    obj = repo.get(revision) if isinstance(revision, pygit2.Oid) else repo.revparse_single(str(revision))
    if obj is None:
        raise pygit2.GitError("Revision '%s' is missing from the repository" % revision)
    commit = obj.peel(pygit2.Commit)
    repo.checkout_tree(commit, strategy=CheckoutStrategy.FORCE)
    repo.set_head(commit.id)
    return commit.id


def _default_branch(repo: pygit2.Repository) -> str:
    """The short name of the branch the remote considers its default.

    A clone records it as a symbolic origin/HEAD, which is the only place the
    remote's own choice survives locally.
    """
    try:
        head = repo.references["refs/remotes/origin/HEAD"]
        if head.type == ReferenceType.SYMBOLIC:
            return head.target.removeprefix("refs/remotes/origin/")
    except KeyError:
        pass
    if not repo.head_is_detached:
        return repo.head.shorthand
    raise pygit2.GitError("Could not determine the default branch of 'origin'")


def clone_single_commit(repo_url, cache_path, revision, git_config=()) -> pygit2.Repository:
    """Make one commit available without downloading any history.

    A clone cannot check out a commit id by name, and a shallow clone of a
    branch would not contain it, so the cheapest route is an empty repository
    plus a request for that one commit. What lands is a single commit and
    nothing else, checked out.

    Servers do not have to allow this, though most now do. Under protocol v2,
    the default since git 2.26, a reachable commit is served whatever
    uploadpack.allowReachableSHA1InWant says. Only a server still speaking v0
    applies that setting, and there the request is refused unless it was turned
    on. Where it is refused, fall back to taking the whole history so the
    checkout can succeed: one wasted round trip on such a server, and nothing at
    all on one that answers directly.
    """
    repo = pygit2.init_repository(cache_path)
    _apply_git_config(repo, git_config)
    _create_origin(repo, repo_url, revision)
    try:
        _checkout(repo, _fetch(repo, revision, depth=get_clone_options(revision).depth))
        return repo
    except GIT_ERRORS as e:
        if is_retryable(e):
            raise  # a real network failure, let the retry loop see it
        pc_logging.warning(
            "Server would not serve commit %s of %s directly (%s), falling back to the whole history",
            revision,
            repo_url,
            str(e).splitlines()[-1] if str(e) else e,
        )

    shutil.rmtree(cache_path, ignore_errors=True)
    repo = _clone(repo_url, cache_path, git_config, get_fallback_clone_options(revision))
    _checkout(repo, revision)
    return repo


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

    def _git_config(self) -> dict[str, str]:
        params = {}
        for key, value in self.ctx.user_config.git_config.items():
            if key.find("url") != -1 and key.find("insteadOf") != -1:
                continue

            params[key] = str(value)
        return params


@telemetry.instrument()
class ProjectFactoryGit(pf.ProjectFactory, GitImportConfiguration):
    def __init__(self, ctx, parent, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        GitImportConfiguration.__init__(self)

        self.git_config: dict[str, str] = self._git_config()
        self.path = self._clone_or_update_repo(self.import_config_url)

        # Complement the config object here if necessary
        self._create(config)

        # TODO(clairbee): actually fill in the self.project object here

        self._save()

    def _download(self, repo_url, cache_path, options: CloneOptions) -> pygit2.Repository:
        """Fill 'cache_path' from 'repo_url', with the revision checked out."""
        if options.revision is None:
            return _clone(repo_url, cache_path, self.git_config, options)

        # A branch or a tag. Ask the server for that ref alone: a clone can only
        # check out a branch, so reaching a tag through one would mean taking
        # the default branch's history first.
        repo = pygit2.init_repository(cache_path)
        _apply_git_config(repo, self.git_config)
        _create_origin(repo, repo_url, options.revision)
        _checkout(repo, _fetch(repo, options.revision, options.depth))
        return repo

    def _clone_repo(self, repo_url, cache_path, options: CloneOptions) -> pygit2.Repository:
        """Download 'repo_url' into 'cache_path' with the revision checked out.

        The cheapest download can be refused for reasons that say nothing about
        reachability: a server with shallow requests turned off, or a revision
        the server will not resolve the cheap way. None of that should stop the
        import, so ask for the whole history rather than give up.

        An attempt that fails leaves nothing behind. Whatever it had managed to
        create would be taken for a cached copy by the next attempt, which
        would then try to refresh a repository that was never filled in.
        """

        def attempt(download):
            try:
                return download()
            except GIT_ERRORS:
                shutil.rmtree(cache_path, ignore_errors=True)
                raise

        if options.single_commit:
            # One commit, no history. Handles its own fallback for the servers
            # that refuse the request.
            return attempt(lambda: clone_single_commit(repo_url, cache_path, options.revision, self.git_config))

        try:
            return attempt(lambda: self._download(repo_url, cache_path, options))
        except GIT_ERRORS as e:
            if is_retryable(e):
                raise  # a real network failure, let the retry loop see it
            pc_logging.warning(
                "Optimized clone of %s failed (%s), retrying with a full clone",
                self.import_config_url,
                str(e).splitlines()[-1] if str(e) else e,
            )

        return attempt(lambda: self._download(repo_url, cache_path, get_fallback_clone_options(options.revision)))

    def _create_project(self, config):
        return ProjectLocal(
            self.ctx,
            self.name,
            self.path,
            include_paths=self.include_paths,
            inherited_config=self.inherited_config,
        )

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
                                repo = pygit2.Repository(cache_path)
                                before = repo.head.target

                                # If there is more than 1 remote branch, we have to
                                # explicitly specify the branch to pull.
                                short_branch_name = _default_branch(repo)
                                pc_logging.debug("Refreshing the GIT branch: %s" % short_branch_name)
                                with telemetry.start_as_current_span(
                                    "*ProjectFactoryGit._clone_or_update_repo.{Remote.fetch}"
                                ):
                                    fetched = _fetch(repo, short_branch_name)
                                    repo.reset(fetched, ResetMode.HARD)
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

                            stale = now - os.path.getmtime(guard_path) > 24 * 3600
                            if looks_like_commit_id(self.import_revision):
                                # A commit id names one immutable commit, so a
                                # periodic re-check has nothing to find and
                                # would only ask the server for a commit id by
                                # name again, which not every server serves.
                                # An explicit force_update still gets through,
                                # because it empties "before" above.
                                stale = False

                            if before != self.import_revision or stale:
                                repo = pygit2.Repository(cache_path)
                                # head.target, not the active branch: checking
                                # out a tag or a commit id leaves HEAD detached,
                                # and there is no branch to read there. HEAD
                                # works either way.
                                before = repo.head.target
                                # Need to check for updates
                                with telemetry.start_as_current_span(
                                    "*ProjectFactoryGit._clone_or_update_repo.{Remote.fetch}"
                                ):
                                    fetched = _fetch(repo, self.import_revision)
                                    repo.reset(fetched, ResetMode.HARD)

                                self.ctx.stats_git_ops += 1
                                os.utime(guard_path, (now, now))
                            else:
                                # No update was performed
                                before = None

                        if not before is None:
                            # Update was performed
                            after = repo.head.target
                            if before != after:
                                pc_logging.info("Updated the GIT repo: %s" % self.import_config_url)
                            if before != after or self.ctx.user_config.force_update:
                                with open(guard_path, "w") as f:
                                    if self.import_revision is None:
                                        f.write(str(after))
                                    else:
                                        f.write(self.import_revision)
                        break
                    except GIT_ERRORS as e:
                        # Check if the error is a transient network failure
                        if is_retryable(e) and attempt < max_retries:
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
                            "*ProjectFactoryGit._clone_or_update_repo.{clone_repository}"
                        ):
                            repo = self._clone_repo(repo_url, cache_path, clone_options)
                        self.ctx.stats_git_ops += 1
                        if self.import_revision is not None:
                            after = self.import_revision
                        else:
                            after = repo.head.target

                        with open(guard_path, "w") as f:
                            f.write(str(after))
                        break
                    except GIT_ERRORS as e:
                        # Check if the error is a transient network failure
                        if is_retryable(e) and attempt < max_retries:
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
