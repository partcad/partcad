#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to speed up parallel rendering

import os
import sys

import cadquery as cq

# import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        cq_obj = cq.Solid.makeBox(1, 1, 1)
        cq_obj.wrapped = request["wrapped"]

        vertices, triangles = cq_obj.tessellate(request["tolerance"], request["angularTolerance"])

        # b3d_obj = b3d.Shape(request["wrapped"])
        # vertices, triangles = b3d.Mesher._mesh_shape(
        #     b3d_obj, request["tolerance"], request["angularTolerance"]
        # )

        with open(path, "w", encoding="utf-8", buffering=256 * 1024) as f:
            f.write("# OBJ file\n")
            for v in vertices:
                f.write("v %.4f %.4f %.4f\n" % (v.x, v.y, v.z))
                # f.write("v %.4f %.4f %.4f\n" % (v[0], v[1], v[2]))
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
