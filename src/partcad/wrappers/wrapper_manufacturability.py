#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to run the shape analysis the 'pc test' manufacturability checks need, so
# the core process never has to touch a live OCP object. The shape arrives as a
# BREP envelope and the analysis result goes back as plain data.

import math
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def free_bounds(request):
    """How many free boundaries the shape has, which is how open it is.

    A solid a machine can make is closed: every edge of it is shared by two
    faces. A free boundary is an edge that is not, so a count above zero is a
    shape with a hole in its surface - a surface model, or a solid that failed
    to sew - and 'ManufacturabilityTest' reports it as a part nothing can be made from.
    """
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBoundsProperties

    shape = request["shape"]
    fbp = ShapeAnalysis_FreeBoundsProperties(shape)
    fbp.Perform()
    return {"free_bounds": fbp.NbFreeBounds()}


def flatness(request):
    """How much of the shape lies in the horizontal planes at its top and bottom.

    The question a sheet metal blank has to answer: it is a piece of sheet, so
    the plane through its highest point and the plane through its lowest one
    each meet it in a face rather than touching it at an edge or a point. The
    area of that meeting is the answer, and zero means it is not a blank.

    Computed as the area of the shape's own horizontal planar faces that sit at
    each extreme, which is exactly the area of the intersection and costs no
    boolean: a plane cannot cut a solid at the very limit of it, so anything the
    plane meets there is surface the shape already has. Doing it as a boolean
    instead would depend on a tolerance to decide whether the plane and the face
    are the same plane, which is the thing being measured.

    'z_min' and 'z_max' come from the bounding box rather than from those faces,
    and that is the whole reason the box is here: a dome has a horizontal face
    at its base and nothing at its top, and only the box knows where its top is.
    The box is asked for the geometry's own extent - no gap, and not inflated by
    the shapes' tolerances - because the question is about a plane through the
    extreme point and not about a plane near it.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    shape = request["shape"]

    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if box.IsVoid():
        return {"z_min": None, "z_max": None, "area_min": 0.0, "area_max": 0.0}
    _, _, z_min, _, _, z_max = box.Get()

    # What counts as "at the extreme" and as "horizontal". Both are relative to
    # the shape: a plane is level if its normal is within a millionth of
    # vertical, and a face is at the top if it is within a millionth of the
    # height of it. A flat blank is flat to far better than that, and a curved
    # surface misses by far more.
    height = max(abs(z_max - z_min), 1.0)
    tolerance = 1e-6 * height
    area_min = 0.0
    area_max = 0.0

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
            continue
        plane = surface.Plane()
        axis = plane.Axis().Direction()
        if abs(abs(axis.Z()) - 1.0) > 1e-6:
            continue
        z = plane.Location().Z()
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, properties)
        if abs(z - z_max) <= tolerance:
            area_max += properties.Mass()
        if abs(z - z_min) <= tolerance:
            area_min += properties.Mass()

    return {"z_min": z_min, "z_max": z_max, "area_min": area_min, "area_max": area_max}


def _volume(shape) -> float:
    """The volume a solid encloses, in cubic millimetres.

    Zero for a shape with no solid in it, which is what an empty boolean result
    is: 'BRepAlgoAPI_Cut' of a shape by one that contains it produces a valid
    compound with nothing inside, not a null shape, so "is it empty" has to be
    asked of the volume rather than of the handle.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    if shape is None:
        return 0.0
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return float(properties.Mass())


