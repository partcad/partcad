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

A drawing with neither -- which is every drawing PartCAD imported before either
was done -- is read exactly as it was. And a reference that cannot be followed
-- to a block the file does not define, or to one that places itself
('endless_blocks') -- draws nothing, which is what every reference drew before;
it is a warning rather than a failure, so that no drawing that imported then
fails now.

Only ezdxf is imported, and no CAD library, so all of it can be read -- and
tested -- without a sandbox, like 'dxf_metadata' beside it.
"""

import os
import sys

import ezdxf
from ezdxf.upright import upright_all

sys.path.append(os.path.dirname(__file__))
import dxf_metadata


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


def explode_blocks(document):
    """Replace every block reference in modelspace with what it draws; what was left out, as warnings."""
    modelspace = document.modelspace()
    endless = endless_blocks(document)
    left_out = {}  # why -> how many references

    # One pass per level of nesting: what a block places comes out as further
    # references, exploded on the next pass.
    while True:
        inserts = list(modelspace.query("INSERT"))
        if not inserts:
            break
        for insert in inserts:
            layer = insert.dxf.layer
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

    return ["%d block reference(s) were left out: %s" % (count, why) for why, count in left_out.items()]


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


def read(path, include=None, exclude=None):
    """What the selected layers of the drawing at 'path' draw: '(layers, warnings)'."""
    if include and exclude:
        # Refused before anything is read: 'is_included' would apply both, and
        # hand back a sketch for a request CadQuery's importer -- whose rule
        # this is -- rejects. 'SketchFactoryDxf' catches this first and says
        # which sketch; this is the reader being right on its own.
        raise ValueError("you may specify either 'include' or 'exclude' but not both")
    document = ezdxf.readfile(path)
    warnings = explode_blocks(document)
    upright_all(document.modelspace())
    return layers(document, include, exclude), warnings


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
