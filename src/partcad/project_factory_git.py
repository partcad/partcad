#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import contextlib
import gc
import hashlib
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import traceback
import uuid
import weakref
from dataclasses import dataclass
from urllib.parse import urlparse

import pygit2
from filelock import FileLock
from pygit2.enums import CheckoutStrategy, ConfigLevel, CredentialType, ReferenceType, ResetMode

from partcad_utils import config_yaml

from . import consts
from . import logging as pc_logging
from . import project_factory as pf
from . import revision as pc_revision
from . import telemetry
from .project_local import ProjectLocal


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

    Credentials a remote needs beyond that come from the user configuration
    (``git.auth``), which is why they are configured upfront: this callback may
    be running inside the background daemon or a CI job, where there is nobody
    to ask. When nothing is configured for the host, it says so and names the
    setting instead of failing with a bare authentication error.
    """

    # What ssh would reach for on its own. A key that needs a passphrase only
    # works through the agent, unless the passphrase is configured too.
    _ssh_key_files = ("id_ed25519", "id_ecdsa", "id_rsa")

    def __init__(self, user_config=None):
        super().__init__()
        self._ssh_credentials = None
        if user_config is None:
            # The process-wide configuration; injectable for tests.
            from partcad_utils.user_config import user_config as default_user_config

            user_config = default_user_config
        self._user_config = user_config

    def _auth_entry(self, url) -> dict:
        """The ``git.auth`` entry configured for this remote's host, if any."""
        auth = getattr(self._user_config, "git_auth", None)
        auth = auth.to_dict() if auth is not None else {}
        if not auth:
            return {}
        host = urlparse(url).hostname
        if not host and "@" in url:
            # scp-style "git@github.com:owner/repo" carries no scheme to parse.
            host = url.split("@", 1)[1].split(":", 1)[0]
        return auth.get(host) or auth.get("default") or {}

    def _no_credentials(self, url, wanted: str) -> pygit2.GitError:
        host = urlparse(url).hostname or "<host>"
        return pygit2.GitError(
            "Authentication is required for '%s' and no %s is configured. "
            "PartCAD never prompts for credentials, so set them in the user configuration under "
            "'git.auth.%s' (username/password for HTTPS, sshKey/sshKeyPassphrase for SSH)." % (url, wanted, host)
        )

    def credentials(self, url, username_from_url, allowed_types):
        entry = self._auth_entry(url)
        username = entry.get("username") or username_from_url or "git"

        if allowed_types & CredentialType.USERNAME:
            return pygit2.Username(username)

        if allowed_types & CredentialType.USERPASS_PLAINTEXT:
            # An HTTPS remote. Only a configured token can answer this; there is
            # no ambient equivalent of the ssh agent to fall back on.
            password = entry.get("password")
            if password:
                return pygit2.UserPass(username, str(password))
            raise self._no_credentials(url, "'git.auth' username/password")

        if allowed_types & CredentialType.SSH_KEY:
            if self._ssh_credentials is None:
                self._ssh_credentials = self._ssh_candidates(username, entry)
            if self._ssh_credentials:
                return self._ssh_credentials.pop(0)
            raise self._no_credentials(url, "usable SSH key")

        raise self._no_credentials(url, "credential of a supported type")

    def _ssh_candidates(self, username, entry: dict) -> list:
        candidates = []

        # A configured key is tried first: it is the deliberate answer for this
        # host, and unlike the defaults below it may carry a passphrase.
        private_key = entry.get("sshKey")
        if private_key:
            private_key = os.path.expanduser(str(private_key))
            public_key = entry.get("sshKeyPublic") or (private_key + ".pub")
            public_key = os.path.expanduser(str(public_key))
            candidates.append(
                pygit2.Keypair(
                    username,
                    public_key if os.path.exists(public_key) else "",
                    private_key,
                    str(entry.get("sshKeyPassphrase") or ""),
                )
            )

        candidates.append(pygit2.KeypairFromAgent(username))

        ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
        for name in self._ssh_key_files:
            default_key = os.path.join(ssh_dir, name)
            if not os.path.exists(default_key):
                continue
            public_key = default_key + ".pub"
            candidates.append(
                pygit2.Keypair(username, public_key if os.path.exists(public_key) else "", default_key, "")
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


# An authentication or credential failure, as opposed to a transient network
# problem (is_retryable) or a definitive answer such as a 404 or a missing ref.
# These are what a 'url.*.insteadOf' rewrite in the ambient git config produces
# when it sends an anonymous clone to a transport whose credentials are not
# available here, so they are the failures worth retrying with that config
# ignored. A repository that is genuinely gone answers differently and must not
# match: ignoring the config cannot make a missing repository appear.
auth_error_patterns = [
    r"authentication is required",
    r"authentication required",
    r"no credentials",
    r"unsupported credentials",
    r"failed to authenticate",
    r"permission denied",
    r"too many redirects or authentication replays",
    # HTTP unauthorized/forbidden, worded the way libgit2 words a bad status
    r"unexpected http status code: 40[13]",
]


def is_auth_failure(error: Exception) -> bool:
    """Whether 'error' is an authentication or credential failure."""
    message = str(error)
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in auth_error_patterns)


# A commit id, whole or abbreviated. Anything else is treated as a branch or
# tag name. Ambiguity is resolved towards "this is a commit id", because that
# choice merely costs a slightly larger clone, whereas guessing "branch" for a
# commit id makes the clone ask the server for a branch that does not exist.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# "git@github.com:org/repo", the scp-like spelling of an ssh url. It has no
# scheme, so urlparse cannot tell it apart from a local path.
_SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9_.-]+:")


