#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What uses what, among what a context has loaded.

Two questions the IDE's Operations tab asks, one in each direction:

* **Used by.** Which objects refer to this object, or to anything in this
  package (at a revision, for the Revisions tab), and how many times each.
  An assembly that places a bolt four times uses it four times.
* **Uses.** Which packages a package declares as its dependencies, and which
  commit each one is at.

**Only what is loaded is looked at.** The declarations of every package the
context has read, and the children of every assembly and scene it has built --
nothing is loaded or built to answer, because "what uses this" over everything
that *could* be loaded is a question about the whole world. So the answer grows
as the context does: an assembly not built yet is counted by what its
declaration names, and once it is built, by what it places.

A reference is counted where it is written, the way PartCAD reads it: resolved
against the package that wrote it ('Project.resolve'), so ':bolt', 'bolt' and
'//pkg:bolt' written in '//pkg' are one object, and a name asked for at a
revision by a tag is the revision it names ('Context.project_aliases').
"""

import typing

from . import logging as pc_logging
from . import package_versions
from . import reference as pc_reference
from . import revision as pc_revision
from .serialize import PROSE_KEYS, REFERENCE_KEYS

# The kinds of object that refer to others, in the order they are listed.
REFERRING_KINDS = ("sketch", "interface", "part", "assembly", "scene")

# The keys 'reference.source_of' reads, which are read together rather than one by one.
_SOURCE_KEYS = frozenset({"source", "source_resolved", "package", "project"})


def _canonical(ctx, package: str) -> str:
    """The name a package is loaded under, for a name that is another name of it.

    A revision named by a tag or a branch that nothing has loaded yet is read as
    the commit it names in the package's repository, as it would be loaded -
    without loading it, and without fetching anything: what is asked is which
    revision a declaration means, not what is in it. Each '@' along the name is
    read so ('//outer@v1/dep@v2'), against the package it follows, as far as
    what is loaded already says.
    """
    known = ctx.project_aliases.get(package)
    if known is not None or package in ctx.projects or not package_versions.is_versioned(package):
        return known or package
    base, selector = package_versions.split(package)
    found = _at_revision(ctx, base, selector)
    return package if found is None else found


def _at_revision(ctx, name: str, selector: str) -> typing.Optional[str]:
    """The loaded name of the package 'name' at the revision 'selector' starts with, and of what the rest names below it.

    None when 'name' is not loaded or has no repository, or nothing in it is
    what 'selector' names - which nothing here fetches.
    """
    loaded = ctx.project_aliases.get(name, name)
    current = ctx.projects.get(loaded)
    repository = package_versions.repository_of(current.config_dir) if current is not None else None
    if repository is None:
        return None
    for revision, rest in package_versions.selector_candidates(selector):
        try:
            sha = package_versions.resolve(repository, revision)
        except ValueError:
            continue
        versioned = package_versions.versioned_name(loaded, sha)
        return _below(ctx, ctx.project_aliases.get(versioned, versioned), rest)
    return None


def _below(ctx, name: str, rest: str) -> str:
    """The loaded name of what 'rest' names below the package 'name', which may be at a revision of its own."""
    if not rest:
        return name
    from partcad_utils.utils import get_child_project_path

    path, separator, selector = rest.partition(package_versions.SEPARATOR)
    child = get_child_project_path(name, path) if path else name
    if not separator:
        return child
    found = _at_revision(ctx, child, selector)
    return found if found is not None else child + package_versions.SEPARATOR + selector


def _strip_parameters(name: str) -> str:
    return name.partition(";")[0]


def _looks_like_reference(value: str) -> bool:
    head = value.partition(";")[0]
    if not head or any(character.isspace() for character in head) or "://" in head:
        return False
    return ":" in head


# What a reference written under a key is to the object writing it, as the
# Dependencies and Used By views say it ('How'); any other key says itself.
_HOW = {
    "sketch": "sketch",
    "openings": "opening",
    "visual": "visual",
    "implements": "implements",
    "inherits": "inherits",
    "part": "placed",
    "assembly": "placed",
    "scene": "placed",
    "links": "placed",
    "children": "placed",
    "mates": "mate",
    "ports": "port",
}


def _walk(project, config, found: list, depth: int = 0, how: typing.Optional[str] = None) -> None:
    """Every '<package>:<object>' 'config' names, resolved against 'project', into 'found' with how it is named."""
    if depth > 32:
        return
    if isinstance(config, dict):
        for key, value in config.items():
            if key in PROSE_KEYS or key in _SOURCE_KEYS:
                continue
            said = _HOW.get(key, how or key)
            if key in REFERENCE_KEYS and isinstance(value, str) and value and ":" not in value:
                # A bare name where only an object can be: one of this package's.
                found.append((project.name, _strip_parameters(value), _HOW.get(key, key)))
                continue
            _walk(project, value, found, depth + 1, said)
    elif isinstance(config, (list, tuple)):
        for item in config:
            _walk(project, item, found, depth + 1, how)
    elif isinstance(config, str) and _looks_like_reference(config):
        try:
            package, name = project.resolve(config)
        except Exception:  # pylint: disable=broad-except
            return
        found.append((package, _strip_parameters(name), how or "reference"))


def references_how(project, kind: str, config) -> list:
    """Every object the declaration 'config' of a 'kind' in 'project' refers to, as (package, name, how), once per mention.

    'how' is what the reference is to the object: 'source (alias)' or 'source
    (enrich)' for what it is made from, 'placed' for what it places, 'sketch',
    'implements', 'inherits', 'opening', 'visual' -- or the key it is written
    under.
    """
    found = []
    if not isinstance(config, dict):
        if isinstance(config, str) and kind in ("sketch", "part", "assembly", "scene"):
            # The short form of an alias: 'cube: //other:cube'.
            config = {"type": "alias", "source": config}
        else:
            return found
    if "source" in config or "package" in config or "project" in config:
        try:
            source = pc_reference.source_of(project, project.name, config, kind)
            package, name = pc_reference.split(source)
            said = config.get("type") if config.get("type") in ("alias", "enrich") else None
            found.append((package, _strip_parameters(name), "source (%s)" % said if said else "source"))
        except Exception:  # pylint: disable=broad-except
            pass
    _walk(project, config, found)
    return found


def references(project, kind: str, config) -> list:
    """Every object the declaration 'config' of a 'kind' in 'project' refers to, as (package, name), once per mention."""
    return [(package, name) for package, name, _how in references_how(project, kind, config)]


def _loaded_projects(ctx) -> list:
    """Every package the context has loaded, once each, PartCAD's built-in ones and its revisions left out.

    A revision of a package ('//pkg@v1', '//pkg@STAGED') is loaded to be
    compared or listed: it is the package's history, not one more package
    using anything.
    """
    from .output import BUILTIN_PATHS

    seen = set()
    result = []
    for name, project in list(ctx.projects.items()):
        if project is None or id(project) in seen or name in BUILTIN_PATHS:
            continue
        if package_versions.is_versioned(name) or getattr(project, "revision_sha", None):
            continue
        seen.add(id(project))
        result.append(project)
    return result


def _uses(ctx, project, kind: str, name: str, config, wanted, hows: typing.Optional[list] = None) -> int:
    """How many times the object 'kind' 'name' of 'project' refers to what 'wanted' accepts; each 'how' into 'hows'."""
    count = 0
    reference_type = isinstance(config, dict) and config.get("type") in pc_reference.REFERENCE_TYPES
    if kind in ("assembly", "scene") and not reference_type:
        # Built: what it places, each placement once. An alias or an enrich
        # places nothing of its own; what it names is counted below.
        built = project.objects(kind).get(name)
        children = getattr(built, "children", None) if built is not None else None
        if children:
            for child in children:
                item = getattr(child, "item", None)
                package = getattr(item, "project_name", None)
                placed = _strip_parameters(getattr(item, "name", "") or "")
                if package is not None and wanted(_canonical(ctx, package), placed):
                    count += 1
                    if hows is not None:
                        hows.append("placed")
    for package, object_name, how in references_how(project, kind, config):
        if wanted(_canonical(ctx, package), object_name):
            count += 1
            if hows is not None:
                hows.append(how)
    return count


def used_by(ctx, wanted: typing.Callable[[str, str], bool], exclude: typing.Callable[[str], bool] = None) -> list:
    """The loaded objects that refer to something 'wanted(package, name)' accepts, each with how many times.

    'exclude(package)' leaves a package's own objects out: what a package uses of
    itself is not what it is used by. Sorted by package and name.
    """
    result = []
    for project in _loaded_projects(ctx):
        if exclude is not None and exclude(project.name):
            continue
        for kind in REFERRING_KINDS:
            # What the package has read, without asking a plugin-backed one to
            # list what it has not.
            configs = project._object_configs.get(kind)
            for name, config in list((configs or {}).items()):
                hows = []
                try:
                    count = _uses(ctx, project, kind, name, config, wanted, hows)
                except Exception as e:  # pylint: disable=broad-except
                    pc_logging.debug("%s:%s: could not read what it refers to: %s" % (project.name, name, e))
                    continue
                if count:
                    result.append(
                        {
                            "object": "%s:%s" % (project.name, name),
                            "package": project.name,
                            "name": name,
                            "kind": kind,
                            "count": count,
                            "how": sorted(set(hows)),
                        }
                    )
    result.sort(key=lambda row: (row["package"], row["name"]))
    return result


def _is_within(name: str, parent: str) -> bool:
    return name == parent or name.startswith(parent.rstrip("/") + "/")


def object_used_by(ctx, package: str, name: str) -> list:
    """The loaded objects that refer to '<package>:<name>'."""
    package = _canonical(ctx, package)

    def wanted(other_package, other_name):
        return other_package == package and other_name == name

    def same(other):
        # The object itself is not one of its own users; the rest of its
        # package may well be.
        return False

    rows = used_by(ctx, wanted, same)
    return [row for row in rows if not (row["package"] == package and row["name"] == name)]


def package_used_by(ctx, package: str) -> list:
    """The loaded objects outside 'package' that refer to anything in it."""
    package = _canonical(ctx, package)
    return used_by(ctx, lambda other, _name: other == package, lambda other: other == package)


def revision_names(ctx, base: str, sha: str) -> set:
    """Every name the package 'base' at the commit 'sha' is loaded and known under in 'ctx'."""
    versioned = package_versions.versioned_name(base, sha)
    names = {versioned}
    target = ctx.project_aliases.get(versioned, versioned)
    names.add(target)
    names.update(alias for alias, aliased in ctx.project_aliases.items() if aliased == target)
    return names


def revision_used_by(ctx, base: str, sha: str) -> list:
    """The loaded objects that refer to anything in 'base' at the commit 'sha', or in a package inside it.

    Which includes the objects referring to 'base' itself, without a revision,
    where 'base' is a copy PartCAD downloaded at exactly that commit: that is the
    revision they use.
    """
    names = revision_names(ctx, base, sha)

    def inside(package):
        return any(_is_within(package, name) for name in names)

    return used_by(ctx, lambda other, _name: inside(other), inside)


# The dependency types whose files are not in this checkout: a package downloaded,
# unpacked or served by something else.
_FETCHED = ("git", "tar", "external")


def load_workspace(ctx, project=None) -> int:
    """Load every package of the workspace below 'project' (the root by default), and say how many there are.

    The packages whose files are in this checkout: sub-folders, and dependencies
    declared with a local 'path'. Not what the workspace downloads - a 'pc init'
    package imports the whole public index, and loading that to ask who uses
    a bracket would be a download of everything. What 'Used By' looks at is
    what is loaded (see the module's description); this is how a command makes
    that the workspace rather than whatever happened to be asked for before.
    """
    start = project if project is not None else ctx.root
    seen = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current is None or current.name in seen or getattr(current, "broken", False):
            continue
        seen.add(current.name)
        declared = current.dependencies() or {}
        from partcad_utils.utils import get_child_project_path

        # By the names the package itself gives them, which is what its
        # 'dependencies:' are keyed by, whatever the package is called.
        for child in current.get_child_project_names(absolute=False) or []:
            config = declared.get(child)
            if isinstance(config, dict) and (config.get("type") in _FETCHED or config.get("url")):
                continue
            try:
                stack.append(ctx.get_project(get_child_project_path(current.name, child)))
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("Not loading %s: %s" % (child, e))
    return len(seen)


def dependencies(ctx, project) -> list:
    """The packages 'project' declares as dependencies, each with the commit it is at.

    {'name': as declared, 'package': the name it is loaded under here,
    'current': the same package without a revision, where the context has it,
    'sha', 'short': its commit, or None for a package in no repository, and
    'versioned': the name that loads it at that commit}. Loading a dependency
    may download it: this is what the view is opened for.
    """
    from .context import _dependency_package_name

    rows = []
    for dependency, config in (project.dependencies() or {}).items():
        package = _dependency_package_name(project.name, dependency, config)
        loaded = ctx.get_project(package)
        sha = pc_revision.package_revision(loaded) if loaded is not None else None
        if sha is None and isinstance(config, dict):
            pinned = config.get("revision")
            from .project_factory_git import looks_like_commit_id

            if isinstance(pinned, str) and looks_like_commit_id(pinned):
                sha = pinned
        current = package_versions.unversioned(package)
        current_project = ctx.get_project(current) if current != package else loaded
        rows.append(
            {
                "name": dependency,
                "package": package,
                "current": current if current_project is not None else None,
                "sha": sha,
                "short": package_versions.short(sha),
                "versioned": (
                    package_versions.versioned_name(current, sha)
                    if sha is not None and current_project is not None
                    else None
                ),
                "type": config.get("type") if isinstance(config, dict) else None,
            }
        )
    return rows


# ---- Dependencies and the packages that depend -------------------------------


def _kind_of(ctx, package: str, name: str) -> typing.Optional[str]:
    try:
        loaded = ctx.get_project(package)
        return loaded.object_kind(name) if loaded is not None else None
    except Exception:  # pylint: disable=broad-except
        return None


def object_dependencies(ctx, project, kind: str, name: str) -> list:
    """What '<kind> <name>' of 'project' names, and once built places: one row per object, with how and how many times.

    {'object', 'package', 'name', 'kind', 'how', 'count', 'revision',
    'short'}, 'revision' being the commit the package it comes from is at.
    Asking what kind each is may load the package it is in.
    """
    name = _strip_parameters(name)
    config = project.object_config(kind, name)
    if config is None:
        raise ValueError("%s declares no %s '%s'" % (project.name, kind, name))
    found = {}

    def note(package: str, object_name: str, how: str) -> None:
        package = _canonical(ctx, package)
        row = found.setdefault(
            (package, object_name),
            {
                "object": "%s:%s" % (package, object_name),
                "package": package,
                "name": object_name,
                "how": [],
                "count": 0,
            },
        )
        row["count"] += 1
        if how not in row["how"]:
            row["how"].append(how)

    raw = project._object_configs.get(kind, {}).get(name, config)
    reference_type = isinstance(raw, dict) and raw.get("type") in pc_reference.REFERENCE_TYPES
    if kind in ("assembly", "scene") and not reference_type:
        built = project.objects(kind).get(name)
        for child in getattr(built, "children", None) or []:
            item = getattr(child, "item", None)
            package = getattr(item, "project_name", None)
            placed = _strip_parameters(getattr(item, "name", "") or "")
            if package is not None and placed:
                note(package, placed, "placed")
    for package, object_name, how in references_how(project, kind, raw):
        if package == project.name and object_name == name:
            continue
        note(package, object_name, how)
    rows = []
    for row in found.values():
        row["kind"] = _kind_of(ctx, row["package"], row["name"])
        loaded = ctx.get_project(row["package"]) if row["kind"] is not None else None
        sha = pc_revision.package_revision(loaded) if loaded is not None else None
        row["revision"] = sha
        row["short"] = package_versions.short(sha)
        rows.append(row)
    rows.sort(key=lambda row: (row["package"], row["name"]))
    return rows


def _identity(project) -> typing.Optional[tuple]:
    """(the repository a package's files are in, where in it the package is), or None for one in no repository."""
    directory = getattr(project, "config_dir", None)
    if not directory:
        return None
    exported = package_versions.exported_sha(directory)
    repository = package_versions.repository_of(directory)
    if repository is None or exported is not None:
        return None
    return repository.identity, repository.relpath


def _behind(repository, pinned: typing.Optional[str]) -> typing.Optional[int]:
    """How many revisions of the package are newer than the commit 'pinned', in its own repository; None when unknown."""
    if not pinned:
        return None
    for count, row in enumerate(package_versions.revisions(repository)):
        if row["sha"].startswith(str(pinned).lower()):
            return count
    return None


def package_dependencies(ctx, project) -> dict:
    """What a package depends on: {'package', 'declared', 'undeclared', 'subpackages'}.

    'declared' is 'dependencies' (each declared dependency with the commit it
    is at) with what each declaration says: its location, the branch it
    tracks, the commit it is pinned to. 'undeclared' the packages its objects
    reach without declaring them -- through an index the workspace root
    imports, say -- each with the objects that do. 'subpackages' the packages
    in directories below it, which need no pin: the commit checked out is it.
    """
    from .context import _dependency_package_name
    from .output import BUILTIN_PATHS

    declared_config = project.dependencies() or {}
    declared = dependencies(ctx, project)
    for row in declared:
        config = declared_config.get(row["name"])
        if isinstance(config, dict):
            row["location"] = config.get("url") or config.get("path")
            row["track"] = config.get("track")
            pinned = config.get("revision")
            row["pinned"] = None if pinned is None else str(pinned)
    declared_packages = [
        _dependency_package_name(project.name, name, config) for name, config in declared_config.items()
    ]
    children = [
        child for child in (project.get_child_project_names(absolute=False) or []) if child not in declared_config
    ]
    from partcad_utils.utils import get_child_project_path

    subpackages = [{"name": child, "package": get_child_project_path(project.name, child)} for child in children]

    def ours(package: str) -> bool:
        if _is_within(package, project.name) or package in BUILTIN_PATHS:
            return True
        return any(_is_within(package, dependency) for dependency in declared_packages)

    undeclared = {}
    kinds = {}
    for kind in REFERRING_KINDS:
        for name, config in list((project.object_configs(kind) or {}).items()):
            kinds.setdefault(name, kind)
            try:
                mentioned = references_how(project, kind, config)
            except Exception:  # pylint: disable=broad-except
                continue
            for package, _object_name, _how in mentioned:
                package = package_versions.unversioned(_canonical(ctx, package))
                if ours(package):
                    continue
                users = undeclared.setdefault(package, {})
                users[name] = users.get(name, 0) + 1
    return {
        "package": project.name,
        "declared": declared,
        "undeclared": [
            {
                "package": package,
                "users": [
                    {"name": name, "object": "%s:%s" % (project.name, name), "kind": kinds.get(name), "count": count}
                    for name, count in sorted(users.items())
                ],
            }
            for package, users in sorted(undeclared.items())
        ],
        "subpackages": subpackages,
    }


def package_dependents(ctx, project) -> list:
    """The loaded packages that declare 'project' as a dependency: {'package', 'name', 'type', 'pinned', 'short', 'behind'}.

    Found by the package each declaration loads, and by where its files come
    from: a dependency fetched from the very repository 'project' is in, at
    its directory, is 'project' at another commit. 'behind' is how many
    revisions of 'project' are newer than the one it is pinned to.
    """
    from .context import _dependency_package_name

    target = project.name
    identity = _identity(project)
    repository = package_versions.repository_of(project.config_dir)
    rows = []
    for other in _loaded_projects(ctx):
        if other.name == target or _is_within(other.name, target):
            continue
        for name, config in (other.dependencies() or {}).items():
            loaded_as = _dependency_package_name(other.name, name, config)
            matches = _canonical(ctx, loaded_as) == target
            if not matches:
                loaded = ctx.projects.get(loaded_as)
                if loaded is not None and identity is not None:
                    found = package_versions.repository_of(loaded.config_dir)
                    matches = found is not None and (found.identity, found.relpath) == identity
            if not matches:
                continue
            kind = config.get("type") if isinstance(config, dict) else None
            pinned = config.get("revision") if isinstance(config, dict) else None
            rows.append(
                {
                    "package": other.name,
                    "name": name,
                    "type": kind or ("local" if isinstance(config, dict) and config.get("path") else None),
                    "pinned": None if pinned is None else str(pinned),
                    "short": package_versions.short(str(pinned)) if pinned else None,
                    "behind": _behind(repository, pinned) if repository is not None else None,
                }
            )
    rows.sort(key=lambda row: (row["package"], row["name"]))
    return rows
