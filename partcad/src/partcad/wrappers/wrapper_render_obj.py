#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to speed up parallel rendering, and not to leverage any other benefits of sandboxing

import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from utils_ocp import tessellate


def process(path, request):

    try:
        obj = request["wrapped"]

        vertices, triangles = tessellate(obj, request["tolerance"], request["angularTolerance"])

        # b3d_obj = b3d.Shape(request["wrapped"])
        # vertices, triangles = b3d.Mesher._mesh_shape(
        #     b3d_obj, request["tolerance"], request["angularTolerance"]
        # )

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

        return {
            "success": True,
            "exception": None,
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": e,
        }


path, request = wrapper_common.handle_input()

# Perform rendering
response = process(path, request)

wrapper_common.handle_output(response)
