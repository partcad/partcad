#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in three.js JSON exporter (see '//builtin/export' in partcad.yaml)."""

import json
import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common
from utils_ocp import tessellate

BUFFER_SIZE = 256 * 1024  # 256KB buffer for file writes


def process(path, request):
    try:
        obj = request["wrapped"]

        vertices, triangles = tessellate(
            obj,
            request.get("tolerance", 0.1),
            request.get("angularTolerance", 0.1),
        )

        result = {
            "vertices": [[x, y, z] for [x, y, z] in vertices],
            # 0 means just a triangle
            "faces": [[0, i, j, k] for [i, j, k] in triangles],
            "nVertices": len(vertices),
            "nFaces": len(triangles),
        }

        with open(path, "w", encoding="utf-8", buffering=BUFFER_SIZE) as f:
            json.dump(result, f)

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
