#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A package at a revision of its repository: '[<path>/]<name>@<revision>'.

A reference names a package by where it is loaded ('//pub/std/metric'), which is
whatever is checked out there: the working tree for the package the user is
standing in, the commit a dependency is pinned to for one PartCAD downloaded.
Writing '@<revision>' after the package's name names the package *as it was* at
that revision instead -- a commit id, a tag or a branch of the repository the
package's files are in -- so an object can point at the bracket of last week's
release while the bracket in the working tree moves on:

    //pub/std/metric@v1.2:m3-bolt
    ../brackets@3f2a9c1e:corner
    :widget                       (no revision: the package as loaded, as always)

**Every revision is a package of its own in the same context, named after its
commit.** '//pkg@v1.2' and '//pkg@main' resolve to a commit, and the package is
loaded once, as '//pkg@<the full commit id>' -- its objects are
'//pkg@<sha>:<name>', and a reference it makes to itself (relative, or by the
name it declares for itself, see 'Project.relocate') stays inside that revision.
The other names it was asked for by are *aliases* of that one package
('Context.project_aliases'), not second copies: two spellings of one commit are
one package, and two revisions of one package are two.

**The files come from '~/.partcad/git', never from the working tree.** The
commit's tree is written out of the repository's object database into a
directory named after the repository and the commit, beside the copies of the
dependencies PartCAD downloads, and read from there -- so uncommitted edits are
not part of any revision, and a revision is the same files however often it is
read. A package without '@' is loaded the way it always was, under its plain
name: the working tree's for the package the user is in, and the downloaded
copy's for a dependency.

A dependency PartCAD downloaded is itself checked out at a commit, with nothing
of anybody's in its working tree, so '//pkg@<that commit>' *is* the package
already loaded as '//pkg': it is answered with that package, as an alias, rather
than written out and loaded a second time (see 'Context.get_versioned_project').

