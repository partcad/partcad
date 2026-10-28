#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A cross-section: an object cut by a box before anything is drawn of it.

What the Digital Thread's section sliders ask for. Each of the three says how
much of the object to keep along one axis, from where to where, in the frame
the object is shown in - millimetres, Z up, the frame of its tree's root - and
the three together are a box:

    {"x": [-10.0, 25.0], "z": [0.0, 12.5]}

keeps what lies between those planes and cuts the rest away. An axis that is
not named is not cut, and a section that names none is no section at all
('normalize' says so by answering None, which is what every caller passes on
as "draw the whole object").

The cut is a CAD operation, so it is done where every other one is: in the
sandbox, by 'wrappers/wrapper_section.py', on the BREP form of the tree, node by
node - so a cut object is still the same tree of nodes, and the viewer, a
filter and a render implementation all read it as they read the whole one. Two
callers, two ways in:

  * the 3D view's glTF is cut and tessellated in one sandbox, by handing the
    section to the glTF wrapper with the tree (see 'shape_gltf.convert_async');
  * a file - the 2D tab's picture, the Draft tab's drawing - is written by an
    implementation that is handed a BREP tree, so the tree is cut first, here
    ('section_async'), and the implementation is handed the cut.

Either answer is cached on exactly what the sandbox was handed, the section
included, so moving a slider back to where it was is a read.
"""

import math
from typing import Optional

from . import cache_artifacts
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, wrapper
from .process_crash import describe_exit_code

# The axes a section names, in the order of a point's coordinates.
AXES = ("x", "y", "z")

# What cutting needs in the sandbox: OCP's booleans, through the same stack the
# glTF wrapper asks for, which is what every sandbox's own environment holds
# (see 'runtime_python.base_requirements').
_DEPENDENCIES = (sandbox_versions.BUILD123D, sandbox_versions.OCP)


def normalize(section) -> Optional[dict]:
    """The section a request asks for, checked, or None for "do not cut".

    'section' is a mapping of axis to a pair of numbers, '[lo, hi]', or to None
    for an axis left uncut - what a client sends. What comes back names only the
    axes that cut, each as two floats, in a canonical form: the same section
    asked for twice is one key in every cache that holds an answer to it.

    Raises:
        ValueError: anything that is not such a mapping, an axis that is not
            one of 'AXES', or a pair that keeps nothing (lo not below hi) or is
            not two finite numbers.
    """
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError("A section is a mapping of axis to [from, to], not %r" % (section,))
    unknown = sorted(str(key) for key in section if key not in AXES)
    if unknown:
        raise ValueError("A section cuts along x, y and z; %s is not an axis" % ", ".join(unknown))
    normalized = {}
    for axis in AXES:
        value = section.get(axis)
        if value is None:
            continue
        # A string is a sequence too, and "12" would read as [1, 2].
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("The %s of a section is [from, to], two numbers; got %r" % (axis, value))
        try:
            low, high = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            raise ValueError("The %s of a section is [from, to], two numbers; got %r" % (axis, value)) from None
        if not (math.isfinite(low) and math.isfinite(high)):
            raise ValueError("The %s of a section must be finite; got %r" % (axis, value))
        if not low < high:
            raise ValueError(
                "The %s of a section keeps nothing: it runs from %g to %g, and 'from' has to be below 'to'"
                % (axis, low, high)
            )
        normalized[axis] = [low, high]
    return normalized or None


def describe(section) -> str:
    """'section' as one line for a log: "x 0..25, z 0..12.5"."""
    if not section:
        return "nothing cut"
    return ", ".join("%s %g..%g" % (axis, section[axis][0], section[axis][1]) for axis in AXES if axis in section)


async def section_async(ctx, tree, section, cacheable: bool = True, keep_empty: bool = True):
    """'tree' - the BREP form - with the geometry of every node cut by 'section'.

    'section' is normalized first; one that cuts nothing hands back 'tree' as
    it was, without a sandbox. A node with nothing left inside the box keeps its
    place with an empty compound for geometry, so that what reads the tree as
    shapes - a render implementation decoding it - reads every node it had; a
    node that would not cut is left whole, and said so in the log.

    'cacheable' False - a subject with `cache: false` - cuts every time.

    'keep_empty' False leaves such a node with no geometry at all instead, for
    a reader that draws the tree rather than decodes it (see
    'shape_gltf.convert_async').

    Raises if the sandbox could not be run or answered a failure.
    """
    section = normalize(section)
    if section is None or tree is None:
        return tree
    if ctx is None:
        raise ValueError("A context is required to cut a shape tree")
    if not shape_envelope.is_node(tree):
        raise ValueError("Not a shape tree: %r" % (list(tree) if isinstance(tree, dict) else type(tree),))

    request = {"tree": tree, "section": section}
    if not keep_empty:
        # Only when asked, so that a cut for a reader that decodes the tree is
        # asked - and cached - as it always was.
        request["keepEmpty"] = False

    cache = getattr(ctx, "cache_artifacts", None)
    artifact = cache_artifacts.wrapper_hash(
        "%s#section" % (tree.get("name") or "tree"),
        "section.py",
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
        # 'shape_envelope.serialize'), serialized when the process starts (see
        # 'shape_gltf.convert_async').
        exitcode, response_serialized, errors = await runtime.run_async(
            [wrapper.get("section.py"), "section"],
            lambda: shape_envelope.serialize(request),
        )
        if exitcode != 0 and not errors:
            errors = "Failed to cut the shape tree (%s)" % describe_exit_code(exitcode)
        if errors:
            raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "Failed to cut the shape tree")
    for reason in result.get("errors") or []:
        pc_logging.warning("Shown uncut, because it could not be cut (%s): %s" % (describe(section), reason))
    cut = result.get("tree")
    # Kept empty or not, what comes back is a node: one with nothing left in the
    # box and not kept empty is a node with no geometry, for its reader to say so.
    if not (shape_envelope.is_node(cut) or (not keep_empty and isinstance(cut, dict))):
        raise Exception("Cutting produced no shape tree")
    if not cached:
        await cache_artifacts.store_response_async(cache, artifact, response_serialized)
    return cut
