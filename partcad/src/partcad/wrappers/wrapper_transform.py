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


def _relocate(shape, offset):
    """Relocate 'shape' by the packed [translation, axis, angle] offset.

    Mirrors the build123d relocate() the core used to run in-process, so the
    accepted 'offset' form is exactly what 'build123d.Location(*offset)' takes.
    """
    import build123d as b3d

    solid = b3d.Solid.make_box(1, 1, 1)
    solid.wrapped = shape
    solid.relocate(b3d.Location(*offset))
    return solid.wrapped


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
        return _relocate(request["shape"], request["offset"])
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
