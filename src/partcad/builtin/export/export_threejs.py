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
import cmf_export
import wrapper_common
from utils_ocp import tessellate

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: says that the CMF of what it writes is not in the file.
CACHE_VERSION = 2

# How this implementation meshes what it is handed, so that the files of one
# object written together can share one decoding of it and one mesh (see
# 'wrapper_export.TESSELLATION_NAME'): to an absolute deflection, through
# 'utils_ocp.tessellate()', as the OBJ exporter does. Only the mesh is left on
# the shape, and what is written is decided by the geometry and that mesh
# alone.
TESSELLATION = ("absolute", "tolerance", "angularTolerance")

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

        # The format has no colour, material or finish to write, and whoever
        # exported a part that states them is told so, once (see
        # 'cmf_export.dropped').
        dropped = cmf_export.dropped(request, "three.js JSON")
        return {"success": True, "exception": None, "files": [], "warnings": [dropped] if dropped else []}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
