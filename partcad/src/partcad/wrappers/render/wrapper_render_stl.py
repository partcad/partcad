import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common

def process(path, request):
    try:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer

        obj = request["wrapped"]
        tolerance = request.get("tolerance", 0.1)
        angular_tolerance = request.get("angularTolerance", 0.1)
        ascii = request.get("ascii", False)

        BRepMesh_IncrementalMesh(
            obj,
            theLinDeflection=tolerance,
            isRelative=True,
            theAngDeflection=angular_tolerance,
            isInParallel=True,
        )

        writer = StlAPI_Writer()
        writer.ASCIIMode = ascii
        success = writer.Write(obj, path)

        if not success or not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create STL file: {path}")

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}

if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