What a revision cannot reach is a relative reference *out of* the package
('../other:part'): that names the other package as it is loaded now, because the
revision is of this package's repository, and a sibling may be in another one.
"""

import os
import threading
import typing
import uuid

import pygit2
from filelock import FileLock
from pygit2.enums import FileMode

from . import logging as pc_logging

# What separates a package's name from the revision it is asked for at.
SEPARATOR = "@"

# How many characters of a commit id a person is shown.
SHORT_SHA = 8

# Written last into an exported revision, so that a directory that is there is
# told apart from one an interrupted export left behind.
GUARD = ".partcad.git.exported"

# How many commits a listing of a package's revisions goes back at most.
REVISIONS_LIMIT = 500

# The first line of a Git LFS pointer, which is what such a file's blob holds.
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"

_export_locks: dict[str, threading.Lock] = {}
_export_locks_lock = threading.Lock()


def short(sha: typing.Optional[str]) -> typing.Optional[str]:
    """The first 'SHORT_SHA' characters of a commit id, which is how one is shown."""
    return None if sha is None else sha[:SHORT_SHA]


def is_versioned(package_path: typing.Optional[str]) -> bool:
    """Whether a package path names a revision anywhere along it."""
    return isinstance(package_path, str) and SEPARATOR in package_path


def split(package_path: str) -> typing.Optional[tuple]:
    """'//a/b@rev' as ('//a/b', 'rev'); None for a path naming no revision.

    The revision is everything after the first '@': a branch may hold a '/'
    ('feature/x'). A package *inside* a revision ('//a@<sha>/sub', which is how
    the sub-packages and the dependencies of a revision are named) is told apart
    by 'candidates', which tries the longest revision first.
    """
    if not is_versioned(package_path):
        return None
    base, _, revision = package_path.partition(SEPARATOR)
    return base, revision


def candidates(package_path: str) -> list:
    """Every (package, revision, the rest of the path) 'package_path' can be read as, longest revision first.

    '//a@feature/x/sub' is the branch 'feature/x' and the package 'sub' in it,
    or the branch 'feature' and 'x/sub' -- which one only the repository can
    say, so both are offered, in that order.
    """
    found = split(package_path)
    if found is None:
        return []
    base, revision = found
    parts = revision.split("/")
    result = []
    for count in range(len(parts), 0, -1):
        result.append((base, "/".join(parts[:count]), "/".join(parts[count:])))
    return result


def versioned_name(base: str, revision: str) -> str:
    """The name a package is loaded under at a revision."""
    return "%s%s%s" % (base, SEPARATOR, revision)


def unversioned(package_path: str) -> str:
    """The package a versioned name is a revision of, and the rest of its path ('//a@x/sub' -> '//a/sub')."""
    found = split(package_path)
    if found is None:
        return package_path
    base, revision = found
    rest = revision.split("/", 1)[1] if "/" in revision else ""
    if not rest:
        return base
    from partcad_utils.utils import get_child_project_path

    return get_child_project_path(base, rest)


def revision_root(package_name: str) -> typing.Optional[tuple]:
    """For a package loaded at a revision or inside one: (the package asked for, the revision it was loaded as).

    '//a@<sha>/sub' is ('//a', '//a@<sha>'): the package whose revision was
    asked for, and what it is called at that revision. None for a package that
    is not inside a revision.
    """
    found = split(package_name)
    if found is None:
        return None
    base, revision = found
    return base, versioned_name(base, revision.split("/", 1)[0])


def _is_builtin(package: str) -> bool:
    from .output import BUILTIN_ROOT_PACKAGE

    return package == BUILTIN_ROOT_PACKAGE or package.startswith(BUILTIN_ROOT_PACKAGE + "/")


def rebase(package_name: str, pattern: str) -> str:
    """A reference written inside a revision, pointed into that revision.

    A revision of '//a' was written against '//a', so what it says of '//a' and
    of the packages under it ('//a:x', '//a/sub:y') it says of itself:
    '//a@<sha>:x', '//a@<sha>/sub:y'. Anything else it names - a package beside
    it, PartCAD's built-in ones, a package already named at a revision - is left
    as it is. So is a relative reference, which is already read against the
    package's own, versioned, name.
    """
    root = revision_root(package_name)
    if root is None or not isinstance(pattern, str) or not pattern.startswith("/"):
        return pattern
    from partcad_utils.utils import split_resource_path

    package, rest = split_resource_path(pattern)
    if package is None:
        package, rest = pattern, None
    if is_versioned(package) or _is_builtin(package):
        return pattern
    base, versioned = root
    trimmed = base.rstrip("/")
    if package.rstrip("/") == trimmed or (base == "//" and package == "//"):
        rebased = versioned
    elif base == "//" and package.startswith("//"):
        rebased = versioned + "/" + package[2:]
    elif package.startswith(trimmed + "/"):
        rebased = versioned + package[len(trimmed) :]
    else:
        return pattern
    return rebased if rest is None else rebased + ":" + rest


def check_revision(revision: str) -> None:
    """Refuse a revision that cannot be one: empty, or holding what a reference uses as a separator."""
    if not revision:
        raise ValueError("No revision is given after '%s'" % SEPARATOR)
    for character in (":", ";", " ", SEPARATOR):
        if character in revision:
            raise ValueError("'%s' is not a revision: it contains '%s'" % (revision, character))


class Repository:
    """The git repository a package's files are in, and where in it the package is."""

    def __init__(self, repo: pygit2.Repository, relpath: str):
        self.repo = repo
        # The package's directory relative to the repository's working tree,
        # with '/' separators; '' for a package at its root.
        self.relpath = relpath

    @property
    def identity(self) -> str:
        """What names this repository in '~/.partcad/git': where it comes from, or where it is.

        Its origin's URL where it has one, so that a revision of a package is one
        directory however many copies of the repository it was asked through --
        the working tree, a dependency's download, a second download of it at
        another pin.
        """
        try:
            return self.repo.remotes["origin"].url or self.repo.path
        except (KeyError, ValueError):
            return self.repo.path

    def head(self) -> typing.Optional[str]:
        try:
            if self.repo.head_is_unborn:
                return None
            return str(self.repo.head.target)
        except pygit2.GitError:
            return None


