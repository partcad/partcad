# This script is executed within the python sandbox environment (python runtime)
# to read BREP files.

import os
import sys

# from OCP.BRep import BRep_Builder
# from OCP.BRepTools import BRepTools
# from OCP.TopoDS import TopoDS_Shape

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        from OCP.BRepTools import BRepTools

        obj = request.get("wrapped")
        if obj is None:
            raise Exception("No wrapped object provided for BREP export")

        # Ensure the output path is absolute.
        if not os.path.isabs(path):
            path = os.path.abspath(path)

        # Ensure the output directory exists.
        out_dir = os.path.dirname(path)
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)


        brep_writer = BRepTools()
        with open(path, "wb") as brep_file:
            success = brep_writer.Write_s(obj, brep_file)

        # Check that the file was successfully created.
        if not success or not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create BREP file: {path}")

        return {"success": True, "exception": None}
    except Exception as e:
        # Handle exception and return error details.
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}

if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