def _remove_tree(path) -> None:
    """Remove a downloaded copy, including what Windows will not let go of.

    libgit2 writes a repository's objects read-only, and on Windows a read-only
    file cannot be deleted: 'shutil.rmtree(..., ignore_errors=True)' gave up on
    them without a word and left half a repository behind, which the next load
    then took for a copy. Each such file is made writable and removed again;
    whatever still refuses is left, and is what an existing directory without
    its '.partcad.git.cloned' marker is there to catch.

    Windows will not delete a file that is open either, and a repository object
    keeps its pack files open and mapped until it is freed. So whatever opened
    the copy has to let go of it first: '.free()' on a repository in hand, and
    '_release(error)' when the copy is removed because something failed, whose
    traceback keeps every repository the failed attempt opened alive. And a
    'pygit2.Repository' nobody holds is not freed when its last reference goes:
    it sits in a cycle with its own collections ('branches', 'references',
    'remotes', ...), so only the cycle collector frees it - every temporary one
    that read a 'HEAD' keeps its pack open until then. Removing a copy is rare
    enough to collect first.
    """
    gc.collect()

    def retry_writable(func, failed_path, _error):
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            func(failed_path)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry_writable)
    else:
        shutil.rmtree(path, onerror=retry_writable)  # 'onexc' is 3.12's spelling


def _release(error: BaseException) -> None:
    """Let go of everything a failed attempt still holds through 'error'.

    A traceback keeps each frame it passes through alive, and with it every
    local of those frames - the repositories and remotes the attempt opened,
    which keep their files open. The frames themselves stay, so the error is
    reported where it happened; only their locals go.
    """
    traceback.clear_frames(error.__traceback__)


# A copy of a tracked branch is moved from pin to pin, and a package loaded out
# of it reads its files lazily for as long as its context lives - in this
# process, or in a daemon serving another workspace. So a context built from a
# copy at a commit it is pinned to says so, in '<copy>.claims/<commit>.<nonce>',
# and holds that file locked while it does; nothing moves a copy another context
# claims at another commit (see 'ProjectFactoryGit._claimed_by_others'). The
# lock is what makes it a claim: the operating system drops it when the process
# ends, however it ends, so a claim file nobody holds locked is one a process
# that went away left behind, and is removed by whoever finds it.
_CLAIMS_SUFFIX = ".claims"
# The claims this process holds, so that finding one of them on disk is known
# to be about another context here, which may be garbage not yet collected.
_claims_here = weakref.WeakValueDictionary()

if sys.platform == "win32":
    import msvcrt

    def _try_lock(file) -> bool:
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(file) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(file) -> bool:
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(file) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class _Claim:
    """One context's claim on the copy at 'cache_path', at 'commit'. Held until 'release()' or collection."""

    def __init__(self, path, commit, file):
        self.path = path
        self.commit = commit
        self._file = file

    @classmethod
    def take(cls, cache_path, commit):
        """Claim the copy at 'cache_path'; None where files cannot be locked, which claims nothing."""
        directory = cache_path + _CLAIMS_SUFFIX
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "%s.%s" % (commit, uuid.uuid4().hex))
            file = open(path, "xb")
        except OSError:
            return None
        if not _try_lock(file):
            file.close()
            with contextlib.suppress(OSError):
                os.remove(path)
            return None
        claim = cls(path, commit, file)
        _claims_here[path] = claim
        return claim

    def release(self) -> None:
        with contextlib.suppress(OSError):
            _unlock(self._file)
        self._file.close()
        with contextlib.suppress(OSError):
            # Windows refuses while somebody probes it; whoever probes it next removes it.
            os.remove(self.path)


def _is_claimed(path) -> bool:
    """Whether the claim file at 'path' is held by a context; removed if it is not."""
    try:
        file = open(path, "rb")
    except OSError:
        return False
    try:
        if not _try_lock(file):
            return True
        with contextlib.suppress(OSError):
            _unlock(file)
    finally:
        file.close()
    with contextlib.suppress(OSError):
        os.remove(path)
    return False


def _claimed_commit(path) -> str:
    return os.path.basename(path).split(".", 1)[0]


def _claimed_commits(cache_path, own=None, matters=None) -> set:
    """The commits contexts other than the one holding 'own' claim the copy at 'cache_path' at.

    A claim lives as long as its context, and a context sits in reference
    cycles: one this process let go of goes on claiming until the cycle
    collector runs. Collecting is a pass over the whole heap, so it is paid only
    when a claim of this process's at a commit that 'matters' is in the way.
    """
    directory = cache_path + _CLAIMS_SUFFIX
    try:
        paths = [os.path.join(directory, name) for name in os.listdir(directory)]
    except OSError:
        return set()
    held = [path for path in paths if (own is None or path != own.path) and _is_claimed(path)]
    if matters is not None and any(path in _claims_here and matters(_claimed_commit(path)) for path in held):
        gc.collect()
        held = [path for path in held if _is_claimed(path)]
    return {_claimed_commit(path) for path in held}


def looks_like_commit_id(revision: str) -> bool:
    return bool(_SHA_RE.match(revision.strip()))


