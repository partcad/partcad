#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Core-side entry point for 'pc filter'.

``pc filter <filter> <src> <dst>`` leaves the package holding a second object
made of some of the first one's links: the ASSY file of ``src`` with everything
the filter drops taken out of it, written as ``<dst>.assy`` and declared beside
``src``. A sub-assembly somebody keeps referring to -- the head of the logo, one
bay of a rack -- becomes an object with a name, which every operation then works
on: it renders, it exports, it has a bill of materials of its own, suppliers
quote for it.

It is one of two ways to look at part of an assembly, and the two are
deliberately different things. This one writes a **declaration**: a new object
of the package, in the repository, reviewable as a diff, with its own
``connect:`` sections intact. ``pc render --filter`` writes **nothing**: it
filters the assembly it has already built, for one picture, and so can select
inside a part of another package that this file cannot name (see
`partcad.assembly_filter`). Both read the same mask, from
`partcad_utils.assy_filter`, so what they keep is the same links.

The file is filtered rather than the built assembly on purpose. An ASSY file
says how its items were brought together, and that is what makes the result an
assembly somebody can build: the links the filter keeps keep their
``connect:``/``connectPorts:`` sections, their ``how:`` instructions, their
parameters and their comments, and the document is still a document a person
wrote. Rebuilding the file out of an instantiated tree would reduce every one of
those to a hard-coded ``location:``.

What that leaves is one thing to check, and it is the reason the ``connect:``
sections survive at all: a kept link may connect to a dropped one. Nothing in
the schema can see that -- it is a relation between two parts of one document --
so `partcad_utils.assy_lint.check_links` is what sees it, which is the very
check ``pc lint`` runs over every ASSY file of a package. It is run here, over
the file that was just written, so the command that produced the problem is the
command that reports it.
"""

import os

import ruamel.yaml

from partcad_utils import assy_filter, assy_lint

from .. import logging as pc_logging
from ..project import Project
from ..utils import resolve_resource_path

# Which section of 'partcad.yaml' each kind is declared in.
SECTIONS = {"assembly": "assemblies", "scene": "scenes"}

# The only assembly type there is an ASSY file to filter. A 'step' or a 'urdf'
# assembly is a foreign file PartCAD reads; it has no links of its own to select
# from, and 'pc convert assembly -t assy' is what turns one into a file that
# does.
SOURCE_TYPE = "assy"


def _yaml():
    """A round-trip YAML, configured as every other writer here configures it."""
    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    # Wide enough that nothing is folded onto a second line, as
    # 'Project.add_object_config' does and for its reason.
    yaml.width = 4096
    return yaml


def _detect_kind(project: Project, name: str, kind=None) -> str:
    """Whether ``name`` is an assembly or a scene of this package.

    The result follows the source: a filtered assembly is an assembly and a
    filtered scene is a scene, so the caller normally says nothing and this
    answers. A package that declares both under one name is the one case it
    cannot answer, and it says so rather than choosing.
    """
    if kind is not None:
        if kind not in SECTIONS:
            raise ValueError("'%s' is neither an assembly nor a scene" % kind)
        return kind
    declared = [one for one in SECTIONS if project.object_configs(one).get(name) is not None]
    if not declared:
        raise ValueError("'%s' is not an assembly or a scene of %s" % (name, project.name))
    if len(declared) > 1:
        raise ValueError(
            "%s declares both an assembly and a scene called '%s'; name which one with '-a' or '-S'"
            % (project.name, name)
        )
    return declared[0]


def _source_document(project: Project, shape, path: str):
    """The ASSY document to filter, and whether its own text survived.

    Round-trip first, which is what keeps the comments, the quoting and the
    Jinja2 expressions of the file somebody wrote. A templated file is not YAML
    until it has been rendered -- ``{{ param_n }}`` where a value goes is not a
    value -- so such a file is read through the factory that renders it, and the
    caller is told that the result is the rendered document rather than the
    source.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        document = _yaml().load(text)
        if isinstance(document, dict):
            return document, True
        if document is None:
            raise ValueError("%s is empty" % project.rel_path(path))
        raise ValueError("%s does not hold an ASSY document" % project.rel_path(path))
    except ruamel.yaml.YAMLError:
        pass

    # A Jinja2 template. The rendered document is what PartCAD reads, so it is
    # what gets filtered; what is lost is the templating and the comments, and
    # saying so is the honest thing rather than refusing a file that works.
    render = getattr(shape, "rendered_source", None)
    if render is None:
        raise ValueError(
            "%s is not valid YAML, and it is not a template PartCAD can render either" % project.rel_path(path)
        )
    with open(render(), "r", encoding="utf-8") as f:
        document = _yaml().load(f.read())
    if not isinstance(document, dict) or not document:
        raise ValueError("%s does not hold an ASSY document" % project.rel_path(path))
    return document, False


