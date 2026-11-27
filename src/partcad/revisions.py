#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the IDE's Revisions tab is drawn from: a package's history, and an object compared with one of its revisions.

The list is the commits that changed the package (see
'package_versions.revisions'), newest first. A package in no repository -- or in
one where nothing of it was ever committed -- has none, and is "not published
yet".

A comparison is of two texts, the object as the context holds it now and the
same object loaded at the revision ('<package>@<sha>:<name>', see
'package_versions'), each written out the way 'pc copy' would write it
('partcad.serialize') -- so what differs is what the object *means*, and two
spellings of one declaration compare equal. A package is compared by its
'partcad.yaml' as Jinja2 rendered it when PartCAD read it
('ProjectLocal.rendered_config'): the very text PartCAD parsed, rather than a
second rendering of it that could come out otherwise.

The comparison is made here rather than in the IDE, as rows of a side-by-side
view (see 'side_by_side'), because Python has a line differ and the webview has
no business shipping one.
"""

import difflib
import hashlib
import json
import os
import threading
import typing

from . import logging as pc_logging
from . import package_versions
from . import revision as pc_revision
from . import serialize

# The kind a comparison of a whole package is asked for with.
PACKAGE = "package"


def current_project(ctx, project):
    """The package without a revision that 'project' is, or is a revision of; 'project' itself where there is none."""
    if project is None:
        return None
    name = package_versions.unversioned(project.name)
    if name == project.name:
        return project
    return ctx.get_project(name) or project


# How many revisions one page of a listing holds, unless asked for another number.
PAGE = 100


def history(ctx, project, limit: int = PAGE, after: typing.Optional[str] = None) -> dict:
    """{'package', 'published', 'head', 'revisions', 'more', 'next'} of the package 'project' is (or is a revision of).

    Every commit that changed the package's directory, newest first, a page of
    'limit' at a time from after the commit 'after' -- the 'next' of the page
    before, which 'more' says there is. A commit that changed only sub-packages
    of it says which ('in'): the package's directory holds them, and they are
    packages of their own.
    """
    limit = max(1, int(limit))
    current = current_project(ctx, project)
    repository = package_versions.repository_of(current.config_dir) if current is not None else None
    found = (
        package_versions.revisions(repository, limit=limit + 1, after=after)
        if repository is not None
        else package_versions.Revisions()
    )
    rows = list(found[:limit])
    if len(found) > limit:
        following = rows[-1]["sha"]
    elif found.truncated:
        # The walk looked at as many commits as it may: the next page goes on
        # from where it stopped, whether or not it found anything here.
        following = found.scanned
    else:
        following = None
    if repository is not None:
        for row in rows:
            within = _sub_packages_touched(repository, row["sha"])
            if within:
                row["in"] = within
    return {
        "package": current.name if current is not None else None,
        "published": bool(rows) or after is not None,
        "head": repository.head() if repository is not None else None,
        "revisions": rows,
        "more": following is not None,
        "next": following,
    }


def _tree_at(commit, relpath: str):
    if commit is None:
        return None
    try:
        return commit.tree[relpath] if relpath else commit.tree
    except (KeyError, ValueError):
        return None


def changed_paths(repository, sha: str) -> typing.Optional[list]:
    """The paths inside the package that the commit 'sha' changed against its first parent; None when unknown."""
    import pygit2

    repo = repository.repo
    try:
        commit = repo[sha].peel(pygit2.Commit)
    except (KeyError, ValueError, pygit2.GitError):
        return None
    parent = None
    if commit.parent_ids:
        try:
            parent = repo[commit.parent_ids[0]]
        except (KeyError, ValueError):
            return None
    here = _tree_at(commit, repository.relpath)
    before = _tree_at(parent, repository.relpath)
    if not isinstance(here, pygit2.Tree):
        here = None
    if not isinstance(before, pygit2.Tree):
        before = None
    if here is None and before is None:
        return []
    if before is None:
        diff = here.diff_to_tree(swap=True)
    elif here is None:
        diff = before.diff_to_tree()
    else:
        diff = before.diff_to_tree(here)
    paths = set()
    for delta in diff.deltas:
        for path in (delta.old_file.path, delta.new_file.path):
            if path:
                paths.add(path)
    return sorted(paths)


def _sub_packages_touched(repository, sha: str) -> list:
    """The sub-packages a commit changed, when it changed nothing of the package's own; [] otherwise."""
    import pygit2

    paths = changed_paths(repository, sha)
    if not paths:
        return []
    try:
        commit = repository.repo[sha].peel(pygit2.Commit)
        parent = repository.repo[commit.parent_ids[0]] if commit.parent_ids else None
    except (KeyError, ValueError, pygit2.GitError):
        return []
    # A sub-package the commit added is in its tree, and one it deleted in its parent's.
    tops = [top for top in (_tree_at(commit, repository.relpath), _tree_at(parent, repository.relpath)) if top]
    within = set()
    for path in paths:
        parts = path.split("/")
        owner = None
        for depth in range(1, len(parts)):
            candidate = "/".join(parts[:depth])
            if any(_has(top, candidate + "/partcad.yaml") for top in tops):
                owner = candidate
                break
        if owner is None:
            return []
        within.add(owner)
    return sorted(within)


