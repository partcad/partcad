#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to read a sketch of a plan as the walls that stand on it (see
# 'partcad.scene_factory_walls'). The sketch arrives as a BREP envelope, and what
# goes back is plain data: the walls of each thing the plan draws, one entry per
# edge, in the order a walk along it meets them, saying where it starts, which
# way it sets off, how long it is and how it bends - which is everything a 'wall'
# part needs to be placed along it.
#
# A plan draws three kinds of thing, told apart by their geometry alone:
#
#   * an **outline** - a face's outer boundary, or a closed loop inside no other -
#     is a room. It is walked clockwise, seen from above, whichever way it was
#     drawn. A wall is seen from its right (see 'wrapper_wall.py'), and the right
#     of a clockwise walk is the inside: every wall of the room looks into it,
#     and from outside the room every wall is looked through.
#   * a **closed space** - a hole in a face, or a closed loop inside an outline -
#     is a closet, a shaft, a column: a space walled in rather than looked into.
#     It is walked anticlockwise, so that every wall of it looks out, into the
#     room around it, and its thickness goes into the space.
#   * a **standalone wall** - a line, or lines joined end to end, that close
#     nothing - is a wall standing in a room, walked the way it was drawn: seen
#     from its right, its thickness on its left.
#
# Only straight lines and arcs of circles, drawn on the XY plane, are read.
# Anything else is refused, in words, rather than approximated - a spline is a
# wall nobody can build out of straight and arc walls - and so is a plan whose
# walls would stand in each other: two outlines that touch (the wall two rooms
# share is drawn once, as a line inside one outline), a closed space touching
# the room around it, a closed loop inside a closed space.

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
CACHE_VERSION = 2

# What each thing a plan draws is, as the walls placed along it are named and
# built (see 'partcad.scene_factory_walls').
OUTLINE = "outline"
ENCLOSURE = "enclosure"
PARTITION = "partition"

# How far, in millimetres, the outline may stray from the XY plane, and how
# close two ends have to be to join: a thousandth of a millimetre, the
# tolerance a wall's openings are held to (see 'wrapper_wall.TOLERANCE').
TOLERANCE = 1e-3

# How many points each edge is sampled at to tell which way round the loop
# goes. The sign of an area, not the area: a handful is plenty for any outline
# that is not self-intersecting, and one that is has no inside to look into.
SAMPLES_PER_EDGE = 16


class OutlineError(Exception):
    """A sketch whose plan is not one walls can stand on, in words for whoever drew it."""


def _explore(shape, kind, avoid=None):
    """Every sub-shape of 'shape' of 'kind' ("face", "wire" or "edge"), as that type - none inside an 'avoid'."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHAPE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    types = {"face": TopAbs_FACE, "wire": TopAbs_WIRE, "edge": TopAbs_EDGE}
    cast = {"face": TopoDS.Face_s, "wire": TopoDS.Wire_s, "edge": TopoDS.Edge_s}[kind]
    found = []
    explorer = TopExp_Explorer(shape, types[kind], types[avoid] if avoid else TopAbs_SHAPE)
    while explorer.More():
        found.append(cast(explorer.Current()))
        explorer.Next()
    return found


def _wires_of(sketch):
    """'(faces, wires)': the faces 'sketch' draws, and the wires it draws besides them.

    The wires are those no face is bounded by, and the edges no wire holds -
    a DXF of lines nobody joined into a polyline - joined end to end.
    """
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.TopoDS import TopoDS

    faces = _explore(sketch, "face")
    wires = _explore(sketch, "wire", avoid="face")
    edges = _explore(sketch, "edge", avoid="wire")
    if edges:
        sequence = TopTools_HSequenceOfShape()
        for edge in edges:
            sequence.Append(edge)
        joined = TopTools_HSequenceOfShape()
        ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(sequence, TOLERANCE, False, joined)
        wires += [TopoDS.Wire_s(joined.Value(index)) for index in range(1, joined.Length() + 1)]
    return faces, wires


def _edges(wire):
    """The edges of 'wire', in the order a walk along it meets them."""
    from OCP.BRepTools import BRepTools_WireExplorer

    edges = []
    explorer = BRepTools_WireExplorer(wire)
    while explorer.More():
        edges.append(explorer.Current())
        explorer.Next()
    return edges


def _inside(point, polygon):
    """Whether 'point' is inside the closed 'polygon' (points, in order): an even-odd crossing count."""
    x, y = point
    inside = False
    for index, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(index + 1) % len(polygon)]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _touch(first, second):
    """Whether two wires come within the tolerance of each other anywhere."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    distance = BRepExtrema_DistShapeShape(first, second)
    return distance.IsDone() and distance.Value() <= TOLERANCE


