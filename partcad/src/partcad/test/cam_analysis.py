#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Manufacturability shape analysis for the CAM 'pc test' checks.

The OCCT free-bounds analysis runs in a sandbox wrapper (wrapper_cam), so the
core process stays free of any CAD library; only the shape's BREP envelope and
the numeric result cross the boundary.
"""

from .. import wrapper
from .. import shape_envelope
from .. import sandbox_versions


async def free_bounds_count(ctx, envelope):
    """The number of free bounds of the shape (0 for a closed solid).

    'envelope' is the shape's BREP envelope, as returned by Shape.get_wrapped().
    """
    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

    wrapper_path = wrapper.get("cam.py")
    request = {"shape": envelope}
    exitcode, response_serialized, errors = await runtime.run_async(
        [wrapper_path, "cam"], shape_envelope.serialize(request)
    )
    if exitcode != 0 and not errors:
        errors = "cam analysis failed with exit code %s" % exitcode
    if errors:
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "cam analysis failed")
    return result["free_bounds"]