def _target_path(project: Project, name: str) -> str:
    """Where ``<dst>.assy`` goes, refusing a name that leaves the package.

    A '/' in an object's name is a sub-directory, exactly as it is for the files
    the shapes themselves are written to, so the directories a name asks for are
    created. A name that climbs out of the package is not a name.
    """
    root = os.path.abspath(project.config_dir)
    path = os.path.abspath(os.path.join(root, name + ".assy"))
    if not path.startswith(root + os.sep):
        raise ValueError("'%s' names a file outside the package" % name)
    return path


def _declaration(project: Project, kind: str, name: str, path: str, source_name: str):
    """The declaration ``<dst>`` needs, or ``None`` if it already has it.

    A re-run of ``pc filter`` is how a selection is changed, and the declaration
    is where the user puts the file types they want of this object. So a
    declaration that already points at this very file is left exactly as it is,
    and only the file is rewritten.

    Nothing of the source's declaration is carried over, and that is not an
    oversight: a ``map:`` names the links the source externalizes ports of, and
    some of those are the ones the filter just dropped, so inheriting it would
    declare ports of an object that no longer holds them. The same goes for
    ``parameters:``, which the filtered file no longer has anything templated to
    use them. What the new object publishes is the new object's to say.
    """
    existing = project.object_configs(kind).get(name)
    if isinstance(existing, dict) and existing.get("type") == SOURCE_TYPE:
        declared = existing.get("path") or "%s.assy" % existing.get("orig_name", name)
        if os.path.abspath(os.path.join(project.config_dir, declared)) == path:
            return None
    if existing is not None:
        pc_logging.warning(
            "%s: replacing the declaration of the %s '%s'" % (project.name, kind, name),
        )
    return {"type": SOURCE_TYPE, "desc": "A filtered view of '%s'" % source_name}


def _write(path: str, document, round_trip: bool, source_name: str, project: Project) -> None:
    """Write the filtered document, through a temporary file in its directory.

    Opening the real file for writing truncates it before the dump runs, and a
    dump that fails half way through would leave neither the old object nor the
    new one -- the same reason 'actions.assembly.convert.apply_config' writes
    the package configuration this way.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = (
        "# Generated by 'pc filter' from '%s'. Re-run that command to change\n"
        "# what it holds; an edit made here is lost the next time it is run.\n" % source_name
    )
    if not round_trip:
        header += (
            "#\n# The source file is a Jinja2 template, so this is the document it renders\n"
            "# to: its templating and its comments are not carried over.\n"
        )
    tmp_path = "%s.tmp" % path
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(header)
        _yaml().dump(document, f)
    os.replace(tmp_path, path)
    pc_logging.info("Wrote %s" % project.rel_path(path))


def _validate(path: str, kind: str, project: Project) -> int:
    """Check the written file the way ``pc lint`` checks every ASSY file.

    Only the structural half of it -- a ``connect:`` or an ``interferes:`` that
    names a link nothing places -- because that is the half filtering can break:
    a dropped link that something kept was connected to. The schema half cannot
    be broken by dropping nodes, and a finding from it would be about the file
    the user wrote rather than about the filtering, which ``pc lint`` is the
    command to hear it from.

    Returns how many problems were reported.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    flavor = assy_lint.FLAVOR_SCENE if kind == "scene" else assy_lint.FLAVOR_ASSEMBLY
    diagnostics = assy_lint.validate_source(text, assy_lint.schema_for_file(path, flavor))
    found = [one for one in diagnostics if one.code == assy_lint.CODE_LINKS]
    for diagnostic in found:
        pc_logging.error(diagnostic.format(project.rel_path(path)))
    if found:
        pc_logging.error(
            "%s: the filter kept links that are connected to links it dropped. "
            "Name those links in the filter too, or place the kept ones with 'location:'" % project.rel_path(path)
        )
    return len(found)


