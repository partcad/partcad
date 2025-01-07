#
# PartCAD, 2025
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

import cadquery as cq

sys.path.append(os.path.dirname(__file__))
import wrapper_common

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from utils_ocp import tessellate


def process(path, request):

    try:
        obj = request["wrapped"]

        cq_solid = cq.Solid.makeBox(1, 1, 1)
        cq_solid.wrapped = obj

        cq.exporters.export(
            cq_solid,
            path,
            tolerance=request["tolerance"],
            angularTolerance=request["angularTolerance"],
        )

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
