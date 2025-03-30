import os
import sys

import build123d as b3d

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common

def process(path, request):
    try:
        shape = b3d.Mesher().read(path)[0].wrapped
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