def exported_sha(path: str) -> typing.Optional[str]:
    """The commit a directory was written out of, for one inside an exported revision; None otherwise.

    Found by the guard 'export' leaves at the top of what it writes, looked for
    in the directory and every directory above it.
    """
    if not path:
        return None
    here = os.path.abspath(path)
    while True:
        guard = os.path.join(here, GUARD)
        if os.path.isfile(guard):
            try:
                with open(guard, "r", encoding="utf-8") as f:
                    return f.read().strip() or None
            except OSError:
                return None
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def repository_of(config_dir: str) -> typing.Optional[Repository]:
    """The repository the directory 'config_dir' is in, or None when it is in none.

    None for a revision written out by 'export' too: it is a commit of a
    repository rather than a repository of its own, whatever happens to be
    around it (a home directory kept in git would otherwise answer for it).
    """
    if not config_dir or not os.path.isdir(config_dir):
        return None
    if exported_sha(config_dir) is not None:
        return None
    try:
        path = pygit2.discover_repository(config_dir)
    except Exception:  # pylint: disable=broad-except
        return None
    if path is None:
        return None
    try:
        repo = pygit2.Repository(path)
    except Exception:  # pylint: disable=broad-except
        return None
    if repo.is_bare or repo.workdir is None:
        return None
    workdir = os.path.realpath(repo.workdir)
    here = os.path.realpath(config_dir)
    if not (here == workdir or here.startswith(workdir.rstrip(os.sep) + os.sep)):
        return None
    relpath = os.path.relpath(here, workdir).replace(os.sep, "/")
    return Repository(repo, "" if relpath == "." else relpath)


def _local_commit(repo: pygit2.Repository, revision: str) -> typing.Optional[pygit2.Commit]:
    """What 'revision' names in what the repository already has: a commit id, a tag, a branch."""
    for candidate in (
        revision,
        "refs/tags/%s" % revision,
        "refs/heads/%s" % revision,
        "refs/remotes/origin/%s" % revision,
    ):
        try:
            found = repo.revparse_single(candidate)
        except (KeyError, ValueError, pygit2.GitError):
            continue
        try:
            return found.peel(pygit2.Commit)
        except (ValueError, pygit2.GitError):
            continue
    return None


def resolve(repository: Repository, revision: str, fetch: bool = False, user_config=None) -> str:
    """The commit id 'revision' names in the package's repository.

    With 'fetch', a revision the repository does not have is asked of its origin
    once -- which is what a downloaded dependency needs, since it holds the one
    commit it is pinned to and nothing else. The working tree of the package the
    user is in is never fetched into: what it lacks is theirs to fetch.
    """
    check_revision(revision)
    commit = _local_commit(repository.repo, revision)
    if commit is None and fetch:
        from . import project_factory_git as git

        try:
            git._fetch(repository.repo, revision, depth=1, user_config=user_config)
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("Could not fetch '%s': %s" % (revision, e))
        commit = _local_commit(repository.repo, revision)
    if commit is None:
        raise ValueError("There is no revision '%s' in the repository of this package" % revision)
    return str(commit.id)


def _lfs_object(repo: pygit2.Repository, data: bytes) -> typing.Optional[bytes]:
    """The file an LFS pointer stands for, when the repository has it locally."""
    if not data.startswith(_LFS_POINTER) or len(data) > 1024:
        return None
    oid = None
    for line in data.decode("utf-8", "replace").splitlines():
        if line.startswith("oid sha256:"):
            oid = line.split(":", 1)[1].strip()
    if not oid or len(oid) < 5:
        return None
    path = os.path.join(repo.path, "lfs", "objects", oid[0:2], oid[2:4], oid)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def _write_tree(repo: pygit2.Repository, tree: pygit2.Tree, dest: str) -> None:
    """Write 'tree' out under 'dest', the way a checkout would."""
    os.makedirs(dest, exist_ok=True)
    for entry in tree:
        path = os.path.join(dest, entry.name)
        mode = entry.filemode
        if mode == FileMode.TREE:
            _write_tree(repo, repo[entry.id], path)
        elif mode == FileMode.COMMIT:
            # A submodule: its own repository, which this one only points at.
            os.makedirs(path, exist_ok=True)
        elif mode == FileMode.LINK:
            target = repo[entry.id].data.decode("utf-8", "replace")
            try:
                os.symlink(target, path)
            except (OSError, NotImplementedError):
                # A system that will not make one (Windows without the
                # privilege): what git writes there too, the target as text.
                with open(path, "w", encoding="utf-8") as f:
                    f.write(target)
        else:
            data = repo[entry.id].data
            data = _lfs_object(repo, data) or data
            with open(path, "wb") as f:
                f.write(data)
            if mode == FileMode.BLOB_EXECUTABLE:
                os.chmod(path, 0o755)


