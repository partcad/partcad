#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to read STEP files.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

from OCP.STEPControl import STEPControl_Reader
import OCP.IFSelect
from OCP.TopoDS import (
    TopoDS_Builder,
    TopoDS_Compound,
)

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import step_metadata
import wrapper_common


def process(path, request):
    compound = None
    try:
        reader = STEPControl_Reader()
        readStatus = reader.ReadFile(path)
        if readStatus != OCP.IFSelect.IFSelect_RetDone:
            raise Exception("STEP File could not be loaded")
        for i in range(reader.NbRootsForTransfer()):
            reader.TransferRoot(i + 1)

        occ_shapes = []
        for i in range(reader.NbShapes()):
            occ_shapes.append(reader.Shape(i + 1))

        builder = TopoDS_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for shape in occ_shapes:
            builder.Add(compound, shape)
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            # "exception": e,
            "exception": str(e.with_traceback(None)),
            "shape": None,
        }

    # What the file states about itself and its contents, read here because this
    # is the process it is open in, and handed to the encoder so that it lands
    # on the envelope beside the BREP - and, from there, in the same cache entry
    # as the geometry it describes. It goes in under 'sections', which is the
    # protocol's name for "the source's own vocabulary": the core stores and
    # reports these keys without knowing a STEP file was involved.
    #
    # A file that cannot be read this way still imports: the geometry is the
    # answer that was asked for, and this is the extra.
    try:
        sections = step_metadata.read(path)
    except Exception as e:  # pylint: disable=broad-except
        print("Failed to read what '%s' states: %s" % (path, e), file=sys.stderr)
        sections = None

    shape = ocp_serialize.encode_shape(
        compound,
        name=request.get("name"),
        label=request.get("label"),
        metadata={ocp_serialize.METADATA_SECTIONS: sections} if sections else None,
    )

    return {
        "success": True,
        "exception": None,
        "shape": shape,
    }


path, request = wrapper_common.handle_input()

model = process(path, request)

wrapper_common.handle_output(model)
