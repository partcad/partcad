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


async def _run(ctx, request, cacheable: bool = True, script: str = "measure.py"):
    if ctx is None:
        raise ValueError("A context is required to run the '%s' measurement" % request.get("operation"))

    operation = request["operation"]
    request_serialized = shape_envelope.serialize(request)

    cache = getattr(ctx, "cache_artifacts", None)
    artifact = cache_artifacts.wrapper_hash(
        "%s#%s" % (script.rsplit(".", 1)[0], operation),
        script,
        cache_artifacts.request_key(request) if cacheable else None,
        _DEPENDENCIES,
    )
    response_serialized = await cache_artifacts.restore_response_async(cache, artifact)
    cached = response_serialized is not None
    if not cached:
        runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        for dep in _DEPENDENCIES:
            await runtime.ensure_async(dep)

        command = [wrapper.get(script), operation]
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


async def displacement(ctx, shape, cacheable: bool = True):
    """How much 'shape' would push aside if it were submerged, in one sandbox trip.

    ``{"displacement": float | None, "solids": int, "cavities": int}``: the
    volume each solid's outer shell encloses, added up - its material and every
    void sealed inside it - in mm^3, and None for a shape holding no solid.
    'shape' is what 'Shape.get_wrapped' answers, a part's envelope or an
    assembly's tree; an assembly's solids are its parts'. See
    'shape_measure.displacement' among the wrappers.

    Measured when asked rather than as every shape is built: only 'pc compare'
    and a 'match:' requirement ask, and only of the objects they compare.
    """
    return await _run(ctx, {"operation": "displacement", "shape": shape}, cacheable)


async def extent_z(ctx, shape, frame: Location = None, cacheable: bool = True):
    """The length of 'shape' along the Z axis of 'frame', or None if unmeasurable."""
    box = await bbox(ctx, shape, frame, cacheable)
    if box is None:
        return None
    return box[5] - box[2]


async def surface_distance(
    ctx, reference, current, spacing: float, allowance=None, worst: int = 10, cacheable: bool = True
):
    """How far the surface of 'current' is from the surface of 'reference', point by point.

    Both are what 'Shape.get_wrapped' answers - a part's envelope or an
    assembly's tree - and are compared where they are: neither is moved onto
    the other. 'spacing' is how far apart the points measured on the reference
    are, in millimetres; 'allowance' how far apart the two surfaces may be
    anywhere, for the answer to count the points further apart than that; and
    'worst' how many of the furthest points are listed. What comes back, and how
    each point is chosen and measured, is 'wrapper_compare.surface_distance'.
    Remembered like any other measurement, by both models and every argument.
    """
    request = {
        "operation": "surface",
        "reference": reference,
        "current": current,
        "spacing": float(spacing),
        "allowance": None if allowance is None else float(allowance),
        "worst": int(worst),
    }
    return await _run(ctx, request, cacheable, "compare.py")


async def material_clusters(ctx, tree, distance: float, cacheable: bool = True):
    """Where each material of 'tree' is: its clusters, as the "Materials" callout writes them.

    'tree' is a shape tree as 'Shape.get_wrapped' answers it, and 'distance' how
    far apart two surfaces of one material may be and still be one cluster, in
    millimetres. Each cluster is '{"material", "name", "at", "nodes", "faces"}'
    (see 'material_clusters.clusters' among the wrappers): what it is made of,
    what a person reads that as, the point of it a callout is pinned to in the
    frame of the tree, the path of every node with a face in it, and how many
    faces it is. Remembered like a measurement, by the tree and the distance.
    """
    request = {"operation": "clusters", "shape": tree, "distance": float(distance)}
    return await _run(ctx, request, cacheable, "materials.py")
