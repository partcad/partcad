#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The route a filament printer follows, and what that route deposits (see '//builtin/cam').

A printer is a router run once per layer that lays a bead down where a router
cuts one away, so its route is made of the same pieces `cam_gcode` cuts with:
the section of the design at a height (`_faces_at`), its outline as a polyline
within a tolerance (`_wire_points`), and the program (`Program`). What a cut
never needed, and a print does on every layer, is offsetting a region that has
holes in it -- every hole of a printed part is an island its perimeters go round
-- and clipping lines to a region, which is what infill is. OCCT's 2D offset
drops a hole where its offset touches the outline's (docs/design/additive.md,
section 5), so both are Clipper's, as they are in every slicer: `pyclipper`, in
integer coordinates of `SCALE` per millimetre.

Per layer, at `z_i = z_min + (i + 1/2) h`:

* **walls** -- rings around every outline and every hole, the first half a line
  in, then a line spacing apart; the spacing of a stadium bead,
  `s = w - h (1 - pi / 4)` (Slic3r's flow model), so that adjacent beads have
  exactly the area they are fed;
* **skins** -- what is left inside the walls and is not under (over) the same
  region in each of the `topLayers` (`bottomLayers`) layers above (below), filled
  solid with lines `s` apart;
* **infill** -- the rest, filled with lines `s / infill` apart, at +45 and -45
  degrees on alternate layers ('rectilinear'; 'grid' crosses both on every
  layer), or with rings that far apart ('concentric', a pocket's rings).

What it deposits (`deposit`) is that route stroked at the line spacing -- the
rectangle with the stadium's area -- and extruded by a layer: a compound of
planar prisms, never fused (fusing ten layers of a 20 mm cube takes longer than
building all hundred). It is what `pc cam --materialize` writes and what a
printed part with no geometry of its own is.
"""

import math

import pyclipper

# Clipper's integer units per millimetre: 10 nm, far below anything a nozzle
# lays and far above the noise of the floating-point section.
SCALE = 1e5

# The infill patterns this route draws, and what each is.
PATTERNS = ("rectilinear", "grid", "lines", "concentric")


class Settings:
    """A printer's settings as the request carries them, every one a number in mm or a count."""

    def __init__(self, request):
        def number(key, default):
            value = request.get(key)
            return float(default if value is None else value)

        self.layer_height = number("layerHeight", 0.2)
        self.line_width = number("lineWidth", 0.45)
        self.walls = int(number("walls", 2))
        self.top_layers = int(number("topLayers", 4))
        self.bottom_layers = int(number("bottomLayers", 4))
        self.infill = number("infill", 0.15)
        self.pattern = str(request.get("infillPattern") or "rectilinear").lower()
        self.filament = number("filament", 1.75)
        self.tolerance = number("tolerance", 0.01)
        if self.layer_height <= 0 or self.line_width <= 0:
            raise Exception("'layerHeight' and 'lineWidth' have to be positive lengths")
        if self.layer_height > self.line_width:
            raise Exception(
                "a layer %.3f mm high is taller than the %.3f mm line laid in it" % (self.layer_height, self.line_width)
            )
        if not 0.0 <= self.infill <= 1.0:
            raise Exception("'infill' is a fraction from 0 to 1, not %r" % request.get("infill"))
        if self.pattern not in PATTERNS:
            raise Exception(
                "'infillPattern: %s' is not one this route draws; it draws %s. A slicer named as the route's"
                " 'implementation:' draws the rest" % (self.pattern, ", ".join(PATTERNS))
            )

    @property
    def spacing(self):
        """Centre to centre of adjacent lines: the stadium bead's flow spacing."""
        return self.line_width - self.layer_height * (1.0 - math.pi / 4.0)

    @property
    def bead_area(self):
        """The stadium cross-section a line has: what its `E` feeds."""
        return self.layer_height * self.spacing


class Path:
    """One extrusion path: a polyline in mm, in the layer it is laid in."""

    __slots__ = ("layer", "z", "role", "points", "closed")

    def __init__(self, layer, z, role, points, closed):
        self.layer = layer
        self.z = z
        self.role = role
        self.points = points
        self.closed = closed

    def polyline(self):
        """The points the head goes through, back to the first for a closed one."""
        return self.points + [self.points[0]] if self.closed else self.points

    @property
    def length(self):
        pts = self.polyline()
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _to_clipper(points):
    return [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in points]


def _from_clipper(path):
    return [(x / SCALE, y / SCALE) for x, y in path]


def section(obj, z, tolerance, faces_at, wire_points):
    """The design's region at height z, as Clipper paths, from `pc cam`'s own section and polylines."""
    wires = []
    for face in faces_at(obj, z):
        for wire in [face.outer_wire()] + list(face.inner_wires()):
            points = wire_points(wire, tolerance)
            if len(points) >= 4:
                wires.append(_to_clipper(points[:-1]))
    if not wires:
        return []
    clipper = pyclipper.Pyclipper()
    clipper.AddPaths(wires, pyclipper.PT_SUBJECT, True)
    # Even-odd: which wire is a hole is what it lies inside, whichever way round
    # the section wrote it.
    return clipper.Execute(pyclipper.CT_UNION, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)


def offset(paths, amount, tolerance):
    """A region offset by `amount` mm (negative inward), holes and all."""
    if not paths:
        return []
    offsetter = pyclipper.PyclipperOffset()
    offsetter.ArcTolerance = max(tolerance, 1e-4) * SCALE
    offsetter.AddPaths(paths, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return offsetter.Execute(amount * SCALE)


def boolean(subject, clip, operation):
    if not subject:
        return list(clip) if operation == pyclipper.CT_UNION else []
    if not clip:
        return list(subject) if operation in (pyclipper.CT_UNION, pyclipper.CT_DIFFERENCE) else []
    clipper = pyclipper.Pyclipper()
    clipper.AddPaths(subject, pyclipper.PT_SUBJECT, True)
    clipper.AddPaths(clip, pyclipper.PT_CLIP, True)
    return clipper.Execute(operation, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def intersect_all(regions):
    """What every region covers: empty as soon as one of them is."""
    if not regions or any(not region for region in regions):
        return []
    common = regions[0]
    for region in regions[1:]:
        common = boolean(common, region, pyclipper.CT_INTERSECTION)
        if not common:
            return []
    return common


def area(paths):
    """mm2 of a region; holes count negative, as Clipper orients them."""
    return sum(pyclipper.Area(path) for path in paths) / SCALE**2


def hatch(region, spacing, angle, phase):
    """Lines `spacing` apart at `angle` degrees, clipped to the region: open polylines."""
    if not region or spacing <= 0:
        return []
    points = [point for path in region for point in path]
    radians = math.radians(angle)
    along = (math.cos(radians), math.sin(radians))
    across = (-along[1], along[0])
    projections = [(x * across[0] + y * across[1]) / SCALE for x, y in points]
    extents = [(x * along[0] + y * along[1]) / SCALE for x, y in points]
    low, high = min(projections), max(projections)
    start, end = min(extents) - 1.0, max(extents) + 1.0
    lines = []
    t = math.floor((low - phase) / spacing) * spacing + phase
    while t <= high:
        a = (across[0] * t + along[0] * start, across[1] * t + along[1] * start)
        b = (across[0] * t + along[0] * end, across[1] * t + along[1] * end)
        lines.append(_to_clipper([a, b]))
        t += spacing
    clipper = pyclipper.Pyclipper()
    clipper.AddPaths(region, pyclipper.PT_CLIP, True)
    clipper.AddPaths(lines, pyclipper.PT_SUBJECT, False)
    tree = clipper.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    return [_from_clipper(path) for path in pyclipper.OpenPathsFromPolyTree(tree)]


def rings(region, first, step, tolerance, limit=100000):
    """Concentric loops inside a region, `first` in and then every `step`: a pocket's rings, islands and all."""
    loops = []
    amount = first
    for _ in range(limit):
        found = offset(region, -amount, tolerance)
        if not found:
            break
        loops.extend(_from_clipper(path) for path in found)
        amount += step
    return loops


def layers(obj, settings, faces_at, wire_points):
    """Every path of the route, layer by layer, and each layer's height and section."""
    box = obj.bounding_box()
    h = settings.layer_height
    count = int(math.floor((box.max.Z - box.min.Z) / h + 0.5))
    heights = [box.min.Z + (index + 0.5) * h for index in range(count)]
    sections = [section(obj, z, settings.tolerance, faces_at, wire_points) for z in heights]
    w, s = settings.line_width, settings.spacing
    paths = []
    for index, (z, region) in enumerate(zip(heights, sections)):
        if not region:
            continue
        for ring in range(settings.walls):
            for loop in offset(region, -(w / 2.0 + ring * s), settings.tolerance):
                paths.append(Path(index, z, "perimeter", _from_clipper(loop), True))
        inside = offset(region, -(w / 2.0 + settings.walls * s), settings.tolerance) if settings.walls else region
        if not inside:
            continue
        above = [sections[j] if j < count else [] for j in range(index + 1, index + 1 + settings.top_layers)]
        below = [sections[j] if j >= 0 else [] for j in range(index - 1, index - 1 - settings.bottom_layers, -1)]
        covered_above = intersect_all(above) if settings.top_layers else region
        covered_below = intersect_all(below) if settings.bottom_layers else region
        skin = boolean(
            boolean(inside, covered_above, pyclipper.CT_DIFFERENCE),
            boolean(inside, covered_below, pyclipper.CT_DIFFERENCE),
            pyclipper.CT_UNION,
        )
        sparse = boolean(inside, skin, pyclipper.CT_DIFFERENCE)
        angle = 45 if index % 2 else -45
        for line in hatch(skin, s, angle, s / 2.0):
            paths.append(Path(index, z, "skin", line, False))
        if sparse and settings.infill > 0:
            step = s / settings.infill
            if settings.pattern == "concentric":
                for loop in rings(sparse, 0.0, step, settings.tolerance):
                    paths.append(Path(index, z, "infill", loop, True))
            else:
                angles = (45, -45) if settings.pattern == "grid" else (angle,)
                for each in angles:
                    for line in hatch(sparse, step * len(angles), each, step / 2.0):
                        paths.append(Path(index, z, "infill", line, False))
    return paths, heights, sections


def route(request, obj, units, helpers):
    """The program a filament printer runs, and the paths it was written from.

    'helpers' are `cam_gcode`'s own: `faces_at`, `wire_points` and `Program`.
    Returns (program, warnings, stats, paths).
    """
    settings = Settings(request)
    paths, heights, sections = layers(obj, settings, helpers.faces_at, helpers.wire_points)
    if not paths:
        raise Exception("This object has no section to print at any layer")

    feed = float(request.get("feed") or 1800.0)
    per_mm = settings.bead_area / (math.pi * (settings.filament / 2.0) ** 2)
    comments = request.get("comments")
    program = helpers.Program(units, request.get("precision") or 3, True if comments is None else bool(comments))
    program.comment("PartCAD route")
    name = request.get("shape_name")
    package = request.get("package_name")
    if name:
        program.comment("object: %s" % ("%s:%s" % (package, name) if package else name))
    program.comment(
        "machine: fff, layer %s, line %s, %d walls, %d/%d skins, infill %s%% %s"
        % (
            program.number(settings.layer_height),
            program.number(settings.line_width),
            settings.walls,
            settings.top_layers,
            settings.bottom_layers,
            ("%.1f" % (settings.infill * 100.0)).rstrip("0").rstrip("."),
            settings.pattern,
        )
    )
    program.comment("units: %s" % ("millimeters" if units == "mm" else "inches"))
    program.code("G21" if units == "mm" else "G20")
    program.code("G90")
    program.code("M83")

    extruded = 0.0
    layer = None
    for path in paths:
        if path.layer != layer:
            layer = path.layer
            # The nozzle sits on top of the bead it lays.
            program.rapid_z(path.z + settings.layer_height / 2.0)
        points = path.polyline()
        program.rapid_xy(points[0])
        first = True
        for a, b in zip(points, points[1:]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length <= 1e-9:
                continue
            e = length * per_mm
            extruded += e
            program.code(
                "G1 X%s Y%s E%.5f%s"
                % (program.number(b[0]), program.number(b[1]), e, " F%s" % program.feed(feed) if first else "")
            )
            program.cut_length += length
            first = False
    program.code("M30")

    volume = sum(path.length for path in paths) * settings.bead_area
    stats = {
        "machine": "fff",
        "operation": "print",
        "layers": len(heights),
        "paths": len(paths),
        "passes": len(heights),
        "cut_length": program.cut_length,
        "filament_length": extruded,
        # What the extruder feeds, which is what the print weighs at the
        # filament's density (docs/design/additive.md, section 9.2).
        "volume": volume,
        "solid_volume": sum(area(region) for region in sections) * settings.layer_height,
    }
    return program, [], stats, paths


def footprint(paths, width, tolerance):
    """The region these paths' beads cover, each stroked to `width`: Clipper paths."""
    offsetter = pyclipper.PyclipperOffset()
    offsetter.ArcTolerance = max(tolerance, 1e-4) * SCALE
    for path in paths:
        points = _to_clipper(path.points)
        if path.closed:
            offsetter.AddPath(points, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDLINE)
        else:
            offsetter.AddPath(points, pyclipper.JT_ROUND, pyclipper.ET_OPENROUND)
    return offsetter.Execute(width / 2.0 * SCALE)


# How close two corners of an outline may be before one is dropped, in mm:
# twice what the 'defects' check calls a sliver. An offset leaves corners a few
# nanometres apart where arcs meet, and each pair is a side face of a prism no
# thicker than the gap.
CLEAN = 0.002


def _clean(path):
    """'path' without corners closer than CLEAN to their neighbours, or in line with them."""
    return pyclipper.CleanPolygon(path, CLEAN * SCALE)


def prisms(regions, height, builder, compound):
    """Each region at its height, a face extruded by `height`, added to `compound`. Never fused."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    count = 0
    for z, region in regions:
        clipper = pyclipper.Pyclipper()
        clipper.AddPaths(region, pyclipper.PT_SUBJECT, True)
        tree = clipper.Execute2(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)

        def wire(path, bottom):
            polygon = BRepBuilderAPI_MakePolygon()
            for x, y in _from_clipper(path):
                polygon.Add(gp_Pnt(float(x), float(y), bottom))
            polygon.Close()
            return polygon.Wire()

        def walk(node, bottom):
            nonlocal count
            for child in node.Childs:
                contour = _clean(child.Contour)
                if child.IsHole or len(contour) < 3:
                    continue
                maker = BRepBuilderAPI_MakeFace(wire(contour, bottom), True)
                for hole in child.Childs:
                    hole_contour = _clean(hole.Contour)
                    if len(hole_contour) >= 3:
                        maker.Add(wire(hole_contour, bottom))
                if maker.IsDone():
                    builder.Add(compound, BRepPrimAPI_MakePrism(maker.Face(), gp_Vec(0, 0, height)).Shape())
                    count += 1
                for hole in child.Childs:
                    walk(hole, bottom)

        walk(tree, z - height / 2.0)
    return count


def deposit(paths, settings):
    """What the route lays down: per layer, its paths stroked at the line spacing, extruded by a layer.

    Stroked at the spacing rather than the width so that each bead has the
    stadium's area (`h s`) and adjacent beads tile a solid region without
    overlapping; within 2-3% of the bead model's volume (section 8 of the
    design record). A compound of prisms, in the frame the route was written in.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    by_layer = {}
    for path in paths:
        by_layer.setdefault((path.layer, path.z), []).append(path)
    regions = [
        (z, footprint(layer_paths, settings.spacing, settings.tolerance))
        for (_layer, z), layer_paths in sorted(by_layer.items())
    ]
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    if not prisms(regions, settings.layer_height, builder, compound):
        raise Exception("The route deposits nothing")
    return compound


# The script 'sdf_script' writes: the route's deposit as a distance field, bead
# by bead, for the 'sdf' part type to mesh. Self-contained -- the route travels
# inside it, compressed -- so that the file a print is materialized into is the
# whole of what it is, as a '.brep' is.
_SDF_SCRIPT = """# The print of %(name)s: the deposit of its route as a distance field.
#
# Written by PartCAD's '//builtin/cam' (cam_fff.sdf_script) from the route 'pc cam'
# writes for it, and meshed by the 'sdf' part type. Every bead is a stadium
# %(width)s mm wide and %(height)s mm tall laid along its path; the field of a
# layer is the distance in the plane to the nearest path, sampled every
# %(grid)s mm, and the bead's profile over it (docs/design/additive.md, 7.1).
import base64
import json
import math
import zlib

import numpy as np
from sdf import X, Y, box, sdf3

ROUTE = json.loads(zlib.decompress(base64.b64decode(
    %(data)r
)).decode("utf-8"))

H = ROUTE["layerHeight"]
W = ROUTE["lineWidth"]
G = ROUTE["grid"]
LAYERS = ROUTE["layers"]
_points = [xy for _z, paths in LAYERS for _closed, flat in paths for xy in zip(flat[0::2], flat[1::2])]
X0 = min(x for x, _ in _points) - W
Y0 = min(y for _, y in _points) - W
NX = int(math.ceil((max(x for x, _ in _points) + W - X0) / G)) + 2
NY = int(math.ceil((max(y for _, y in _points) + W - Y0) / G)) + 2
ZS = np.array([z for z, _paths in LAYERS])
# How far each path's distance is sampled from it, and so what a point beyond
# every path's reach is known to be at least. Never more: the mesher skips a
# region whose distance says no surface is near, and a distance that overstated
# it would drop the beads across an infill gap.
REACH = W / 2.0 + 2.0 * G
FAR = REACH


def _splat(field, a, b):
    reach = REACH
    i0 = max(int(math.floor((min(a[0], b[0]) - reach - X0) / G)), 0)
    i1 = min(int(math.ceil((max(a[0], b[0]) + reach - X0) / G)) + 1, NX)
    j0 = max(int(math.floor((min(a[1], b[1]) - reach - Y0) / G)), 0)
    j1 = min(int(math.ceil((max(a[1], b[1]) + reach - Y0) / G)) + 1, NY)
    if i0 >= i1 or j0 >= j1:
        return
    px, py = np.meshgrid(X0 + np.arange(i0, i1) * G, Y0 + np.arange(j0, j1) * G)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = np.zeros_like(px) if length2 <= 0 else np.clip(((px - a[0]) * dx + (py - a[1]) * dy) / length2, 0.0, 1.0)
    distance = np.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))
    view = field[j0:j1, i0:i1]
    np.minimum(view, distance, out=view)


FIELDS = []
for _z, paths in LAYERS:
    field = np.full((NY, NX), FAR)
    for closed, flat in paths:
        points = list(zip(flat[0::2], flat[1::2]))
        if closed:
            points.append(points[0])
        for a, b in zip(points, points[1:]):
            _splat(field, a, b)
    FIELDS.append(field)


@sdf3
def deposit():
    def f(p):
        fx = (p[:, 0] - X0) / G
        fy = (p[:, 1] - Y0) / G
        i = np.clip(np.floor(fx).astype(int), 0, NX - 2)
        j = np.clip(np.floor(fy).astype(int), 0, NY - 2)
        tx = np.clip(fx - i, 0.0, 1.0)
        ty = np.clip(fy - j, 0.0, 1.0)
        # The layer nearest each sample, found by the layers' heights: a height
        # where the design has no section has no layer, so they are not one
        # 'H' apart everywhere. Then the one below it and the one above it.
        if len(ZS) > 1:
            above = np.clip(np.searchsorted(ZS, p[:, 2]), 1, len(ZS) - 1)
            nearest = np.where(p[:, 2] - ZS[above - 1] <= ZS[above] - p[:, 2], above - 1, above)
        else:
            nearest = np.zeros(len(p), dtype=int)
        out = np.full(len(p), FAR)
        for k in (-1, 0, 1):
            index = nearest + k
            inside = (index >= 0) & (index < len(ZS))
            for layer in np.unique(index[inside]):
                chosen = inside & (index == layer)
                D = FIELDS[layer]
                ii, jj, ux, uy = i[chosen], j[chosen], tx[chosen], ty[chosen]
                d = (
                    D[jj, ii] * (1 - ux) * (1 - uy)
                    + D[jj, ii + 1] * ux * (1 - uy)
                    + D[jj + 1, ii] * (1 - ux) * uy
                    + D[jj + 1, ii + 1] * ux * uy
                )
                u = np.maximum(d - (W - H) / 2.0, 0.0)
                v = p[chosen, 2] - ZS[layer]
                out[chosen] = np.minimum(out[chosen], np.sqrt(u * u + v * v) - H / 2.0)
        return out.reshape((-1, 1))

    return f


# Within the box the route fills, which is a true distance outside it: what the
# mesher's bounds are found by. From the lowest layer to the highest, whatever
# is missing between them.
BOUNDS = box(
    (NX * G, NY * G, ZS[-1] - ZS[0] + 3 * H),
    center=(X0 + NX * G / 2.0, Y0 + NY * G / 2.0, (ZS[0] + ZS[-1]) / 2.0),
)
print_ = (deposit() & BOUNDS)%(turn)s
show_object(print_)
"""


def _turn_back(tool_axis_vector) -> str:
    """The sdf call that turns the deposit from the machine's frame back into the part's (see 'cam_gcode._orientation')."""
    if not tool_axis_vector:
        return ""
    x, y, z = (float(component) for component in tool_axis_vector)
    if abs(x) <= 1e-6 and abs(y) <= 1e-6 and z < 0:
        return ""
    if abs(z) > 0.5:
        return ".rotate(math.pi, X)"
    if abs(x) > 0.5:
        return ".rotate(%s, Y)" % ("-math.pi / 2" if x > 0 else "math.pi / 2")
    return ".rotate(%s, X)" % ("math.pi / 2" if y > 0 else "-math.pi / 2")


def sdf_script(paths, settings, name, tool_axis_vector=None) -> str:
    """The script an SDF print is: its route, and the distance field of what the route deposits."""
    import base64
    import json
    import zlib

    layers = {}
    for path in paths:
        flat = [round(coordinate, 4) for point in path.points for coordinate in point]
        layers.setdefault(round(path.z, 6), []).append([bool(path.closed), flat])
    grid = round(settings.line_width / 8.0, 6)
    data = {
        "layerHeight": settings.layer_height,
        "lineWidth": settings.line_width,
        "grid": grid,
        "layers": [[z, layer_paths] for z, layer_paths in sorted(layers.items())],
    }
    encoded = base64.b64encode(zlib.compress(json.dumps(data, separators=(",", ":")).encode("utf-8"), 9))
    return _SDF_SCRIPT % {
        "name": name or "the part",
        "width": settings.line_width,
        "height": settings.layer_height,
        "grid": grid,
        "data": encoded.decode("ascii"),
        "turn": _turn_back(tool_axis_vector),
    }
