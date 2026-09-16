#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Manufacturability shape analysis for the 'pc test' manufacturability checks.

The OCCT free-bounds analysis runs in a sandbox wrapper
(wrapper_manufacturability), so the core process stays free of any CAD library;
only the shape's BREP envelope and the numeric result cross the boundary.

Not to be confused with anything under `partcad.cam`, which is the *route* a
machine cuts an object with. This asks whether an object can be made at all;
that one produces the program that makes it. The names were one word until the
collision was worth removing.
"""

from .. import sandbox_versions, shape_envelope, wrapper


async def free_bounds_count(ctx, envelope):
    """The number of free bounds of the shape (0 for a closed solid).

    'envelope' is the shape's BREP envelope, as returned by Shape.get_wrapped().
    """
    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

    wrapper_path = wrapper.get("manufacturability.py")
    request = {"shape": envelope}
    exitcode, response_serialized, errors = await runtime.run_async(
        [wrapper_path, "manufacturability"], shape_envelope.serialize(request)
    )
    if exitcode != 0 and not errors:
        errors = "manufacturability analysis failed with exit code %s" % exitcode
    if errors:
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "manufacturability analysis failed")
    return result["free_bounds"]
