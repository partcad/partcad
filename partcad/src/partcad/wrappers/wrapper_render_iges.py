import base64
import os
import pickle
import sys
sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        from OCP.IGESControl import IGESControl_Writer
        from OCP.Interface import Interface_Static

        obj = request["wrapped"]
        write_pcurves = 1 if request.get("write_pcurves", True) else 0
        precision_mode = request.get("precision_mode", 0)

        writer = IGESControl_Writer()
        Interface_Static.SetIVal_s("write.surfacecurve.mode", write_pcurves)
        Interface_Static.SetIVal_s("write.precision.mode", precision_mode)

        writer.AddShape(obj)
        writer.Write(path)

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create IGES file: {path}")

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
