#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment to read a glTF
# file -- '.gltf' with its buffers beside it, or a single '.glb' -- as a part.
#
# OpenCASCADE's own reader does the reading: it follows the node tree, applies
# every node's transform, and turns glTF's metres and Y-up into PartCAD's
# millimetres and Z-up. What it hands back is triangles, so they go through the
# same mesher an STL part does, which states them as the planar faces of a
# solid rather than as a triangulation nothing downstream can cut.

import os
import sys
import tempfile

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

import build123d as b3d

from OCP.Message import Message, Message_ProgressRange
from OCP.RWGltf import RWGltf_CafReader
from OCP.RWMesh import RWMesh_CoordinateSystem
from OCP.StlAPI import StlAPI_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1


def read_triangles(path):
    """Every mesh in the file, placed, in millimetres and Z-up."""
    # The reader reports its progress through OpenCASCADE's messenger, which
    # prints to the console: on stderr here, where it reads as a complaint.
    messenger = Message.DefaultMessenger_s()
    for printer in list(messenger.Printers()):
        messenger.RemovePrinter(printer)

    reader = RWGltf_CafReader()
    reader.SetSystemLengthUnit(0.001)
    reader.SetSystemCoordinateSystem(RWMesh_CoordinateSystem.RWMesh_CoordinateSystem_Zup)
    reader.SetDocument(TDocStd_Document(TCollection_ExtendedString("BinXCAF")))
    if not reader.Perform(os.fsdecode(path), Message_ProgressRange()):
        raise RuntimeError("Failed to read the glTF file")
    shape = reader.SingleShape()
    if shape is None or shape.IsNull():
        raise RuntimeError("The glTF file holds no mesh")
    return shape


def process(path, request):
    try:
        triangles = read_triangles(path)
        with tempfile.TemporaryDirectory(prefix="partcad-gltf-") as tmp:
            stl = os.path.join(tmp, "mesh.stl")
            writer = StlAPI_Writer()
            # Binary: the mesher below reads STL through lib3mf, which takes no
            # other kind.
            writer.ASCIIMode = False
            if not writer.Write(triangles, stl):
                raise RuntimeError("The glTF file holds no triangles")
            try:
                shape = b3d.Mesher().read(stl)[0].wrapped
            except Exception:
                shape = b3d.import_stl(stl).wrapped

        return {"success": True, "exception": None, "shape": shape}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e), "shape": None}


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    result = process(path, request)
    wrapper_common.handle_output(result)
