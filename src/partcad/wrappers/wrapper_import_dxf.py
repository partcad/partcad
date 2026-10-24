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
CACHE_VERSION = 3


def _faces(wires):
    """The faces one layer's closed wires bound, each outline with the holes inside it.

    CadQuery's importer, which this follows, sorts the wires into outlines and
    the holes inside them and makes a face of each outline.
    """
    return [Face.makeFromWires(wire_set[0], wire_set[1:]) for wire_set in sortWiresByBuildOrder(wires)]


def as_sketch(layers, tolerance):
    """What the selected layers draw, as '(shape, warning)': see 'dxf_drawing.sketch'.

    Each layer's entities are joined into wires by CadQuery's own converters;
    which of them become faces, and what is said about the rest, is decided
    there.
    """
    wires = {layer: _dxf_convert(entities, tolerance) for layer, entities in layers.items()}
    shape, warning = dxf_drawing.sketch(wires, lambda wire: wire.IsClosed(), _faces, Compound.makeCompound)
    return shape.wrapped, warning


def process(path, request):
    try:
        drawing = dxf_drawing.read(request["path"], request["include"], request["exclude"], request.get("units"))
        shape, warning = as_sketch(drawing.layers, request["tolerance"])
        warnings = drawing.warnings + ([warning] if warning else [])

        # What the drawing says about its own elements, and about itself, which
        # the geometry cannot carry: BREP has nowhere to put an angle written
        # against a line, nor the name of a layer that was filtered out. Read
        # here, as the file is imported, because this is the one process that
        # ever has the file open - and handed to the encoder below, so that both
        # halves land on the envelope beside the BREP and, from there, in the
        # same cache entry as the geometry.
        #
        # Read off the same drawing the geometry was, with the same layer
        # filters, so the annotations describe what is in the sketch: the
        # elements a block reference placed rather than the reference, where
        # the sketch has them and in the millimetres it is in.
        read = dxf_metadata.read_document(
            drawing.document,
            include=request["include"],
            exclude=request["exclude"],
            origins=drawing.origins,
            millimetres_per_unit=drawing.scale,
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
