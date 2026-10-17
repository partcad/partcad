#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The work behind ``pc update``: move each tracked dependency's pin, then fetch.

Loading a package never moves a git dependency: whatever was downloaded first
is what the package is built from, for as long as nothing asks for newer (see
``ProjectFactoryGit._wants_refresh``). ``pc update`` is what asks, and it moves
a dependency in the *file* rather than in the cache:

1. Every git dependency that says ``track: <branch>``, in a package of this
   workspace, has its ``revision:`` rewritten to the commit that branch is at
   now. That is the whole of the update: a change to ``partcad.yaml`` that
   ``git diff`` shows, that can be reviewed, committed and reverted, and that
   every other checkout of the package builds from as soon as it has it.
2. Every package is loaded again from the files as they now are, with every
   import fetched anew. The new pins are downloaded, and a dependency that still
   names a branch the old way (``revision: main``, or no revision at all) is
   moved to that branch's newest commit -- which is what ``pc update`` always did
   for those, and still the most it can do for one that tracks nothing.

"This workspace" is the packages whose files are the user's to edit: the root,
and every package reached from it through ``local`` dependencies and
subfolders. A package reached through an import is somebody else's release.
Its pins are its maintainers' to move, and its files are a copy in the cache
that the next download replaces, so nothing below an import is edited.
"""

import os

from ... import consts
from ... import logging as pc_logging
from ... import project_factory_git as rfg
from ...dependency_pin import set_dependency_revision
from ...utils import get_child_project_path


def _dependency_type(config: dict):
    """The transport a dependency declaration names, guessed the way an import guesses it."""
    if config.get("type"):
        return config["type"]
    if "url" in config:
        return "tar" if str(config["url"]).endswith(".tar.gz") else "git"
    if "path" in config:
        return "local"
    return None


def _dependency_path(project, name: str, config: dict) -> str:
    """The package path a dependency of 'project' is loaded at."""
    if config.get("onlyInRoot", False):
        return "//" + name
    return get_child_project_path(project.name, name)


def _local_children(project, is_root: bool) -> list[str]:
    """The packages below 'project' that are read from this workspace rather than imported."""
    children = []
    for name, config in (project.dependencies() or {}).items():
        if not isinstance(config, dict) or _dependency_type(config) != "local":
            continue
        if config.get("onlyInRoot", False) and not is_root:
            # Loaded only when the package declaring it is the root, as the
            # traversal does ('Context._import_all_recursive').
            continue
        children.append(_dependency_path(project, name, config))

    config_dir = getattr(project, "config_dir", None)
    if config_dir and os.path.isdir(config_dir):
        for entry in sorted(os.scandir(config_dir), key=lambda e: e.name):
            if entry.is_dir() and os.path.exists(os.path.join(entry.path, consts.DEFAULT_PACKAGE_CONFIG)):
                children.append(get_child_project_path(project.name, entry.name))
    return children


def workspace_packages(ctx) -> list:
    """The root package and every package reached from it without going through an import.

    Only what is local is loaded to find them, so nothing is downloaded: a git
    dependency is read off the declaration, never followed.
    """
    root = ctx.get_project(ctx.name)
    if root is None:
        return []
    packages = []
    seen = set()
    queue = [root]
    while queue:
        project = queue.pop(0)
        if project.name in seen:
            continue
        seen.add(project.name)
        packages.append(project)
        for child_path in _local_children(project, project is root):
            child = ctx.get_project_from(project, child_path)
            if child is not None:
                queue.append(child)
    return packages


def tracked_dependencies(ctx) -> list[tuple]:
    """Every git dependency this workspace declares with a 'track:', as (package, name, config)."""
    tracked = []
    for project in workspace_packages(ctx):
        for name, config in (project.dependencies() or {}).items():
            if not isinstance(config, dict) or _dependency_type(config) != "git":
                continue
            if config.get("track"):
                tracked.append((project, name, config))
    return tracked


def pin_tracked_dependencies(ctx) -> dict:
    """Step 1 of 'update': rewrite each tracked dependency's 'revision:' to where its branch is.

    Returns how many were moved ("pinned"), how many were where their branch
    is already ("current"), and how many could not be moved ("failed"), each of
    which has been reported.
    """
    stats = {"pinned": 0, "current": 0, "failed": 0}
    tracked = tracked_dependencies(ctx)
    if tracked and ctx.user_config.offline:
        pc_logging.error("Not moving %d tracked dependencies: PartCAD is configured to work offline" % len(tracked))
        stats["failed"] += len(tracked)
        return stats

    for project, name, config in tracked:
        dependency = _dependency_path(project, name, config)
        url = config.get("url")
        track = str(config["track"])
        if not url:
            pc_logging.error("Failed to update %s: it tracks '%s' but names no 'url'" % (dependency, track))
            stats["failed"] += 1
            continue

        try:
            _, commit = rfg.tracked_commit(ctx.user_config, url, track)
        except rfg.GIT_ERRORS as e:
            pc_logging.error("Failed to find where '%s' of %s is: %s" % (track, url, e))
            stats["failed"] += 1
            continue

        current = config.get("revision")
        current = None if current is None else str(current).strip()
        if current and rfg.looks_like_commit_id(current) and commit.startswith(current.lower()):
            pc_logging.debug("%s is at the tip of '%s' already: %s" % (dependency, track, commit))
            stats["current"] += 1
            continue

        reason = set_dependency_revision(project.config_path, name, commit)
        if reason is not None:
            pc_logging.error(
                "Failed to pin %s to the tip of '%s' in the 'partcad.yaml' of %s: %s. Set 'revision: %s' in it by hand."
                % (dependency, track, project.name, reason, commit)
            )
            stats["failed"] += 1
            continue

        pc_logging.info(
            "Pinned %s to %s, the tip of '%s'%s"
            % (dependency, commit, track, " (was '%s')" % current if current else "")
        )
        stats["pinned"] += 1
    return stats


def update(ctx) -> dict:
    """Move every tracked dependency's pin to its branch, then fetch every import again.

    Returns the counts 'pin_tracked_dependencies' returns, and "count", how many
    packages there are once it is done.
    """
    stats = pin_tracked_dependencies(ctx)

    # From the files as they are now, and every import resolved anew: a warm
    # context has packages loaded long before, at what were the pins then.
    ctx.reload_all_packages()
    ctx.refresh_imports = True
    try:
        stats["count"] = len(list(ctx.get_all_packages()))
    finally:
        ctx.refresh_imports = False
    return stats
