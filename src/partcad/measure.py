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

A measurement is remembered (see 'partcad.cache_artifacts'), keyed on the
envelope it was asked of and where from: the length a connection is pushed
through is measured once per object and frame, not once per process that asks.
"""

from . import cache_artifacts
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, wrapper
from .geom import Location
from .process_crash import describe_exit_code

# The bounding box only needs OCCT itself, no CAD kernel on top of it.
_DEPENDENCIES = (sandbox_versions.OCP,)


async def _run(ctx, request, cacheable: bool = True):
    if ctx is None:
        raise ValueError("A context is required to run the '%s' measurement" % request.get("operation"))

    operation = request["operation"]
    request_serialized = shape_envelope.serialize(request)

    cache = getattr(ctx, "cache_artifacts", None)
    artifact = cache_artifacts.wrapper_hash(
        "measure#%s" % operation,
        "measure.py",
        cache_artifacts.request_key(request) if cacheable else None,
        _DEPENDENCIES,
    )
    response_serialized = await cache_artifacts.restore_response_async(cache, artifact)
    cached = response_serialized is not None
    if not cached:
        runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        for dep in _DEPENDENCIES:
            await runtime.ensure_async(dep)

        command = [wrapper.get("measure.py"), operation]
        exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
        if exitcode != 0 and not errors:
            errors = "measure '%s' failed: %s" % (operation, describe_exit_code(exitcode))
        if errors:
            pc_logging.error(errors)
            raise Exception(errors)

    response = shape_envelope.deserialize(response_serialized)
    if not response.get("success", False):
        raise Exception(response.get("exception") or ("measure '%s' failed" % operation))
    if not cached:
        await cache_artifacts.store_response_async(cache, artifact, response_serialized)
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


async def bbox(ctx, shape, frame: Location = None, cacheable: bool = True):
    """The bounding box of 'shape' as [xmin, ymin, zmin, xmax, ymax, zmax].

    'frame' is the coordinate system to measure in - a 'geom.Location', most
    often a port's placement - and defaults to the shape's own. Returns None for
    an empty shape. 'cacheable' False - the shape of an object with
    `cache: false` - is measured every time.
    """
    return await _run(ctx, {"operation": "bbox", "shape": in_frame(shape, frame)}, cacheable)


async def measurements(ctx, shape, cacheable: bool = True):
    """How big 'shape' is and how much of it there is, in one sandbox trip.

    ``{"bbox": [xmin, ymin, zmin, xmax, ymax, zmax] | None, "volume": float |
    None, "solids": int}``, in the shape's own coordinates. 'volume' is None for
    a shape holding no solid - a sketch, a shell, a wire.

    One call rather than a box and a volume separately: what costs here is the
    sandbox process, not the arithmetic inside it, and 'pc info' wants both.
    """
    return await _run(ctx, {"operation": "measurements", "shape": shape}, cacheable)


async def extent_z(ctx, shape, frame: Location = None, cacheable: bool = True):
    """The length of 'shape' along the Z axis of 'frame', or None if unmeasurable."""
    box = await bbox(ctx, shape, frame, cacheable)
    if box is None:
        return None
    return box[5] - box[2]