def _has(tree, path: str) -> bool:
    import pygit2

    try:
        return isinstance(tree, pygit2.Tree) and path in tree
    except (KeyError, ValueError):
        return False


def object_text(project, kind: str, name: typing.Optional[str]) -> typing.Optional[str]:
    """The text an object -- or with 'PACKAGE', a whole package -- is compared by; None where there is no such thing."""
    if project is None:
        return None
    if kind == PACKAGE:
        return getattr(project, "rendered_config", None)
    try:
        return serialize.yaml_text(name, serialize.declaration(project, kind, name))
    except ValueError:
        return None


def side_by_side(left: typing.Optional[str], right: typing.Optional[str]) -> list:
    """The rows of a side-by-side comparison of two texts.

    One row per line of either side: {'tag', 'left', 'right', 'leftLine',
    'rightLine'}, where 'tag' is 'equal', 'replace' (a line changed: both
    sides), 'delete' (on the left only) or 'insert' (on the right only), and a
    side with no line in a row is None there. Lines are numbered from 1.
    """
    a = (left or "").splitlines()
    b = (right or "").splitlines()
    rows = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(_row("equal", a, b, i1 + offset, j1 + offset))
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                i = i1 + offset if i1 + offset < i2 else None
                j = j1 + offset if j1 + offset < j2 else None
                if i is not None and j is not None:
                    tag_here = "replace"
                else:
                    tag_here = "delete" if j is None else "insert"
                rows.append(_row(tag_here, a, b, i, j))
        elif tag == "delete":
            for i in range(i1, i2):
                rows.append(_row("delete", a, b, i, None))
        elif tag == "insert":
            for j in range(j1, j2):
                rows.append(_row("insert", a, b, None, j))
    return rows


def _row(tag: str, a: list, b: list, i, j) -> dict:
    return {
        "tag": tag,
        "left": a[i] if i is not None else None,
        "right": b[j] if j is not None else None,
        "leftLine": i + 1 if i is not None else None,
        "rightLine": j + 1 if j is not None else None,
    }


# How many lines of what did not change a unified diff shows around a change, by default: git's.
UNIFIED_CONTEXT = 3


def unified(
    left: typing.Optional[str],
    right: typing.Optional[str],
    from_label: str,
    to_label: str,
    context: int = UNIFIED_CONTEXT,
) -> str:
    """The two texts as a unified diff, the way 'git diff' writes one; empty when they are the same.

    What the command line and an agent read where the IDE shows the two sides
    side by side ('side_by_side'): the same comparison, of the same texts.
    """
    a = (left or "").splitlines(keepends=True)
    b = (right or "").splitlines(keepends=True)
    lines = []
    for line in difflib.unified_diff(a, b, fromfile=from_label, tofile=to_label, n=max(0, int(context))):
        lines.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(lines)


