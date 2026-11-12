#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a machine makes out of what it is given, by following its instructions (see '//builtin/cam').

The other half of a route. `cam_gcode` writes the program a machine runs; this
works out what comes off the machine when it runs it -- the part's own geometry
as the manufacturing process makes it, which `pc cam --materialize` writes and a
part with no geometry of its own is:

* a **router, laser or drill** takes away, from the stock its part names, the
  volume its tool sweeps along the route it was given: each path stroked by the
  tool's radius (half the kerf for a laser), from the bottom of the cut to above
  the top, and each drilled hole as the drill's own cylinder. What a profile cut
  separates from the part -- the offcut around it, the slug in a hole -- is left
  on the bed: of what remains, the part is what lies inside the outline the cut
  went round;
* a **saw** takes away everything beyond each of its cuts;
* a **mold** gives back its cavity, shrunk by the material's shrinkage as it
  cools (a linear fraction, about the part's origin).

All of it in the part's own frame. The route is written in the machine's, where
the tool axis is -Z (`cam_gcode._orient`), so what is computed there is turned
back before it is handed over.
"""

import math

import pyclipper

SCALE = 1e5


def _to_clipper(points):
    return [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in points]


def _stroke(paths, radius, tolerance):
    """The region a tool of `radius` sweeps along closed paths."""
    offsetter = pyclipper.PyclipperOffset()
    offsetter.ArcTolerance = max(tolerance, 1e-4) * SCALE
    for points in paths:
        offsetter.AddPath(_to_clipper(points), pyclipper.JT_ROUND, pyclipper.ET_CLOSEDLINE)
    return offsetter.Execute(max(radius, 1e-4) * SCALE)


def _region(paths, amount, tolerance):
    """The interiors of closed paths, offset by `amount` (negative inward)."""
    if not paths:
        return []
    offsetter = pyclipper.PyclipperOffset()
    offsetter.ArcTolerance = max(tolerance, 1e-4) * SCALE
    offsetter.AddPaths([_to_clipper(points) for points in paths], pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return offsetter.Execute(amount * SCALE)


def _prism_tool(region, bottom, top):
    """A region extruded from `bottom` to `top`, as a compound of prisms."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    import cam_fff

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    height = top - bottom
    count = cam_fff.prisms([(bottom + height / 2.0, region)], height, builder, compound)
    return compound if count else None


def _cut(shape, tool):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    operation = BRepAlgoAPI_Cut(shape, tool)
    if not operation.IsDone():
        raise Exception("taking the tool's sweep away from the stock failed")
    return operation.Shape()


def _solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    found = []
    while explorer.More():
        found.append(TopoDS.Solid_s(explorer.Current()))
        explorer.Next()
    return found


def _centre_and_volume(solid):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props)
    centre = props.CentreOfMass()
    return (centre.X(), centre.Y()), props.Mass()


def _compound(solids):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    if len(solids) == 1:
        return solids[0]
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for solid in solids:
        builder.Add(compound, solid)
    return compound


def removal(stock, removed, tolerance):
    """The part a router or a laser leaves of `stock` (in the machine's frame) after its route.

    'removed' is what the emitter recorded: every path the tool centre followed
    (with whether it went round a hole), the tool's radius, and the depth of the
    cut. Of what is left, a profile cut keeps what lies inside the outline it
    went round and outside every hole; a pocket or an engraving separates
    nothing, and keeps it all.
    """
    paths = [points for points, _inside in removed["paths"]]
    radius = float(removed["radius"])
    swept = _stroke(paths, radius, tolerance)
    if not swept:
        raise Exception("the route sweeps nothing")
    tool = _prism_tool(swept, float(removed["bottom"]), float(removed["top"]) + 1.0)
    if tool is None:
        raise Exception("the route sweeps nothing")
    remaining = _solids(_cut(stock, tool))
    if not remaining:
        raise Exception("the route takes all of the stock away")
    if removed.get("operation") != "profile":
        return _compound(remaining)

    # What a profile cut separated is told from the part by where it lies: the
    # part inside the outline the tool went round (that path, less the tool's
    # radius), every slug inside a hole's. By bounding box rather than by a
    # point: the offcut frame around a part is centred on it.
    tolerance_box = max(radius, tolerance) + 1e-6
    outlines = [_bounds(_region([points], -radius, tolerance)) for points, inside in removed["paths"] if not inside]
    holes = [_bounds(_region([points], radius, tolerance)) for points, inside in removed["paths"] if inside]
    kept = []
    for solid in remaining:
        box = _box_of(solid)
        if not any(_within(box, outline, tolerance_box) for outline in outlines if outline):
            continue
        if any(_within(box, hole, tolerance_box) for hole in holes if hole):
            continue
        kept.append(solid)
    if not kept:
        # Nothing separated cleanly (a cut short of through): the largest piece.
        kept = [max(remaining, key=lambda solid: _centre_and_volume(solid)[1])]
    return _compound(kept)


