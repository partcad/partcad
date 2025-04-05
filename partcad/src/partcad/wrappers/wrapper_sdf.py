import os
import re
import sys
import io
from typing import Iterable
import numpy as np
from contextlib import redirect_stdout

import sdf

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import custom_cqgi
import py_stubs.ocp_vscode
from ocp_serialize import sdf_triangles_to_topods
from ocp_tessellate.ocp_utils import (
    is_vector,
    vertex,
)


def process(path, request):
    try:
        build_parameters = request.get("build_parameters", {})
        patch = request.get("patch", {})

        with open(path, "r", encoding="utf-8") as fobj:
            script = fobj.read()

        # Apply regex patches from the request
        for old, new in patch.items():
            script = re.sub(old, new, script, flags=re.MULTILINE)

        if "import partcad" in script:
            script = "import logging\nlogging.basicConfig(level=60)\n" + script  # Disable PartCAD logging

        # Ignore ocp_vscode as it is of no use in the sandboxed environment
        # and it produces a lot of sporadic output to stdout and stderr
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

        script_object = custom_cqgi.parse(script)
        build_result = script_object.build(build_parameters=build_parameters)

        if not build_result.success:
            wrapper_common.handle_exception(build_result.exception, path)

        step = build_parameters.get("step")
        samples = build_parameters.get("samples", 2**20)
        batch_size = build_parameters.get("batch_size", 32)
        sparse = build_parameters.get("sparse", True)

        results = []
        for result in build_result.results:
            shape = result.shape

            if isinstance(shape, sdf.d3.SDF3):
                try:
                    points = shape.generate(
                        step=step,
                        samples=samples,
                        batch_size=batch_size,
                        sparse=sparse,
                        verbose=False,
                    )
                    tri_points = np.array(points).reshape(-1, 3)
                    shape_3d = sdf_triangles_to_topods(tri_points)
                    results.append(shape_3d)
                    continue
                except Exception as e:
                    results.append(shape)

            elif isinstance(shape, Iterable):
                def unpack(objs):
                    for obj in objs:
                        if isinstance(obj, sdf.d3.SDF3):
                            try:
                                pts = shape.generate(
                                    step=step,
                                    samples=samples,
                                    sparse=sparse,
                                    verbose=False,
                                )
                                tpts = np.array(pts).reshape(-1, 3)
                                yield sdf_triangles_to_topods(tpts)
                            except Exception as e:
                                yield obj
                        elif is_vector(obj):
                            yield vertex(obj.wrapped)
                        else:
                            yield obj

                results.extend(unpack(shape))

            else:
                results.append(shape)

        return {
            "success": build_result.success,
            "exception": build_result.exception,
            "shapes": results,
        }

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
        }


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    result = process(path, request)
    wrapper_common.handle_output(result)
