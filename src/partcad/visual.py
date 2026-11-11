#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a part looks like, when that is not what it is: a part's 'visual:'.

    parts:
      wall:
        type: wall
        thickness: 100
        visual: wall-surface     # what a picture of this wall draws instead of it

A part is what it is - the body a check measures, a simulation moves, an
analysis meshes and an export writes. Sometimes the right *picture* of it is
something else: a wall in a floor plan is a solid with a thickness, and it is
drawn as the one-sided surface a plan shows, which is looked through from
outside the room; a part simplified to what a simulation collides with is
drawn as the detailed model it stands in for. 'visual:' names that other part,
and it is drawn in the part's place.

**Only where a picture is drawn**, which is two places:

  * the Digital Thread's 3D view ('Shape.show_async'), and
  * a 'render:' file type whose implementation says it draws pictures,
    'visuals: true' ('output.Implementation.visuals'): '//builtin/render''s
    SVG, PNG and JPEG - the IDE's 2D tab - and its videos. A file type another
    package implements draws what that package draws, and says so itself.

And nowhere else. Not in an export, whatever its file type says - an export is
what another tool computes with, and a visual is not what the part is; not in a
DXF, which is the projection a laser cuts from; not in a dimensioned drawing,
which the IDE's Draft tab asks for without visuals whoever implements it
('render_async(visuals=False)'); and never in the tree a part *is*
('Shape.get_wrapped'), which is what every test, every manufacturability
check, every analysis, every route, every bill of materials and every
simulation reads. The substitution happens to a copy of that tree on its way to
a picture, and nothing of it is kept or cached as the part: a picture is
keyed on the visuals it drew ('Shape._output_run_async'), and the part's own
key does not mention them.

What is drawn:

  * The visual is a **part**, named the way a link names one: a bare name in
    the package that declares the part, ':name', '../package:name' or
    '//package:name', with '<name>;<parameter>=<value>,...' for an instance of
    it, and a '%...%' expression anywhere in it worked out over the part's
    parameters. It may be private to that package (see 'partcad.privacy'); a visual is a
    reference like any other, so another package's private part is refused.
  * It is asked for with **the part's own parameter values** for every parameter
    it declares too, and the ones its reference names on top: a wall 4200 long
    is drawn as a surface 4200 long, painted as the wall is painted. A colour,
    material or finish passed on is spelled out in full on the way, since a
    short name means the package that wrote it.
  * It is drawn **where the part is**: the node keeps the part's name, its link
    label, its placement and its ports - what the 3D view selects, what a filter
    and a callout name - and takes the visual's geometry and appearance in place
    of the part's. Each of the two is built as its own declaration says, its
    'offset' and 'scale' included, in the frame a link places.
  * An **alias or an enrich** of a part that has a visual is drawn as that visual,
    moved by its own 'offset'. One that scales the part is drawn as itself: a
    scale is work on the geometry, which a picture cannot do on its way.
  * A visual's own 'visual:' is not followed. A visual is what is drawn.
  * A **printed part** that names its design ('manufacturing: method: additive'
    with a 'source:') and no 'visual:' is drawn as that design: the design is
    what the designer had in mind and what the print looks like from outside,
    while the part is the print - what it weighs and what a section through it
    shows (see 'part_config_manufacturing.ADDITIVE_REQUIRED'). A 'visual:' of
    its own still wins.

