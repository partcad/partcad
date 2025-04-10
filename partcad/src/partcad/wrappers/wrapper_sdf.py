import os
import re
import sys
import tempfile
from typing import Iterable
import numpy as np

import sdf
from OCP.gp import gp_Pnt
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.Poly import Poly_Triangle, Poly_Array1OfTriangle, Poly_Triangulation
from OCP.TopoDS import TopoDS_Face, TopoDS_Shell, TopoDS_Solid
from OCP.BRep import BRep_Builder
from OCP.StlAPI import StlAPI_Writer

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import custom_cqgi
import py_stubs.ocp_vscode
from ocp_tessellate.ocp_utils import is_vector, vertex


def tessellate(shape):
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    mesh = BRepMesh_IncrementalMesh(shape, 0.1)
    mesh.Perform()
    return shape


def serialize_stl(shape, ascii=True):
    mode = "w" if ascii else "wb"
    with tempfile.NamedTemporaryFile(suffix=".stl", mode=mode, delete=False) as f:
        writer = StlAPI_Writer()
        writer.SetASCIIMode(ascii)
        writer.Write(shape, f.name)
        f.flush()
        f.seek(0)
        return f.read()


def sdf_triangles_to_topods(triangles: np.ndarray, as_solid: bool = False):
    if len(triangles) == 0:
        return None

    arr = np.array(triangles)
    pts = TColgp_Array1OfPnt(1, len(arr))
    for i, (x, y, z) in enumerate(arr):
        pts.SetValue(i + 1, gp_Pnt(x, y, z))

    n_tris = len(arr) // 3
    tris = Poly_Array1OfTriangle(1, n_tris)
    for i in range(n_tris):
        t = Poly_Triangle(i * 3 + 1, i * 3 + 2, i * 3 + 3)
        tris.SetValue(i + 1, t)

    poly = Poly_Triangulation(pts, tris)

    face = TopoDS_Face()
    builder = BRep_Builder()
    builder.MakeFace(face, poly)

    if as_solid:
        shell = TopoDS_Shell()
        builder.MakeShell(shell)
        builder.Add(shell, face)

        solid = TopoDS_Solid()
        builder.MakeSolid(solid)
        builder.Add(solid, shell)
        return solid

    return face


def process(path, request):
    try:
        build_parameters = request.get("build_parameters", {})
        patch = request.get("patch", {})

        with open(path, "r", encoding="utf-8") as fobj:
            script = fobj.read()

        if "import partcad" in script:
            script = "import logging\nlogging.basicConfig(level=60)\n" + script

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

        for param in build_parameters:
            pattern = r"^\s*" + re.escape(param) + r"\s*=.*$"
            script = re.sub(pattern, "", script, flags=re.MULTILINE)

        injected_params = "\n".join(f"{k} = {repr(v)}" for k, v in build_parameters.items())
        script = injected_params + "\n" + script

        script_object = custom_cqgi.parse(script)
        build_result = script_object.build(build_parameters=build_parameters)

        if not build_result.success:
            wrapper_common.handle_exception(build_result.exception, path)

        step = build_parameters.get("step")
        samples = build_parameters.get("samples", 2**16)
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

                    if shape_3d is None or (hasattr(shape_3d, "IsNull") and shape_3d.IsNull()):
                        continue

                    results.append(shape_3d)

                except Exception:
                    continue

            elif isinstance(shape, Iterable):

                def unpack(objs):
                    for obj in objs:
                        if isinstance(obj, sdf.d3.SDF3):
                            try:
                                pts = obj.generate(
                                    step=step,
                                    samples=samples,
                                    sparse=sparse,
                                    verbose=False,
                                )
                                tpts = np.array(pts).reshape(-1, 3)
                                yield sdf_triangles_to_topods(tpts)
                            except Exception:
                                continue
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
