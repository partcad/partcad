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
    revision a declaration means, not what is in it.
    """
    known = ctx.project_aliases.get(package)
    if known is not None or package in ctx.projects or not package_versions.is_versioned(package):
        return known or package
    for base, revision, rest in package_versions.candidates(package):
        current = ctx.projects.get(base)
        repository = package_versions.repository_of(current.config_dir) if current is not None else None
        if repository is None:
            continue
        try:
            sha = package_versions.resolve(repository, revision)
        except ValueError:
            continue
        versioned = package_versions.versioned_name(base, sha)
        versioned = ctx.project_aliases.get(versioned, versioned)
        if not rest:
            return versioned
        from partcad_utils.utils import get_child_project_path

        return get_child_project_path(versioned, rest)
    return package


def _strip_parameters(name: str) -> str:
    return name.partition(";")[0]


def _looks_like_reference(value: str) -> bool:
    head = value.partition(";")[0]
    if not head or any(character.isspace() for character in head) or "://" in head:
        return False
    return ":" in head


def _walk(project, config, found: list, depth: int = 0) -> None:
    """Every '<package>:<object>' 'config' names, resolved against 'project', into 'found'."""
    if depth > 32:
        return
    if isinstance(config, dict):
        for key, value in config.items():
            if key in PROSE_KEYS or key in _SOURCE_KEYS:
                continue
            if key in REFERENCE_KEYS and isinstance(value, str) and value and ":" not in value:
                # A bare name where only an object can be: one of this package's.
                found.append((project.name, _strip_parameters(value)))
                continue
            _walk(project, value, found, depth + 1)
    elif isinstance(config, (list, tuple)):
        for item in config:
            _walk(project, item, found, depth + 1)
    elif isinstance(config, str) and _looks_like_reference(config):
        try:
            package, name = project.resolve(config)
        except Exception:  # pylint: disable=broad-except
            return
        found.append((package, _strip_parameters(name)))


def references(project, kind: str, config) -> list:
    """Every object the declaration 'config' of a 'kind' in 'project' refers to, as (package, name), once per mention."""
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
            found.append((package, _strip_parameters(name)))
        except Exception:  # pylint: disable=broad-except
            pass
    _walk(project, config, found)
    return found


def _loaded_projects(ctx) -> list:
    """Every package the context has loaded, once each, PartCAD's built-in ones left out."""
    from .output import BUILTIN_PATHS

    seen = set()
    result = []
    for name, project in list(ctx.projects.items()):
        if project is None or id(project) in seen or name in BUILTIN_PATHS:
            continue
        seen.add(id(project))
        result.append(project)
    return result


def _uses(ctx, project, kind: str, name: str, config, wanted) -> int:
    """How many times the object 'kind' 'name' of 'project' refers to what 'wanted' accepts."""
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
                if package is not None and wanted(_canonical(ctx, package), getattr(item, "name", "")):
                    count += 1
    for package, object_name in references(project, kind, config):
        if wanted(_canonical(ctx, package), object_name):
            count += 1
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
                try:
                    count = _uses(ctx, project, kind, name, config, wanted)
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
