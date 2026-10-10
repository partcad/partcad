#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an implementation runs, as a key: the code of the package it comes from.

A cached analysis, route or simulation (see 'cache_artifacts') is keyed on the
question and on what answers it. "What answers it" used to be the
implementation's own script and PartCAD's wrapper -- and an implementation is
rarely one file. 'partcad-sim-mujoco' keeps what its exporter, its reader and
its simulator share in 'mujoco_common.py'; the Gazebo plugin draws its pictures
in 'snapshot_raster.py'; PartCAD's own wrappers import 'wrapper_common' and
'ocp_serialize'. A release of a plugin that changed only such a module was
answered with the result the old module produced, until '--cache-bypass'.

So the key now covers **the package the implementation comes from**, as two
things, each covering what the other cannot:

* **its Python sources**: every '.py' file under the package's directory, by
  path relative to it and by content. That is what the script can import, and
  it is the only thing that sees an edit to a package somebody is working on
  locally, which has no revision to read. It is *only* the Python sources, and
  that is deliberate: a package is also where PartCAD writes what it produces
  -- an analysis keeps its model beside the package, a render its pictures and
  its README -- so a key over every file would be moved by the run it keys, and
  nothing would ever be found. PartCAD writes no '.py' file into a package.
* **its revision, when PartCAD fetched it from git**: the commit the clone is
  at. That covers what the first cannot -- a data file the plugin reads, a
  native library it ships -- for exactly the packages whose contents are a
  release somebody else made. A local package has none to read, and a revision
  alone would miss the edit that is the whole reason for a local package.

Both are what the package *is*, never where it is or when it was touched: paths
are relative and '/'-separated, line endings are normalised, and no
modification time or absolute path reaches the key. An entry written on one
machine is found on another that has the same plugin, which is what #753
promised ('Implementation.environment_cache_key' keeps the same rule for the
sandbox).

**Cheap**, because it is asked on every run and every 'pc test' verdict: a file
is read and hashed once per process, and after that only when its size or its
modification time changes. That costs one 'stat' per source file per run, which
is what makes a local edit invalidate in a long-lived daemon without reading the
package again; the modification time decides only whether to read a file again,
never what the key is. A file written in the last few seconds is read on every
call until it settles (see 'directory_key'), because two quick edits of the same
length can leave its timestamp as it was. A git revision is read once per
package object, because a managed clone changes only when its package is fetched
again, which makes a new one.
"""

import hashlib
import os
import threading
import time
import typing
import weakref

from . import logging as pc_logging

# Directories that hold no source a script imports: version control, caches,
# environments. Hidden directories are skipped as a whole, which covers '.git',
# '.venv' and the rest.
_SKIPPED_DIRECTORIES = frozenset({"__pycache__", "node_modules", "site-packages", "venv"})

# The file every package is declared in. A directory below the package that has
# one is another package, with sources of its own, and keys its own runs.
_PACKAGE_FILE = "partcad.yaml"

# How recently a file may have been written before its timestamp is trusted to
# tell a later write apart. Two seconds is the coarsest clock a file system
# PartCAD runs on keeps (FAT); one more is margin.
_RACY_NS = 3 * 1_000_000_000

_lock = threading.Lock()
# directory -> (what the files looked like, the key they had). See 'directory_key'.
_directories: typing.Dict[str, typing.Tuple[tuple, str]] = {}
# package -> its git revision, or None. See 'package_key'.
_revisions: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _sources(directory: str) -> typing.List[typing.Tuple[str, str]]:
    """The Python sources of the package in 'directory', as (relative path, path), sorted."""
    found = []
    for root, dirs, files in os.walk(directory):
        kept = []
        for name in dirs:
            if name.startswith(".") or name in _SKIPPED_DIRECTORIES:
                continue
            if os.path.isfile(os.path.join(root, name, _PACKAGE_FILE)):
                continue
            kept.append(name)
        dirs[:] = sorted(kept)
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(root, name)
                found.append((os.path.relpath(path, directory).replace(os.sep, "/"), path))
    return found


def _content(path: str) -> bytes:
    """A source file as the key reads it: line endings normalised, so a checkout's are not in it."""
    with open(path, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def directory_key(directory: str) -> str:
    """The Python sources under 'directory', as one hash.

    Recomputed only when a file was added, removed, or changed size or
    modification time since the last call for this directory -- which is a
    'stat' per file per call, and a read of every file only when one of them
    moved.

    Except while a file is *racy*, which is git's word for it: modified so
    recently that another write could still land within the same timestamp.
    Two edits of the same length inside one tick of the file system's clock
    leave the size and the modification time exactly as they were, so a
    remembered key would hide the second one. A directory with such a file is
    hashed afresh on every call until its files have settled, which is never
    for long, and costs only the package somebody is editing right now.
    """
    directory = os.path.abspath(directory)
    sources = _sources(directory)
    seen = []
    newest = 0
    for relative, path in sources:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        seen.append((relative, stat.st_size, stat.st_mtime_ns))
        newest = max(newest, stat.st_mtime_ns)
    seen = tuple(seen)
    settled = time.time_ns() - newest > _RACY_NS

    with _lock:
        known = _directories.get(directory)
    if settled and known is not None and known[0] == seen:
        return known[1]

    hasher = hashlib.sha256()
    for relative, path in sources:
        try:
            content = _content(path)
        except OSError:
            # Gone between the walk and the read: it is not part of what runs.
            continue
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0%d\0" % len(content))
        hasher.update(content)
    key = "py:" + hasher.hexdigest()
    with _lock:
        _directories[directory] = (seen, key)
    return key


def _git_revision(project) -> typing.Optional[str]:
    """The commit a package PartCAD fetched from git is at, or None.

    Only for a package imported as ``type: git``. A local package that happens
    to sit inside somebody's own repository has a revision too, but it is the
    revision of a tree they are editing, and the edit is what has to count.
    """
    if getattr(project, "import_config_type", None) != "git":
        return None
    try:
        return _revisions[project]
    except (KeyError, TypeError):
        pass
    revision = None
    try:
        import pygit2

        repository = pygit2.discover_repository(project.config_dir)
        if repository:
            revision = str(pygit2.Repository(repository).head.target)
    except Exception as e:  # pylint: disable=broad-except
        # No revision is a key with less in it, not a key that cannot be made:
        # the sources still are.
        pc_logging.debug("%s: no git revision to key its implementations on: %s" % (project.name, e))
    try:
        _revisions[project] = revision
    except TypeError:
        pass
    return revision


def package_key(project) -> str:
    """What runs when a package's implementation does: its sources, and its revision if it has one."""
    key = directory_key(project.config_dir)
    revision = _git_revision(project)
    if revision:
        key += ";git:" + revision
    return key


def wrappers_key() -> str:
    """PartCAD's own wrappers, which run every implementation and import each other."""
    return directory_key(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wrappers"))
