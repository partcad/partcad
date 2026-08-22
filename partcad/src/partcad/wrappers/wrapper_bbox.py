#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment to measure a
# shape. The core has no CAD library, so the only way it can learn how big
# something is - which is what an exploded view has to know before it can decide
# how far apart to pull two items - is to ask a runtime that has one.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        shape = request.get("wrapped")
        if shape is None:
            raise Exception("No wrapped object provided to measure")

        box = Bnd_Box()
        # 'useTriangulation': a shape that carries a mesh but no exact geometry
        # (an imported STL, an SDF part) has an empty box otherwise.
        BRepBndLib.Add_s(shape, box, True)
        if box.IsVoid():
            return {"success": True, "exception": None, "bounding_box": None}

        x_min, y_min, z_min, x_max, y_max, z_max = box.Get()
        return {
            "success": True,
            "exception": None,
            "bounding_box": [x_min, y_min, z_min, x_max, y_max, z_max],
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "bounding_box": None,
        }


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