def export(repository: Repository, sha: str, git_cache_dir: str) -> str:
    """The directory the commit 'sha' of 'repository' is written out in, writing it if it is not there yet.

    Named the way a downloaded dependency's copy is ('cache_dir_name'), after
    the repository and the commit, so the two sit side by side in
    '~/.partcad/git' and the healthcheck and 'pc system status' see both. Written
    into a temporary directory and moved into place, under a lock, so that two
    processes asking for one revision at once write it once and neither reads it
    half written.

    Returns the directory of the repository's working tree; the package is at
    'repository.relpath' under it.
    """
    from .project_factory_git import cache_dir_name

    os.makedirs(git_cache_dir, exist_ok=True)
    name = cache_dir_name(repository.identity, sha)
    dest = os.path.join(git_cache_dir, name)
    guard = os.path.join(dest, GUARD)
    if os.path.exists(guard):
        return dest

    with _export_locks_lock:
        lock = _export_locks.setdefault(name, threading.Lock())
    with lock, FileLock(dest + ".lock"):
        if os.path.exists(guard):
            return dest
        commit = repository.repo.get(sha)
        if commit is None:
            raise ValueError("The commit %s is missing from %s" % (sha, repository.repo.path))
        commit = commit.peel(pygit2.Commit)
        staging = "%s.tmp-%s" % (dest, uuid.uuid4().hex[:8])
        try:
            _write_tree(repository.repo, commit.tree, staging)
            with open(os.path.join(staging, GUARD), "w", encoding="utf-8") as f:
                f.write(sha)
            if os.path.exists(dest):
                # An export that never finished: replaced, not read.
                from .project_factory_git import _remove_tree

                _remove_tree(dest)
            os.replace(staging, dest)
        finally:
            if os.path.exists(staging):
                from .project_factory_git import _remove_tree

                _remove_tree(staging)
        pc_logging.debug("Wrote out %s of %s in %s" % (short(sha), repository.identity, dest))
    return dest


def _subtree_id(commit: pygit2.Commit, relpath: str):
    """The id of the tree at 'relpath' in 'commit', or None where the commit has nothing there."""
    if not relpath:
        return commit.tree.id
    try:
        return commit.tree[relpath].id
    except (KeyError, ValueError):
        return None


def revisions(repository: Repository, limit: int = REVISIONS_LIMIT) -> list:
    """The commits that changed the package, newest first, from the one checked out.

    A commit is listed when what it has at the package's directory differs from
    what its first parent had there -- 'git log --first-parent -- <dir>' -- so a
    package that shares its repository with others lists its own history and
    nobody else's. A package at the repository's root lists every commit.

    Each is {'sha', 'short', 'summary', 'author', 'time'}: the time as seconds
    since the epoch, which is what a reader formats in its own time zone.
    """
    head = repository.head()
    if head is None:
        return []
    found = []
    try:
        walker = repository.repo.walk(head, pygit2.enums.SortMode.TOPOLOGICAL | pygit2.enums.SortMode.TIME)
        walker.simplify_first_parent()
    except (pygit2.GitError, ValueError, KeyError):
        return []
    relpath = repository.relpath
    for commit in walker:
        here = _subtree_id(commit, relpath)
        if here is None:
            # Not there yet in this commit, nor (on a first-parent walk) before it.
            break
        parents = commit.parent_ids
        if parents:
            try:
                parent = repository.repo[parents[0]]
            except (KeyError, ValueError):
                parent = None
            # A shallow copy stops here: the parent was never downloaded.
            before = _subtree_id(parent, relpath) if parent is not None else None
            if before == here:
                continue
        found.append(
            {
                "sha": str(commit.id),
                "short": short(str(commit.id)),
                "summary": commit.message.splitlines()[0] if commit.message else "",
                "author": commit.author.name if commit.author is not None else "",
                "time": commit.commit_time,
            }
        )
        if len(found) >= limit:
            break
    return found