A visual that cannot be had - not found, refused, failing to build - is
reported and the part is drawn as itself: a picture of the part is still a
picture of the part.
"""

import typing

from . import cmf
from . import config as pc_config
from . import expr
from . import logging as pc_logging
from . import shape_envelope
from .shape_config import transform_of
from .utils import format_parameterized_name, parse_parameterized_name

# The key, on a part's declaration.
VISUAL_KEY = "visual"

# The key, on a node drawn as the visual of the part it holds: the visual's full
# name, which a reader of a picture's tree can show beside the part's own. Never
# on a tree that is not on its way to a picture (see the module docstring).
NODE_KEY = "visual"

# What a node takes from the visual it is drawn as: its geometry, in either form,
# what was recorded about that geometry, and how it is drawn. The rest of the
# node - its name, label, placement, kind, joint, ports - stays the part's.
_DRAWN_KEYS = frozenset(
    {
        shape_envelope.KEY_BREP,
        shape_envelope.KEY_CHILD,
        shape_envelope.KEY_GLTF,
        shape_envelope.KEY_GLTF_REF,
        shape_envelope.KEY_ASSEMBLY,
        shape_envelope.KEY_METADATA,
        shape_envelope.KEY_PROPERTIES,
    }
)

# The reference types that stand for another part, whose visual is theirs.
_REFERENCE_TYPES = ("alias", "enrich")


class Drawn(typing.NamedTuple):
    """A part's visual, as it is drawn: the visual, and where it goes in the part's frame."""

    part: typing.Any
    # A placement of the visual in the part's frame, or None for none: an
    # alias's 'offset', when the visual is the one of the part it points at.
    location: typing.Any = None


def declared(config) -> typing.Optional[str]:
    """The 'visual:' a declaration states, or None."""
    if not isinstance(config, dict):
        return None
    value = config.get(VISUAL_KEY)
    if value in (None, ""):
        return None
    return str(value)


def design(config) -> typing.Optional[str]:
    """The design a printed or molded part is drawn as where it states no 'visual:', or None.

    The 'source:' of an 'additive' or 'forming' part's own 'manufacturing:'
    section: what it is a print of, or the cavity it is molded in -- what the
    designer had in mind, and never stock. That holds whether the part has a
    geometry of its own or is what its machine makes (the 'manufactured' type,
    see 'part_config_manufacturing.implied_type'): a print is drawn as its
    design, and its own geometry, bead by bead, only where that is asked for.
    A cut part is drawn as itself, since its 'source:' is the stock it is cut
    from. None for a reference: what it is drawn as is what the part it stands
    for is drawn as ('_inherited_async').
    """
    if not isinstance(config, dict) or config.get("type") in _REFERENCE_TYPES:
        return None
    section = config.get("manufacturing")
    if not isinstance(section, dict) or section.get("method") not in ("additive", "forming"):
        return None
    value = section.get("source")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _declares_or_refers(config) -> bool:
    """Whether a declaration could have a visual at all: it states one, it is made after a design, or it stands for another part."""
    return isinstance(config, dict) and (
        declared(config) is not None or design(config) is not None or config.get("type") in _REFERENCE_TYPES
    )


def _passed_parameters(ctx, part, declared_parameters) -> dict:
    """The part's own parameter values for each parameter the visual declares too, CMF spelled in full."""
    if not isinstance(declared_parameters, dict) or not declared_parameters:
        return {}
    values = pc_config.parameter_values(part.config.get("parameters"))
    passed = {name: value for name, value in values.items() if name in declared_parameters and value is not None}
    return cmf.canonical_parameters(ctx, passed, part.project_name)


