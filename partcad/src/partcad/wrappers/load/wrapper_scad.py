import os
import shutil
import sys
import tempfile
import subprocess
import base64
import pickle

import build123d as b3d

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import wrapper_common


def process(scad_path):
    result = {
        "success": False,
        "exception": None,
        "shape": None,
        "components": [],
    }

    try:
        openscad_exe = shutil.which("openscad")
        if not openscad_exe:
            raise RuntimeError("OpenSCAD executable not found in PATH")

        stl_path = tempfile.mktemp(".stl")

        process = subprocess.run(
            [
                openscad_exe,
                "--export-format", "binstl",
                "-o", stl_path,
                scad_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        if not os.path.exists(stl_path) or os.path.getsize(stl_path) == 0:
            raise RuntimeError("OpenSCAD failed to produce a valid STL file")

        try:
            shape = b3d.Mesher().read(stl_path)[0].wrapped
        except Exception:
            shape = b3d.import_stl(stl_path).wrapped

        result["shape"] = shape
        result["components"] = [shape]
        result["success"] = True

        os.unlink(stl_path)
    except Exception as e:
        result["exception"] = str(e)

    return result


if __name__ == "__main__":
    scad_path, _ = wrapper_common.handle_input()
    model = process(scad_path)
    wrapper_common.handle_output(model)
