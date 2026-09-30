#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The glTF form of a shape tree: the same tree, tessellated.

A shape is carried as a tree of nodes - a part is one node, an assembly is a node
per thing it holds, an interface is a node per port - and the geometry at each
node takes one of two forms (see 'shape_envelope.FORM_BREP' / 'FORM_GLTF'). BREP
is what the core composes and caches, because it is exact. glTF is what something
can draw, because it is triangles. This module is the conversion from the first
to the second, and it is a conversion of the *tree*: nothing about the hierarchy,
the names, the placements or the ports changes, only what sits at each node that
has geometry.

It runs in a sandbox, like every other operation on geometry: the core has no CAD
library and never holds a live OCP object. One sandbox for the whole tree rather
than one per node, because starting an interpreter and importing OCP is seconds
and tessellating a part is not - an assembly of five hundred parts converted one
node at a time would cost longer than building it.

Nothing here is specific to the IDE viewer. The viewer is the one caller today
(see 'viewer.py'), and it is the reason the form exists, but a caller that wants
a drawable tree asks the shape for one: 'shape.get_representation(ctx, "gltf")'.
"""

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, wrapper
from .process_crash import describe_exit_code

# The tessellation a preview gets, as a budget in *pixels* rather than a distance
# in millimetres. A preview is looked at, so what decides whether it is fine
# enough is how far a facet lands from the surface on the screen - and that is the
# chord error divided by what a pixel is worth, which depends on the size of the
# thing being shown. A part 5 mm across and an assembly 5 m across want the same
# answer to "is this smooth enough" and two very different deflections to get it.
#
# So the linear deflection is derived, per tree, from the overall size of that
# tree: SCREEN_PIXELS is the viewport this budget assumes, PIXEL_BUDGET is how much
# of one pixel the tessellation may be out by, and the wrapper divides the
# bounding box diagonal by the two of them together (see 'wrapper_gltf._budget').
# At a half pixel over a thousand, a facet is out by a five-hundredth of what is on
# screen, whatever the object is.
#
# It is a budget for the whole object shown at once, which is what the viewer shows
# when a tree arrives, and deliberately not for a close-up: zoom far enough into
# any tessellation and it is faceted. Trading that away is what makes an assembly
# openable at all.
SCREEN_PIXELS = 1000
PIXEL_BUDGET = 0.5
SCREEN_DIVISOR = SCREEN_PIXELS / PIXEL_BUDGET

# What that budget may not exceed in either direction, in mm. The floor keeps a
# tiny object from being tessellated to death for no visible gain, and the ceiling
# keeps a bogus bounding box - a stray node a kilometre from the origin - from
# flattening everything else into facets.
MIN_TOLERANCE = 0.001
MAX_TOLERANCE = 10.0

# The angular cap, in radians, and the one number here that is *not* a function of
# the object's size - which is exactly why it is the one that matters most on a
# large assembly. A curve is tessellated to whichever is the finer of the linear
# budget above and this angle between successive segments, and for a small radius
# the angle always wins: at 0.2 rad a 3 mm hole is drawn with 31 segments whether
# it covers two hundred pixels or two. So its job here is only to keep a circle
# from degenerating into a triangle, and the linear budget above does the real
# work.
#
# Measured on '//pub/examples/partcad/feature_import:AeroAssembly_assy_example/
# AeroAssembly_connected' (8 parts, 413 mm diagonal), holding the linear budget at
# diagonal/2000: 0.2 rad gives 48304 triangles, 0.3 gives 30624, 0.4 gives 23480,
# 0.5 gives 19752. The knee is between 0.3 and 0.5; below it the extra triangles
# are nearly all in small features that are a few pixels across when the whole
# object is shown.
DEFAULT_ANGULAR_TOLERANCE = 0.4

# export_gltf is build123d's; cadquery-ocp comes last because build123d pulls
# the VTK-less 'cadquery-ocp-novtk' build over it (see sandbox_versions).
_DEPENDENCIES = (sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP)


async def in_form_async(ctx, tree, form):
    """'tree' with its geometry in 'form', whatever form it arrived in.

    The one place that decides what a form means, so that every kind of subject -
    a part, an assembly, an interface - answers 'get_representation()' the same
    way and none of them has to know that glTF is produced by a sandbox.
    """
    if form == shape_envelope.FORM_BREP:
        return tree
    shape_envelope.geometry_key(form)
    if tree is None:
        return None
    return await convert_async(ctx, tree)


async def convert_async(ctx, tree, tolerance=None, angular_tolerance=None):
    """'tree' with its geometry tessellated into glTF, one copy per distinct shape.

    'tolerance' is the linear deflection in mm. Left at None - which is how the
    viewer asks - it is derived in the sandbox from the overall size of this tree,
    because that is where the geometry is and so where the size can be measured
    without a second round trip; see the budget above and 'wrapper_gltf._budget'.
    Passing one overrides that outright, for a caller that knows what it wants in
    millimetres.

    What comes back carries the geometry on the root, in KEY_GEOMETRY, with every
    node naming its entry: a hundred instances of one bolt are one entry named a
    hundred times.

    Raises if the sandbox could not be run or answered a failure. A single node
    whose geometry will not tessellate is not that: it comes back without
    geometry and with the reason logged, because the rest of the tree is still
    worth looking at. A sketch made of edges alone is not such a node: its edges
    are drawn as line segments (see 'wrapper_gltf._to_glb').
    """
    if ctx is None:
        raise ValueError("A context is required to tessellate a shape tree")
    if not shape_envelope.is_node(tree):
        raise ValueError("Not a shape tree: %r" % (list(tree) if isinstance(tree, dict) else type(tree),))

    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    # Installed one at a time, not concurrently: the order matters because
    # build123d overwrites the OCP native module cadquery-ocp installs.
    for dep in _DEPENDENCIES:
        await runtime.ensure_async(dep)

    request = {
        "tree": tree,
        # None means "work it out from the tree", which is the ordinary case; the
        # policy travels with it so that the sandbox applies this module's numbers
        # rather than a second copy of them.
        "tolerance": tolerance,
        "angularTolerance": DEFAULT_ANGULAR_TOLERANCE if angular_tolerance is None else angular_tolerance,
        "screenDivisor": SCREEN_DIVISOR,
        "minTolerance": MIN_TOLERANCE,
        "maxTolerance": MAX_TOLERANCE,
    }

    # argv[1] is mandatory for every wrapper (wrapper_common.handle_input reads
    # it as the output path). This one writes no file - the glTF comes back over
    # the pipe - so it carries the operation name, which is what shows up in
    # process listings and logs.
    exitcode, response_serialized, errors = await runtime.run_async(
        [wrapper.get("gltf.py"), "gltf"],
        shape_envelope.serialize(request),
    )
    if exitcode != 0 and not errors:
        errors = "Failed to tessellate the shape tree (%s)" % describe_exit_code(exitcode)
    if errors:
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "Failed to tessellate the shape tree")
    for reason in result.get("errors") or []:
        pc_logging.warning("Nothing to draw for %s" % reason)
    converted = result.get("tree")
    if not shape_envelope.is_node(converted):
        raise Exception("The tessellation produced no shape tree")

    # Worth one line in the log: it is the number that decides both how long this
    # took and how big what it produced is, and it is not in the configuration
    # anywhere to be read off.
    pc_logging.debug(
        "Tessellated %s: %s"
        % (
            tree.get("name") or "a shape tree",
            ", ".join(
                "%s=%s" % (key, result[key]) for key in ("tolerance", "angularTolerance", "size") if key in result
            ),
        )
    )
    return converted