def ref_text(value, key: str, dependency=None):
    """A dependency's 'revision:' or 'track:' as the text that was written, or None if it names none.

    'partcad.yaml' is YAML 1.1, which types an unquoted value by what it looks
    like, and every git operation here takes the value as text. A commit id is
    hex, and an abbreviated one made of decimal digits alone -- 'revision:
    875940244746', about one in three hundred 12-character ids -- is an int to
    YAML; so is a branch or a tag named '2024', '1_000', '0123', '0x1f' or
    '1:30', and of all of those only '875940244746' and '2024' are the decimal
    text of the int they are read as (1000, 83, 31 and 90 are not the others).

    An int is therefore given back as the text it was written as, exactly:
    'ProjectLocal' reads the file with 'partcad_utils.config_yaml', which keeps
    that text beside every int that is not spelled as its decimal text
    ('1_000' is not branch '1000'). An int that is not one of those was written
    as its decimal text, or came from somewhere with no other way to write one
    (a repository plugin's JSON).

    Anything else that is not text is refused, with the fix named: a float
    ('1.10' is 1.1, and its text is not kept -- see 'config_yaml'), a bool
    ('yes', 'on'), a date ('2024-01-01'). A spelling that only looks numeric is
    text already: PyYAML's float wants a '.', so '1e10' and every other id with
    an 'e' in it is a string, and so is '0189', a leading zero with an '8' or a
    '9' after it.
    """
    if value is None or isinstance(value, str):
        return value
    # A bool is an int to Python, and 'yes' is not "1".
    if isinstance(value, int) and not isinstance(value, bool):
        return config_yaml.spelling(value)
    raise ValueError(
        "The '%s:' of %s is read as the %s %s, and the text it was written as is lost by then: "
        "quote it in 'partcad.yaml', as in %s: '<as written>'"
        % (key, dependency or "a git dependency", type(value).__name__, value, key)
    )


def repo_path(url: str) -> str:
    """The "<owner>/<name>" that a repository URL names, lowercased.

    Every spelling of the same repository has to normalize alike, because a
    dependency may be written in any of them: the https and ssh URLs, the
    scp-like "git@host:owner/name" form, with or without a trailing slash and
    with or without the optional ".git" suffix. What is left identifies the
    repository; the host is deliberately dropped, so a mirror of the same
    repository is recognized as well.
    """
    url = (url or "").strip()
    if _SCP_LIKE_RE.match(url):
        path = url.split(":", 1)[1]
    else:
        path = urlparse(url).path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return path.lower()


def is_pub_index_url(url: str) -> bool:
    """Whether 'url' names the repository the public PartCAD index lives in."""
    return repo_path(url) in consts.DEVEL_INDEX_REPO_PATHS


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


def _single_branch_remote(user_config=None):
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
        for ref in repo.remotes.create_anonymous(url).list_heads(callbacks=GitCallbacks(user_config), proxy=True):
            if ref.name == "HEAD":
                head = ref.symref_target
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


def _clone(repo_url, cache_path, git_config, options: CloneOptions, user_config=None) -> pygit2.Repository:
    """Clone 'repo_url' into 'cache_path', taking as few branches as will do."""
    return pygit2.clone_repository(
        repo_url,
        cache_path,
        depth=options.depth if _supports_shallow(repo_url) else 0,
        callbacks=GitCallbacks(user_config),
        repository=_repository_factory(git_config),
        # A commit id can be on any branch, so that search needs the wildcard
        # refspec a clone configures by default.
        remote=None if options.all_branches else _single_branch_remote(user_config),
        # Honour http.proxy from the config written above and, failing that,
        # HTTPS_PROXY/HTTP_PROXY and NO_PROXY from the environment, the way the
        # git command line did through curl. Without this libgit2 ignores both
        # and talks to the remote directly -- which on a machine whose only
        # route out is a proxy means every import stalls until it times out.
        proxy=True,
    )


