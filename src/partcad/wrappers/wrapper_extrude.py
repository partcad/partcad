#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to extrude a sketch profile into a solid, so the core process never has to
# touch a live OCP object to do it. The source sketch arrives in the request as
# a BREP envelope and the extruded solid goes back the same way.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(request):
    from OCP.gp import gp_Vec
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

    sketch = request["sketch"]
    depth = request["depth"]
    maker = BRepPrimAPI_MakePrism(sketch, gp_Vec(0.0, 0.0, depth))
    maker.Build()
    return maker.Shape()


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        shape = process(request)
        model = {"success": True, "exception": None, "shape": shape}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    wrapper_common.handle_output(model)
