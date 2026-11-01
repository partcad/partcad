#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to read the outline of a sketch as the walls that follow it (see
# 'partcad.scene_factory_walls'). The sketch arrives as a BREP envelope, and what
# goes back is plain data: one entry per edge of the outline, in the order a
# walk around it meets them, saying where it starts, which way it sets off, how
# long it is and how it bends - which is everything a 'wall' part needs to be
# placed along it.
#
# The walk goes clockwise, seen from above, whichever way the sketch was drawn.
# A wall is seen from its right (see 'wrapper_wall.py'), and the right of a
# clockwise walk is the inside of what it walks around: so every wall of the
# room looks into the room, and from outside the room every wall is looked
# through.
#
# Only an outline that is one closed loop of straight lines and arcs of circles,
# drawn on the XY plane, is read. Anything else is refused, in words, rather than
# approximated: a second loop is a second room or a column nobody said how to
# draw, a spline is a wall nobody can build out of straight and arc walls, and a
# guess at either is a room that is not the one that was drawn.

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

# How far, in millimetres, the outline may stray from the XY plane, and how
# close two ends have to be to join: a thousandth of a millimetre, the
# tolerance a wall's openings are held to (see 'wrapper_wall.TOLERANCE').
TOLERANCE = 1e-3

# How many points each edge is sampled at to tell which way round the loop
# goes. The sign of an area, not the area: a handful is plenty for any outline
# that is not self-intersecting, and one that is has no inside to look into.
SAMPLES_PER_EDGE = 16


class OutlineError(Exception):
    """A sketch whose outline is not one walls can follow, in words for whoever drew it."""


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


def the_loop(sketch, where="the sketch"):
    """The one closed wire 'sketch' is the outline of, or OutlineError saying why there is not one.

    A face with no holes is its outer wire. A sketch of wires is its one wire,
    which has to close. A sketch of loose edges - a DXF of lines nobody joined
    into a polyline - is joined end to end first, and has to come out as one
    closed wire too.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.TopoDS import TopoDS

    faces = _explore(sketch, "face")
    if faces:
        if len(faces) > 1:
            raise OutlineError(
                "%s has %d faces; walls follow a single enclosed outline, one face with no holes in it"
                % (where, len(faces))
            )
        wires = _explore(faces[0], "wire")
        if len(wires) > 1:
            holes = len(wires) - 1
            raise OutlineError(
                "%s has %s in it; walls follow a single enclosed outline, one face with no holes in it"
                % (where, "a hole" if holes == 1 else "%d holes" % holes)
            )
        return BRepTools.OuterWire_s(faces[0])

    wires = _explore(sketch, "wire")
    if not wires:
        edges = _explore(sketch, "edge")
        if not edges:
            raise OutlineError("%s draws nothing" % where)
        sequence = TopTools_HSequenceOfShape()
        for edge in edges:
            sequence.Append(edge)
        joined = TopTools_HSequenceOfShape()
        ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(sequence, TOLERANCE, False, joined)
        wires = [TopoDS.Wire_s(joined.Value(index)) for index in range(1, joined.Length() + 1)]
    if len(wires) > 1:
        raise OutlineError("%s has %d separate outlines; walls follow a single enclosed one" % (where, len(wires)))
    wire = wires[0]
    if not BRep_Tool.IsClosed_s(wire):
        raise OutlineError("%s is an open outline; walls follow a single enclosed one, which closes" % where)
    return wire


def _bounds(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return None if box.IsVoid() else box.Get()


def _edge_ends(edge):
    """'(curve, start, end)' of 'edge' as a walk along it goes: its own orientation taken into account."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopAbs import TopAbs_REVERSED

    curve = BRepAdaptor_Curve(edge)
    first, last = curve.FirstParameter(), curve.LastParameter()
    if edge.Orientation() == TopAbs_REVERSED:
        return curve, last, first
    return curve, first, last


def _samples(edges):
    """Points along the walk 'edges' make, in order, for the sign of the area they enclose."""
    points = []
    for edge in edges:
        curve, start, end = _edge_ends(edge)
        for step in range(SAMPLES_PER_EDGE):
            point = curve.Value(start + (end - start) * step / SAMPLES_PER_EDGE)
            points.append((point.X(), point.Y()))
    return points


