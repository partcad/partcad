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

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
