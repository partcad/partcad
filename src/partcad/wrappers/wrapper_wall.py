#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to build a wall: the surface a room is drawn with, rather than a body anybody
# makes (see 'partcad.part_factory_wall'). The openings sketch, when there is
# one, arrives as a BREP envelope; the dimensions arrive as plain data; and the
# wall goes back as a BREP envelope.
#
# A wall is one-sided. It is a face - or, where an opening divides it, several -
# whose normal points to the side it is seen from, and it is drawn from that
# side only, so that from the other side it is not there at all: the wall
# between the viewer and a room is looked through, and the far walls of the room
# are seen. That is the whole of what it is for, and it is why the orientation
# of every face is settled here, explicitly, rather than left to whatever order
# OCCT happened to build the edges in.
#
# The frame, which 'scene_factory_walls' places walls by and the openings sketch
# is drawn in:
#
#   * The base of the wall starts at the origin and sets off along +X, and the
#     wall rises along +Z for 'height'.
#   * It is seen from its front, which is -Y where it starts: from where
#     'pc render --view front' looks, so that a wall drawn from the front is the
#     wall as its openings were drawn, door on the left where it was drawn on the
#     left. Walk along a wall from its start and the side it is seen from is the
#     side on your right, which is the inside of an outline traced clockwise.
#   * A straight wall runs along the X axis for 'length'. An arc wall is 'length'
#     long measured along the arc, and bends towards the side it is seen from -
#     to its right, towards -Y - for a positive 'radius' (the inside of a round
#     room), and away from it for a negative one (the outside of a column).
#   * The openings are drawn as if the wall were unrolled flat in front of the
#     viewer: X along its base from 0 to 'length', Y up from 0 to 'height'. On an
#     arc wall X is the distance along the arc, so a door 900 mm wide is 900 mm
#     wide on the wall whatever the wall's radius.

import math
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# How far, in millimetres, an opening may stray past the edge of the wall before
# it counts as reaching beyond it: a thousandth of a millimetre, the tolerance
# 'partcad.test.degenerate' measures flatness to. Enough for a drawing whose
# door was drawn to the floor through a chain of floating-point arithmetic, and
# nothing anybody could see.
TOLERANCE = 1e-3


class WallError(Exception):
    """A wall that cannot be built as declared, in words for whoever declared it."""


def _explore(shape, kind):
    """Every sub-shape of 'shape' of 'kind' ("face", "wire" or "edge"), as that type."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    cast = {"face": TopoDS.Face_s, "wire": TopoDS.Wire_s, "edge": TopoDS.Edge_s}[kind]
    found = []
    explorer = TopExp_Explorer(shape, {"face": TopAbs_FACE, "wire": TopAbs_WIRE, "edge": TopAbs_EDGE}[kind])
    while explorer.More():
        found.append(cast(explorer.Current()))
        explorer.Next()
    return found


def _bounds(shape):
    """'(x_min, y_min, z_min, x_max, y_max, z_max)' of 'shape', measured on its exact geometry."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if box.IsVoid():
        return None
    return box.Get()


