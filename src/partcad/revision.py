#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which revision of its source repository a package's files come from.

A bill of materials that names a package names something that changes: the same
'//vendor/boards:controller-fw' is a different file after the package publishes
again. For hardware that hardly matters within a build - the part is whatever
the geometry says it is - but for software it is the whole question, because the
file is the artifact. So every software line item carries the commit its package
was read at, and that is what this module answers.

The revision is a property of the *repository the package's files sit in*, not
of the package: a package imported with 'type: git' is read out of the cached
clone at the revision the import asked for, and a package developed locally is
read out of whatever the developer has checked out. Both are answered the same
way here - by discovering the repository the package's configuration directory
belongs to and reading its HEAD - so neither the import mechanism nor the
consumer has to special-case the other. A package that is in no repository at
all (a tarball import, an unpacked directory) has no revision, and says so with
'None' rather than with something invented.
"""

import threading
import typing

import pygit2

from . import logging as pc_logging

# Keyed on the discovered repository path, because that is what the answer is a
# property of: the packages of one repository share one revision, and a
# repository is read once no matter how many of them ask.
_revisions: dict[str, typing.Optional[str]] = {}
_revisions_lock = threading.Lock()


def _repository_path(path: str) -> typing.Optional[str]:
    try:
        return pygit2.discover_repository(path)
    except Exception:  # pylint: disable=broad-except
        # Not in a repository, or the path is unreadable. Neither is a failure
        # worth reporting: a package is perfectly entitled to live outside git.
        return None


def _head_commit(repository_path: str) -> typing.Optional[str]:
    try:
        repo = pygit2.Repository(repository_path)
        if repo.head_is_unborn:
            # A repository with no commit yet. There is no revision to name.
            return None
        return str(repo.head.target)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("Failed to read the revision of %s: %s" % (repository_path, e))
        return None


def package_revision(project) -> typing.Optional[str]:
    """The commit id the package's files were read at, or None.

    'None' means the question has no answer here - the package is not in a git
    repository - and never that the answer failed to be computed and could be
    retried later.
    """
    config_dir = getattr(project, "config_dir", None)
    if not config_dir:
        return None

    repository_path = _repository_path(config_dir)
    if repository_path is None:
        return None

    with _revisions_lock:
        if repository_path in _revisions:
            return _revisions[repository_path]

    revision = _head_commit(repository_path)

    with _revisions_lock:
        _revisions[repository_path] = revision
    return revision


def reset_cache() -> None:
    """Forget the revisions read so far.

    For the tests, and for the one case where the answer genuinely changes
    within a process: a package updated on disk after it was first read.
    """
    with _revisions_lock:
        _revisions.clear()