async def visual_of_async(ctx, part) -> typing.Optional[Drawn]:
    """The part drawn in the place of 'part', or None where it is drawn as itself.

    A visual that is declared and cannot be had is reported here, once per
    asking, and answers None.
    """
    if getattr(part, "kind", None) != "part" or not isinstance(getattr(part, "config", None), dict):
        return None
    config = part.config
    where = "%s:%s" % (part.project_name, part.name)
    reference = declared(config)
    if reference is None:
        reference = design(config)
    if reference is None:
        return await _inherited_async(ctx, part, config, where)

    project = ctx.get_project(part.project_name)
    if project is None:
        return None
    # A '%...%' anywhere in it is worked out over the part's parameters first,
    # as in every reference a declaration writes (see 'object-reference').
    reference = str(expr.resolve(reference, pc_config.parameter_values(config.get("parameters")), where))
    base, explicit = parse_parameterized_name(reference)
    if ":" in base:
        package, name = project.resolve(base)
    else:
        package, name = project.name, base
    owner = ctx.get_project(package)
    if owner is None:
        pc_logging.error("%s: the package of its visual '%s' is not found: %s" % (where, reference, package))
        return None
    visual_config = owner.get_part_config(name)
    parameters = _passed_parameters(ctx, part, (visual_config or {}).get("parameters"))
    parameters.update(cmf.canonical_parameters(ctx, explicit, part.project_name))
    full = format_parameterized_name(name, parameters)
    if owner.name == part.project_name and full == part.name:
        pc_logging.error("%s: a part cannot be its own visual" % where)
        return None
    # A reference this part's package wrote, refused here if it names a part
    # another package keeps to itself.
    visual = await owner.get_part_async(full, referrer=part.project_name)
    if visual is None:
        pc_logging.error("%s: its visual '%s' is not a part that can be drawn" % (where, reference))
        return None
    return Drawn(visual)


async def _inherited_async(ctx, part, config, where) -> typing.Optional[Drawn]:
    """The visual of the part an alias or an enrich stands for, moved by the reference's own 'offset'.

    Known by what it resolved to, 'source_resolved', rather than by its type:
    a prepared enrich reports the type of the instance it stands for (see
    'enrich.adopt_source_config'). Only where that is a *part*: a 'compound'
    records the assembly it flattens there too, and has no visual to inherit -
    it is drawn as itself, and asking for its assembly as a part is not a
    mistake to report.
    """
    source = config.get("source_resolved")
    if not source or config.get("scale") is not None:
        return None
    package, _, name = str(source).partition(":")
    project = ctx.get_project(package) if package and name else None
    if project is None:
        return None
    # Resolved, and refused if it had to be, when the reference was prepared;
    # quietly, since a source that is not a part is no reference to one.
    target = await project.get_part_async(name, quiet=True)
    if target is None or target is part:
        return None
    drawn = await visual_of_async(ctx, target)
    if drawn is None:
        return None
    offset = transform_of(config, "offset", where)
    if offset is None:
        return drawn
    from .geom import Location

    moved = Location(offset)
    return Drawn(drawn.part, moved if drawn.location is None else moved * drawn.location)


def drawn_node(node: dict, envelope: dict, visual_name: str, location=None) -> dict:
    """'node' drawn as 'envelope': the visual's geometry and looks, the part's place and identity.

    'location' is where the visual sits in the part's frame, if anywhere but
    its origin. The visual's own placement, if its tree carries one, is
    composed under it, and the node's placement over both - the one
    composition 'shape_envelope.placed' is.
    """
    geometry = {key: value for key, value in envelope.items() if key in _DRAWN_KEYS}
    own = envelope.get(shape_envelope.KEY_LOCATION)
    if own is not None:
        geometry[shape_envelope.KEY_LOCATION] = own
    if location is not None:
        geometry = shape_envelope.placed(geometry, location)
    geometry = shape_envelope.placed(geometry, node.get(shape_envelope.KEY_LOCATION))
    drawn = {key: value for key, value in node.items() if key not in _DRAWN_KEYS and key != shape_envelope.KEY_LOCATION}
    drawn.update(geometry)
    drawn[NODE_KEY] = visual_name
    return drawn


class Substitution:
    """One tree's parts drawn as their visuals: the tree, and the visuals that went into it.

    'keys' is '[[visual, cache key], ...]', one per distinct visual, sorted: what
    a picture of the tree is keyed on beside the part's own key, since the
    geometry it drew is not the part's ('Shape._output_run_async'). A key that
    is None means a visual that is not cacheable, and so neither is the picture.
    """

    def __init__(self, tree, keys):
        """'tree', as it is drawn, and '[[visual, cache key], ...]' for the visuals drawn in it."""
        self.tree = tree
        self.keys = keys

    @property
    def cacheable(self) -> bool:
        """Whether a picture of the tree may be cached: every visual drawn in it has a key."""
        return all(key is not None for _name, key in self.keys)