def opening_faces(sketch, where="the openings sketch"):
    """The openings 'sketch' draws, as faces in the XY plane.

    A sketch is made of faces as often as not - a basic sketch, a DXF of closed
    polylines, a script's 'Rectangle' - and those are the openings. A sketch of
    closed wires and no faces says the same thing, and each wire is turned into
    the face it bounds. An open wire bounds nothing and cannot be an opening, and
    is refused rather than ignored: a door drawn with three sides is a door
    somebody meant, and a wall with no hole where it was meant to be is a wall
    nobody would notice was wrong.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    faces = _explore(sketch, "face")
    if faces:
        return faces
    wires = _explore(sketch, "wire")
    if not wires:
        if _explore(sketch, "edge"):
            raise WallError(
                "%s is made of loose edges; an opening is a closed outline, a face or a closed wire" % where
            )
        raise WallError("%s draws nothing" % where)
    for wire in wires:
        if not BRep_Tool.IsClosed_s(wire):
            raise WallError("%s has an open wire; an opening is a closed outline" % where)
        maker = BRepBuilderAPI_MakeFace(wire, True)
        if not maker.IsDone():
            raise WallError("%s has a wire that does not lie in a plane, or does not bound a face" % where)
        faces.append(maker.Face())
    return faces


def check_openings(faces, length, height, where="the openings sketch"):
    """Refuse openings that are not on the wall: off its plane, or past any of its four edges.

    The sketch is drawn on the XY plane, X along the wall from 0 to 'length' and
    Y up from 0 to 'height', and this is where that is held to. An opening that
    reaches past an edge is not quietly clipped to it, because the wall it would
    then build is not the wall that was drawn: a window drawn 200 mm too wide is
    a mistake in the drawing, or in the wall's length, and either one is worth
    hearing about. An opening that *meets* an edge is perfectly good - a door
    stands on the floor - so the edges themselves are inside, to within
    'TOLERANCE'.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for face in faces:
        builder.Add(compound, face)
    box = _bounds(compound)
    if box is None:
        raise WallError("%s draws nothing" % where)
    x_min, y_min, z_min, x_max, y_max, z_max = box
    if z_min < -TOLERANCE or z_max > TOLERANCE:
        raise WallError(
            "%s is not drawn on the XY plane (it spans Z from %.6g to %.6g mm): an opening is drawn as if the "
            "wall were unrolled flat, X along its base and Y up from it" % (where, z_min, z_max)
        )
    if x_min < -TOLERANCE or y_min < -TOLERANCE or x_max > length + TOLERANCE or y_max > height + TOLERANCE:
        raise WallError(
            "%s reaches beyond the wall: it spans X from %.6g to %.6g and Y from %.6g to %.6g mm, and the wall "
            "is %.6g mm long and %.6g mm high - X from 0 to the length, Y from 0 to the height"
            % (where, x_min, x_max, y_min, y_max, length, height)
        )


def developed(length, height, openings=None):
    """The wall unrolled flat on the XY plane, with its openings cut out: a list of faces.

    Built on a plane whose own (u, v) are (x, y), so that every edge of the
    result has a curve in the plane's parameters that *is* its drawing - which
    is what an arc wall is wrapped from (see 'wrapped').

    More than one face where the openings divide the wall: a door that is as
    tall as the wall leaves the wall either side of it, and nothing joins them.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    plane = gp_Pln(gp_Ax3(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0), gp_Dir(1.0, 0.0, 0.0)))
    face = BRepBuilderAPI_MakeFace(plane, 0.0, length, 0.0, height).Face()
    if not openings:
        return [face]

    tool = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(tool)
    for opening in openings:
        builder.Add(tool, opening)
    cut = BRepAlgoAPI_Cut(face, tool)
    if not cut.IsDone():
        raise WallError("the openings could not be cut out of the wall")
    faces = _explore(cut.Shape(), "face")
    if not faces:
        raise WallError("the openings leave nothing of the wall")
    return faces


def _scaled(curve, scale):
    """A 2D curve with its X scaled by 'scale', as a B-spline: an affine map is a map of its poles."""
    from OCP.Geom2dConvert import Geom2dConvert
    from OCP.gp import gp_Pnt2d

    spline = Geom2dConvert.CurveToBSplineCurve_s(curve)
    for index in range(1, spline.NbPoles() + 1):
        pole = spline.Pole(index)
        spline.SetPole(index, gp_Pnt2d(pole.X() * scale, pole.Y()))
    return spline


def wrapped(face, surface, radius):
    """'face', drawn on the XY plane, wrapped onto the cylinder 'surface' of 'radius' (positive).

    The cylinder's own parameters are an angle around its axis and a height
    along it, and the wall's drawing is a distance along the arc and a height:
    so every edge is carried across as the curve it is in the plane, with its X
    divided by the radius - an affine map, which a B-spline undergoes by moving
    its poles and nothing else - and laid on the cylinder as the curve of an edge
    in the cylinder's parameters. Lengths along the arc are kept, and so is the
    area: a door 900 mm wide is 900 mm wide on the wall.

    Only for a wall bending to its left, which keeps the drawing's sense: the
    cylinder's angle grows the way the wall goes. A wall bending to its right is
    this one mirrored (see 'build'), rather than a drawing mirrored on its way
    across - which turns every loop of it inside out, and an opening with it.
    Which way the face looks is settled by 'oriented'.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepLib import BRepLib
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.Geom2d import Geom2d_TrimmedCurve
    from OCP.ShapeFix import ShapeFix_Face
    from OCP.TopAbs import TopAbs_REVERSED

    outer = BRepTools.OuterWire_s(face)
    wires = [outer] + [wire for wire in _explore(face, "wire") if not wire.IsSame(outer)]
    carried = []
    for wire in wires:
        maker = BRepBuilderAPI_MakeWire()
        explorer = BRepTools_WireExplorer(wire, face)
        while explorer.More():
            edge = explorer.Current()
            first, last = BRep_Tool.Range_s(edge, face)
            drawn = BRep_Tool.CurveOnSurface_s(edge, face, first, last)
            curve = _scaled(Geom2d_TrimmedCurve(drawn, first, last), 1.0 / radius)
            made = BRepBuilderAPI_MakeEdge(curve, surface, curve.FirstParameter(), curve.LastParameter())
            if not made.IsDone():
                raise WallError("an opening could not be laid onto the curved wall")
            new = made.Edge()
            if edge.Orientation() == TopAbs_REVERSED:
                new.Reverse()
            maker.Add(new)
            explorer.Next()
        if not maker.IsDone():
            raise WallError("an opening could not be laid onto the curved wall")
        carried.append(maker.Wire())

    maker = BRepBuilderAPI_MakeFace(surface, carried[0], True)
    for wire in carried[1:]:
        maker.Add(wire)
    if not maker.IsDone():
        raise WallError("the curved wall could not be built around its openings")
    result = maker.Face()
    BRepLib.BuildCurves3d_s(result)
    fix = ShapeFix_Face(result)
    fix.Perform()
    return fix.Face()


