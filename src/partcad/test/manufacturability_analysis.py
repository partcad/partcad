#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Manufacturability shape analysis for the 'pc test' manufacturability checks.

Every one of these runs in a sandbox wrapper (wrapper_manufacturability), so the
core process stays free of any CAD library; only the shape's BREP envelope and
the numeric result cross the boundary.

Not to be confused with anything under `partcad.cam`, which is the *route* a
machine cuts an object with. This asks whether an object can be made at all;
that one produces the program that makes it. The names were one word until the
collision was worth removing.
"""

from .. import sandbox_versions, shape_envelope, wrapper
from ..process_crash import describe_exit_code


async def _analyze(ctx, envelope, op: str, **extra) -> dict:
    """Run one analysis of 'wrapper_manufacturability' over a shape, and hand back its result.

    'envelope' is the shape's BREP envelope, as returned by Shape.get_wrapped().
    'extra' is whatever else that analysis needs: a second shape to measure the
    first against, the axis a machine works along. It travels in the same
    request, which is what keeps one round trip to the sandbox per question --
    the sandbox is the expensive part, not the arithmetic inside it.
    """
    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

    wrapper_path = wrapper.get("manufacturability.py")
    request = {"shape": envelope, "op": op}
    request.update(extra)
    exitcode, response_serialized, errors = await runtime.run_async(
        [wrapper_path, "manufacturability"], shape_envelope.serialize(request)
    )
    if exitcode != 0 and not errors:
        errors = "manufacturability analysis failed: %s" % describe_exit_code(exitcode)
    if errors:
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "manufacturability analysis failed")
    return result


async def free_bounds_count(ctx, envelope):
    """The number of free bounds of the shape (0 for a closed solid)."""
    return (await _analyze(ctx, envelope, "free_bounds"))["free_bounds"]


async def flatness(ctx, envelope) -> dict:
    """How much of the shape lies in the horizontal planes at its top and bottom.

    'z_min'/'z_max' say where those planes are, and 'area_min'/'area_max' how
    much of the shape each of them meets - zero where the shape merely touches
    it. See 'wrappers/wrapper_manufacturability.flatness', which is where it is
    worked out.
    """
    return await _analyze(ctx, envelope, "flatness")


async def enclosure(ctx, envelope, source_envelope) -> dict:
    """Whether the source strictly contains the part, and by how much.

    'outside_volume' is what the part has and the stock did not, and
    'removed_volume' is what the machine takes off. A subtractive part needs the
    first to be nothing and the second to be something. See
    'wrappers/wrapper_manufacturability.enclosure', which is where it is worked
    out, for why both are asked.
    """
    return await _analyze(ctx, envelope, "enclosure", source=source_envelope)


async def wall_alignment(ctx, envelope, tool_axis_vector, source_envelope=None) -> dict:
    """How the shape's faces lie relative to the axis a machine works along.

    'walls' are the faces parallel to that axis -- the ones a beam or a drill
    can make -- 'caps' the ones across it, which it does not cut at all, and
    'other' the ones that are neither and so cannot be produced on it. 'round'
    counts the walls that are cylinders coaxial with the axis, which is what a
    drill is limited to. 'offenders' describes up to eight of the 'other' ones,
    so a failure can name what is wrong rather than only how many.
    """
    extra = {} if source_envelope is None else {"source": source_envelope}
    return await _analyze(ctx, envelope, "wall_alignment", tool_axis_vector=list(tool_axis_vector), **extra)


async def cut(ctx, envelope, source_envelope, cuts: list) -> dict:
    """What cutting the stock across at 'cuts' leaves, compared with the part.

    'extra_volume' is what the part has beyond the cut stock and
    'missing_volume' what the cut stock has beyond the part; a part a saw can
    make has neither. 'removed' is what each cut took off, and 'planes' where
    each one was, resolved against the stock. See
    'wrappers/wrapper_manufacturability.cut'.
    """
    return await _analyze(ctx, envelope, "cut", source=source_envelope, cuts=cuts)