def _cut(minuend, subtrahend):
    """What is left of one shape when another is taken out of it."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    operation = BRepAlgoAPI_Cut(minuend, subtrahend)
    operation.Build()
    if not operation.IsDone():
        raise Exception("the boolean operation failed")
    return operation.Shape()


def enclosure(request):
    """Whether the source strictly contains the part, and by how much.

    Subtraction takes material away, so the part has to be what is left of the
    stock rather than something else the same size: every point of it inside the
    source, and the source bigger than it somewhere. Both halves are asked
    because each catches a different mistake, and neither implies the other.

    * 'outside' is the part minus the source -- material the part has where the
      stock had none. Anything above zero means the part does not fit what it
      is cut from, which no amount of cutting will fix.
    * 'removed' is the source minus the part -- what the machine takes off. Zero
      means the two are the same solid, which is a part that declares a source
      it is not actually cut from: usually the source naming the part itself,
      or a copy of it.

    Volumes rather than a boolean, because the number is what makes the failure
    legible: "0.02 mm3 outside" is a part that pokes out by a rounding error and
    "1900 mm3 outside" is the wrong source entirely, and a check that said only
    "does not fit" would leave the reader to find out which.
    """
    part = request["shape"]
    source = request["source"]
    return {
        "part_volume": _volume(part),
        "source_volume": _volume(source),
        "outside_volume": _volume(_cut(part, source)),
        "removed_volume": _volume(_cut(source, part)),
    }


def wall_alignment(request):
    """How every face of the subject lies relative to the machine's own axis.

    The question all three subtractive machines raise in one form or another: a
    beam that does not tilt, and a drill that only goes in and out, can make a
    wall parallel to the axis they work along and nothing else. So each face is
    measured against that axis by its own normal:

    * a **wall** is a face whose normal is everywhere perpendicular to the axis.
      That is exactly a face the tool sweeps along without changing what it
      touches -- a plane containing the axis, a cylinder coaxial with it, any
      surface extruded along it.
    * a **cap** is a face whose normal is everywhere parallel to the axis: the
      top and the bottom, which the machine does not cut at all. They are what
      the stock already had.
    * anything else is a face that is neither, which is a chamfer, a taper, a
      dome or a fillet rolling over an edge -- and the thing a laser cannot cut
      and a drill cannot make.

    Sampled over each face's parameter space rather than read off its surface
    type, because the type is not the question. A cylinder is a wall when it is
    coaxial with the axis and a defect when it lies across it; a B-spline
    extruded along the axis is a perfectly good wall that no type test would
    accept. The normal is what the machine actually cares about, so it is what
    is measured.

    'round' counts the walls that are cylinders coaxial with the axis, which is
    the extra thing a drill needs: it makes round holes, so a wall that is not
    one is a feature it cannot produce however vertical it is.

    A 'source' in the request changes *what* is measured rather than how: the
    material the machine takes off, which is the source minus the part. That is
    the right subject wherever the part keeps faces the machine did not make --
    a drilled plate's straight sides came with the stock -- and it is the whole
    of the difference between what a drill is asked and what a laser is.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    shape = request["shape"]
    source = request.get("source")
    if source is not None:
        # What the machine actually cuts, rather than what the part ends up
        # bounded by. The difference matters for a drill: a drilled plate's
        # outline is the stock's outline, and a drill did not make it -- asking
        # the part's own walls would fail every plate for having straight sides.
        # Asked of the removed material, the same plate is exactly what it
        # should be: a couple of round holes.
        shape = _cut(source, shape)
    axis = request.get("tool_axis_vector") or [0.0, 0.0, -1.0]
    length = math.sqrt(sum(component * component for component in axis))
    if length <= 0:
        raise Exception("the tool axis is a zero vector")
    axis = [component / length for component in axis]

    # How far from perpendicular a normal may be and still count as a wall.
    # Generous next to the 1e-6 'flatness' uses, because this is sampled on
    # curved surfaces where the normal is computed rather than exact, and
    # because the thing being excluded -- a chamfer, a taper, a dome -- misses
    # by degrees rather than by microns. 1e-3 is about 0.06 degrees.
    tolerance = float(request.get("angular_tolerance") or 1e-3)
    # How finely each face is sampled. A face is rejected on its *worst* sample,
    # so this only has to be fine enough to land on the part of a surface that
    # departs from the axis; a 4x4 grid does that for anything a machinist would
    # call a chamfer or a fillet.
    steps = 4

    counts = {"walls": 0, "caps": 0, "other": 0, "round": 0}
    offenders = []
    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()

        surface = BRepAdaptor_Surface(face)
        u0, u1 = surface.FirstUParameter(), surface.LastUParameter()
        v0, v1 = surface.FirstVParameter(), surface.LastVParameter()
        if not all(map(math.isfinite, (u0, u1, v0, v1))):
            # An unbounded parameter range is a surface with no face on it
            # worth measuring; it cannot be sampled and it is not geometry
            # the part is bounded by.
            continue

        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, properties)
        area = float(properties.Mass())

        worst_wall = 0.0  # the largest |n.axis| seen: 0 is a perfect wall
        worst_cap = 1.0  # the smallest |n.axis| seen: 1 is a perfect cap
        measured = 0
        props = BRepLProp_SLProps(surface, 1, 1e-7)
        for i in range(steps + 1):
            for j in range(steps + 1):
                u = u0 + (u1 - u0) * i / steps
                v = v0 + (v1 - v0) * j / steps
                props.SetParameters(u, v)
                if not props.IsNormalDefined():
                    # A pole of a sphere, a degenerate corner. The rest of
                    # the face still answers for it.
                    continue
                normal = props.Normal()
                dot = abs(normal.X() * axis[0] + normal.Y() * axis[1] + normal.Z() * axis[2])
                worst_wall = max(worst_wall, dot)
                worst_cap = min(worst_cap, dot)
                measured += 1
        if measured == 0:
            continue

        if worst_wall <= tolerance:
            counts["walls"] += 1
            if surface.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                direction = surface.Cylinder().Axis().Direction()
                aligned = abs(direction.X() * axis[0] + direction.Y() * axis[1] + direction.Z() * axis[2])
                if abs(aligned - 1.0) <= tolerance:
                    counts["round"] += 1
        elif worst_cap >= 1.0 - tolerance:
            counts["caps"] += 1
        else:
            counts["other"] += 1
            if len(offenders) < 8:
                offenders.append(
                    {
                        "surface": str(surface.GetType()).rsplit(".", 1)[-1].replace("GeomAbs_", ""),
                        "area": area,
                        # The angle between the face and the axis, in
                        # degrees, which is what a reader can act on: 45 is
                        # a chamfer, 0.4 is a draft angle somebody did not
                        # mean to leave in.
                        "tilt": math.degrees(math.acos(min(1.0, max(0.0, worst_wall)))),
                    }
                )

    counts["offenders"] = offenders
    return counts


# The analyses this wrapper performs, by the name the request asks for. Named
# rather than one per wrapper because each is a few lines of OCCT over a shape
# that has just been deserialized, and starting a second sandbox to run them
# would cost more than all of them together.
OPERATIONS = {
    "free_bounds": free_bounds,
    "flatness": flatness,
    "enclosure": enclosure,
    "wall_alignment": wall_alignment,
}


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        # 'free_bounds' by default, because that is what this wrapper did before
        # it had more than one thing to do, and a request is not required to say.
        model = {"success": True, "exception": None}
        model.update(OPERATIONS[request.get("op") or "free_bounds"](request))
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(model)
