#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for a 'wrapper'-kind partType.

A partType of kind 'wrapper' is a package-supplied Python script that builds a
part. This meta-wrapper runs inside the PartCAD sandbox (so it may import OCP /
build123d), executes that script with 'runpy', and serializes the shape(s) it
produces back to PartFactoryWrapper.

The partType script is executed with these globals available:

    request  -- the part's config/parameters (see PartFactoryWrapper)

and is expected to leave its result in a global 'output':

    output = {"shape": <TopoDS_Shape>}                # a single shape, or
    output = {"shapes": [<TopoDS_Shape>, ...]}        # several, or
    output = {"exception": "<message>"}               # a failure

Both '__file__' and the run name '__partcad_part__' are set on the script, so it
can gate its build logic (``if __name__ == "__partcad_part__":``) and remain
importable for its own unit tests.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        result = runpy.run_path(
            path,
            init_globals={"request": request},
            run_name="__partcad_part__",
        )
    except Exception as e:
        wrapper_common.handle_exception(e, path)
        return {"success": False, "exception": wrapper_common.exception_to_str(e), "shapes": []}

    output = result.get("output", {}) if isinstance(result, dict) else {}

    shapes = output.get("shapes")
    if shapes is None:
        shape = output.get("shape")
        shapes = [shape] if shape is not None else []

    exception = output.get("exception")
    if exception:
        wrapper_common.handle_exception(Exception(str(exception)), path)
        return {"success": False, "exception": str(exception), "shapes": shapes}

    return {"success": True, "exception": None, "shapes": shapes}


path, request = wrapper_common.handle_input()
result = process(path, request)
wrapper_common.handle_output(result)
