#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc cae cfd`, by FieldCraft: incompressible flow through one part, by the lattice Boltzmann method.

The part is read as the **fluid volume**, as every PartCAD flow analysis reads
it. Its `cfd:` keys, applied to the faces each port covers:

* `load:` names an **inlet**, pushed on with the pressure that is its force over
  the area its port covers;
* `outlet:` names where the flow **leaves**, at the reference pressure;
* every other surface is a **wall**, no-slip.

FieldCraft's fluid solver is not a finite element one: it is a D3Q19 lattice
Boltzmann solver on a box of cubic cells, with solid obstacles in it, and flow
enters and leaves only through the faces of the box. So the part is posed to it
inside out: the box is the part's bounding box, rounded up to whole cells, and
the obstacle is everything in the box that is *not* the part -- a block with the
part's shape cut out of it, imported as a closed surface. Each inlet and outlet
is the box face its port lies on, held at its pressure; every other box face is
a wall, and so is the obstacle's surface. That is exactly the part's own
problem, with one restriction: **a port has to lie on a face of the part's
bounding box, flat, with its normal along an axis** -- the ends of a straight
pipe or of a duct, the faces of a manifold block. A port anywhere else is
refused, saying so, rather than approximated.

The run goes until the flow and the outlets' flow rate stop changing
(FieldCraft's `steady` rule) or `end_time` of flow time has passed, on the CPU
backend so that it gives the same digits on every machine. The flow rate is what
FieldCraft measured through the outlet faces; the model is the part's surface
coloured by the pressure in the fluid just inside it.
"""

import math
import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import fieldcraft_common as fc  # noqa: E402
from fieldcraft_common import WARNING, support  # noqa: E402

STEP = "Flow"
DOMAIN = "Flow"
TURBULENT_REYNOLDS = 2300.0
AXES = "xyz"


def process(path, request):
    try:
        return _analyse(path, request)
    except (support.ToolMissing, support.ToolFailed) as e:
        return support.failed(e)


def _analyse(path, request):
    findings = []
    density = float(request.get("density", 1.204))
    viscosity = float(request.get("viscosity", 1.82e-5))
    _inlets, inlet_records, inlet_empty = support.condition_groups(request, "load", "inlet")
    _outlets, outlet_records, outlet_empty = support.condition_groups(request, "outlet", "outlet")
    findings.extend(fc.nothing_covered(record) for record in inlet_empty + outlet_empty)
    if not inlet_records:
        raise support.ToolFailed("'cfd:' drives nothing: name an inlet under 'load:', on a port that covers a surface")
    if not outlet_records:
        raise support.ToolFailed(
            "'cfd:' names no outlet, so the flow has nowhere to go and the problem has no downstream pressure "
            "reference: name where it leaves under 'outlet:', on a port that covers a surface"
        )
    shape = request.get("wrapped")
    if shape is None:
        raise support.ToolFailed("No shape was handed to the analysis")

    low, high = bounding_box(shape)
    inlets = [(box_face(record, low, high), record) for record in inlet_records]
    outlets = [(box_face(record, low, high), record) for record in outlet_records]
    faces = [face for face, _record in inlets + outlets]
    if len(set(faces)) != len(faces):
        raise support.ToolFailed(
            "Two ports lie on the same face of the part's bounding box (%s): FieldCraft holds a whole box face at "
            "one condition, so they cannot be told apart" % ", ".join(sorted({f for f in faces if faces.count(f) > 1}))
        )
    pressures = {face: float(r["load"]) / (float(r["area"]) * fc.M2_PER_MM2) for face, r in inlets}

    spacing = cell_size(request, low, high, inlet_records + outlet_records, faces)
    box_low, box_high, counts = domain(low, high, spacing, faces)
    cells = counts[0] * counts[1] * counts[2]
    limit = int(float(request.get("max_cells", 4.0e6)))
    if cells > limit:
        raise support.ToolFailed(
            "The flow would take %d cells of %.3g mm, past 'max_cells' (%d): raise 'mesh_size' or lower "
            "'cells_across'" % (cells, spacing, limit)
        )

    timing = timing_of(request, inlets, outlets, pressures, density, viscosity, low, high)
    with tempfile.TemporaryDirectory() as work:
        work = fc.case_dir(work)
        obstacle = os.path.join(work, "obstacle.stl")
        write_obstacle(shape, box_low, box_high, spacing, obstacle)
        samples, triangles, points = wall_samples(shape, spacing, int(request.get("max_samples", 4000)))
        with fc.Session(work, request) as session:
            imported = session.batch(
                [fc.UNITS, {"command": "geometry.import.mesh", "params": {"path": obstacle, "unit": "mm"}}]
            )
            surface = surface_name(imported[-1])
            solved = session.batch(
                commands_for(
                    request, surface, box_low, box_high, spacing, pressures, outlets, density, viscosity, timing
                )
            )[-1]
            pressure = probe_pressure(session, samples, findings)

    execution = solved.get("execution")
    stop = (solved.get("stop") or {}).get("reason")
    if execution == "diverged" or stop == "diverged":
        raise support.ToolFailed(
            "FieldCraft's flow diverged: lower 'mesh_size' (more cells), or the inlet pressure. Its report: %s"
            % _brief(solved)
        )
    if stop is not None and stop != "steady":
        findings.append(
            {
                "severity": WARNING,
                "message": "The flow did not settle within %.3g s of flow time: these numbers are not a steady "
                "state. Raise 'end_time'." % timing["end_time"],
            }
        )

    flow = outflow(solved, [face for face, _record in outlets])
    outlet_area = sum(float(record["area"]) for _face, record in outlets) * fc.M2_PER_MM2
    mean_speed = flow / outlet_area if outlet_area else 0.0
    peak_speed = float(solved.get("final_max_speed") or solved.get("max_speed") or 0.0)
    reynolds = density * abs(mean_speed) * math.sqrt(4.0 * outlet_area / math.pi) / viscosity

    support.write_glb(path, points, triangles, pressure)

    if reynolds > TURBULENT_REYNOLDS and not request.get("turbulence"):
        findings.append(
            {
                "severity": WARNING,
                "message": "The flow is likely turbulent (Reynolds number about %.0f, past %.0f), and this analysis "
                "is laminar: set 'turbulence' to model it." % (reynolds, TURBULENT_REYNOLDS),
            }
        )
    limit = request.get("max_velocity")
    if limit is not None and peak_speed > float(limit):
        findings.append(
            {
                "severity": WARNING,
                "message": "The flow reaches %.3g m/s, past the %.3g m/s it is allowed." % (peak_speed, float(limit)),
                "where": "peak speed",
            }
        )
    minimum = request.get("min_flow_rate")
    if minimum is not None and flow < float(minimum):
        findings.append(
            {
                "severity": WARNING,
                "message": "The part passes %.4g m^3/s, short of the %.4g m^3/s it has to." % (flow, float(minimum)),
                "where": "flow rate",
            }
        )
    return {
        "success": True,
        "findings": findings,
        "warnings": [
            "Flow rate %.4g m^3/s (%.4g L/min), mean outlet speed %.4g m/s, peak speed %.4g m/s, Reynolds number "
            "%.3g, driven by %s, over %d cells of %.3g mm"
            % (
                flow,
                flow * 60000.0,
                mean_speed,
                peak_speed,
                reynolds,
                ", ".join("%.4g Pa" % value for value in pressures.values()),
                cells,
                spacing,
            )
        ],
    }


# --------------------------------------------------------------------------- #
# The box                                                                     #
# --------------------------------------------------------------------------- #


def bounding_box(shape):
    """The part's axis-aligned bounding box, millimetres, exact rather than enlarged by tolerances."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return [xmin, ymin, zmin], [xmax, ymax, zmax]


def box_face(record, low, high):
    """The face of the bounding box a port's faces lie on, as FieldCraft names it ('x_min', ...)."""
    port = record.get("port") or record.get("interface") or "a port"
    extent = max(h - lo for lo, h in zip(low, high))
    tolerance = max(extent * 1e-6, 1e-6)
    found = set()
    for face in record.get("faces") or []:
        normal = face.get("normal")
        if not normal:
            raise support.ToolFailed(
                "Port '%s' covers a curved surface. FieldCraft's flow solver lets a fluid in and out only through "
                "the flat faces of its box, so an inlet or an outlet has to lie on a flat face of the part's "
                "bounding box, its normal along an axis" % port
            )
        axis = max(range(3), key=lambda k: abs(normal[k]))
        if abs(normal[axis]) < 1.0 - 1e-6:
            raise support.ToolFailed(
                "Port '%s' faces %s, which is not along an axis. FieldCraft's flow solver lets a fluid in and out "
                "only through the faces of its box, so an inlet or an outlet has to face along X, Y or Z"
                % (port, ", ".join("%.3g" % c for c in normal))
            )
        side = "max" if normal[axis] > 0 else "min"
        bound = high[axis] if side == "max" else low[axis]
        if abs(face["centroid"][axis] - bound) > tolerance:
            raise support.ToolFailed(
                "Port '%s' lies inside the part's bounding box, not on its %s face. FieldCraft's flow solver lets "
                "a fluid in and out only through the faces of its box, which is the part's bounding box here"
                % (port, "%s_%s" % (AXES[axis], side))
            )
        found.add("%s_%s" % (AXES[axis], side))
    if len(found) != 1:
        raise support.ToolFailed("Port '%s' covers faces on %d sides of the bounding box" % (port, len(found)))
    return found.pop()


def cell_size(request, low, high, records, faces):
    """The cells' edge, millimetres: fine enough for the narrowest port, and a whole number along any axis with a port at each end."""
    extent = max(h - lo for lo, h in zip(low, high))
    size = float(request.get("mesh_size", 0.02)) * extent
    across = float(request.get("cells_across", 8))
    for record in records:
        diameter = 2.0 * math.sqrt(float(record["area"]) / math.pi)
        size = min(size, diameter / across)
    exact = [axis for axis in range(3) if "%s_min" % AXES[axis] in faces and "%s_max" % AXES[axis] in faces]
    if exact:
        length = high[exact[0]] - low[exact[0]]
        size = length / math.ceil(length / size - 1e-9)
        for axis in exact[1:]:
            ratio = (high[axis] - low[axis]) / size
            if abs(ratio - round(ratio)) > 1e-6:
                raise support.ToolFailed(
                    "Ports at both ends of two axes need a cell size that divides both lengths (%.6g and %.6g mm), "
                    "and none near %.3g mm does: FieldCraft's box has to be a whole number of cells along each"
                    % (high[exact[0]] - low[exact[0]], high[axis] - low[axis], size)
                )
    return size


def domain(low, high, spacing, faces):
    """The box FieldCraft solves in, metres, and its cell counts: the bounding box grown to whole cells away from the ports."""
    box_low, box_high, counts = [], [], []
    for axis in range(3):
        length = high[axis] - low[axis]
        count = max(1, int(math.ceil(length / spacing - 1e-9)))
        extra = count * spacing - length
        at_min = "%s_min" % AXES[axis] in faces
        at_max = "%s_max" % AXES[axis] in faces
        if at_min and not at_max:
            below, above = 0.0, extra
        elif at_max and not at_min:
            below, above = extra, 0.0
        else:
            below = above = extra / 2.0
        box_low.append((low[axis] - below) / fc.MM_PER_M)
        box_high.append((high[axis] + above) / fc.MM_PER_M)
        counts.append(count)
    return box_low, box_high, counts


def write_obstacle(shape, box_low, box_high, spacing, path):
    """Everything around the part, as a closed STL in millimetres: a block grown past the box with the part cut out."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.StlAPI import StlAPI_Writer

    margin = 2.0 * spacing
    lo = [value * fc.MM_PER_M - margin for value in box_low]
    hi = [value * fc.MM_PER_M + margin for value in box_high]
    block = BRepPrimAPI_MakeBox(gp_Pnt(*lo), gp_Pnt(*hi)).Shape()
    cut = BRepAlgoAPI_Cut(block, shape)
    if not cut.IsDone():
        raise support.ToolFailed("The part could not be cut out of its surroundings for the flow solver")
    around = cut.Shape()
    BRepMesh_IncrementalMesh(around, spacing / 10.0, False, 0.2, True)
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    if not writer.Write(around, path):
        raise support.ToolFailed("The part's surroundings could not be written for the flow solver")
    return path


def surface_name(reply):
    """The name FieldCraft gave the imported obstacle."""
    for surface in (reply or {}).get("surfaces") or []:
        if surface.get("name"):
            return surface["name"]
    raise support.ToolFailed("FieldCraft imported no surface from the obstacle: %s" % _brief(reply))


# --------------------------------------------------------------------------- #
# The run                                                                     #
# --------------------------------------------------------------------------- #


def timing_of(request, inlets, outlets, pressures, density, viscosity, low, high):
    """How long a flow is run, and over which window it is watched for settling, in seconds of flow time.

    A pressure-driven flow settles in the shorter of the time momentum takes to
    diffuse across the narrowest port (a slow, viscous flow: R^2/nu) and a few
    times the time the fluid takes to pass through (a fast one). Estimated from
    the drive -- the Hagen-Poiseuille speed, capped by Bernoulli's -- and run
    for ten of them, unless 'end_time' says otherwise.
    """
    nu = viscosity / density
    radius = min(math.sqrt(float(r["area"]) / math.pi) for _f, r in inlets + outlets) / fc.MM_PER_M
    centres = [_centre(r) for _f, r in inlets + outlets]
    length = (
        max(math.dist(a, b) for a in centres for b in centres) / fc.MM_PER_M
        or max(h - lo for lo, h in zip(low, high)) / fc.MM_PER_M
    )
    drop = max(pressures.values()) if pressures else 0.0
    speed = min(drop * radius * radius / (8.0 * viscosity * length), math.sqrt(2.0 * abs(drop) / density))
    viscous = radius * radius / nu
    through = length / speed if speed > 0 else viscous
    settle = min(viscous, 5.0 * through)
    end_time = float(request.get("end_time") or 10.0 * settle)
    return {"end_time": end_time, "window": min(end_time / 4.0, max(settle / 2.0, end_time / 40.0))}


def _centre(record):
    faces = record.get("faces") or []
    area = sum(float(f["area"]) for f in faces) or 1.0
    return [sum(float(f["centroid"][k]) * float(f["area"]) for f in faces) / area for k in range(3)]


def commands_for(request, surface, box_low, box_high, spacing, pressures, outlets, density, viscosity, timing):
    faces = {face: {"type": "pressure", "pressure": value} for face, value in pressures.items()}
    for face, _record in outlets:
        faces[face] = {"type": "pressure", "pressure": 0.0, "outflow": request.get("outflow", "uniform")}
    procedure = {
        "type": "fluid",
        "domain": DOMAIN,
        "end_time": timing["end_time"],
        "frames": 2,
        "walls": request.get("walls", "interpolated"),
        "steady": {
            "tolerance": float(request.get("steady_tolerance", 1e-3)),
            "window": timing["window"],
            "monitors": [{"type": "mass_flow", "face": face} for face, _record in outlets],
        },
    }
    if request.get("collision"):
        procedure["collision"] = request["collision"]
    if request.get("turbulence"):
        turbulence = request["turbulence"]
        procedure["turbulence"] = turbulence if isinstance(turbulence, dict) else {"type": str(turbulence)}
    return [
        {
            "command": "model.material.create",
            "params": {"name": "fluid", "density": density, "fluid": {"type": "newtonian", "viscosity": viscosity}},
        },
        {
            "command": "model.fluid_domain.create",
            "params": {
                "name": DOMAIN,
                "material": "fluid",
                "min": box_low,
                "max": box_high,
                "spacing": spacing / fc.MM_PER_M,
                "faces": faces,
                "obstacles": [surface],
            },
        },
        {"command": "model.step.create", "params": {"name": STEP, "procedure": procedure}},
        {"command": "solve.fluid", "params": {"step": STEP, "backend": "cpu"}},
    ]


def outflow(reply, outlet_faces):
    """The volume flow out through the outlets, m^3/s, as FieldCraft measured it on the box faces."""
    total = 0.0
    found = False
    for port in ((reply or {}).get("ports") or {}).get("faces") or []:
        if port.get("face") in outlet_faces:
            out = (port.get("outflow") or {}).get("volume_flow") or 0.0
            back = (port.get("inflow") or {}).get("volume_flow") or 0.0
            total += float(out) - float(back)
            found = True
    if not found:
        raise support.ToolFailed("FieldCraft reported no flow through the outlets: %s" % _brief(reply))
    return total


def _brief(reply):
    import json

    text = json.dumps(reply)
    return text if len(text) < 600 else text[:600] + "..."


# --------------------------------------------------------------------------- #
# The picture                                                                 #
# --------------------------------------------------------------------------- #


def wall_samples(shape, spacing, limit):
    """The part's surface as triangles, and a point just inside the fluid behind each.

    Returns '(samples, triangles, points)': 'samples' in metres, one per
    triangle, three-quarters of a cell in from it along its inward normal (where
    the fluid next to the wall is); 'points' in metres, three per triangle so
    that each is drawn in its own sample's colour; 'triangles' their indices.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    extent = max(h - lo for lo, h in zip(*bounding_box(shape)))
    deflection = extent / 100.0
    while True:
        BRepMesh_IncrementalMesh(shape, deflection, False, 0.5, True)
        corners = []
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            location = TopLoc_Location()
            mesh = BRep_Tool.Triangulation_s(face, location)
            if mesh is not None:
                transform = location.Transformation()
                nodes = [mesh.Node(k).Transformed(transform) for k in range(1, mesh.NbNodes() + 1)]
                reverse = face.Orientation() == TopAbs_REVERSED
                for k in range(1, mesh.NbTriangles() + 1):
                    a, b, c = mesh.Triangle(k).Get()
                    if reverse:
                        b, c = c, b
                    corners.append([(p.X(), p.Y(), p.Z()) for p in (nodes[a - 1], nodes[b - 1], nodes[c - 1])])
            explorer.Next()
        if len(corners) <= limit or deflection > extent:
            break
        deflection *= 2.0

    inset = 0.75 * spacing
    samples, points, triangles = [], [], []
    for a, b, c in corners:
        u = [b[k] - a[k] for k in range(3)]
        v = [c[k] - a[k] for k in range(3)]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        size = math.sqrt(sum(x * x for x in n)) or 1.0
        centre = [(a[k] + b[k] + c[k]) / 3.0 for k in range(3)]
        samples.append([(centre[k] - inset * n[k] / size) / fc.MM_PER_M for k in range(3)])
        start = len(points)
        points.extend(tuple(value / fc.MM_PER_M for value in corner) for corner in (a, b, c))
        triangles.append((start, start + 1, start + 2))
    return samples, triangles, points


def probe_pressure(session, samples, findings):
    """The gauge pressure in the fluid at each sample, three values per sample (one per drawn corner)."""
    values = []
    try:
        reply = session.batch([{"command": "solve.probe", "params": {"step": STEP, "points": samples}}])[-1]
        values = _pressures(reply, len(samples))
    except support.ToolFailed as e:
        findings.append({"severity": "info", "message": "The surface is drawn uncoloured: %s" % e})
    known = [v for v in values if v is not None]
    fill = sum(known) / len(known) if known else 0.0
    if len(values) != len(samples):
        values = [None] * len(samples)
    return [v if v is not None else fill for v in values for _corner in range(3)]


def _pressures(reply, count):
    """The 'pressure' of each probed point, in the order asked, None where a point is not in the fluid.

    FieldCraft answers `{"points": [{"point", "cell", "solid", "velocity",
    "pressure"}, ...]}`, with `cell` null for a point outside the box and
    `solid` true for one in an obstacle's cell -- neither of which is the fluid.
    """
    points = (reply or {}).get("points") if isinstance(reply, dict) else None
    if not isinstance(points, list) or len(points) != count:
        return []
    found = []
    for item in points:
        pressure = item.get("pressure") if isinstance(item, dict) else None
        usable = isinstance(pressure, (int, float)) and item.get("cell") is not None and not item.get("solid")
        found.append(float(pressure) if usable else None)
    return found


if __name__ == "__partcad_export__":
    pass
