#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Run geometry transformations (offset, scale, compound) inside a sandbox.

The core process carries shapes as BREP bytes and does not manipulate live OCP
objects. The OCCT/build123d work that 'offset', 'scale' and 'compound' need
therefore happens in wrapper_transform.py inside a managed Python runtime, not
in-process. This module is the core-side entry point: it takes the operand
shape(s) as BREP envelopes, runs the wrapper, and returns the result as a BREP
envelope. Serialization goes through the pure 'shape_envelope' codec, so this
module never touches OCP.
"""

from . import wrapper
from . import sandbox_versions
from . import shape_envelope
from . import logging as pc_logging

# 'offset'/'scale' mirror the build123d relocate()/scale() the core used to run
# in-process, so their runtime needs build123d; 'compound' only needs OCP to
# combine shapes. cadquery-ocp comes last because build123d pulls the VTK-less
# 'cadquery-ocp-novtk' build over it (see sandbox_versions).
_DEPENDENCIES = {
    "offset": (sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP),
    "scale": (sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP),
    "compound": (sandbox_versions.CADQUERY_OCP,),
}


async def _run(ctx, request):
    if ctx is None:
        raise ValueError("A context is required to run the '%s' transform" % request.get("operation"))

    operation = request["operation"]
    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    # Installed one at a time, not concurrently: the order matters because
    # build123d overwrites the OCP native module cadquery-ocp installs.
    for dep in _DEPENDENCIES[operation]:
        await runtime.ensure_async(dep)

    wrapper_path = wrapper.get("transform.py")
    request_serialized = shape_envelope.serialize(request)
    command = [wrapper_path, operation]
    exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
    if exitcode != 0 and not errors:
        errors = "transform '%s' failed with exit code %s" % (operation, exitcode)
    if errors:
        pc_logging.error(errors)
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or ("transform '%s' failed" % operation))
    return result["shape"]


async def offset(ctx, shape, offset):
    """Relocate 'shape' by the packed [translation, axis, angle] offset."""
    return await _run(ctx, {"operation": "offset", "shape": shape, "offset": offset})


async def scale(ctx, shape, factor):
    """Scale 'shape' by 'factor'."""
    return await _run(ctx, {"operation": "scale", "shape": shape, "scale": factor})


async def compound(ctx, shapes):
    """Combine 'shapes' into a single compound."""
    return await _run(ctx, {"operation": "compound", "shapes": list(shapes)})
