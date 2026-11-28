#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What changed in a package between two of its states, object by object.

A state is a revision (a commit id, a tag, a branch, 'HEAD'), 'STAGED' -- what
the git index holds -- or 'WORKTREE', the files on disk (see
'partcad.package_versions'). The package is loaded at both, into the same
context, and every object either declares is compared by what it *means* rather
than by the lines of a file:

* its declaration, written out the way 'pc copy' writes one
  ('partcad.serialize'): rendered, normalized, defaults left out -- so a
  reformatted line is no change, and a new default is one;
* the files it is built from, by content: the 'path:' its declaration names, or
  the files named after it that the default path would be;
* whether any of that touches its geometry: a declaration that differs only in
  what the shape cache leaves out ('desc', 'comments', 'qual', ...) changes
  nothing that is built.

Every Operations view that asks "what changed" asks this: the revisions of one
object, what is staged and what is not, and Impact.
"""

import hashlib
import os
import typing

from partcad_utils.object_names import NAMED_KINDS, SECTIONS

from . import logging as pc_logging
from . import package_versions, serialize

# The file a package is declared in, which belongs to every object of it.
PACKAGE_FILE = "partcad.yaml"

# How an object changed, as each change row says it.
ADDED = "added"
REMOVED = "removed"
DECLARATION = "declaration"
SOURCE = "source"

# The most files of a package that are read to tell which changed: a package
# with more is compared by its objects alone.
_FILES_LIMIT = 5000

# The keys of a package's own declaration that are not about the package: the
# sections objects are declared in, and what loading it adds.
_NOT_PACKAGE_KEYS = frozenset(SECTIONS.values()) | {"name", "isRoot", "importUrl", "path", "type", "includePaths"}


def _non_geometric_keys() -> frozenset:
    from .shape import _NON_GEOMETRIC_CONFIG_KEYS

    return _NON_GEOMETRIC_CONFIG_KEYS


def package_at(ctx, package: str, state: typing.Optional[str]):
    """'package' at 'state' -- None or 'WORKTREE' for the files on disk -- or None where it is not there.

    Raises ValueError for 'STAGED' while the index has conflicts, and for a
    state that holds the package but could not be loaded at it. The parent of
    a first commit ('<sha>~1') is before the history: nothing is there.
    """
    if not state or state == package_versions.WORKTREE:
        # As the files are now: a 'partcad.yaml' edited since the package was
        # loaded is read again (a stat, when nothing changed).
        reload = getattr(ctx, "reload_changed_packages", None)
        if reload is not None:
            try:
                reload([package])
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("%s: could not tell whether it changed on disk: %s" % (package, e))
        return ctx.get_project(package)
    if state == package_versions.STAGED:
        # An index with conflicts holds no tree: that is an answer of its own,
        # and not a package with nothing in it.
        current = ctx.get_project(package)
        repository = package_versions.repository_of(current.config_dir) if current is not None else None
        if repository is not None:
            package_versions.index_tree(repository)
    if package_versions._PARENT.match(state):
        current = ctx.get_project(package)
        repository = package_versions.repository_of(current.config_dir) if current is not None else None
        if repository is not None and package_versions.before_history(repository, state):
            return None
    try:
        found = ctx.get_project(package_versions.versioned_name(package, state))
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s is not there at %s: %s" % (package, state, e))
        found = None
    if found is None:
        # Not there is an answer; there and not loaded is not, and would be
        # read as every object of it removed.
        current = ctx.get_project(package)
        repository = package_versions.repository_of(current.config_dir) if current is not None else None
        if repository is not None and package_versions.declares_package_at(repository, state):
            raise ValueError("%s is at %s, but could not be loaded there: see the log" % (package, state))
    return found


def _configs(project, kind: str) -> dict:
    if project is None:
        return {}
    try:
        return dict(project.object_configs(kind) or {})
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s: could not list its %s declarations: %s" % (project.name, kind, e))
        return {}


def _relative(path: str) -> typing.Optional[str]:
    """A path a declaration names, as a path inside its package with '/' separators; None for one outside it."""
    if not isinstance(path, str) or not path or "://" in path or os.path.isabs(path):
        return None
    normalized = os.path.normpath(path).replace(os.sep, "/")
    if normalized == ".." or normalized.startswith("../"):
        return None
    return normalized


# The extensions the file of each type has where its declaration names no
# 'path:' (see each factory's 'locate_source'), by kind and type; a kind's ''
# entry is its type when the declaration says none.
_EXTENSIONS = {
    "cadquery": (".py",),
    "build123d": (".py",),
    "sdf": (".py",),
    "chili3d": (".chili",),
    "step": (".step", ".stp"),
    "stl": (".stl",),
    "3mf": (".3mf",),
    "obj": (".obj",),
    "brep": (".brep",),
    "gltf": (".gltf", ".glb"),
    "scad": (".scad",),
    "svg": (".svg",),
    "dxf": (".dxf",),
    "assy": (".assy",),
}
_DEFAULT_TYPE = {"assembly": "assy"}
# Types made of other objects or of nothing but their declaration: no file.
_NO_FILE = frozenset({"alias", "enrich", "basic", "ai-cadquery", "ai-build123d", "ai-openscad"})
# What is written next to an object rather than read to build it: a rendered
# drawing or picture is not a source of the object, even named after it.
_OUTPUTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".svg", ".md", ".txt", ".html"})


def object_files(project, kind: str, name: str) -> list:
    """The files of 'project' that '<kind> <name>' is built from, as paths inside the package.

    The 'path:' its declaration names, or the default path of its type --
    '<name>' and the type's extension ('FileSource.locate_source') -- and the
    files it says it reads ('dependencies:'). A type PartCAD does not know the
    extension of is taken to read the files named after the object, rendered
    pictures and drawings left out.
    """
    if project is None:
        return []
    try:
        config = project.object_config(kind, name) or {}
    except Exception:  # pylint: disable=broad-except
        config = {}
    if not isinstance(config, dict):
        return []
    found = []
    declared = _relative(config.get("path"))
    kind_type = config.get("type") or _DEFAULT_TYPE.get(kind)
    if declared is not None:
        found.append(declared)
    elif kind_type not in _NO_FILE and kind not in ("interface", "scene"):
        stem = config.get("orig_name") or name.partition(";")[0]
        # A name may have directories in it ('brackets/left'), and its file is in them.
        within, _, base = stem.rpartition("/")
        directory = os.path.join(project.config_dir, *within.split("/")) if within else project.config_dir
        extensions = _EXTENSIONS.get(kind_type)
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            entries = []
        for entry in entries:
            path = os.path.join(directory, entry)
            # A symbolic link is a file of it whether or not what it points at
            # is there: it is compared by what it says ('_digest').
            if not entry.startswith(base + ".") or not (os.path.islink(path) or os.path.isfile(path)):
                continue
            extension = entry[len(base) :].lower()
            if (extension in extensions) if extensions else (extension not in _OUTPUTS):
                found.append(within + "/" + entry if within else entry)
    for dependency in config.get("dependencies") or []:
        rel = _relative(dependency) if isinstance(dependency, str) else None
        if rel is not None and rel not in found:
            found.append(rel)
    return found


def _digest(path: str, repository=None) -> typing.Optional[str]:
    """What a file holds, as git would store it: the id of its blob; a symbolic link by what it says.

    A file of a working tree is read through its repository's filters --
    'core.autocrlf', '.gitattributes' -- as 'git add' would read it, so that
    a file checked out with CRLF line ends on Windows is the blob a revision
    holds and no change from it. A file written out of a revision, or in no
    repository, is that blob as it is. Read a piece at a time by libgit2.

    A link is what git keeps of it -- its target, as text -- and not what it
    points at, which may be outside the package and change without any
    revision of it changing.
    """
    import pygit2

    try:
        if os.path.islink(path):
            return hashlib.sha256(b"link:" + os.fsencode(os.readlink(path))).hexdigest()
        if repository is not None:
            # Its path in the working tree, with '/', is what git's filters are
            # looked up by: given a Windows path, libgit2 does not take it for
            # one of the working tree's and applies none.
            workdir = os.path.realpath(repository.repo.workdir)
            within = os.path.relpath(os.path.realpath(path), workdir).replace(os.sep, "/")
            return str(repository.repo.hashfile(path, as_path=within))
        return str(pygit2.hashfile(path))
    except (OSError, ValueError, pygit2.GitError):
        return None


def object_state(project, kind: str, name: str) -> typing.Optional[dict]:
    """What '<kind> <name>' of 'project' is, as two states of it are compared by; None where it is not declared."""
    if project is None:
        return None
    try:
        if project.object_config(kind, name) is None:
            return None
        declared = serialize.declaration(project, kind, name)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s:%s could not be read: %s" % (project.name, name, e))
        return None
    text = serialize.yaml_text(name, declared)
    if isinstance(declared, dict):
        skipped = _non_geometric_keys()
        geometric = serialize.yaml_text(name, {key: value for key, value in declared.items() if key not in skipped})
    else:
        geometric = text
    repository = package_versions.repository_of(project.config_dir)
    files = {
        rel: _digest(os.path.join(project.config_dir, *rel.split("/")), repository)
        for rel in object_files(project, kind, name)
    }
    return {"declaration": text, "geometric": geometric, "files": files}


def compare_object(before: typing.Optional[dict], after: typing.Optional[dict]) -> typing.Optional[dict]:
    """How an object changed between two of its 'object_state's: {'how', 'geometry', 'prose'}; None when it did not."""
    if before is None and after is None:
        return None
    if before is None:
        return {"how": [ADDED], "geometry": True, "prose": False}
    if after is None:
        return {"how": [REMOVED], "geometry": True, "prose": False}
    how = []
    if before["declaration"] != after["declaration"]:
        how.append(DECLARATION)
    if before["files"] != after["files"]:
        how.append(SOURCE)
    if not how:
        return None
    geometry = before["geometric"] != after["geometric"] or SOURCE in how
    return {"how": how, "geometry": geometry, "prose": not geometry}


def _sub_packages(directory: str) -> set:
    """The directories directly or deeper below 'directory' that hold a package of their own."""
    found = set()
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if root != directory and PACKAGE_FILE in files:
            found.add(os.path.relpath(root, directory).replace(os.sep, "/"))
            dirs[:] = []
    return found


def package_files(project) -> typing.Optional[dict]:
    """Every file of 'project' itself -- none of its sub-packages' -- by path inside it, with its digest.

    {} for no package; None for one with more files than are compared
    ('_FILES_LIMIT'), which is not the same as having none of them.
    """
    if project is None or not os.path.isdir(getattr(project, "config_dir", "") or ""):
        return {}
    top = project.config_dir
    # The files on disk are a working tree's: what git ignores there, and does
    # not track, is not in any revision or in the index, so it is no
    # difference from them either. A file git tracks is one whatever an ignore
    # rule says, dotfiles included. A snapshot of a revision or of the index
    # is in no repository, and is all tracked.
    repository = package_versions.repository_of(top)
    tracked = _tracked(repository)
    found = {}
    for root, dirs, files in os.walk(top):
        # A link to a directory is a file to git -- the link, not what it
        # points at -- and is compared as one ('_digest'), not walked into.
        links = [d for d in dirs if os.path.islink(os.path.join(root, d))]
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in links
            and d not in (".git", "__pycache__")
            and not os.path.isfile(os.path.join(root, d, PACKAGE_FILE))
        )
        for name in sorted(files + links):
            if name == package_versions.GUARD:
                continue
            rel = os.path.relpath(os.path.join(root, name), top).replace(os.sep, "/")
            if repository is not None and _ignored(repository, rel, tracked):
                continue
            found[rel] = None
            if len(found) > _FILES_LIMIT:
                return None
    for rel in found:
        found[rel] = _digest(os.path.join(top, *rel.split("/")), repository)
    return found


def _tracked(repository) -> frozenset:
    if repository is None:
        return frozenset()
    try:
        repository.repo.index.read(False)
        return frozenset(entry.path for entry in repository.repo.index)
    except Exception:  # pylint: disable=broad-except
        return frozenset()


def _ignored(repository, rel: str, tracked=frozenset()) -> bool:
    path = "/".join(part for part in (repository.relpath, rel) if part)
    if path in tracked:
        return False
    try:
        return bool(repository.repo.path_is_ignored(path))
    except Exception:  # pylint: disable=broad-except
        return False


def _package_declaration(project) -> dict:
    config = getattr(project, "config_obj", None) or {}
    return {key: value for key, value in config.items() if key not in _NOT_PACKAGE_KEYS}


def qualified(package: str, name: str) -> str:
    return "%s:%s" % (package, name)


def changes(
    ctx,
    package: str,
    before: typing.Optional[str] = "HEAD",
    after: typing.Optional[str] = None,
    only=None,
    projects: typing.Optional[tuple] = None,
) -> dict:
    """What changed in 'package' from the state 'before' to the state 'after' (None: the working tree).

    {'package', 'from', 'to', 'objects', 'files', 'package_changed'}: 'objects'
    is one row per object that changed, {'kind', 'name', 'object', 'how',
    'geometry', 'prose'}; 'files' the files no object is built from that were
    added, removed or modified ({'path', 'how'}); 'package_changed' whether the
    package's own declaration -- its dependencies, its settings -- changed.
    'only' is a (kind, name) to compare that object alone. 'projects' is the
    package at the two states, where the caller has loaded it already: one
    reading of each, for everything it says about them. 'files_compared' is
    false for a package of more files than are compared one by one.

    A side the package is not at (a revision before it existed, an index it is
    not in) is compared as empty: everything on the other side was added, or
    removed.
    """
    if projects is not None:
        left, right = projects
    else:
        left = package_at(ctx, package, before)
        right = package_at(ctx, package, after)
    if left is None and right is None:
        raise ValueError("%s is at neither %s nor %s" % (package, before, after or package_versions.WORKTREE))
    rows = []
    named = {PACKAGE_FILE}
    kinds = [only[0]] if only else list(NAMED_KINDS)
    for kind in kinds:
        names = [only[1]] if only else sorted(set(_configs(left, kind)) | set(_configs(right, kind)))
        for name in names:
            a = object_state(left, kind, name)
            b = object_state(right, kind, name)
            for state in (a, b):
                if state is not None:
                    named.update(state["files"])
            changed = compare_object(a, b)
            if changed is None:
                continue
            rows.append({"kind": kind, "name": name, "package": package, "object": qualified(package, name), **changed})
    files = []
    package_changed = False
    files_compared = True
    if not only:
        old = package_files(left)
        new = package_files(right)
        if old is None or new is None:
            # Too many files to compare one by one: say nothing of them rather
            # than call the ones not listed added or removed -- and say so.
            old = new = {}
            files_compared = False
        for rel in sorted(set(old) | set(new)):
            if rel in named:
                continue
            if rel not in old:
                files.append({"path": rel, "how": ADDED})
            elif rel not in new:
                files.append({"path": rel, "how": REMOVED})
            elif old[rel] != new[rel]:
                files.append({"path": rel, "how": "modified"})
        package_changed = _package_declaration(left) != _package_declaration(right)
    return {
        "package": package,
        "from": before or package_versions.WORKTREE,
        "to": after or package_versions.WORKTREE,
        "objects": rows,
        "files": files,
        "files_compared": files_compared,
        "package_changed": package_changed,
    }