def _fetch(repo: pygit2.Repository, revision: str, depth: int = 1, user_config=None) -> pygit2.Oid:
    """Fetch 'revision' from origin, returning the commit it resolved to."""
    remote = repo.remotes["origin"]
    remote.fetch(
        [revision],
        depth=depth if _supports_shallow(remote.url) else 0,
        callbacks=GitCallbacks(user_config),
        # As in _clone: the proxy the configuration or the environment names.
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
            fetched = repo.get(fields[0].strip())
            if fetched is None:
                # Named, but nothing came down for it: what a local remote
                # answers when asked for a commit id it does not have.
                break
            # An annotated tag resolves to the tag object, not to a commit.
            return fetched.peel(pygit2.Commit).id

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


def clone_single_commit(repo_url, cache_path, revision, git_config=(), user_config=None) -> pygit2.Repository:
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
        _checkout(repo, _fetch(repo, revision, depth=get_clone_options(revision).depth, user_config=user_config))
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

    repo.free()
    _remove_tree(cache_path)
    repo = _clone(repo_url, cache_path, git_config, get_fallback_clone_options(revision), user_config)
    _checkout(repo, revision)
    return repo


def get_cache_lock(hash):
    global_cache_lock.acquire()
    if hash not in cache_locks:
        cache_locks[hash] = threading.Lock()
    lock = cache_locks[hash]
    global_cache_lock.release()
    return lock


# libgit2 reads the ambient git configuration (~/.gitconfig and the system
# config) directly. A user's 'url.*.insteadOf' rewrite there can send an
# anonymous clone to a transport whose credentials are not available here (an
# https URL rewritten to ssh with no key in a container, for example). When a
# clone has otherwise failed, PartCAD retries it once with these configuration
# levels ignored, so the URL is used as written. Clearing them is a process-wide
# libgit2 setting, so the retry must run with no clone that honors the ambient
# config in flight, and the levels have to be restored afterwards.
_AMBIENT_CONFIG_LEVELS = (ConfigLevel.SYSTEM, ConfigLevel.XDG, ConfigLevel.GLOBAL)


class _AmbientConfigGuard:
    """Coordinate the process-wide libgit2 config search path across threads.

    The search path is a single process-wide libgit2 setting, so clearing it for
    one clone would strip the ambient configuration from every clone running
    beside it. Clones that honor the ambient config are therefore readers and
    stay concurrent, while the fallback clone that clears the search path is the
    writer: it waits until no reader is in flight, then blocks new readers until
    it has restored the search path.

    This coordinates threads within one process, which is all the search path
    needs: it is process-local memory, so a separate process clearing its own
    copy cannot affect this one. Cross-process safety of the shared cache on
    disk is a different concern, handled by the per-repository file lock.
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._readers = 0
        self._writer = False

    @contextlib.contextmanager
    def honoring_ambient_config(self):
        with self._condition:
            while self._writer:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextlib.contextmanager
    def ignoring_ambient_config(self):
        with self._condition:
            while self._writer or self._readers > 0:
                self._condition.wait()
            self._writer = True
        saved = {level: pygit2.settings.search_path[level] for level in _AMBIENT_CONFIG_LEVELS}
        try:
            for level in _AMBIENT_CONFIG_LEVELS:
                pygit2.settings.search_path[level] = ""
            yield
        finally:
            for level, path in saved.items():
                pygit2.settings.search_path[level] = path
            with self._condition:
                self._writer = False
                self._condition.notify_all()


_ambient_config_guard = _AmbientConfigGuard()


def git_config_params(user_config) -> dict[str, str]:
    """The user's 'git.config' settings, as written into every repository PartCAD makes."""
    params = {}
    for key, value in user_config.git_config.items():
        if key.find("url") != -1 and key.find("insteadOf") != -1:
            continue

        params[key] = str(value)
    return params


def remote_heads(repo_url, git_config=(), user_config=None) -> list:
    """What 'repo_url' advertises: every branch and tag, and the commit each is at.

    This is 'git ls-remote', and it is all 'pc update' needs to learn where a
    tracked branch is: the advertisement is the first thing a server sends, so
    nothing is downloaded. libgit2 can only ask through a repository, so a
    throwaway one is made for the question, configured the way a clone would be
    (a proxy in 'git.config' has to apply here too).
    """
    with tempfile.TemporaryDirectory(prefix="partcad-ls-remote-", ignore_cleanup_errors=True) as path:
        repo = pygit2.init_repository(path, bare=True)
        try:
            _apply_git_config(repo, git_config)
            return repo.remotes.create_anonymous(repo_url).list_heads(callbacks=GitCallbacks(user_config), proxy=True)
        finally:
            # Let go of the repository before its directory is removed, which
            # on Windows cannot happen while a handle is open.
            repo.free()


def default_branch_of(heads) -> str | None:
    """The branch a remote's 'HEAD' points at, out of what 'remote_heads' returned."""
    for head in heads:
        if head.name == "HEAD" and head.symref_target:
            return head.symref_target.removeprefix("refs/heads/")
    return None


def branch_commit(heads, branch: str) -> str | None:
    """The commit 'branch' is at, out of what 'remote_heads' returned."""
    for head in heads:
        if head.name == "refs/heads/" + branch:
            return str(head.oid)
    return None


def query_remote(user_config, repo_url, describe: str):
    """'remote_heads' for 'repo_url', with an import's timeout and retries.

    'describe' says what the question is for, in the messages a failure leaves.
    """
    _apply_git_timeout(user_config.git_clone_timeout)
    max_retries = user_config.get_int("git.clone.retry.max")
    patience = user_config.get_float("git.clone.retry.patience")
    git_config = git_config_params(user_config)
    attempt = 0
    while True:
        try:
            with _ambient_config_guard.honoring_ambient_config():
                return remote_heads(repo_url, git_config, user_config)
        except GIT_ERRORS as e:
            if is_retryable(e) and attempt < max_retries:
                pc_logging.warning(
                    "Failed to reach %s for %s. Retrying (%d/%d) in %d secs...",
                    repo_url,
                    describe,
                    attempt + 1,
                    max_retries,
                    patience,
                )
                time.sleep(patience)
                attempt += 1
                continue
            if is_auth_failure(e):
                # As for a clone: most often a 'url.*.insteadOf' rewrite in the
                # ambient git config, so ask once more with it ignored.
                try:
                    with _ambient_config_guard.ignoring_ambient_config():
                        return remote_heads(repo_url, git_config, user_config)
                except GIT_ERRORS:
                    pass
            raise


def tracked_commit(user_config, url: str, track: str | None = None) -> tuple[str, str]:
    """Where branch 'track' of the repository at 'url' is now, as (branch, commit id).

    With no 'track', the branch is the one the remote calls its default. 'url'
    is the one a dependency declares: the user's 'dependencies.overrides.url'
    applies here as it does to the import, so the two ask the same server.
    """
    repo_url = overridden_url(user_config, url)
    heads = query_remote(user_config, repo_url, "branch '%s'" % track if track else "its default branch")
    if not track:
        track = default_branch_of(heads)
        if not track:
            raise pygit2.GitError("%s does not say which branch is its default, so name one to track" % url)
    commit = branch_commit(heads, track)
    if commit is None:
        raise pygit2.GitError("There is no branch '%s' in %s" % (track, url))
    return track, commit


def cache_dir_name(repo_url, name) -> str:
    """The directory a copy of 'repo_url' is kept in, for the branch or revision 'name'.

    Module level rather than a method: 'ProjectFactoryGit' is wrapped by
    'telemetry.instrument()', which hands every callable in the class a 'self'.
    """
    # Generate a unique identifier for the repository based on its URL.
    repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()[:16]
    if name is not None:
        # Append the name to the hash instead of using it as an input to the
        # hash function. This way we can navigate in the cache a lot easier
        # when there are multiple revisions of the same repo.
        display_rev = name.replace("/", "-slash-")
        if os.name == "nt":
            # On Windows, we need to replace backslashes as well.
            display_rev = display_rev.replace(os.path.sep, "-sep-")
        repo_hash += "-" + display_rev
    return repo_hash


def overridden_url(user_config, url: str) -> str:
    """'url' as 'dependencies.overrides.url' in the user configuration rewrites it.

    Every reader of a git dependency's URL goes through this - the import that
    clones it and 'pc update' asking where its branch is - so that the two never
    talk to different servers about the same dependency.
    """
    url_override = user_config.get("dependencies.overrides.url")
    if url_override:
        for key, value in url_override.items():
            if value in url:
                url = url.replace(value, key)
    return url


class GitImportConfiguration:
    """What a 'type: git' dependency asks for, after the user configuration has had its say.

    A dependency names its revision two ways, and they mean different things:

    * 'revision:' is the **pin**: a commit id (or, the old way, a branch or a
      tag) that is checked out, and once it has been downloaded it is never
      fetched again by loading the package.
    * 'track:' is the **branch the pin follows**. Loading does not read it at
      all while there is a pin; 'pc update' does, and moves 'revision:' to
      where that branch is now. A 'track:' with no 'revision:' yet is checked
      out at the branch, once, and stays where it landed until 'pc update' pins
      it.

    The one setting that changes that is 'forceUpdate' -- the "force auto-update"
    -- under which loading follows 'track:' past the pin, to the branch's
    newest commit, every time.

    'import_cache_name' is what the downloaded copy is named after: the branch
    a dependency tracks when it tracks one, so there is one copy per branch that
    moves from pin to pin, and otherwise the revision, as it always was.
    """

    def __init__(self):
        self.import_config_url = self.config_obj.get("url")
        # As text, whatever YAML made of them: see 'ref_text'.
        dependency = self.config_obj.get("name")
        self.import_revision = ref_text(self.config_obj.get("revision"), "revision", dependency)
        self.import_track = ref_text(self.config_obj.get("track"), "track", dependency)
        self.import_rel_path = self.config_obj.get("relPath")
        self.import_cache_name = None

        self._apply_track()
        self._apply_import_overrides()
        if self.import_cache_name is None:
            self.import_cache_name = self.import_revision

    def _apply_track(self):
        """Decide between the pin and the branch it tracks.

        Before the overrides below, so that 'develIndex' still has the last word
        on which revision of the public index is used, whatever the dependency
        says it tracks.
        """
        if not self.import_track:
            return
        self.import_cache_name = self.import_track
        if self.import_revision is None or self.ctx.user_config.force_update:
            self.import_revision = self.import_track

    def _apply_import_overrides(self):
        self.import_config_url = overridden_url(self.ctx.user_config, self.import_config_url)

        self._apply_devel_index_override()

    def _apply_devel_index_override(self):
        """Point the public index at its unreleased branch when asked to.

        The public index lives in a repository of its own, and a package
        imports it at 'main': the branch 'pc init' has the dependency track, at
        the commit it pins it to and 'pc update' moves it on from. Either way
        that is the released state.
        'develIndex' is how the staged state is exercised instead, and it names no
        dependency: the index is recognized by the repository its URL points at,
        so it is redirected wherever in the dependency tree it appears and under
        whatever name the importing package gave it.

        Run after the url overrides above so that a URL rewritten there is still
        recognized. A revision the package pinned itself is replaced rather than
        respected -- this is an override, and a pin is exactly what it exists to
        get past.
        """
        if not getattr(self.ctx.user_config, "devel_index", False):
            return
        if not is_pub_index_url(self.import_config_url):
            return
        if self.import_revision == consts.DEVEL_INDEX_REVISION:
            return
        pc_logging.info(
            "Using the '%s' revision of the public index: %s",
            consts.DEVEL_INDEX_REVISION,
            self.import_config_url,
        )
        self.import_revision = consts.DEVEL_INDEX_REVISION
        # A copy of its own, rather than the one of the branch it tracks: turning
        # 'develIndex' on and off must not move that one back and forth.
        self.import_cache_name = consts.DEVEL_INDEX_REVISION

    def _git_config(self) -> dict[str, str]:
        return git_config_params(self.ctx.user_config)


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
            return _clone(repo_url, cache_path, self.git_config, options, self.ctx.user_config)

        # A branch or a tag. Ask the server for that ref alone: a clone can only
        # check out a branch, so reaching a tag through one would mean taking
        # the default branch's history first.
        repo = pygit2.init_repository(cache_path)
        _apply_git_config(repo, self.git_config)
        _create_origin(repo, repo_url, options.revision)
        _checkout(repo, _fetch(repo, options.revision, options.depth, self.ctx.user_config))
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
            except GIT_ERRORS as e:
                _release(e)
                _remove_tree(cache_path)
                raise

        if options.single_commit:
            # One commit, no history. Handles its own fallback for the servers
            # that refuse the request.
            return attempt(
                lambda: clone_single_commit(
                    repo_url, cache_path, options.revision, self.git_config, self.ctx.user_config
                )
            )

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

    def _clone_ignoring_ambient_config(self, repo_url, cache_path, clone_options, guard_path) -> bool:
        """Retry a failed clone with the ambient git config ignored.

        Returns True if the retry filled the cache. A False return leaves the
        original failure for the caller to report, because ignoring the config
        did not help.
        """
        pc_logging.warning(
            "Clone of %s failed to authenticate; retrying with the ambient git config ignored",
            self.import_config_url,
        )
        try:
            with _ambient_config_guard.ignoring_ambient_config():
                repo = self._clone_repo(repo_url, cache_path, clone_options)
        except GIT_ERRORS:
            return False
        self.ctx.stats_git_ops += 1
        with open(guard_path, "w") as f:
            f.write(str(repo.head.target))
        pc_logging.info("Cloned %s with the ambient git config ignored", self.import_config_url)
        return True

    def _wants_refresh(self) -> bool:
        """Whether a copy that was downloaded already is to be fetched again.

        Never on its own. A dependency downloaded once is what the package is
        built from until somebody asks for newer, which is one of two things:
        'pc update', which moves the pins and then fetches what they name (it
        sets 'Context.refresh_imports' for the duration), or the "force
        auto-update" setting, 'forceUpdate', under which every load fetches every
        branch again.

        There used to be a third: any copy older than a day was refreshed by
        whatever loaded it next. That is gone on purpose. A dependency that moves
        while nobody changed anything is a package that builds differently today
        from yesterday with nothing in it to say why -- and two machines that
        happened to refresh on different days building different things from
        the same commit.
        """
        return bool(self.ctx.user_config.force_update or getattr(self.ctx, "refresh_imports", False))

    def _at_revision(self, cache_path) -> bool:
        """Whether the copy at 'cache_path' is at the commit this dependency is pinned to.

        Always, for a revision that is not a commit id: a branch is whatever was
        downloaded of it, until something asks for newer.
        """
        revision = self.import_revision
        if revision is None or not looks_like_commit_id(revision):
            return True
        try:
            head = str(pygit2.Repository(cache_path).head.target)
        except GIT_ERRORS:
            return False
        return head.startswith(revision.strip().lower())

    def _refresh(self, repo_url, cache_path, guard_path):
        """Bring a downloaded copy to what this dependency names now.

        A commit id names one commit for good: a copy elsewhere -- the copy of a
        tracked branch, which 'pc update' has since pinned somewhere else -- is
        moved to it, and a copy at it is left alone, since there is nothing newer
        to fetch. A branch or a tag is fetched by name, and no revision at all
        means the remote's default branch.
        """
        revision = self.import_revision
        repo = pygit2.Repository(cache_path)
        # head.target, not the active branch: checking out a tag or a commit id
        # leaves HEAD detached, and there is no branch to read there. HEAD works
        # either way.
        before = repo.head.target
        if revision is not None and looks_like_commit_id(revision):
            if str(before).startswith(revision.strip().lower()):
                return
            repo = self._move_to_commit(repo_url, repo, cache_path, revision.strip())
        else:
            with _ambient_config_guard.honoring_ambient_config():
                if revision is None:
                    # If there is more than 1 remote branch, we have to
                    # explicitly specify the branch to pull.
                    revision = _default_branch(repo)
                pc_logging.debug("Refreshing the GIT revision: %s" % revision)
                with telemetry.start_as_current_span("*ProjectFactoryGit._clone_or_update_repo.{Remote.fetch}"):
                    fetched = _fetch(repo, revision, user_config=self.ctx.user_config)
                    repo.reset(fetched, ResetMode.HARD)
        self.ctx.stats_git_ops += 1

        after = repo.head.target
        if before != after:
            pc_logging.info("Updated the GIT repo: %s" % self.import_config_url)
            # The revision a package read out of this copy reports is cached by
            # the repository's path, and the path has not changed.
            pc_revision.reset_cache()
        with open(guard_path, "w") as f:
            f.write(str(after))

    def _move_to_commit(self, repo_url, repo, cache_path, commit) -> pygit2.Repository:
        """Check 'commit' out in the copy at 'cache_path', fetching it if it is not there yet.

        It is asked for by its id, which costs one commit's worth of download.
        A server that will not serve a commit by its id is the one case where
        the copy is downloaded again instead, the way a clone of that commit
        would be - which knows how to get past such a server. That download goes
        beside the copy, which makes way for it only once it has succeeded: the
        same refusal is what a commit the remote does not have at all looks
        like, and that is no reason to lose the copy there is.
        """
        local = _local_commit(repo, commit)
        if local is None:
            try:
                with _ambient_config_guard.honoring_ambient_config():
                    local = _fetch(repo, commit, depth=1, user_config=self.ctx.user_config)
            except GIT_ERRORS as e:
                if is_retryable(e):
                    raise  # a real network failure, let the retry loop see it
                pc_logging.warning(
                    "Server would not serve commit %s of %s directly (%s), downloading it again",
                    commit,
                    self.import_config_url,
                    str(e).splitlines()[-1] if str(e) else e,
                )
                download_path = cache_path + ".partcad-download"
                _remove_tree(download_path)
                with _ambient_config_guard.honoring_ambient_config():
                    self._clone_repo(repo_url, download_path, get_clone_options(commit)).free()
                repo.free()
                _remove_tree(cache_path)
                try:
                    os.replace(download_path, cache_path)
                except OSError as replace_error:
                    raise pygit2.GitError(
                        "Could not put the download of %s in place of %s: %s" % (commit, cache_path, replace_error)
                    ) from replace_error
                return pygit2.Repository(cache_path)
        repo.reset(local, ResetMode.HARD)
        return repo

    def _held_by_others(self, cache_path):
        """The commit 'cache_path' is checked out at for another package of this context, if one is built from it.

        A copy shared by every pin of a branch is moved from pin to pin, and a
        package already loaded out of it reads its files lazily, for as long as
        the context lives. So a copy one package is built from is not moved for
        another: 'Context.git_checkouts' records who uses which copy, and the
        packages are released when the context drops them.
        """
        checkouts = getattr(self.ctx, "git_checkouts", None)
        if checkouts is None:
            return None
        with self.ctx.git_checkouts_lock:
            entry = checkouts.get(cache_path)
            if entry is not None and entry["holders"] - {self.name}:
                return entry["commit"]
        return None

    def _claimed_by_others(self, cache_path, name):
        """The commits other contexts, in this process or another, claim the copy named 'name' at."""
        own = None
        checkouts = getattr(self.ctx, "git_checkouts", None)
        if checkouts is not None:
            with self.ctx.git_checkouts_lock:
                own = checkouts.get(cache_path, {}).get("claim")
        return _claimed_commits(cache_path, own, lambda commit: self._would_move(name, commit))

    def _branch_tip(self, repo_url):
        """The commit the branch this dependency follows is at now; None if it cannot be found out."""
        if not self.ctx.is_connected():
            return None
        try:
            heads = query_remote(self.ctx.user_config, repo_url, "the branch it follows")
        except GIT_ERRORS as e:
            pc_logging.warning("Could not find out where %s is now: %s" % (self.import_config_url, e))
            return None
        branch = self.import_revision or default_branch_of(heads)
        return branch_commit(heads, branch) if branch else None

    def _would_move(self, name, commit) -> bool:
        """Whether this dependency would move the copy named 'name' off 'commit', were it nobody else's."""
        if name != self.import_revision:
            return not self._accepts(commit)
        # A copy named after the revision: only a refresh of a branch moves it.
        return self._wants_refresh() and not looks_like_commit_id(self.import_revision or "")

    def _hold(self, cache_path, claim):
        """Record that this package is built from the copy at 'cache_path', at the commit it is at.

        With 'claim', other contexts are told so as well, for as long as this
        one holds it: a copy moved under a package pinned to a commit would have
        it read another commit's files.
        """
        checkouts = getattr(self.ctx, "git_checkouts", None)
        if checkouts is None or not os.path.isdir(cache_path):
            return
        try:
            commit = str(pygit2.Repository(cache_path).head.target)
        except GIT_ERRORS:
            return
        with self.ctx.git_checkouts_lock:
            entry = checkouts.setdefault(cache_path, {"commit": commit, "holders": set(), "claim": None})
            if entry["claim"] is not None and entry["claim"].commit != commit:
                # Moved by the one package that held it, which may.
                entry["claim"].release()
                entry["claim"] = None
            entry["commit"] = commit
            entry["holders"].add(self.name)
            if claim and entry["claim"] is None:
                entry["claim"] = _Claim.take(cache_path, commit)

    def _clone_or_update_repo(self, repo_url, cache_dir=None):
        """
        Make the revision this dependency names available locally.

        A copy is downloaded once and then used as it is: loading a package does
        not ask the remote whether anything moved since, so the network is
        reached only to download a revision that is not here yet, or when a
        refresh was asked for (see '_wants_refresh').

        A dependency that tracks a branch is kept in a copy named after the
        branch, which is moved to whichever commit the dependency is pinned to:
        'pc update' moving a pin moves that copy, rather than leaving the old
        commit's behind. The one exception is a copy another package is already
        built from at another commit - of this context, or of another one that
        claimed it (a daemon serving another workspace); that pin is then kept
        in a copy named after the commit, the way every revision used to be.

        Args:
          repo_url: URL of the Git repository to clone.
          cache_dir: Directory to store the cached copies of repositories (defaults to ".cache").

        Returns:
          Local path to the cloned repository.
        """

        if cache_dir is None:
            cache_dir = os.path.join(self.ctx.user_config.internal_state_dir, "git")
        os.makedirs(cache_dir, exist_ok=True)

        cache_path = self._prepare_copy(repo_url, cache_dir, self.import_cache_name)
        if cache_path is None and not looks_like_commit_id(self.import_revision or ""):
            # A branch to follow past a copy another context is built from: it
            # is followed as a pin on the commit the branch is at now - the copy
            # as it is if that is where it is, a copy named after the commit if
            # not - or, when where it is cannot be found out, not followed.
            tip = self._branch_tip(repo_url)
            if tip is None:
                cache_path = self._prepare_copy(repo_url, cache_dir, self.import_cache_name, isolate=False)
            else:
                self.import_revision = tip
                cache_path = self._prepare_copy(repo_url, cache_dir, self.import_cache_name)
        if cache_path is None:
            cache_path = self._prepare_copy(repo_url, cache_dir, self.import_revision)

        if self.import_rel_path is not None:
            cache_path = os.path.join(cache_path, self.import_rel_path)

        return cache_path

    def _prepare_copy(self, repo_url, cache_dir, name, isolate=True):
        """Make the copy named 'name' hold this dependency's revision; None if it is in use at another.

        With 'isolate', a branch to be followed past a copy another context is
        built from also gets None, to be followed in a copy of its own; without,
        that copy is used as it is.

        Returns the copy's path.
        """
        repo_hash = cache_dir_name(repo_url, name)
        cache_path = os.path.join(cache_dir, repo_hash)
        cache_lock = get_cache_lock(repo_hash)

        # A file lock beside the cached copy serializes this repository across
        # processes as well, not just across the threads the threading lock
        # covers, so two 'pc' invocations never clone into the same directory at
        # once. The lock file is released when the process exits but left on
        # disk; the 'StaleGitLocks' healthcheck removes ones no process holds.
        repo_file_lock = FileLock(os.path.join(cache_dir, repo_hash + ".lock"))

        # Written last, once the revision is checked out, so it is what tells a
        # copy that was downloaded from one that only started to be.
        guard_path = os.path.join(cache_path, ".partcad.git.cloned")

        with cache_lock, repo_file_lock:
            held = self._held_by_others(cache_path)
            # Claims by other contexts that agree with what this one would do
            # change nothing; only the ones in its way do.
            blocking = {
                commit for commit in self._claimed_by_others(cache_path, name) if self._would_move(name, commit)
            }
            if held is not None or blocking:
                if name != self.import_revision and (blocking or self._would_move(name, held)):
                    # Another package, of this context or another, is built
                    # from this copy at another commit: not to be moved under it.
                    return None
                # In use already, and at what this dependency asks for: used as
                # it is, without a refresh moving it under the other package.
                if blocking:
                    if isolate:
                        return None
                    pc_logging.warning(
                        "Not updating %s: another PartCAD context is built from it at %s"
                        % (self.import_config_url, ", ".join(sorted(blocking)))
                    )
            else:
                if os.path.exists(cache_path) and not os.path.exists(guard_path):
                    # A download that never finished: a process killed mid-clone, a
                    # disk that filled up. Whatever part of the tree arrived is not
                    # the revision, so it is downloaded again rather than built from.
                    pc_logging.warning("Discarding an incomplete copy of %s" % self.import_config_url)
                    _remove_tree(cache_path)

                if os.path.exists(guard_path) and not self._wants_refresh() and self._at_revision(cache_path):
                    # Downloaded already, at what is asked for, and nobody asked
                    # for anything newer. This is the common case, and it needs no
                    # network at all -- not even the connectivity probe, which is
                    # why it is decided up here.
                    pass
                else:
                    self._download_or_refresh(repo_url, cache_path, guard_path)

                if os.path.exists(guard_path) and not self._at_revision(cache_path):
                    pc_logging.warning(
                        "%s is not at the commit it is pinned to, %s, which could not be fetched: "
                        "using the copy that was downloaded before" % (self.import_config_url, self.import_revision)
                    )
            # Only a copy that moves needs claiming: one named after its commit
            # never does.
            self._hold(cache_path, claim=not looks_like_commit_id(name or ""))

        return cache_path

    def _accepts(self, commit) -> bool:
        """Whether a copy at 'commit' is what this dependency asks for."""
        revision = self.import_revision
        if revision is None or not looks_like_commit_id(revision):
            # A branch is whatever this context already has of it.
            return True
        return commit.startswith(revision.strip().lower())

    def _download_or_refresh(self, repo_url, cache_path, guard_path):
        """Clone the revision, or refresh the copy there is, retrying what is worth it."""
        attempt = 0
        # Bound every network operation below. Without this a stalled
        # remote hangs forever, and the retry loop never helps because a
        # hang raises nothing for it to catch.
        _apply_git_timeout(self.ctx.user_config.git_clone_timeout)
        max_retries = self.ctx.user_config.get_int("git.clone.retry.max")
        patience = self.ctx.user_config.get_float("git.clone.retry.patience")
        while attempt <= max_retries and self.ctx.is_connected():
            # Check if the repository is already cached: by the marker a clone
            # writes last, not by the directory, which a removal that did not
            # finish can leave behind.
            if os.path.exists(guard_path):
                # Update the repository if it is already cached.
                try:
                    self._refresh(repo_url, cache_path, guard_path)
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
                        # Fall back to using the previous copy, which is
                        # complete: only a refresh gets here.
                        break
            else:
                # Clone the repository if it's not cached yet.
                try:
                    pc_logging.info("Cloning the GIT repo: %s" % self.import_config_url)
                    clone_options = get_clone_options(self.import_revision)
                    with _ambient_config_guard.honoring_ambient_config():
                        with telemetry.start_as_current_span(
                            "*ProjectFactoryGit._clone_or_update_repo.{clone_repository}"
                        ):
                            repo = self._clone_repo(repo_url, cache_path, clone_options)
                    self.ctx.stats_git_ops += 1

                    # The commit, whatever the revision named: a copy named after
                    # a branch moves from commit to commit.
                    with open(guard_path, "w") as f:
                        f.write(str(repo.head.target))
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
                        # An authentication failure here is most often a
                        # 'url.*.insteadOf' rewrite in the ambient git config
                        # sending this anonymous clone to a transport whose
                        # credentials are not available. Try once more with
                        # that config ignored, using the URL as written,
                        # before giving up. Other definitive failures (a 404,
                        # a missing ref) are reported as-is.
                        if is_auth_failure(e) and self._clone_ignoring_ambient_config(
                            repo_url, cache_path, clone_options, guard_path
                        ):
                            break
                        pc_logging.error("Failed to clone repo %s after %d retries", self.import_config_url, attempt)
                        raise RuntimeError(f"Failed to clone repo: {e}") from e
            attempt += 1