def face_normal(face):
    """'(point, normal)' of 'face' at the middle of its parameters, with the face's orientation taken into account.

    The middle of a wall's parameters may well be in one of its openings - a
    window in the middle of a wall is what windows mostly are - and that does not
    matter here: the surface is there whether or not the face covers that part
    of it, and a plane or a cylinder looks the same way all over.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TopAbs import TopAbs_REVERSED

    u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face)
    surface = BRepAdaptor_Surface(face)
    point = gp_Pnt()
    du = gp_Vec()
    dv = gp_Vec()
    surface.D1((u_min + u_max) / 2.0, (v_min + v_max) / 2.0, point, du, dv)
    normal = du.Crossed(dv)
    if normal.Magnitude() == 0.0:
        return point, None
    normal.Normalize()
    if face.Orientation() == TopAbs_REVERSED:
        normal.Reverse()
    return point, normal


def oriented(face, radius):
    """'face', turned to look the way a wall looks: to its front, see the top of this file.

    A straight wall looks along -Y. An arc wall looks towards its axis when it
    bends towards its front (a positive radius: the inside of a round room) and
    away from it when it bends away (the outside of a column the room goes
    around), which in both cases is -Y where it starts.
    """
    from OCP.gp import gp_Vec

    point, normal = face_normal(face)
    if normal is None:
        return face
    if radius == 0.0:
        wanted = gp_Vec(0.0, -1.0, 0.0)
    else:
        # The axis is at (0, -radius): towards it for a positive radius, away
        # from it for a negative one.
        wanted = gp_Vec(-point.X(), -radius - point.Y(), 0.0) * (1.0 if radius > 0.0 else -1.0)
    if normal.Dot(wanted) < 0.0:
        from OCP.TopoDS import TopoDS

        return TopoDS.Face_s(face.Reversed())
    return face


def cylinder(radius):
    """The cylinder an arc wall bending to its left with 'radius' (positive) lies on, parametrized as it is drawn.

    Its axis stands at (0, radius), on the wall's left, and its angle is
    measured from the wall's start, anticlockwise, which makes the drawing's X
    divided by the radius the angle: at nought the wall is at the origin,
    heading along +X. Up is +Z, so the height is the cylinder's own.
    """
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt

    axis = gp_Ax3(gp_Pnt(0.0, radius, 0.0), gp_Dir(0.0, 0.0, 1.0), gp_Dir(0.0, -1.0, 0.0))
    return Geom_CylindricalSurface(axis, radius)


def build(length, height, radius=0.0, openings=None, where="the openings sketch"):
    """The wall these dimensions describe, with the openings 'openings' (a sketch's shape, or None) cut out of it."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf
    from OCP.TopoDS import TopoDS, TopoDS_Compound

    length = float(length)
    height = float(height)
    radius = float(radius or 0.0)
    if not length > 0.0:
        raise WallError("a wall is longer than nothing: 'length' is %s" % length)
    if not height > 0.0:
        raise WallError("a wall is taller than nothing: 'height' is %s" % height)
    if radius != 0.0:
        around = 2.0 * math.pi * abs(radius)
        if length > around + TOLERANCE:
            raise WallError(
                "an arc wall of radius %.6g mm goes once around at most, which is %.6g mm, and 'length' is %.6g mm"
                % (abs(radius), around, length)
            )
        # Once around is once around exactly. A length that is short of it by
        # less than anybody could measure - the circumference of a round room,
        # written down to a millionth of a millimetre on its way here - would
        # otherwise leave the two ends of the wall a fraction of a micron apart:
        # two edges in one place that are not one edge, which is a face no
        # boolean can cut cleanly, nor a drawing take the back half off.
        if length > around - TOLERANCE:
            length = around

    holes = None
    if openings is not None:
        holes = opening_faces(openings, where)
        check_openings(holes, length, height, where)

    if radius == 0.0:
        faces = developed(length, height, holes)
        # Stood up: the drawing's Y becomes the wall's Z, and its X stays where it is.
        turn = gp_Trsf()
        turn.SetRotation(gp_Ax1(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(1.0, 0.0, 0.0)), math.pi / 2.0)
        faces = [TopoDS.Face_s(BRepBuilderAPI_Transform(face, turn, True).Shape()) for face in faces]
    else:
        # Built bending to the left (towards +Y), and mirrored across the X axis
        # where it bends to the right - which a positive radius does, towards the
        # side the wall is seen from. The mirror keeps where the wall starts, the
        # way it sets off and how far along it every opening is, and changes
        # nothing else: which way it looks is settled below, for either.
        magnitude = abs(radius)
        surface = cylinder(magnitude)
        if not holes:
            # The plain arc, straight off the cylinder: no drawing to carry across.
            faces = [BRepBuilderAPI_MakeFace(surface, 0.0, length / magnitude, 0.0, height, 1e-7).Face()]
        else:
            faces = [wrapped(face, surface, magnitude) for face in developed(length, height, holes)]
        if radius > 0.0:
            mirror = gp_Trsf()
            mirror.SetMirror(gp_Ax2(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 1.0, 0.0)))
            faces = [TopoDS.Face_s(BRepBuilderAPI_Transform(face, mirror, True).Shape()) for face in faces]

    faces = [oriented(face, radius) for face in faces]
    if len(faces) == 1:
        return faces[0]
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for face in faces:
        builder.Add(compound, face)
    return compound


def process(request):
    return build(
        request["length"],
        request["height"],
        request.get("radius", 0.0),
        request.get("openings"),
        "the openings sketch '%s'" % request.get("openingsName", ""),
    )


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        shape = process(request)
    except WallError as e:
        # Somebody's declaration, not a fault in this script: said as it is,
        # without a traceback for the reader to wade through.
        model = {"success": False, "exception": str(e), "shape": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    else:
        # Moved here, while it is live (see wrapper_common.finished). A wall is
        # asked not to be validated - it is a surface on purpose, see
        # 'Shape.finish_request' - so the request it carries says so.
        model = {"success": True, "exception": None, "shape": wrapper_common.finished(shape)}
    wrapper_common.handle_output(model)