def parts_of(sketch, where="the sketch"):
    """'[(kind, wire)]': the outlines, the closed spaces and the standalone walls 'sketch' is the plan of.

    A face is an outline, and each of its holes a closed space. A closed wire is
    an outline, or a closed space where it is inside an outline; an open one is a
    standalone wall. In that order: the outlines first, as the faces and then the
    wires come, then the closed spaces, then the standalone walls.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools

    faces, wires = _wires_of(sketch)
    if not faces and not wires:
        raise OutlineError("%s draws nothing" % where)

    # Every closed loop, with what it is where that is already said: '(wire, kind, face it bounds)'.
    rings = []
    for index, face in enumerate(faces):
        outer = BRepTools.OuterWire_s(face)
        rings.append((outer, OUTLINE, index))
        rings += [(wire, ENCLOSURE, index) for wire in _explore(face, "wire") if not wire.IsSame(outer)]
    loose = len(rings)
    rings += [(wire, None, None) for wire in wires if BRep_Tool.IsClosed_s(wire)]
    standalone = [wire for wire in wires if not BRep_Tool.IsClosed_s(wire)]

    # Nothing of one stands in another: a room's outline and its own holes apart, no two loops meet.
    for i, (first, _kind, face) in enumerate(rings):
        for second, _other, other_face in rings[i + 1 :]:
            if face is not None and face == other_face:
                continue
            if _touch(first, second):
                raise OutlineError(
                    "%s draws two loops that touch: the walls along them would stand in each other. Two rooms "
                    "side by side share one wall - draw them as one outline with a line between them - and a "
                    "closed space touching its room is a notch in the room's outline" % where
                )

    # What a loose loop is follows from how many others it is inside: none, an
    # outline; one, a closed space in it; more, something inside a closed space.
    polygons = [_polygon(wire) for wire, _kind, _face in rings]
    kinds = []
    for index, (wire, kind, face) in enumerate(rings):
        point = polygons[index][0]
        around = [j for j in range(len(rings)) if j != index and _inside(point, polygons[j])]
        if index < loose:
            if kind == OUTLINE and around:
                raise OutlineError("%s draws a room inside another loop; rooms stand side by side" % where)
            kinds.append(kind)
        elif len(around) > 1:
            raise OutlineError(
                "%s draws a closed loop inside a closed space; a closed space is walled in, and has nothing in it"
                % where
            )
        else:
            kinds.append(ENCLOSURE if around else OUTLINE)

    found = [(OUTLINE, wire) for (wire, _k, _f), kind in zip(rings, kinds) if kind == OUTLINE]
    found += [(ENCLOSURE, wire) for (wire, _k, _f), kind in zip(rings, kinds) if kind == ENCLOSURE]
    found += [(PARTITION, wire) for wire in standalone]
    return found


def _polygon(wire):
    """Points along the walk 'wire' makes, in order."""
    return _samples(_edges(wire))


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


def walk(kind, wire, where="the sketch"):
    """The walls along 'wire', in order: around an outline clockwise, around a closed space anticlockwise.

    A standalone wall is walked the way it was drawn, from its first edge.
    """
    box = _bounds(wire)
    if box is None:
        raise OutlineError("%s draws nothing" % where)
    if box[2] < -TOLERANCE or box[5] > TOLERANCE:
        raise OutlineError(
            "%s is not drawn on the XY plane (it spans Z from %.6g to %.6g mm); walls stand on it, so it is drawn "
            "as a plan is, from above" % (where, box[2], box[5])
        )
    edges = _edges(wire)
    if not edges:
        raise OutlineError("%s draws nothing" % where)

    reverse = False
    if kind != PARTITION:
        area = signed_area(_samples(edges))
        if abs(area) <= TOLERANCE:
            raise OutlineError("%s encloses no area, so it has no inside for walls to look into" % where)
        # Walked the other way round when it was drawn the other way: the
        # last edge first, and each one from its end to its start.
        reverse = area > 0.0 if kind == OUTLINE else area < 0.0
    if reverse:
        edges = list(reversed(edges))
    return [segment(edge, reverse, index + 1, where) for index, edge in enumerate(edges)]


def plan(sketch, where="the sketch"):
    """'[{"kind", "segments"}]': the walls of every outline, closed space and standalone wall 'sketch' draws."""
    parts = parts_of(sketch, where)
    # A plan of one outline names its edges as it always has: 'edge 3 of the sketch'.
    if len(parts) == 1 and parts[0][0] == OUTLINE:
        return [{"kind": OUTLINE, "segments": walk(OUTLINE, parts[0][1], where)}]
    found = []
    numbers = {}
    for kind, wire in parts:
        numbers[kind] = numbers.get(kind, 0) + 1
        what = {OUTLINE: "outline", ENCLOSURE: "closed space", PARTITION: "standalone wall"}[kind]
        found.append({"kind": kind, "segments": walk(kind, wire, "%s %d of %s" % (what, numbers[kind], where))})
    return found


def outline(sketch, where="the sketch"):
    """The walls that follow the one outline 'sketch' is, clockwise from its first edge.

    For a plan that is a room and nothing else; 'plan' reads any other.
    """
    found = plan(sketch, where)
    if len(found) != 1 or found[0]["kind"] != OUTLINE:
        raise OutlineError("%s is not one outline and nothing else" % where)
    return found[0]["segments"]


def process(request):
    return plan(request["sketch"], "the sketch '%s'" % request.get("sketchName", ""))


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        walls = process(request)
    except OutlineError as e:
        # The drawing's, not this script's: said as it is, with no traceback.
        model = {"success": False, "exception": str(e), "walls": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "walls": None}
    else:
        model = {"success": True, "exception": None, "walls": walls}
    wrapper_common.handle_output(model)