async def substitute_async(ctx, shape, tree) -> Substitution:
    """'tree', the tree of 'shape', with every part in it that has a visual drawn as that visual.

    'tree' is not changed: what comes back is a copy where anything was drawn
    differently, and 'tree' itself where nothing was. A part is found by the
    name its node carries, which is the object the node holds ('<package>:
    <name>', see 'Assembly._child_name_label'), and only a name whose package
    declares the part with a 'visual:', or as a reference to another part, is
    looked up at all: the parts a STEP assembly holds, say, are never built for
    the asking.
    """
    if tree is None:
        return Substitution(tree, [])
    looked_up: dict = {}
    used: dict = {}

    async def visual_for(name, part=None):
        """'(envelope, visual name, location)' the part called 'name' is drawn as, or None to draw it as itself.

        Looked up once per name, however many nodes hold that part, and
        reported once where it cannot be had.
        """
        if name in looked_up:
            return looked_up[name]
        looked_up[name] = None
        try:
            if part is None:
                part = await _part_named_async(ctx, name)
            if part is None:
                return None
            drawn = await visual_of_async(ctx, part)
            if drawn is None:
                return None
            envelope = await drawn.part.get_wrapped(ctx)
        except Exception as e:  # pylint: disable=broad-except
            # A picture is still a picture of the part: see the module docstring.
            pc_logging.error("%s: its visual could not be drawn, and it is drawn as itself: %s" % (name, e))
            return None
        if envelope is None:
            pc_logging.error(
                "%s:%s: its visual %s:%s produced no shape; it is drawn as itself"
                % (part.project_name, part.name, drawn.part.project_name, drawn.part.name)
            )
            return None
        visual_name = "%s:%s" % (drawn.part.project_name, drawn.part.name)
        if visual_name not in used:
            used[visual_name] = await drawn.part.get_cache_key_async() if drawn.part.get_cacheable() else None
        looked_up[name] = (envelope, visual_name, drawn.location)
        return looked_up[name]

    async def walk(node, part=None):
        """'node' with every part under it drawn as its visual: itself where nothing changed, a copy where it did."""
        if not isinstance(node, dict):
            return node
        children = node.get(shape_envelope.KEY_ASSEMBLY)
        if part is not None or (children is None and node.get(shape_envelope.KEY_KIND) in (None, "part")):
            name = node.get("name") if part is None else "%s:%s" % (part.project_name, part.name)
            if isinstance(name, str) and ":" in name:
                found = await visual_for(name, part)
                if found is not None:
                    envelope, visual_name, location = found
                    return drawn_node(node, envelope, visual_name, location)
            return node
        if not isinstance(children, list):
            return node
        walked = [await walk(child) for child in children]
        if all(new is old for new, old in zip(walked, children)):
            return node
        copy = dict(node)
        copy[shape_envelope.KEY_ASSEMBLY] = walked
        return copy

    root_part = shape if getattr(shape, "kind", None) == "part" else None
    result = await walk(tree, root_part)
    return Substitution(result, sorted([name, key] for name, key in used.items()))


async def _part_named_async(ctx, name: str):
    """The part a node names, if its package declares it in a way that could have a visual; otherwise None."""
    package, _, rest = name.partition(":")
    if not package or not rest:
        return None
    project = ctx.get_project(package)
    if project is None:
        return None
    base, _ = parse_parameterized_name(rest)
    try:
        config = project.get_part_config(base)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s: not looked at for a visual: %s" % (name, e))
        return None
    if not _declares_or_refers(config):
        return None
    # The node's own object, asked for by its own package: no reference is
    # being made, and nothing is refused.
    return await project.get_part_async(rest, quiet=True)