def signed_area(points):
    """The area 'points' enclose, positive where they go round anticlockwise (the shoelace formula)."""
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def segment(edge, reverse, index, where="the sketch"):
    """One edge of the walk, as the wall that follows it: a dict of plain numbers.

    'start' is where the wall starts, 'heading' the direction it sets off in,
    in degrees anticlockwise from +X, 'length' how long it is along its base,
    and 'radius' 0 for a straight line or the radius of an arc, positive where
    the arc bends to the right of the walk - towards the side the wall is seen
    from, which on a clockwise walk is a curve that bulges out of the room - and
    negative where it bends to the left, into the room. 'end' is where it
    finishes, for whoever checks that the walls meet.
    """
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    from OCP.gp import gp_Pnt, gp_Vec

    curve, start, end = _edge_ends(edge)
    if reverse:
        start, end = end, start
    kind = curve.GetType()
    if kind not in (GeomAbs_Line, GeomAbs_Circle):
        names = {
            0: "straight line",
            1: "circle",
            2: "ellipse",
            3: "hyperbola",
            4: "parabola",
            5: "Bezier curve",
            6: "B-spline",
            7: "offset curve",
        }
        raise OutlineError(
            "edge %d of %s is a %s; a wall follows a straight line or an arc of a circle, and so do the edges of "
            "an outline walls are built along" % (index, where, names.get(int(kind), "curve of another kind"))
        )
    length = GCPnts_AbscissaPoint.Length_s(curve)
    origin = gp_Pnt()
    tangent = gp_Vec()
    curve.D1(start, origin, tangent)
    if end < start:
        tangent.Reverse()
    finish = curve.Value(end)
    radius = 0.0
    if kind == GeomAbs_Circle:
        circle = curve.Circle()
        centre = circle.Location()
        towards = gp_Vec(centre.X() - origin.X(), centre.Y() - origin.Y(), 0.0)
        # The centre on the right of the way the walk goes is a bend to the
        # right, towards the side the wall is seen from.
        right = tangent.X() * towards.Y() - tangent.Y() * towards.X() < 0.0
        radius = circle.Radius() if right else -circle.Radius()
    return {
        "kind": "arc" if radius else "line",
        "start": [origin.X(), origin.Y()],
        "end": [finish.X(), finish.Y()],
        "heading": math.degrees(math.atan2(tangent.Y(), tangent.X())),
        "length": length,
        "radius": radius,
    }


def outline(sketch, where="the sketch"):
    """The walls that follow the outline of 'sketch', clockwise from its first edge."""
    from OCP.BRepTools import BRepTools_WireExplorer

    wire = the_loop(sketch, where)
    box = _bounds(wire)
    if box is None:
        raise OutlineError("%s draws nothing" % where)
    if box[2] < -TOLERANCE or box[5] > TOLERANCE:
        raise OutlineError(
            "%s is not drawn on the XY plane (it spans Z from %.6g to %.6g mm); walls stand on it, so it is drawn "
            "as a plan is, from above" % (where, box[2], box[5])
        )

    edges = []
    explorer = BRepTools_WireExplorer(wire)
    while explorer.More():
        edges.append(explorer.Current())
        explorer.Next()
    if not edges:
        raise OutlineError("%s draws nothing" % where)

    area = signed_area(_samples(edges))
    if abs(area) <= TOLERANCE:
        raise OutlineError("%s encloses no area, so it has no inside for walls to look into" % where)
    # Walked the other way round when it was drawn anticlockwise: the last
    # edge first, and each one from its end to its start.
    reverse = area > 0.0
    if reverse:
        edges = list(reversed(edges))
    return [segment(edge, reverse, index + 1, where) for index, edge in enumerate(edges)]


def process(request):
    return outline(request["sketch"], "the sketch '%s'" % request.get("sketchName", ""))


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        segments = process(request)
    except OutlineError as e:
        # The drawing's, not this script's: said as it is, with no traceback.
        model = {"success": False, "exception": str(e), "segments": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "segments": None}
    else:
        model = {"success": True, "exception": None, "segments": segments}
    wrapper_common.handle_output(model)
