#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# to render a glTF file from wrapped shape

import os
import sys
import pickle
import base64

import build123d as b3d

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common


def process(path, request):
    try:
        obj = request.get("wrapped")
        if obj is None:
            raise ValueError("No wrapped object provided for GLTF export")

        tolerance = request.get("tolerance", 0.1)
        angular_tolerance = request.get("angularTolerance", 0.1)
        binary = request.get("binary", False)

        if not os.path.isabs(path):
            path = os.path.abspath(path)

        out_dir = os.path.dirname(path)
        os.makedirs(out_dir, exist_ok=True)

        b3d.export_gltf(
            obj,
            path,
            binary=binary,
            linear_deflection=tolerance,
            angular_deflection=angular_tolerance,
        )

        # Check if file is successfully created
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create GLTF file: {path}")

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
