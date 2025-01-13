#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-07
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to speed up parallel rendering, and not to leverage any other benefits of sandboxing

import os
import sys
import json

sys.path.append(os.path.dirname(__file__))
import wrapper_common

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from utils_ocp import tessellate


def process(path, request):

    try:
        obj = request["wrapped"]

        vertices, triangles = tessellate(obj, request["tolerance"], request["angularTolerance"])

        result = {
            "vertices": [],
            "faces": [],
            "nVertices": len(vertices),
            "nFaces": len(triangles),
        }

        # add vertices
        for [x, y, z] in vertices:
            result["vertices"].append([x, y, z])

        # add triangles
        for [i, j, k] in triangles:
            # 0 means just a triangle
            result["faces"].append([0, i, j, k])

        BUFFER_SIZE = 256 * 1024  # 256KB buffer for file writes

        json_str = json.dumps(result)
        with open(path, "w", encoding="utf-8", buffering=BUFFER_SIZE) as f:
            f.write(json_str)

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
