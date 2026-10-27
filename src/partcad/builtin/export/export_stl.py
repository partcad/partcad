#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in STL exporter (see '//builtin/export' in partcad.yaml)."""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# How this implementation meshes what it is handed, so that the files of one
# object written together can share one decoding of it and one mesh (see
# 'wrapper_export.TESSELLATION_NAME'): relative to the size of each edge and
# face, as 'BRepMesh_IncrementalMesh' does with 'isRelative' - which is what
# cadquery does for the 3MF exporter too, though that one runs in another
# environment. Only the mesh is left on the shape, and what is written is
# decided by the geometry and that mesh alone.
TESSELLATION = ("relative", "tolerance", "angularTolerance")


def process(path, request):
    try:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer

        obj = request["wrapped"]
        tolerance = request.get("tolerance", 0.1)
        angular_tolerance = request.get("angularTolerance", 0.1)
        ascii = request.get("ascii", False)

        BRepMesh_IncrementalMesh(
            obj,
            theLinDeflection=tolerance,
            isRelative=True,
            theAngDeflection=angular_tolerance,
            isInParallel=True,
        )

        writer = StlAPI_Writer()
        writer.ASCIIMode = ascii
        success = writer.Write(obj, path)

        if not success or not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create STL file: {path}")

        return {"success": True, "exception": None, "files": []}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
