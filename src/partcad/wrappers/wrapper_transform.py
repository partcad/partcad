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
#
# That makes this the fallback, for a shape that is already a BREP when it is
# moved: a reference to another part, or a part whose wrapper could not do it.
# A part's own 'offset' and 'scale' are applied by the wrapper that builds it,
# while the shape is still live ('wrapper_common.finished'), with the very same
# 'relocate()' and 'scale()' below - one definition of what moving a part
# means, and one CACHE_VERSION that says when it changed, whichever process
# runs it.

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

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1


def relocate(shape, offset):
    """Move 'shape' by the packed [translation, axis, angle] offset.

    The transform is applied to the geometry, so what comes back sits at the
    new place with an identity location and carries the offset nowhere else.

    It used to call build123d's 'relocate()', which does the opposite of what
    the name suggests to anyone writing an 'offset:': it gives the shape a new
    local frame and bakes the inverse into the geometry, so the shape does not
    move at all. A 1mm box asked to move 10mm in X stayed at x[0, 1].

    That left the offset expressed only as a location, and the consumers did
    not agree about it. Exporting and rendering dropped it and so saw the
    compensating inverse - a part rotated by the opposite of what was asked -
    while 'partcad.test.interference' honoured it and saw a part that had not
    moved. Two errors that cancelled in a picture and did not in a check:
    'feature_enrich:desk-enrich' rendered as a desk while the check was shown
    four legs lying across each other, and reported 4.8 million mm^3 of
    overlap that is not there.

    Baking it into the geometry is what stops any of that being possible: an
    envelope is BREP bytes, and nothing downstream has to remember a frame.

    What the offset means is build123d's 'Location(*offset)'. The packed form,
    which is the one PartCAD documents, is built here the way that constructor
    builds it, call for call, so that it does not cost importing build123d -
    seconds of IPython and friends, in a wrapper that reads a STEP file and
    would otherwise never load it; any other form is handed to build123d
    itself. 'test_part_finish' holds the two to the same bytes.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    transformation = _packed_transformation(offset)
    if transformation is None:
        import build123d as b3d

        transformation = b3d.Location(*offset).wrapped.Transformation()
    transform = BRepBuilderAPI_Transform(shape, transformation, True)
    return transform.Shape()


def scale(shape, factor):
    """Scale 'shape' by 'factor' about its own position, as build123d's 'Shape.scale()' does.

    A plain number is scaled here, by the very transformation that method
    builds for one - about the translation of the shape's own location - and
    without importing build123d for it (see 'relocate'); anything else goes to
    build123d, which knows what else it accepts.
    """
    if _is_number(factor):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Pnt, gp_Trsf

        transformation = gp_Trsf()
        transformation.SetScale(gp_Pnt(shape.Location().Transformation().TranslationPart()), float(factor))
        return ocp_serialize.downcast(BRepBuilderAPI_Transform(shape, transformation, True).Shape())

    import build123d as b3d

    solid = b3d.Solid.make_box(1, 1, 1)
    solid.wrapped = shape
    solid = solid.scale(factor)
    return solid.wrapped


def _is_number(value):
    # 'bool' is an 'int'; build123d takes one as a number too, and is left to.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _packed_transformation(offset):
    """What build123d's 'Location(*offset)' makes of '[[x, y, z], [ax, ay, az], angle]', or None for any other form.

    That constructor, given a position, a direction and an angle in degrees,
    rotates about the direction through the origin and then sets the
    translation: the same three OCCT calls, with the same doubles, here.
    """
    if not isinstance(offset, (list, tuple)) or len(offset) != 3:
        return None
    translation, axis, angle = offset
    for vector in (translation, axis):
        if not isinstance(vector, (list, tuple)) or len(vector) != 3 or not all(map(_is_number, vector)):
            return None
    if not _is_number(angle):
        return None

    import math

    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    transformation = gp_Trsf()
    transformation.SetRotation(
        gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(gp_Vec(*[float(value) for value in axis]).XYZ())), math.radians(angle)
    )
    transformation.SetTranslationPart(gp_Vec(*[float(value) for value in translation]))
    return TopLoc_Location(transformation).Transformation()


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
        return relocate(request["shape"], request["offset"])
    if operation == "scale":
        return scale(request["shape"], request["scale"])
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