def compare(ctx, project, kind: str, name: typing.Optional[str], revision: str, context: int = UNIFIED_CONTEXT) -> dict:
    """The object now and at 'revision': {'revision', 'short', 'left', 'right', 'same', 'rows', 'unified'}.

    The revision is the left side and the context as it is now the right, the
    way a change reads: from what it was to what it is. A side where the object
    is not declared says so ('missing') and is compared as empty. 'rows' is the
    comparison side by side, for the IDE; 'unified' the same as a unified diff,
    with 'context' lines around each change, for the command line and agents --
    '<package>@<short>:<name>' against '<package>:<name>', or for a package its
    'partcad.yaml' at each.
    """
    current = current_project(ctx, project)
    if current is None:
        raise ValueError("The package is not loaded")
    versioned_name = package_versions.versioned_name(current.name, revision)
    at_revision = ctx.get_project(versioned_name)
    if at_revision is None:
        raise ValueError("%s could not be loaded" % versioned_name)
    # Said by its commit, whatever it was asked by: a downloaded copy answering
    # for its own commit knows it from its repository (see 'revision').
    sha = (
        getattr(at_revision, "revision_sha", None)
        or pc_revision.package_revision(at_revision)
        or package_versions.split(versioned_name)[1]
    )
    left = object_text(at_revision, kind, name)
    right = object_text(current, kind, name)
    short = package_versions.short(sha)
    if kind == PACKAGE:
        from partcad_utils.utils import get_child_project_path

        from_label = get_child_project_path("%s@%s" % (current.name, short), "partcad.yaml")
        to_label = get_child_project_path(current.name, "partcad.yaml")
    else:
        from_label = "%s@%s:%s" % (current.name, short, name)
        to_label = "%s:%s" % (current.name, name)
    return {
        "package": current.name,
        "revision": sha,
        "short": package_versions.short(sha),
        "loaded": at_revision.name,
        "left": {"label": package_versions.short(sha), "missing": left is None},
        "right": {"label": "Current", "missing": right is None},
        "same": (left or "") == (right or ""),
        "rows": side_by_side(left, right),
        "unified": unified(left, right, from_label, to_label, context),
    }


# ---- one object's revisions -------------------------------------------------

_history_lock = threading.Lock()


def _cache_path(ctx) -> str:
    return os.path.join(ctx.user_config.internal_state_dir, "ops", "object-revisions.json")


def _cache_key(ctx, repository, kind: str, name: str, sha: str) -> str:
    # The tags of the context are in the key: an object an 'unless' skips here
    # is not there to have changed, and a context with other tags may see it.
    tags = hashlib.sha256("\n".join(sorted(getattr(ctx, "tags", None) or ())).encode()).hexdigest()[:12]
    # 'v2': what was kept before templates were compared in full is not kept on.
    return "v2|%s|%s|%s|%s|%s|%s" % (repository.identity, repository.relpath, kind, name, sha, tags)


