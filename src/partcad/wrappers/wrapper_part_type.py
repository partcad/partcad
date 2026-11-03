#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for a 'wrapper'-kind partType.

A partType of kind 'wrapper' is a package-supplied Python script that builds a
part. This meta-wrapper runs inside the PartCAD sandbox (so it may import OCP /
build123d), executes that script with 'runpy', and serializes the shape(s) it
produces back to PartFactoryWrapper.

The partType script is executed with these globals available:

    request  -- the part's config/parameters (see PartFactoryWrapper)

and is expected to leave its result in a global 'output':

    output = {"shape": <TopoDS_Shape>}                # a single shape, or
    output = {"shapes": [<TopoDS_Shape>, ...]}        # several, or
    output = {"exception": "<message>"}               # a failure

A single shape may come with what it is in, as plain data the script makes
without importing anything of PartCAD's (docs/design/cmf.md, section 7):

    output["cmf"] = {
        "convention": "ldraw",            # the terms the designations are in
        "faces": [<set or None>, ...],    # one per face, in TopExp::MapShapes order
        "solids": [<set or None>, ...],   # optional: one per solid, the same way
    }

where a set is '{"color": ..., "material": ..., "finish": ..., "rgba": [r, g,
b, a]}', every key optional: the source's own designations, which the core
converts by the convention's 'ids' (see 'partcad.cmf_conventions'), and the
colour to draw a face in when nothing claims its designation ('rgba', 0-255
and an alpha from 0 to 1).

Both '__file__' and the run name '__partcad_part__' are set on the script, so it
can gate its build logic (``if __name__ == "__partcad_part__":``) and remain
importable for its own unit tests.

A shape handed back as a *closed shell* is stated as the solid it already bounds
before it is serialized (see wrapper_common.solidify). A partType that meshes
triangles naturally builds a shell, and a shell is a skin: nothing downstream of
a boolean works on one. So a partType need not know to declare the solid itself,
and one that already does is unaffected.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: a script's 'output["cmf"]' is carried. 3: a
# NaN alpha in it is dropped rather than drawn opaque.
CACHE_VERSION = 3


def _rgba(value):
    """'(red, green, blue, alpha)' of a script's 'rgba' - channels 0 to 255, alpha 0 to 1 - or None if it is not one."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        red, green, blue = (max(0, min(255, int(round(float(channel))))) for channel in value[:3])
        alpha = float(value[3])
    except (TypeError, ValueError, OverflowError):
        return None
    # A NaN alpha is no alpha. It is asked before clamping, because the clamp
    # would make it 1: every comparison with NaN is false, so 'min(1.0, nan)'
    # keeps the 1.0. (A NaN channel is refused above, by 'round'.)
    if alpha != alpha:
        return None
    return red, green, blue, max(0.0, min(1.0, alpha))


def _section(stated, shape):
    """The CMF section 'stated' (a script's 'output["cmf"]') gives 'shape', or None.

    Read as forgivingly as a script can write it: an entry that is not a set
    says nothing, and a list as long as the shape has none of is a list for
    another shape, which is said rather than applied to the wrong faces.
    """
    if not isinstance(stated, dict) or shape is None:
        return None
    import cmf_section
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    origin = "raw:" + str(stated.get("convention") or "partcad")
    palette = cmf_section.Section()

    def indices(key, kind):
        entries = stated.get(key)
        if not isinstance(entries, list):
            return []
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, found)
        if len(entries) != found.Extent():
            sys.stderr.write(
                "The part type says what %d %s are in, and its shape has %d: what it says is dropped\n"
                % (len(entries), key, found.Extent())
            )
            return []
        result = []
        for entry in entries:
            if not isinstance(entry, dict):
                result.append(cmf_section.NONE)
                continue
            rgba = _rgba(entry.get("rgba"))
            if rgba is None and entry.get("rgba") is not None:
                sys.stderr.write("The part type's rgba %r is not four numbers: it is dropped\n" % (entry.get("rgba"),))
            cmf_set = cmf_section.CmfSet(
                color=entry.get("color"),
                material=entry.get("material"),
                finish=entry.get("finish"),
                origin=origin,
                rgba=rgba,
            )
            result.append(
                palette.index_of(cmf_set) if any(cmf_set.has(c) for c in cmf_section.COMPONENTS) else cmf_section.NONE
            )
        return result

    faces = indices("faces", TopAbs_FACE)
    solids = indices("solids", TopAbs_SOLID)
    section = cmf_section.Section(palette.sets, cmf_section.NONE, solids, faces).compacted()
    return None if section.is_empty() else section


def process(path, request):
    try:
        result = runpy.run_path(
            path,
            init_globals={"request": request},
            run_name="__partcad_part__",
        )
    except Exception as e:
        wrapper_common.handle_exception(e, path)
        return {"success": False, "exception": wrapper_common.exception_to_str(e), "shapes": []}

    output = result.get("output", {}) if isinstance(result, dict) else {}

    shapes = output.get("shapes")
    if shapes is None:
        shape = output.get("shape")
        shapes = [shape] if shape is not None else []

    exception = output.get("exception")
    if exception:
        wrapper_common.handle_exception(Exception(str(exception)), path)
        return {"success": False, "exception": str(exception), "shapes": shapes}

    # A partType that meshes triangles - which is what the ones in the public
    # index do - naturally builds a shell, and a shell is a skin rather than a
    # body: every boolean against one comes back with no solid in it. A closed
    # one is stated as the solid it already bounds, here rather than in each
    # partType, so that a package-supplied script gets it right by default.
    # See wrapper_common.solidify.
    stated = output.get("cmf") if len(shapes) == 1 else None
    section = _section(stated, shapes[0]) if stated is not None else None
    shapes = [wrapper_common.solidify(shape) for shape in shapes]

    # And a part is one shape, validated and moved: the several a script may
    # hand back are compounded here, and the compound finished, while all of it
    # is still live - rather than each travelling to the core only to be sent
    # into a sandbox of its own to be compounded (see
    # wrapper_common.finished_shapes). One shape with what it is in is finished
    # with it: the section is the shape's by index, which solidifying a shell
    # keeps (see wrapper_common.carried_cmf).
    if section is not None:
        shapes = [wrapper_common.finished(shapes[0], cmf=section)]
    else:
        shapes = wrapper_common.finished_shapes(shapes)

    return {"success": True, "exception": None, "shapes": shapes}


path, request = wrapper_common.handle_input()
result = process(path, request)
wrapper_common.handle_output(result)
