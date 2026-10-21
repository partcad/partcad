#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a DXF drawing draws, entity by entity, before any of it becomes geometry.

CadQuery's DXF converters turn lines, arcs, circles, ellipses, splines and
polylines into edges, and that is all they do. Two things a drawing means are
not among them, so they are done here first, on the drawing itself:

* **Block references are exploded.** A block is drawn once and placed with
  INSERT, which is how a drawing repeats a hole pattern or a fastener, and a
  converter that knows only lines, arcs and the like reads an INSERT as nothing.
  So each is replaced with what it draws, where it places it -- and an entity
  the block keeps on layer 0 lands on the layer of the reference, which is what
  layer 0 in a block means. Layers are selected after that, entity by entity:
  what a block keeps on a layer of its own stays on that layer wherever the
  block is placed.
* **Mirrored entities are turned the right way up.** An arc, a circle or a
  polyline is stated in a coordinate system of its own, and one that was
  mirrored -- by MIRROR, or by a block reference with a negative scale -- is
  stated upside down (extrusion (0, 0, -1)), its X running the other way. The
  converters read every one as if it were the right way up, which puts a
  mirrored circle on the far side of the Y axis; 'upright' restates it in the
  drawing's own coordinates, which describes the same curve.

A reference that cannot be followed -- to a block the file does not define, or
to one that places itself ('endless_blocks') -- draws nothing, which is what
every reference drew before; it is a warning rather than a failure, so that no
drawing that imported then fails now.

Two more things are done, and they are what the drawing *says* rather than what
it draws:

* **The numbers are scaled to millimetres**, by what '$INSUNITS' says they are
  in ('millimetres_per_unit'): a drawing of a one-inch profile is a 25.4 mm
  sketch. A unitless drawing is taken as millimetres, and a declaration can say
  what the file does not ('units:').
* **Every exploded element remembers where it came from** ('explode_blocks'
  returns its origins): the entity the file states, in the block definition,
  and the references that placed it there. That is what lets the annotations
  describe the elements that are in the sketch -- a block's contents, where it
  was placed -- and still name each one by a handle the file has.

