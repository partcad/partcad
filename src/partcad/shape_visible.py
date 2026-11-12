#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What of a print can be seen: its tree cut by a section, with the faces nothing can see taken out.

A part made by a printer is what the printer deposits along its route
('//builtin/cam''s 'cam_fff.deposit'): a compound of planar prisms, a layer's
wall ring, its skin, every line of its infill, never fused. That is what a
section through it has to show - the infill the cut exposes, and how full it is
- and drawn as it is, it is also tens of thousands of faces that nothing can
see: every layer lying on the next, the inside of every wall, the infill a skin
closes in. Sending, tessellating and drawing those is what makes such a part
slow to look at, for nothing.

So before such a tree is tessellated for the Digital Thread, it is cut and
stripped in one sandbox, by 'wrappers/wrapper_visible.py' (whose description
says exactly what "can be seen" is taken to mean, and where that is
approximate): a node whose geometry is a print's deposit is cut prism by prism
and keeps only the faces that face space with a way in from outside; every other
node is cut as 'shape_section' cuts it. The answer is cached on exactly what the
sandbox was handed - the tree's geometry, which the part's cache key decides,
and the section - and the glTF of what comes back is cached a shape at a time,
under the level of detail it was tessellated at, like any other (see
'shape_gltf.convert_async'). So a section moved back to where it was, or a print
shown again, is a read.

Only for drawing. What is left is a compound of faces rather than of solids, and
nothing that measures, checks, analyses or exports the part ever sees it: it is
asked for by 'Shape.show_async' and by nothing else.
"""

from . import cache_artifacts
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, shape_section, wrapper
from .process_crash import describe_exit_code

# What it takes in the sandbox: OCP for the geometry, numpy and scipy for the
# grid the empty space is followed on - all three in every sandbox's own
# environment (see 'runtime_python.base_requirements'; build123d requires scipy).
_DEPENDENCIES = (sandbox_versions.BUILD123D, sandbox_versions.OCP)


async def visible_async(ctx, tree, section=None, cacheable: bool = True):
    """'tree' - the BREP form - cut by 'section' (None: not cut), with every print in it stripped of what cannot be seen.

    A node with nothing left inside the box loses its geometry, as
    'shape_section.section_async(keep_empty=False)' leaves it, for a reader that
    draws the tree. A node that could not be looked at is cut as any shape is,
    and said so in the log; one that would not cut either is left whole.

    'cacheable' False - a subject with `cache: false` - does it every time.

    Raises if the sandbox could not be run or answered a failure.
    """
    section = shape_section.normalize(section)
    if tree is None:
        return tree
    if ctx is None:
        raise ValueError("A context is required to look at a shape tree")
    if not shape_envelope.is_node(tree):
        raise ValueError("Not a shape tree: %r" % (list(tree) if isinstance(tree, dict) else type(tree),))

    request = {"tree": tree, "section": section}
    cache = getattr(ctx, "cache_artifacts", None)
    artifact = cache_artifacts.wrapper_hash(
        "%s#visible" % (tree.get("name") or "tree"),
        "visible.py",
        cache_artifacts.request_key(request) if cacheable else None,
        _DEPENDENCIES,
    )
    response_serialized = await cache_artifacts.restore_response_async(cache, artifact)
    cached = response_serialized is not None
    if not cached:
        runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        for dep in _DEPENDENCIES:
            await runtime.ensure_async(dep)
        # argv[1] is required of every wrapper and unused by this one, which
        # answers over the pipe: it carries the operation name. The tree's
        # repeated payloads travel once each, attached to the frame raw (see
        # 'shape_envelope.serialize').
        exitcode, response_serialized, errors = await runtime.run_async(
            [wrapper.get("visible.py"), "visible"],
            lambda: shape_envelope.serialize(request),
        )
        if exitcode != 0 and not errors:
            errors = "Failed to work out what of the shape tree can be seen (%s)" % describe_exit_code(exitcode)
        if errors:
            raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "Failed to work out what of the shape tree can be seen")
    for reason in result.get("errors") or []:
        pc_logging.warning("Drawn as cut, with nothing left out (%s): %s" % (shape_section.describe(section), reason))
    if result.get("dropped"):
        pc_logging.debug(
            "%s: %d face(s) of a print drawn, %d that nothing can see left out (%s)"
            % (
                tree.get("name") or "a shape tree",
                result.get("kept") or 0,
                result.get("dropped") or 0,
                shape_section.describe(section),
            )
        )
    shown = result.get("tree")
    if not isinstance(shown, dict):
        raise Exception("Working out what can be seen produced no shape tree")
    if not cached:
        await cache_artifacts.store_response_async(cache, artifact, response_serialized)
    return shown