def _read_cache(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            found = json.load(f)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(path: str, cache: dict) -> None:
    temporary = "%s.tmp-%d" % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(temporary, path)
    except OSError as e:
        pc_logging.debug("Could not keep what was found about revisions in %s: %s" % (path, e))


_UNKNOWN = object()


def _declared_files_at(repository, sha: str, kind: str, name: str):
    """The files the object's declaration in the commit's 'partcad.yaml' names -- 'path:' and 'dependencies:' --
    read without rendering it; '_UNKNOWN' where the file cannot be read that way (a Jinja2 template, say)."""
    import pygit2
    import yaml

    from partcad_utils.object_names import SECTIONS

    try:
        commit = repository.repo[sha].peel(pygit2.Commit)
        entry = commit.tree[(repository.relpath + "/" if repository.relpath else "") + "partcad.yaml"]
        data = repository.repo[entry.id].data
    except KeyError:
        return set()
    except (ValueError, pygit2.GitError):
        return _UNKNOWN
    if any(opening in data for opening in (b"{{", b"{%", b"{#")):
        # A Jinja2 template reads as YAML often enough, and names files as
        # the template writes them, not as they are rendered.
        return _UNKNOWN
    try:
        config = yaml.safe_load(data) or {}
    except yaml.YAMLError:
        return _UNKNOWN
    if not isinstance(config, dict):
        return _UNKNOWN
    declared = (config.get(SECTIONS.get(kind, "")) or {}).get(name)
    if not isinstance(declared, dict):
        return set()
    from .changes import _relative

    dependencies = declared.get("dependencies")
    names = [declared.get("path")] + (list(dependencies) if isinstance(dependencies, list) else [])
    return {rel for rel in (_relative(value) for value in names) if rel is not None}


def _touches(repository, sha: str, kind: str, name: str, paths: list) -> bool:
    """Whether a commit that changed 'paths' could have changed the object: its declaration, or a file of it.

    The same files 'changes.object_files' compares: the 'path:' and the
    'dependencies:' its declaration names, and the files named after it beside
    it ('<name>.<extension>', directories in the name included). Where the
    declaration cannot be read without rendering, the commit is compared in
    full rather than passed over.
    """
    if "partcad.yaml" in paths:
        return True
    stem = name.partition(";")[0]
    declared = _declared_files_at(repository, sha, kind, stem)
    if declared is _UNKNOWN:
        return True
    directory, _, base = stem.rpartition("/")
    for path in paths:
        if path in declared:
            return True
        within, _, entry = path.rpartition("/")
        if within == directory and entry.startswith(base + "."):
            return True
    return False


def _how_at(ctx, current, repository, kind: str, name: str, sha: str) -> typing.Optional[list]:
    """How the commit 'sha' changed the object against its first parent: [] when it did not, None when unknown.

    Unknown is a commit whose parent is not here -- a shallow clone -- and is
    never kept: fetching the parent later is what answers it.
    """
    import pygit2

    from . import changes

    paths = changed_paths(repository, sha)
    if paths is None:
        return None
    if not _touches(repository, sha, kind, name, paths):
        return []
    commit = repository.repo[sha].peel(pygit2.Commit)
    after = changes.package_at(ctx, current.name, sha)
    before = changes.package_at(ctx, current.name, str(commit.parent_ids[0])) if commit.parent_ids else None
    found = changes.compare_object(
        changes.object_state(before, kind, name),
        changes.object_state(after, kind, name),
    )
    return found["how"] if found else []


def object_history(ctx, project, kind: str, name: str, limit: int = PAGE, after: typing.Optional[str] = None) -> dict:
    """The revisions that changed '<kind> <name>' itself, newest first: {'package', 'object', 'published', 'head', 'revisions', 'more', 'next'}.

    Of the commits that changed its package (see 'history'), the ones where its
    declaration or a file it is built from changed -- each with how
    ('added', 'removed', 'declaration', 'source'). Only direct changes: a change
    to something it uses is a revision of that other object. A commit that
    touched neither 'partcad.yaml' nor a file of the object is passed over
    without loading anything; the rest are loaded at the commit and its parent
    and compared. What is found is kept in '~/.partcad', since a commit never
    changes. A page looks at up to 'package_versions.REVISIONS_LIMIT' commits
    of the package; 'next' is where the next one goes on from ('after').
    """
    current = current_project(ctx, project)
    name = name.partition(";")[0]
    repository = package_versions.repository_of(current.config_dir) if current is not None else None
    result = {
        "package": current.name if current is not None else None,
        "object": "%s:%s" % (current.name, name) if current is not None else name,
        "kind": kind,
        "published": False,
        "head": repository.head() if repository is not None else None,
        "revisions": [],
        "more": False,
        "next": None,
    }
    if repository is None:
        return result
    limit = max(1, int(limit))
    commits = package_versions.revisions(repository, after=after)
    result["published"] = bool(commits) or after is not None
    path = _cache_path(ctx)
    with _history_lock:
        cache = _read_cache(path)
    dirty = False
    found = []
    following = None
    for row in commits:
        key = _cache_key(ctx, repository, kind, name, row["sha"])
        how = cache.get(key)
        if how is None:
            try:
                how = _how_at(ctx, current, repository, kind, name, row["sha"])
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("%s: could not tell what %s did to it: %s" % (result["object"], row["short"], e))
                how = None
            if how is not None:
                cache[key] = how
                dirty = True
        if how:
            if len(found) == limit:
                following = found[-1]["sha"]
                break
            found.append({**row, "how": how})
    else:
        # Every commit of the package this page could look at was looked at:
        # where there are more, the next page goes on from the last of them.
        if len(commits) >= package_versions.REVISIONS_LIMIT or commits.truncated:
            following = commits[-1]["sha"] if len(commits) >= package_versions.REVISIONS_LIMIT else commits.scanned
    if dirty:
        with _history_lock:
            merged = _read_cache(path)
            merged.update(cache)
            _write_cache(path, merged)
    result["revisions"] = found
    result["more"] = following is not None
    result["next"] = following
    return result


def state_label(state: typing.Optional[str]) -> str:
    """How a state is shown beside a package's name: a commit by its first characters, STAGED and WORKTREE as they are."""
    if not state or state == package_versions.WORKTREE:
        return package_versions.WORKTREE
    if package_versions.is_state(state):
        return state
    return package_versions.short(state) if len(state) == 40 else state


def compare_states(
    ctx,
    project,
    kind: str,
    name: typing.Optional[str],
    before: str,
    after: typing.Optional[str] = None,
    context: int = UNIFIED_CONTEXT,
) -> dict:
    """An object -- or with 'PACKAGE', a package -- at the state 'before' and at the state 'after' (None: the working tree).

    What 'compare' answers for a revision and the working tree, for any two
    states: a commit-ish, 'STAGED' or 'WORKTREE' on either side. For a package
    the answer also lists what changed in it object by object
    ('partcad.changes'), since its 'partcad.yaml' says only part of it; for an
    object, the files it is built from that changed ('sources'). 'same' is
    true only where none of that changed either.
    """
    from . import changes

    current = current_project(ctx, project)
    if current is None:
        raise ValueError("The package is not loaded")
    after = after or package_versions.WORKTREE
    # A revision that names nothing is refused, rather than taken for one the
    # package is not at; a state, and the parent of a first commit, are there.
    repository = package_versions.repository_of(current.config_dir)
    for state in (before, after):
        if package_versions.is_state(state) or repository is None:
            continue
        if not package_versions.before_history(repository, state):
            # Fetched where loading it would fetch it: a dependency PartCAD
            # downloaded holds the commit it is pinned to and little else.
            package_versions.resolve(repository, state, fetch=ctx.is_downloaded(current), user_config=ctx.user_config)
    left_project = changes.package_at(ctx, current.name, before)
    right_project = changes.package_at(ctx, current.name, after)
    if left_project is None and right_project is None:
        raise ValueError("%s could be loaded at neither %s nor %s" % (current.name, before, after))
    left = object_text(left_project, kind, name)
    right = object_text(right_project, kind, name)

    def sha_of(loaded, state):
        if loaded is None or package_versions.is_state(state):
            return None
        return getattr(loaded, "revision_sha", None) or pc_revision.package_revision(loaded)

    left_sha = sha_of(left_project, before)
    right_sha = sha_of(right_project, after)
    left_label = state_label(left_sha or before)
    right_label = state_label(right_sha or after)
    if kind == PACKAGE:
        from partcad_utils.utils import get_child_project_path

        from_label = get_child_project_path("%s@%s" % (current.name, left_label), "partcad.yaml")
        to_label = get_child_project_path("%s@%s" % (current.name, right_label), "partcad.yaml")
    else:
        from_label = "%s@%s:%s" % (current.name, left_label, name)
        to_label = "%s@%s:%s" % (current.name, right_label, name)
    answer = {
        "package": current.name,
        "from": before,
        "to": after,
        "fromRevision": left_sha,
        "toRevision": right_sha,
        "left": {"label": left_label, "missing": left is None},
        "right": {"label": right_label, "missing": right is None},
        "same": (left or "") == (right or ""),
        "rows": side_by_side(left, right),
        "unified": unified(left, right, from_label, to_label, context),
    }
    if kind == PACKAGE:
        try:
            # The very packages the text above was read from: one reading of each state.
            found = changes.changes(ctx, current.name, before, after, projects=(left_project, right_project))
        except ValueError as e:
            pc_logging.debug("%s: %s" % (current.name, e))
        else:
            answer["changes"] = found
            # Not 'same' unless everything was compared: a package of too many
            # files to compare one by one is not known to be the same.
            if found["objects"] or found["files"] or found["package_changed"] or not found["files_compared"]:
                answer["same"] = False
    else:
        # The files it is built from are part of what it is: a change to its
        # script alone is a change, though its declaration reads the same.
        sources = source_changes(
            changes.object_state(left_project, kind, name), changes.object_state(right_project, kind, name)
        )
        answer["sources"] = sources
        if sources:
            answer["same"] = False
    return answer


def source_changes(before: typing.Optional[dict], after: typing.Optional[dict]) -> list:
    """The files an object is built from that differ between two of its 'changes.object_state's: [{'path', 'how'}]."""
    old = (before or {}).get("files") or {}
    new = (after or {}).get("files") or {}
    rows = []
    for path in sorted(set(old) | set(new)):
        if path not in old:
            rows.append({"path": path, "how": "added"})
        elif path not in new:
            rows.append({"path": path, "how": "removed"})
        elif old[path] != new[path]:
            rows.append({"path": path, "how": "modified"})
    return rows