def _bounds(region):
    """(xmin, ymin, xmax, ymax) of a Clipper region, in mm; None for an empty one."""
    points = [point for path in region for point in path]
    if not points:
        return None
    xs = [x / SCALE for x, _ in points]
    ys = [y / SCALE for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _box_of(solid):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(solid, box)
    xmin, ymin, _zmin, xmax, ymax, _zmax = box.Get()
    return xmin, ymin, xmax, ymax


def _within(inner, outer, slack):
    return (
        inner[0] >= outer[0] - slack
        and inner[1] >= outer[1] - slack
        and inner[2] <= outer[2] + slack
        and inner[3] <= outer[3] + slack
    )


def drilled(stock, holes, diameter):
    """What a drill leaves of `stock` (in the machine's frame): every hole its own cylinder."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for x, y, top, bottom in holes:
        axis = gp_Ax2(gp_Pnt(float(x), float(y), float(bottom)), gp_Dir(0, 0, 1))
        builder.Add(compound, BRepPrimAPI_MakeCylinder(axis, diameter / 2.0, float(top) - float(bottom) + 1.0).Shape())
    return _compound(_solids(_cut(stock, compound)) or [stock])


def sawn(stock, cuts):
    """What a saw leaves of `stock`: everything beyond each cut taken off.

    Each cut is '{normal, length}' (see 'part_config_manufacturing.parse_cuts'):
    the saw starts where the stock starts along 'normal', goes 'length' into it,
    and what is further along is the offcut.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

    box = Bnd_Box()
    BRepBndLib.Add_s(stock, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    corners = [(x, y, z) for x in (xmin, xmax) for y in (ymin, ymax) for z in (zmin, zmax)]
    size = math.dist((xmin, ymin, zmin), (xmax, ymax, zmax)) + 1.0
    part = stock
    for cut in cuts:
        normal = [float(component) for component in cut["normal"]]
        start = min(sum(c * n for c, n in zip(corner, normal)) for corner in corners)
        at = start + float(cut["length"])
        point = gp_Pnt(*(n * at for n in normal))
        plane = gp_Pln(point, gp_Dir(*normal))
        face = BRepBuilderAPI_MakeFace(plane, -size * 2, size * 2, -size * 2, size * 2).Face()
        beyond = gp_Pnt(*(n * (at + size) for n in normal))
        part = _cut(part, BRepPrimAPI_MakeHalfSpace(face, beyond).Solid())
    solids = _solids(part)
    if not solids:
        raise Exception("the cuts take all of the stock away")
    return _compound(solids)


def molded(cavity, shrinkage):
    """What a mold gives back: its cavity, shrunk by `shrinkage` (a linear fraction) about the origin."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Pnt, gp_Trsf

    if not shrinkage:
        return cavity
    if not 0.0 <= shrinkage < 1.0:
        raise Exception("'shrinkage' is a fraction from 0 to 1, not %r" % shrinkage)
    transform = gp_Trsf()
    transform.SetScale(gp_Pnt(0, 0, 0), 1.0 - shrinkage)
    return BRepBuilderAPI_Transform(cavity, transform, True).Shape()
