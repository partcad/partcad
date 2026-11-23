#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to sweep a routed part's profile along its route (issue #975, design D6), so
# the core process never has to touch a live OCP object. The route arrives as
# the canonical JSON 'route_path.canonical_json' writes: the sampled centreline
# and the profile's X axis at each sample. The profile is a round section
# ('diameter', hollow with 'innerDiameter') or a sketch, which arrives as a BREP
# envelope drawn in its own XY plane. The swept solid goes back as a BREP
# envelope.
#
# The profile is placed in the first end's frame and swept with an auxiliary
# spine through each sample moved along its frame's X, so that the profile turns
# with the frames the core computed (roll included) rather than with OCCT's own.
# What comes out has to be exactly one valid solid of positive volume (design D9,
# after the sweep): anything else means the path could not carry the profile,
# and is refused with the defect named rather than handed back with a warning.

import json
import math
import os

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# How far the auxiliary spine runs beside the path, in millimetres. Small next to
# any bend the route may have (D9 refuses bends tighter than the profile), and
# large next to the modeling tolerance.
AUX_OFFSET = 1.0

# The most samples the spine is interpolated through. The route's samples are
# dense for measuring; the B-spline needs far fewer, and every knot is kept.
MAX_SPINE_POINTS = 400


class RouteBuildError(Exception):
    """The path could not carry the profile (D9, after the sweep)."""


def _spine_indices(count, knots):
    step = max(1, math.ceil(count / MAX_SPINE_POINTS))
    keep = set(range(0, count, step)) | set(knots) | {count - 1}
    return sorted(index for index in keep if 0 <= index < count)


def _bspline_wire(points, start_tangent=None, end_tangent=None):
    """A wire along a B-spline through 'points', exactly: interpolated, not
    approximated, and with the tangents at its ends pinned where given, so that
    the swept solid's end faces are square to the ends' axes."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.TColgp import TColgp_HArray1OfPnt

    array = TColgp_HArray1OfPnt(1, len(points))
    for i, (x, y, z) in enumerate(points, 1):
        array.SetValue(i, gp_Pnt(x, y, z))
    interpolate = GeomAPI_Interpolate(array, False, 1e-9)
    if start_tangent is not None and end_tangent is not None:
        interpolate.Load(gp_Vec(*start_tangent), gp_Vec(*end_tangent), True)
    interpolate.Perform()
    if not interpolate.IsDone():
        raise RouteBuildError("the path could not be interpolated")
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(interpolate.Curve()).Edge()).Wire()


def _first_frame(path):
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt

    origin, z, x = path["points"][0], path["z"][0], path["x"][0]
    return gp_Ax3(gp_Pnt(*origin), gp_Dir(*z), gp_Dir(*x))


def _profiles(request, frame):
    """The profile as (outer wire, [inner wires]) pairs, placed in the first frame."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Trsf
    from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if request.get("diameter") is not None:
        axes = gp_Ax2(frame.Location(), frame.Direction(), frame.XDirection())

        def circle(diameter):
            edge = BRepBuilderAPI_MakeEdge(gp_Circ(axes, diameter / 2.0)).Edge()
            return BRepBuilderAPI_MakeWire(edge).Wire()

        inner = request.get("innerDiameter")
        return [(circle(request["diameter"]), [circle(inner)] if inner else [])]

    sketch = request.get("sketch")
    if sketch is None:
        raise RouteBuildError("a routed part needs a 'diameter' or a 'sketch' to sweep")
    move = gp_Trsf()
    move.SetDisplacement(gp_Ax3(), frame)
    placed = BRepBuilderAPI_Transform(sketch, move, True).Shape()
    profiles = []
    faces = TopExp_Explorer(placed, TopAbs_FACE)
    while faces.More():
        face = TopoDS.Face_s(faces.Current())
        outer = BRepTools.OuterWire_s(face)
        inner = []
        wires = TopExp_Explorer(face, TopAbs_WIRE)
        while wires.More():
            wire = TopoDS.Wire_s(wires.Current())
            if not wire.IsSame(outer):
                inner.append(wire)
            wires.Next()
        profiles.append((outer, inner))
        faces.Next()
    if not profiles:
        raise RouteBuildError("the sketch has no face to sweep")
    return profiles


def _sweep(spine, aux, wire):
    from OCP.BRepFill import BRepFill_TypeOfContact
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell

    maker = BRepOffsetAPI_MakePipeShell(spine)
    # The auxiliary spine sets the profile's normal: from each point of the path
    # towards the point the same share of the way along the auxiliary spine
    # ('CurvilinearEquivalence'). Exact at both ends, where the share is 0 and 1,
    # and as near as the two lengths are elsewhere: the auxiliary spine runs only
    # AUX_OFFSET beside the path. Finding that point instead where the plane
    # square to the path meets the auxiliary spine fails on interpolated curves.
    maker.SetMode(aux, True, BRepFill_TypeOfContact.BRepFill_NoContact)
    maker.Add(wire, False, False)
    maker.Build()
    if not maker.IsDone():
        raise RouteBuildError("the sweep along the path failed")
    if not maker.MakeSolid():
        raise RouteBuildError("the swept profile does not close into a solid")
    return maker.Shape()


def _defects(shape):
    """What is wrong with the swept shape, or None (D9, after the sweep)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    solids = 0
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        solids += 1
        explorer.Next()
    if solids != 1:
        return "the sweep made %d solids, not one" % solids
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    if not props.Mass() > 0:
        return "the swept solid has no volume (%g mm^3)" % props.Mass()
    if not BRepCheck_Analyzer(shape).IsValid():
        return "the swept solid is not valid: the profile intersects itself along the path"
    return None


def process(request):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    route = request.get("route")
    if not route:
        raise RouteBuildError("no route: a routed part is built where an assembly places it with 'route:'")
    path = json.loads(route)["path"]
    count = len(path["points"])
    if count < 2:
        raise RouteBuildError("the route has fewer than two samples")
    indices = _spine_indices(count, path.get("knots", []))
    spine = _bspline_wire([path["points"][i] for i in indices], path["z"][0], path["z"][-1])
    aux = _bspline_wire(
        [[p + AUX_OFFSET * x for p, x in zip(path["points"][i], path["x"][i])] for i in indices],
    )
    frame = _first_frame(path)

    result = None
    for outer, inner in _profiles(request, frame):
        solid = _sweep(spine, aux, outer)
        for hole in inner:
            solid = BRepAlgoAPI_Cut(solid, _sweep(spine, aux, hole)).Shape()
        result = solid if result is None else BRepAlgoAPI_Fuse(result, solid).Shape()

    defect = _defects(result)
    if defect is not None:
        raise RouteBuildError(defect)
    return result


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        shape = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    else:
        # Validated and moved here, while it is live (see wrapper_common.finished).
        model = {"success": True, "exception": None, "shape": wrapper_common.finished(shape)}
    wrapper_common.handle_output(model)
