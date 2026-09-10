#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment to ask whether a
# shape is a solid that OCCT will do arithmetic on. The core has no CAD library,
# so this is the only place the question can be put.
#
# A shape can be built, rendered, exported and measured for size while being
# inside out - its faces oriented inward rather than outward. Nothing about a
# picture of it looks wrong. But a solid's volume is then negative, and every
# boolean against it returns a number unrelated to any shape: two such solids
# 100 mm apart come back sharing 2282 mm^3.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def process(path, request):
    try:
        shape = request.get("wrapped")
        if shape is None:
            raise Exception("No wrapped object provided to check")

        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        solids = 0
        while explorer.More():
            solids += 1
            explorer.Next()

        # A shape with no solid in it is not inside out; it is a sketch, a
        # shell or a wire, and this check has nothing to say about it.
        if solids == 0:
            return {
                "success": True,
                "exception": None,
                "solids": 0,
                "volume": None,
                "valid": None,
            }

        return {
            "success": True,
            "exception": None,
            "solids": solids,
            "volume": _volume(shape),
            "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e), "solids": 0, "volume": None, "valid": None}


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
