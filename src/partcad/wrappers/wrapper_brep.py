# This script is executed within the python sandbox environment (python runtime)
# to read BREP files.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        brep_tools = BRepTools()

        if not brep_tools.Read_s(shape, path, builder):
            raise Exception(f"Failed to load BREP file: {path}")
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "shape": None,
        }

    return {
        "success": True,
        "exception": None,
        "shape": shape,
    }


path, request = wrapper_common.handle_input()

model = process(path, request)

wrapper_common.handle_output(model)
