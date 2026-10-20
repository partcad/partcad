#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to use CadqUery

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

# CadQuery's own DXF converters and face builder. Its importer is not called:
# it keeps only what modelspace draws directly, and 'drawing()' explains what
# that misses.
from cadquery.occ_impl.importers.dxf import _dxf_convert
from cadquery.occ_impl.shapes import Compound, Face, sortWiresByBuildOrder

sys.path.append(os.path.dirname(__file__))
import dxf_metadata
import ocp_serialize
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 2


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


def drawing(request):
    """The selected layers of the drawing, each as the entities it draws, and what was left out.

    Returns '(layers, warnings)'.

    Two things are done to the drawing first, because CadQuery's converters do
    not do them and a drawing means them:

    * **Block references are exploded.** A block is drawn once and placed with
      INSERT, which is how a drawing repeats a hole pattern or a fastener, and a
      converter that knows only lines, arcs and the like reads an INSERT as
      nothing. So each is replaced with what it draws, where it places it -- and
      an entity the block keeps on layer 0 lands on the layer of the reference,
      which is what layer 0 in a block means. Layers are selected after that,
      entity by entity: what a block keeps on a layer of its own stays on that
      layer wherever the block is placed.
    * **Mirrored entities are turned the right way up.** An arc, a circle or a
      polyline is stated in a coordinate system of its own, and one that was
      mirrored -- by MIRROR, or by a block reference with a negative scale -- is
      stated upside down (extrusion (0, 0, -1)), its X running the other way.
      The converters read every one as if it were the right way up, which puts
      a mirrored circle on the far side of the Y axis; 'upright' restates it in
      the drawing's own coordinates, which describes the same curve.

    A drawing with neither -- which is every drawing PartCAD imported before
    either was done -- is read exactly as it was. And a reference that cannot
    be followed -- to a block the file does not define, or to one that places
    itself ('endless_blocks') -- draws nothing, which is what every reference
    drew before; it is a warning rather than a failure, so that no drawing that
    imported then fails now.

    Layer selection is CadQuery's own, mirrored here because this no longer goes
    through its importer: names are matched case-insensitively, and 'include'
    and 'exclude' are mutually exclusive ('process' refuses both).
    'dxf_metadata.is_included' applies the same rule to the annotations, so the
    two describe one set of elements.
    """
    import ezdxf
    from ezdxf.upright import upright_all

    document = ezdxf.readfile(request["path"])
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

    warnings = ["%d block reference(s) were left out: %s" % (count, why) for why, count in left_out.items()]

    upright_all(modelspace)

    selected = {
        name: layer
        for name, layer in modelspace.groupby(dxfattrib="layer").items()
        if dxf_metadata.is_included(name, request["include"], request["exclude"])
    }
    if not selected:
        raise ValueError("no DXF layers selected")
    return selected, warnings


def as_faces(layers, tolerance):
    """The faces what the selected layers draw bound, holes included -- every one of them.

    CadQuery's importer, which this follows: each layer's entities are joined
    into wires, the wires are sorted into outlines and the holes inside them,
    and each outline becomes a face. Raises if a wire does not close, which is
    the case 'as_wires' answers.

    *Every* face is kept. A drawing of two outlines side by side, or one on
    each of two layers, is a sketch of two faces -- not of whichever one the
    importer happened to list first, which is what this used to keep. One face
    comes back as that face, as it always has.
    """
    faces = []
    for layer in layers.values():
        for wire_set in sortWiresByBuildOrder(_dxf_convert(layer, tolerance)):
            faces.append(Face.makeFromWires(wire_set[0], wire_set[1:]))

    if not faces:
        raise ValueError("the selected layers of the DXF file draw nothing")
    if len(faces) == 1:
        return faces[0].wrapped
    return Compound.makeCompound(faces).wrapped


def as_wires(layers, tolerance):
    """What the selected layers draw, as wires, for a drawing that has no faces.

    'as_faces' builds *faces*: it merges each layer's entities into wires and
    then asks each wire for the face it bounds. A drawing whose lines do not
    close bounds nothing, so the whole import fails - and a drawing whose lines
    do not close is precisely what sheet metal bend instructions are. Two
    parallel lines across a blank are where it is folded, and they are open by
    nature.

    So when the face import fails, the wires themselves are the answer. They are
    what the drawing states, they are what an annotation is written against, and
    a sketch of them is a perfectly good sketch - it is only not a face.

    Only ever reached *after* the face import has raised, which is what keeps
    every drawing that imports as faces importing as faces: this is a second
    answer to a question that otherwise had none, never a different answer to
    one that had one.
    """
    wires = []
    for layer in layers.values():
        wires.extend(_dxf_convert(layer, tolerance))

    if not wires:
        raise ValueError("the selected layers of the DXF file draw nothing")
    return Compound.makeCompound(wires).wrapped


def process(path, request):
    if request["include"] and request["exclude"]:
        # Refused before anything is read: 'is_included' would apply both, and
        # hand back a sketch for a request CadQuery's importer -- whose rule
        # this is -- rejects. 'SketchFactoryDxf' catches this first and says
        # which sketch; this is the wrapper being right on its own.
        raise ValueError("you may specify either 'include' or 'exclude' but not both")
    try:
        layers, warnings = drawing(request)
        try:
            shape = as_faces(layers, request["tolerance"])
        except Exception as e:
            # Said out loud rather than fallen back on quietly: a drawing of
            # open lines is meant to import this way, and an outline with a gap
            # in it is a mistake that would otherwise become a sketch nothing
            # can extrude and nobody was told about.
            shape = as_wires(layers, request["tolerance"])
            warnings.append("no face could be built from the DXF file (%s); imported the wires it draws instead" % e)
        warning = "; ".join(warnings) or None

        # What the drawing says about its own elements, and about itself, which
        # the geometry cannot carry: BREP has nowhere to put an angle written
        # against a line, nor the name of a layer that was filtered out. Read
        # here, as the file is imported, because this is the one process that
        # ever has the file open - and handed to the encoder below, so that both
        # halves land on the envelope beside the BREP and, from there, in the
        # same cache entry as the geometry.
        #
        # The same layer filters the import above was given, so the annotations
        # describe what is in the sketch rather than what was filtered out of
        # it. A drawing that cannot be read a second time is reported rather
        # than passed off as one that annotates nothing.
        read = dxf_metadata.read_file(
            request["path"],
            include=request["include"],
            exclude=request["exclude"],
        )
        # Both halves go under the protocol's own section names - the per-element
        # records under 'annotations', what the drawing says about itself under
        # 'sections' - and nothing else travels beside them. There is no second
        # channel: a sibling key on this response would be one more thing for the
        # core to know about, to carry and to cache separately, and knowing that
        # a DXF was involved is exactly what the core must not do.
        #
        # The shape is encoded here rather than left to 'handle_output' because
        # that is what there is to hang the metadata on; the name and the label
        # are the ones the request carried, which is what that step would have
        # stamped on anyway.
        shape = ocp_serialize.encode_shape(
            shape,
            name=request.get("name"),
            label=request.get("label"),
            metadata=ocp_serialize.make_metadata(
                annotations=read["annotations"],
                sections=read["metadata"],
            ),
        )
        return {
            "success": True,
            "exception": None,
            "warning": warning,
            "shape": shape,
        }

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": wrapper_common.exception_to_str(e),
        }


path, request = wrapper_common.handle_input()

# Perform import
response = process(path, request)

wrapper_common.handle_output(response)
