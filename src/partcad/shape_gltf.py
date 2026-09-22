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

# The tessellation a preview gets. Coarser than a render's default would be worth:
# this has to cross a socket and load in a webview, not print.
DEFAULT_TOLERANCE = 0.1
DEFAULT_ANGULAR_TOLERANCE = 0.2

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
    """'tree' with every node's BREP replaced by tessellated glTF.

    Raises if the sandbox could not be run or answered a failure. A single node
    whose geometry will not tessellate is not that: it comes back without
    geometry and with the reason logged, because the rest of the tree is still
    worth looking at - a sketch made of edges alone has no triangles to write and
    is the ordinary case of it.
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
        "tolerance": DEFAULT_TOLERANCE if tolerance is None else tolerance,
        "angularTolerance": DEFAULT_ANGULAR_TOLERANCE if angular_tolerance is None else angular_tolerance,
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
    return converted
