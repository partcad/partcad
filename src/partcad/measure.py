#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Measure geometry inside a sandbox.

The core process carries shapes as BREP bytes and does not manipulate live OCP
objects, so the OCCT work that a measurement needs happens in
wrapper_measure.py inside a managed Python runtime. This module is the
core-side entry point: it takes the shape as a BREP envelope, runs the wrapper,
and returns plain numbers. Serialization goes through the pure 'shape_envelope'
codec, so this module never touches OCP.
"""

from . import logging as pc_logging
from . import sandbox_versions
from . import shape_envelope
from . import wrapper
from .geom import Location

# The bounding box only needs OCCT itself, no CAD kernel on top of it.
_DEPENDENCIES = (sandbox_versions.CADQUERY_OCP,)


async def _run(ctx, request):
    if ctx is None:
        raise ValueError("A context is required to run the '%s' measurement" % request.get("operation"))

    operation = request["operation"]
    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    for dep in _DEPENDENCIES:
        await runtime.ensure_async(dep)

    wrapper_path = wrapper.get("measure.py")
    request_serialized = shape_envelope.serialize(request)
    command = [wrapper_path, operation]
    exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
    if exitcode != 0 and not errors:
        errors = "measure '%s' failed with exit code %s" % (operation, exitcode)
    if errors:
        pc_logging.error(errors)
        raise Exception(errors)

    response = shape_envelope.deserialize(response_serialized)
    if not response.get("success", False):
        raise Exception(response.get("exception") or ("measure '%s' failed" % operation))
    return response["result"]


def in_frame(shape, frame):
    """The shape envelope re-stamped so that it is placed in 'frame' coordinates.

    Measuring "along the Z axis of a port" means measuring the shape as the port
    sees it, which is the shape moved by the inverse of the port's location.
    """
    if frame is None:
        return shape
    placement = frame.inverse()
    own = shape.get(shape_envelope.KEY_LOCATION)
    composed = placement if own is None else (placement * Location(own))
    placed = dict(shape)
    placed[shape_envelope.KEY_LOCATION] = composed.as_packed()
    return placed


async def bbox(ctx, shape, frame: Location = None):
    """The bounding box of 'shape' as [xmin, ymin, zmin, xmax, ymax, zmax].

    'frame' is the coordinate system to measure in - a 'geom.Location', most
    often a port's placement - and defaults to the shape's own. Returns None for
    an empty shape.
    """
    return await _run(ctx, {"operation": "bbox", "shape": in_frame(shape, frame)})


async def extent_z(ctx, shape, frame: Location = None):
    """The length of 'shape' along the Z axis of 'frame', or None if unmeasurable."""
    box = await bbox(ctx, shape, frame)
    if box is None:
        return None
    return box[5] - box[2]
