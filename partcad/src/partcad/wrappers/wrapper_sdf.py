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
import custom_cqgi
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
    
    if "import partcad" in script:
        script = "import logging\nlogging.basicConfig(level=60)\n" + script  # Disable PartCAD logging

    sys.modules["ocp_vscode"] = sys.modules["py_stubs.ocp_vscode"]
    if "from ocp_vscode import " in script:
        script = re.sub(
            r"(from ocp_vscode import .*)\n",
            "saved_show_object_early=show_object\n\\1\nimport ocp_vscode\nocp_vscode.saved_show_object=saved_show_object_early\n",
            script,
        )
    if "import ocp_vscode" in script:
        script = script.replace(
            "import ocp_vscode",
            "import ocp_vscode\nocp_vscode.saved_show_object=show_object\n#",
        )
    
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