Only ezdxf is imported, and no CAD library, so all of it can be read -- and
tested -- without a sandbox, like 'dxf_metadata' beside it.
"""

import os
import sys

import ezdxf
from ezdxf.math import Matrix44
from ezdxf.upright import upright_all

sys.path.append(os.path.dirname(__file__))
import dxf_metadata

# The XDATA application under which, for the length of one read, every entity of
# a block definition carries its own handle into the copies a reference makes of
# it: the copies get handles of their own, and this is how an exploded element is
# traced back to the entity the file states. Written and read in memory only --
# the drawing is never saved -- and taken off each copy as soon as it is read.
SOURCE_APPID = "PARTCAD_SOURCE"

# How many millimetres one of each unit '$INSUNITS' can name is, keyed by the
# name 'dxf_metadata' gives the code. The US survey units are defined by the
# metre (1200/3937 m to the foot), which is why they are not the international
# ones.
MILLIMETRES_PER_UNIT = {
    "mm": 1.0,
    "cm": 10.0,
    "dm": 100.0,
    "m": 1000.0,
    "dam": 10000.0,
    "hm": 100000.0,
    "km": 1000000.0,
    "Gm": 1e12,
    "um": 1e-3,
    "nm": 1e-6,
    "angstrom": 1e-7,
    "in": 25.4,
    "ft": 304.8,
    "yd": 914.4,
    "mi": 1609344.0,
    "mil": 0.0254,
    "uin": 25.4e-6,
    "us-in": 100000.0 / 3937.0,
    "us-ft": 1200000.0 / 3937.0,
    "us-yd": 3600000.0 / 3937.0,
    "us-mi": 6336000000.0 / 3937.0,
    "au": 1.495978707e14,
    "ly": 9.4607304725808e18,
    "pc": 3.0856775814913673e19,
}

# What a declaration's 'units:' may say beside a unit: 'auto' (what the drawing
# says, the default) and 'unitless' (the numbers are millimetres as they are).
UNITS_AUTO = "auto"
UNITS_UNITLESS = "unitless"


def millimetres_per_unit(document, units=None):
    """How many millimetres one of the drawing's units is, and what they were read as.

    Returns '(factor, unit, warning)': 'unit' is the unit's name, or None for a
    drawing taken as millimetres because it says nothing ('unitless').

    'units' is the declaration's override, and 'auto' or nothing defers to the
    drawing's '$INSUNITS'. An override names a unit as 'dxf_metadata' spells it
    ('in', 'mm', 'us-ft', ...), case aside, or is 'unitless'; anything else is
    refused, because a guess here is a sketch 25.4 times the wrong size.

    A '$INSUNITS' code DXF has gained since this table was written is read as
    millimetres with a warning, rather than refused: a drawing that imported
    before this read units at all imports still.
    """
    units = str(units).strip() if units not in (None, "") else UNITS_AUTO
    by_name = {name.lower(): name for name in MILLIMETRES_PER_UNIT}
    if units.lower() != UNITS_AUTO:
        if units.lower() == UNITS_UNITLESS:
            return 1.0, None, None
        name = by_name.get(units.lower())
        if name is None:
            raise ValueError(
                "unknown 'units' %r: expected %s, %s or one of %s"
                % (units, UNITS_AUTO, UNITS_UNITLESS, ", ".join(MILLIMETRES_PER_UNIT))
            )
        return MILLIMETRES_PER_UNIT[name], name, None

    stated = dxf_metadata.units_of(document)
    if stated is None:
        return 1.0, None, None
    if stated not in MILLIMETRES_PER_UNIT:
        return (
            1.0,
            None,
            "the drawing's units are %s, which PartCAD does not know; read as millimetres -- set 'units' "
            "to say what they are" % stated,
        )
    return MILLIMETRES_PER_UNIT[stated], stated, None


def endless_blocks(document):
    """The blocks exploding which would never finish, by lower-cased name.

    A block that places itself, directly or through other blocks, and every
    block that places one of those. AutoCAD refuses to create such a cycle; a
    file written by something else can still contain one, and since a block can
    place itself more than once, what it draws can grow without bound long
    before any depth limit is reached. So the cycles are found first, in the
    block definitions, and a reference to such a block is left out -- as every
    block reference used to be.

    Every other block bottoms out, so exploding references to them alone is
    finite: what it places are references to blocks that bottom out sooner.
    Block names are compared without regard to case, as AutoCAD does.
    """
    places = {
        block.name.lower(): {insert.dxf.name.lower() for insert in block.query("INSERT")} for block in document.blocks
    }
    pending = dict(places)
    finite = set()
    while True:
        # A block is finite once everything it places is finite, or is not
        # defined at all (that reference is left out when it is reached).
        done = [name for name, inner in pending.items() if all(n in finite or n not in places for n in inner)]
        if not done:
            return set(pending)
        for name in done:
            finite.add(name)
            del pending[name]


def _tag_sources(document) -> None:
    """Have every entity of every block definition carry its own handle into its copies (SOURCE_APPID)."""
    for block in document.blocks:
        if block.block_record.is_any_layout:
            continue  # the model space and the paper spaces are not blocks
        for entity in block:
            handle = entity.dxf.get("handle")
            if handle:
                entity.set_xdata(SOURCE_APPID, [(1005, handle)])


def _source_of(entity):
    """The handle the file states for what ``entity`` is a copy of, or None; the tag is taken off."""
    if not entity.has_xdata(SOURCE_APPID):
        return None
    tags = entity.get_xdata(SOURCE_APPID)
    entity.discard_xdata(SOURCE_APPID)
    return str(tags[0][1]) if tags else None


def explode_blocks(document):
    """Replace every block reference in modelspace with what it draws.

    Returns '(warnings, origins)': what was left out, and where each element
    the references placed came from -- keyed by the handle the element has now,
    each origin is ``{"source", "references", "metadata"}``:

    * ``source`` -- the handle of the entity the file states, in the block
      definition: the one a person looking at the file would find.
    * ``references`` -- the handles of the references that placed it, outermost
      first: the one in model space, then the ones inside the blocks it placed.
    * ``metadata`` -- what those references say (their XDATA), outermost first
      and the innermost winning, which the element inherits where it says
      nothing of its own: a reference annotated 'angle=90' says it of every bend
      line its block draws.
    """
    modelspace = document.modelspace()
    endless = endless_blocks(document)
    left_out = {}  # why -> how many references
    origins = {}

    _tag_sources(document)
    # One pass per level of nesting: what a block places comes out as further
    # references, exploded on the next pass.
    while True:
        inserts = list(modelspace.query("INSERT"))
        if not inserts:
            break
        for insert in inserts:
            layer = insert.dxf.layer
            # The reference may itself be something an outer reference placed.
            outer = origins.pop(insert.dxf.handle, None) or {"references": [], "metadata": {}}
            references = outer["references"] + [outer.get("source") or insert.dxf.handle]
            metadata = {**outer["metadata"], **dxf_metadata.metadata_of(insert)}
            if insert.dxf.name.lower() in endless:
                why = 'block "%s" places itself, directly or through other blocks' % insert.dxf.name
                left_out[why] = left_out.get(why, 0) + 1
                modelspace.delete_entity(insert)
                continue
            try:
                # Places a MINSERT's every cell, and removes the reference.
                exploded = insert.explode()
            except Exception as e:
                left_out[str(e)] = left_out.get(str(e), 0) + 1
                modelspace.delete_entity(insert)
                continue
            for entity in exploded:
                if entity.dxf.layer == "0":
                    entity.dxf.layer = layer
                origins[entity.dxf.handle] = {
                    "source": _source_of(entity),
                    "references": references,
                    "metadata": metadata,
                }

    warnings = ["%d block reference(s) were left out: %s" % (count, why) for why, count in left_out.items()]
    return warnings, origins


def scale(document, factor) -> list:
    """Scale everything in modelspace by ``factor``, about the origin; what could not be, as warnings.

    An entity ezdxf cannot transform -- a proxy for something another
    application drew -- is left out rather than left at the wrong size beside
    what was scaled.
    """
    if factor == 1.0:
        return []
    modelspace = document.modelspace()
    matrix = Matrix44.scale(factor)
    skipped = {}
    for entity in list(modelspace):
        try:
            entity.transform(matrix)
        except Exception:
            skipped[entity.dxftype()] = skipped.get(entity.dxftype(), 0) + 1
            modelspace.delete_entity(entity)
    return [
        "%d %s element(s) could not be scaled to millimetres and were left out" % (count, dxftype)
        for dxftype, count in sorted(skipped.items())
    ]


def layers(document, include, exclude):
    """The selected layers of the drawing's modelspace, each as the entities on it.

    Layer selection is CadQuery's own, mirrored here because the wrapper no
    longer goes through its importer: names are matched case-insensitively, and
    'include' and 'exclude' are mutually exclusive ('read' refuses both).
    'dxf_metadata.is_included' is the rule, and applies it to the annotations
    too, so the two describe one set of elements.
    """
    selected = {
        name: entities
        for name, entities in document.modelspace().groupby(dxfattrib="layer").items()
        if dxf_metadata.is_included(name, include, exclude)
    }
    if not selected:
        raise ValueError("no DXF layers selected")
    return selected


class Drawing:
    """A DXF drawing read for a sketch: what its selected layers draw, in millimetres, and what it said.

    * ``document`` -- the drawing as it was read: blocks exploded, mirrored
      entities upright, numbers in millimetres. What the annotations are read
      from, so they describe the elements that are in the sketch.
    * ``layers`` -- the selected layers, each as the entities on it.
    * ``warnings`` -- what was left out or guessed, to be said out loud.
    * ``origins`` -- where each exploded element came from ('explode_blocks').
    * ``scale`` -- millimetres per unit of the file, and ``units`` the unit's
      name (None for a drawing taken as millimetres).
    """

    def __init__(self, document, layers, warnings, origins, scale, units):
        self.document = document
        self.layers = layers
        self.warnings = warnings
        self.origins = origins
        self.scale = scale
        self.units = units


def read(path, include=None, exclude=None, units=None):
    """What the selected layers of the drawing at 'path' draw, as a 'Drawing'.

    'units' is the declaration's override of what '$INSUNITS' says (see
    'millimetres_per_unit').
    """
    if include and exclude:
        # Refused before anything is read: 'is_included' would apply both, and
        # hand back a sketch for a request CadQuery's importer -- whose rule
        # this is -- rejects. 'SketchFactoryDxf' catches this first and says
        # which sketch; this is the reader being right on its own.
        raise ValueError("you may specify either 'include' or 'exclude' but not both")
    document = ezdxf.readfile(path)
    factor, unit, warning = millimetres_per_unit(document, units)
    warnings = [warning] if warning else []
    exploded, origins = explode_blocks(document)
    warnings += exploded
    upright_all(document.modelspace())
    warnings += scale(document, factor)
    return Drawing(document, layers(document, include, exclude), warnings, origins, factor, unit)


def split_closed(wires_by_layer, is_closed):
    """The wires that close, per layer, and the ones that do not, all together.

    Returns '(closed, open)'. A closed outline bounds a face and is built into
    one; an open line -- a bend line, an outline with a gap in it -- does not,
    and stays a wire beside the faces rather than turning every face of the
    drawing into wires too. The closed ones stay grouped by layer because a face
    is built out of one layer's outlines and the holes inside them.
    """
    closed = {}
    open_wires = []
    for layer, wires in wires_by_layer.items():
        closed[layer] = [wire for wire in wires if is_closed(wire)]
        open_wires.extend(wire for wire in wires if not is_closed(wire))
    return closed, open_wires


def sketch(wires_by_layer, is_closed, faces_of, compound):
    """What the selected layers draw, as faces where they close and wires where they do not.

    Returns '(shape, warning)'. The CAD kernel is handed in, so that what is
    decided here is decided the same way wherever it is asked: 'is_closed(wire)'
    says whether a wire closes, 'faces_of(wires)' builds the faces one layer's
    closed wires bound -- each outline with the holes inside it -- and
    'compound(shapes)' joins several shapes into one. Every face is kept, not
    whichever one an importer listed first, and one face comes back as that
    face, as it always has ('one_shape').

    A wire that does not close bounds nothing, and stays a wire beside the
    faces ('split_closed'): two parallel lines across a blank are where it is
    folded, and a drawing of an outline and its bend lines is a sketch of one
    face and two lines, not of three lines. That is said out loud, because the
    other way to arrive there is an outline with a gap in it, which is a
    mistake rather than a drawing of lines.

    A closed wire that still will not make a face -- one that is not flat -- is
    the one case left for the whole drawing to come back as wires, as every
    drawing with an open line in it once did.
    """
    closed, open_wires = split_closed(wires_by_layer, is_closed)
    try:
        # A layer with no closed wire is skipped rather than handed over:
        # CadQuery sorts nothing into one empty set of wires, not into none.
        faces = [face for layer_wires in closed.values() if layer_wires for face in faces_of(layer_wires)]
    except Exception as e:
        everything = [wire for layer_wires in wires_by_layer.values() for wire in layer_wires]
        return (
            one_shape(everything, compound, always_compound=True),
            "no face could be built from the DXF file (%s); imported the wires it draws instead" % e,
        )
    if not open_wires:
        return one_shape(faces, compound), None
    return one_shape(faces + open_wires, compound, always_compound=True), (
        "%d wire(s) of the DXF file do not close, and were imported as wires%s"
        % (len(open_wires), " beside the %d face(s) the rest bound" % len(faces) if faces else "")
    )


def one_shape(shapes, compound, always_compound=False):
    """What a sketch of 'shapes' is: the one shape itself, or 'compound(shapes)' of several.

    One face comes back as that face, as it always has, so that a drawing that
    imported before imports to the same shape; several are a compound of all of
    them, never just the first. Wires are always a compound ('always_compound'),
    as they always were. Nothing at all is not a sketch.
    """
    if not shapes:
        raise ValueError("the selected layers of the DXF file draw nothing")
    if len(shapes) == 1 and not always_compound:
        return shapes[0]
    return compound(shapes)
