import os
import re
import sys
import io
import numpy as np
from contextlib import redirect_stdout

try:
    from sdf import *
except ImportError as e:
    pass

sys.path.append(os.path.dirname(__file__))
import wrapper_common
from ocp_serialize import sdf_triangles_to_topods


def process(path, request):
    # Retrieve parameterization info from the request
    build_parameters = request.get("build_parameters", {})
    patch = request.get("patch", {})

    with open(path, "r", encoding="utf-8") as fobj:
        script = fobj.read()

    # Apply regex patches from the request
    for old, new in patch.items():
        script = re.sub(old, new, script, flags=re.MULTILINE)

    # Remove any existing assignments for our parameters in the script.
    for param in build_parameters.keys():
        pattern = r"^\s*" + re.escape(param) + r"\s*=.*$"
        script = re.sub(pattern, "", script, flags=re.MULTILINE)

    # Inject external parameter definitions at the top.
    param_injection = []
    for k, v in build_parameters.items():
        if isinstance(v, (int, float)):
            param_injection.append(f"{k} = {v}")
        else:
            param_injection.append(f"{k} = '{v}'")
    injected_params = "\n".join(param_injection)
    script = injected_params + "\n" + script

    loc = {"__name__": "__cqgi__"}
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            exec(script, loc, loc)
            if "f" not in loc:
                raise RuntimeError("No 'f' object found in script.")
            shape_sdf = loc["f"]
            points = shape_sdf.generate(verbose=False)
            tri_points = np.array(points).reshape(-1, 3)
            shape_3d = sdf_triangles_to_topods(tri_points)
        sys.stderr.write(buf.getvalue())
        return {
            "success": True,
            "exception": None,
            "shapes": [shape_3d],
        }
    except Exception as e:
        sys.stderr.write(buf.getvalue())
        return {"success": False, "exception": f"{e}", "shapes": []}


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    result = process(path, request)
    wrapper_common.handle_output(result)
