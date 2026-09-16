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

import cadquery as cq

sys.path.append(os.path.dirname(__file__))
import dxf_metadata
import ocp_serialize
import wrapper_common


def as_wires(request):
    """What the selected layers draw, as wires, for a drawing that has no faces.

    CadQuery's importer builds *faces*: it merges each layer's entities into
    wires and then asks each wire for the face it bounds. A drawing whose lines
    do not close bounds nothing, so the whole import fails - and a drawing whose
    lines do not close is precisely what sheet metal bend instructions are. Two
    parallel lines across a blank are where it is folded, and they are open by
    nature.

    So when the face import fails, the wires themselves are the answer. They are
    what the drawing states, they are what an annotation is written against, and
    a sketch of them is a perfectly good sketch - it is only not a face.

    Only ever reached *after* the face import has raised, which is what keeps
    every drawing that imports today importing exactly as it did: this is a
    second answer to a question that otherwise had none, never a different
    answer to one that had one.

    The layer selection is CadQuery's own, mirrored here because this does not
    go through its importer: names are matched case-insensitively, and 'include'
    and 'exclude' are mutually exclusive. 'dxf_metadata.is_included' applies the
    same rule to the annotations, so the two describe one set of elements.
    """
    import ezdxf
    from cadquery.occ_impl.importers.dxf import _dxf_convert
    from cadquery.occ_impl.shapes import Compound

    document = ezdxf.readfile(request["path"])
    layers = document.modelspace().groupby(dxfattrib="layer")

    wires = []
    for name, layer in layers.items():
        if not dxf_metadata.is_included(name, request["include"], request["exclude"]):
            continue
        wires.extend(_dxf_convert(layer, request["tolerance"]))

    if not wires:
        raise ValueError("the selected layers of the DXF file draw nothing")
    return Compound.makeCompound(wires).wrapped


def process(path, request):
    warning = None
    if request["include"] and request["exclude"]:
        # Refused before the import rather than after it, because the import
        # refuses it too and the 'except' below cannot tell that refusal from a
        # drawing that would not close: it would fall back to the wires, apply
        # both filters, and hand back a sketch for a request CadQuery rejected.
        # 'SketchFactoryDxf' catches this first and says which sketch; this is
        # the wrapper being right on its own, since the fallback's rule is
        # meant to be the importer's.
        raise ValueError("you may specify either 'include' or 'exclude' but not both")
    try:
        try:
            workplane = cq.importers.importDXF(
                filename=request["path"],
                tol=request["tolerance"],
                include=request["include"],
                exclude=request["exclude"],
            )
            shape = workplane.val().wrapped
        except Exception as e:
            # Said out loud rather than fallen back on quietly: a drawing of
            # open lines is meant to import this way, and an outline with a gap
            # in it is a mistake that would otherwise become a sketch nothing
            # can extrude and nobody was told about.
            shape = as_wires(request)
            warning = "no face could be built from the DXF file (%s); imported the wires it draws instead" % e

        # What the drawing says about its own elements, and about itself, which
        # the geometry cannot carry: BREP has nowhere to put an angle written
        # against a line, nor the name of a layer that was filtered out. Read
        # here, as the file is imported, so that both travel onwards from here -
        # the elements with the sketch (see 'Sketch.get_annotations'), the rest
        # on the envelope below - and nothing downstream has to know that a DXF
        # file was ever involved.
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
        # What the drawing says about *itself* goes onto the envelope beside the
        # BREP, under the protocol's own key, so the core stores and reports it
        # without knowing a DXF was involved (see 'ocp_serialize.KEY_METADATA').
        # The shape is encoded here rather than left to 'handle_output' because
        # that is what there is to hang the key on; the name and the label are
        # the ones the request carried, which is what that step would have
        # stamped on anyway.
        shape = ocp_serialize.encode_shape(shape, name=request.get("name"), label=request.get("label"))
        if read["metadata"]:
            shape[ocp_serialize.KEY_METADATA] = read["metadata"]
        return {
            "success": True,
            "exception": None,
            "warning": warning,
            "shape": shape,
            "annotations": read["annotations"],
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
