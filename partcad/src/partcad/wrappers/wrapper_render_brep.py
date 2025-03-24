# This script is executed within the python sandbox environment (python runtime)
# to read BREP files.

import os
import sys

# from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        obj = request.get("wrapped")
        if obj is None:
            raise Exception("No wrapped object provided for BREP export")

        if not isinstance(obj, TopoDS_Shape):
            raise TypeError(f"Object type is incorrect: {type(obj)}")

        if not os.path.isabs(path):
            path = os.path.abspath(path)

        out_dir = os.path.dirname(path)
        os.makedirs(out_dir, exist_ok=True)

        brep_writer = BRepTools()
        brep_writer.Write_s(obj, path)

        # Check that the file was successfully created.
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create BREP file: {path}")

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}

if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