def filter_object_action(
    project: Project,
    filter_data,
    source_name: str,
    target_name: str,
    kind: str = None,
    dry_run: bool = False,
) -> dict:
    """Write a filtered copy of one assembly or scene as another object.

    ``filter_data`` is the mask as data -- what a client resolved out of the
    ``<filter-file|filter-expression>`` argument on its own machine (see
    `partcad_utils.assy_filter.resolve_spec`), or the mask itself.

    Returns what was done: the kind, the two names, the file written, what the
    filter asked for and could not have, and how many links nothing places any
    more.
    """
    from .assembly.convert import apply_config

    mask = assy_filter.of(filter_data)
    if mask is None:
        raise ValueError("No filter is given")

    source_package, source = resolve_resource_path(project.name, source_name)
    if source_package != project.name:
        owner = project.ctx.get_project(source_package)
        if owner is None:
            raise ValueError("Package '%s' is not found for '%s'" % (source_package, source))
        project = owner
    target_package, target = resolve_resource_path(project.name, target_name)
    if target_package != project.name:
        # The new object is declared in the package the source came from: its
        # links name that package's parts, and a declaration elsewhere would
        # point at an ASSY file written into somebody else's package.
        raise ValueError(
            "'%s' names the package %s, while '%s' is produced by %s; "
            "the filtered copy is declared beside the source" % (target_name, target_package, source, project.name)
        )
    if target == source:
        raise ValueError("'%s' is the source; name a different object to write the filtered copy to" % target)

    kind = _detect_kind(project, source, kind)
    config = project.object_configs(kind).get(source)
    if config.get("type") != SOURCE_TYPE:
        raise ValueError(
            "the %s '%s' is of type '%s', which has no links of its own to select from. "
            "'pc convert %s -t assy' turns one into an Assembly YAML file" % (kind, source, config.get("type"), kind)
        )

    shape = project.get_scene(source) if kind == "scene" else project.get_assembly(source)
    if shape is None or not shape.path:
        raise ValueError("the %s '%s' has no Assembly YAML file" % (kind, source))
    if not os.path.isfile(shape.path):
        raise ValueError("the Assembly YAML file of '%s' is missing: %s" % (source, project.rel_path(shape.path)))

    path = _target_path(project, target)
    document, round_trip = _source_document(project, shape, shape.path)
    problems = assy_filter.filter_document(document, mask)
    for problem in problems:
        pc_logging.error("%s: %s" % (source, problem))

    if dry_run:
        pc_logging.info(
            "[Dry Run] Would write the %s '%s' as %s, filtered from '%s'"
            % (kind, target, project.rel_path(path), source)
        )
        return {
            "kind": kind,
            "source": source,
            "target": target,
            "path": project.rel_path(path),
            "problems": problems,
            "dangling": 0,
            "dry_run": True,
        }

    _write(path, document, round_trip, source, project)
    declaration = _declaration(project, kind, target, path, source)
    if declaration is not None:
        apply_config(project, {SECTIONS[kind]: {target: declaration}})
    else:
        # The declaration is already right, but whatever was built from the old
        # file has to go or a warm daemon goes on serving it.
        project.object_configs(kind)  # ensure the section is loaded
        (project.scenes if kind == "scene" else project.assemblies).pop(target, None)

    dangling = _validate(path, kind, project)
    pc_logging.info("Created the %s '%s' from '%s'" % (kind, target, source))
    return {
        "kind": kind,
        "source": source,
        "target": target,
        "path": project.rel_path(path),
        "problems": problems,
        "dangling": dangling,
        "dry_run": False,
    }
