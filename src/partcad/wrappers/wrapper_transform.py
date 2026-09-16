#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to apply geometry transformations - "offset", "scale" and "compound" - so the
# core process never has to touch a live OCP object to perform them. The operand
# shape(s) arrive in the request as BREP (see ocp_serialize) and the result goes
# back the same way.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize. Without this the standard
# library's pyexpat binds to VTK's older expat and any later xml.dom use
# (build123d imports IPython, which does exactly that) dies with an
# undefined-symbol ImportError.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common


def _offset(shape, offset):
    """Move 'shape' by the packed [translation, axis, angle] offset.

    The accepted 'offset' form is exactly what 'build123d.Location(*offset)'
    takes, which is what the documented ``offset:`` field of an object is
    written in.

    'moved()', not 'relocate()'. build123d's relocate() keeps the geometry
    exactly where it is and only re-labels the frame it is measured in, so an
    object with an ``offset:`` came back at the coordinates it started at: the
    field had no effect on anything that reads the geometry - an export, a
    render, a route, a part placed in an assembly. It is what the core used to
    run in-process, and porting it into this wrapper carried the mistake along
    with it.

        Solid.make_box(10, 20, 30).relocate(Location([[100, 0, 0], ...]))
            -> x = [0 .. 10]     # unmoved
        Solid.make_box(10, 20, 30).moved(Location([[100, 0, 0], ...]))
            -> x = [100 .. 110]  # what 'offset:' means

    build123d deprecated relocate() for this reason; it warned on every offset
    PartCAD applied.
    """
    import build123d as b3d

    solid = b3d.Solid.make_box(1, 1, 1)
    solid.wrapped = shape
    return solid.moved(b3d.Location(*offset)).wrapped


def _scale(shape, factor):
    """Scale 'shape' by 'factor', mirroring the build123d scale() the core used."""
    import build123d as b3d

    solid = b3d.Solid.make_box(1, 1, 1)
    solid.wrapped = shape
    solid = solid.scale(factor)
    return solid.wrapped


def _compound(shapes):
    """Combine 'shapes' into a single TopoDS_Compound.

    Non-shape entries (a None a script produced, an already-dropped OCCT
    Location/Axis) are skipped rather than fatal, matching the tolerance of the
    in-process loops this replaces.
    """
    import OCP.TopoDS  # noqa: F401

    kept = [shape for shape in shapes if isinstance(shape, OCP.TopoDS.TopoDS_Shape) and not shape.IsNull()]
    return ocp_serialize.compound_of(kept)


def process(request):
    operation = request.get("operation")
    if operation == "offset":
        return _offset(request["shape"], request["offset"])
    if operation == "scale":
        return _scale(request["shape"], request["scale"])
    if operation == "compound":
        return _compound(request.get("shapes", []))
    raise ValueError("Unknown transform operation: %r" % (operation,))


if __name__ == "__main__":
    # argv[1] carries the operation name for readability in process listings and
    # logs; the authoritative copy travels in the request.
    _, request = wrapper_common.handle_input()
    try:
        shape = process(request)
        model = {"success": True, "exception": None, "shape": shape}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    wrapper_common.handle_output(model)
