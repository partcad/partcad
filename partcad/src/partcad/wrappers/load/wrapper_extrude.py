import os
import sys
import pickle
import base64

from OCP.gp import gp_Vec
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common


def process(request):
    try:
        sketch_shape = request["sketch_shape"]
        depth = float(request["depth"])

        maker = BRepPrimAPI_MakePrism(sketch_shape, gp_Vec(0, 0, depth))
        maker.Build()
        result = maker.Shape()

        return {
            "success": True,
            "exception": None,
            "shape": result,
        }
    except Exception as e:
        return {
            "success": False,
            "exception": str(e),
            "shape": None,
        }

if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    model = process(request)
    wrapper_common.handle_output(model)
