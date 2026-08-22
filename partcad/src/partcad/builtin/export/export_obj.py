#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in Wavefront OBJ exporter (see '//builtin/export' in partcad.yaml)."""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common
from utils_ocp import tessellate


def process(path, request):
    try:
        obj = request["wrapped"]

        vertices, triangles = tessellate(
            obj,
            request.get("tolerance", 0.1),
            request.get("angularTolerance", 0.1),
        )

        with open(path, "w", encoding="utf-8", buffering=256 * 1024) as f:
            f.write("# OBJ file\n")
            for v in vertices:
                f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
            for p in triangles:
                f.write("f")
                for i in p:
                    f.write(" %d" % (i + 1))
                f.write("\n")
            f.flush()

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
