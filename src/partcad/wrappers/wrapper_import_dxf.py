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
# it reads only what modelspace draws directly, and 'dxf_drawing' says what
# that misses.
from cadquery.occ_impl.importers.dxf import _dxf_convert
from cadquery.occ_impl.shapes import Compound, Face, sortWiresByBuildOrder

sys.path.append(os.path.dirname(__file__))
import dxf_drawing
import dxf_metadata
import ocp_serialize
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 2


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
    faces = [
        Face.makeFromWires(wire_set[0], wire_set[1:])
        for entities in layers.values()
        for wire_set in sortWiresByBuildOrder(_dxf_convert(entities, tolerance))
    ]
    return dxf_drawing.one_shape(faces, Compound.makeCompound).wrapped


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
    wires = [wire for entities in layers.values() for wire in _dxf_convert(entities, tolerance)]
    return dxf_drawing.one_shape(wires, Compound.makeCompound, always_compound=True).wrapped


def process(path, request):
    try:
        layers, warnings = dxf_drawing.read(request["path"], request["include"], request["exclude"])
        try:
            shape = as_faces(layers, request["tolerance"])
        except Exception as e:
            # Said out loud rather than fallen back on quietly: a drawing of
            # open lines is meant to import this way, and an outline with a gap
            # in it is a mistake that would otherwise become a sketch nothing
            # can extrude and nobody was told about.
            shape = as_wires(layers, request["tolerance"])
            warnings.append("no face could be built from the DXF file (%s); imported the wires it draws instead" % e)

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
            "warning": "; ".join(warnings) or None,
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
