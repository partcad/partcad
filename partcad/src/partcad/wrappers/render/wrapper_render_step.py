import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common

def process(path, request):
    try:
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.Interface import Interface_Static

        obj = request["wrapped"]
        write_pcurves = 1 if request.get("write_pcurves", True) else 0
        precision_mode = request.get("precision_mode", 0)

        writer = STEPControl_Writer()
        Interface_Static.SetIVal_s("write.surfacecurve.mode", write_pcurves)
        Interface_Static.SetIVal_s("write.precision.mode", precision_mode)
        writer.Transfer(obj, STEPControl_AsIs)
        writer.Write(path)

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create STEP file: {path}")

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}

if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
