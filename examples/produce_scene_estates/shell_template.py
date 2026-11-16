#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The outside of a building, as one solid: what it looks like from outside, and
# nothing of its inside. Written by '../make_estate.py' from 'estate.json', with
# the building's measurements in DATA below; run that again rather than edit it.
#
# Everything solid - the walls up to the roof, the roof, the chimneys, the
# dormers, the porches, the steps - is put together and then the house's air is
# taken out of it: the footprint, inset by the thickness the shell keeps, up to
# the underside of the roof. Whatever stands inside - floors, the rooms' walls,
# furniture - stands in that air, so nothing inside the house shares space with
# its shell. The openings are cut through the shell last, and each face is
# painted by where it is: the roof's slope, a porch, the steps, a reveal.
#
# Millimetres, in the house's own frame: X along its front, Y from the front
# to the back, Z up from the ground line.

import math

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Kind,
    Location,
    Plane,
    Polygon,
    Pos,
    Rot,
    extrude,
    offset,
)

DATA = "@DATA@"

BIG = 1.0e6
EPS = 1.0


def prism(points, z0, z1):
    """The polygon (x, y) from z0 up to z1."""
    face = Polygon(*[(x, y) for x, y in points], align=None)
    return extrude(face.moved(Location((0, 0, z0))), amount=z1 - z0)


def inset(points, amount, z0, z1):
    face = Polygon(*[(x, y) for x, y in points], align=None)
    face = offset(face, amount=-amount, kind=Kind.INTERSECTION)
    return extrude(face.moved(Location((0, 0, z0))), amount=z1 - z0)


def profile_along(axis, profile, low, high):
    """A profile drawn across 'axis' ((across, z) points), extruded along it from 'low' to 'high'."""
    if axis == "x":
        plane = Plane(origin=(low, 0, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
    else:
        # Extruded along +Y, its local Y up: its local X is then -X.
        plane = Plane(origin=(0, low, 0), x_dir=(-1, 0, 0), z_dir=(0, 1, 0))
        profile = [(-u, z) for u, z in profile]
    face = plane * Polygon(*profile, align=None)
    # Along the axis whichever way the profile winds, which is what decides its face's normal.
    return extrude(face, amount=high - low, dir=(1, 0, 0) if axis == "x" else (0, 1, 0))


# -- Roofs: each is the region under its outer surface, and that region shifted down --------------------------


def gable_height(roof, u):
    """The outer surface's height at 'u' across the ridge."""
    return roof["ridge_z"] - roof["slope"] * abs(u - roof["ridge"])


def under(roof, shift):
    """Everything under the roof's outer surface, 'shift' mm lower, within the roof's own reach."""
    kind = roof["type"]
    if kind == "flat":
        x0, y0, x1, y1 = roof["reach"]
        return Pos(x0, y0, -BIG) * Box(x1 - x0, y1 - y0, BIG + roof["top"] - shift, align=Align.MIN)
    if kind == "gable":
        a0, a1 = roof["along"]
        c0, c1 = roof["across"]
        far = max(roof["ridge"] - c0, c1 - roof["ridge"]) + 2000.0
        lo, hi = roof["ridge"] - far, roof["ridge"] + far
        profile = [
            (lo, -BIG),
            (hi, -BIG),
            (hi, gable_height(roof, hi) - shift),
            (roof["ridge"], roof["ridge_z"] - shift),
            (lo, gable_height(roof, lo) - shift),
        ]
        return profile_along(roof["axis"], profile, a0, a1)
    if kind == "hip":
        # A pyramid of the eave outline to a ridge: the outline lifted, every side sloping in at one pitch.
        eave = Polygon(*roof["eave_outline"], align=None).moved(Location((0, 0, roof["eave_z"] - shift)))
        rise = roof["ridge_z"] - roof["eave_z"]
        taper = math.degrees(math.atan(1.0 / roof["slope"]))
        top = extrude(eave, amount=rise, taper=90.0 - taper)
        below = prism(roof["eave_outline"], -BIG, roof["eave_z"] - shift)
        return top + below
    raise ValueError("a roof is flat, gable or hip, not %s" % kind)


def block_solids(block):
    """(massive, air) of one block: everything it is made of, and the air its rooms stand in."""
    roof = block["roof"]
    thick = roof["thickness"]
    if roof["type"] == "flat":
        massive = prism(block["outline"], 0.0, roof["top"])
        if roof.get("parapet", 0.0) > 0.0:
            ring = prism(block["outline"], roof["top"] - 1.0, roof["top"] + roof["parapet"]) - inset(
                block["outline"], block["shell"], roof["top"] - 2.0, roof["top"] + roof["parapet"] + 1.0
            )
            massive = massive + ring
        overhang = roof.get("overhang", 0.0)
        if overhang > 0.0:
            slab = inset(block["outline"], -overhang, roof["top"] - thick, roof["top"])
            massive = massive + slab
    else:
        massive = prism(block["outline"], 0.0, roof["ridge_z"] + 1.0) & under(roof, 0.0)
        reach = roof["overhang_outline"]
        slab = (prism(reach, 0.0, roof["ridge_z"] + 1.0) & under(roof, 0.0)) - under(roof, thick)
        massive = massive + slab
    air = inset(block["outline"], block["shell"], -1.0, BIG) & under(roof, thick)
    return massive, air


# -- The rest of the outside -----------------------------------------------------------------------------------


def chimney(spec):
    return Pos(spec["x"], spec["y"], spec.get("bottom", 0.0)) * Box(
        spec["sx"], spec["sy"], spec["top"] - spec.get("bottom", 0.0), align=(Align.CENTER, Align.CENTER, Align.MIN)
    )


def dormer(spec):
    """A dormer: its cheeks and front up to the head, a gable roof over it to the apex, its window a recess."""
    x0, x1 = spec["along"]
    y0, y1 = spec["depth"]
    body = Pos(x0, y0, spec["bottom"]) * Box(x1 - x0, y1 - y0, spec["head"] + 150.0 - spec["bottom"], align=Align.MIN)
    mid, half = (x0 + x1) / 2.0, (x1 - x0) / 2.0 + 60.0
    low, high = (y0 - 60.0, y1) if spec["front"] == "min" else (y0, y1 + 60.0)
    roof = profile_along(
        "y", [(mid - half, spec["head"] + 100.0), (mid + half, spec["head"] + 100.0), (mid, spec["apex"])], low, high
    )
    face_y = y0 if spec["front"] == "min" else y1
    recess = Pos(spec["window"][0], face_y - 100.0, spec["sill"]) * Box(
        spec["window"][1] - spec["window"][0], 200.0, spec["head"] - spec["sill"], align=Align.MIN
    )
    return body + roof - recess


def porch(spec):
    floor = spec["floor"]
    # On the ground, a plinth up to its floor; raised, a floor on what holds it up.
    solid = prism(spec["outline"], floor - spec["slab"] if spec.get("slab") else 0.0, floor)
    for column in spec.get("columns", []):
        solid = solid + Pos(column["x"], column["y"], floor - 1.0) * Cylinder(
            column["d"] / 2.0, column["top"] - floor + 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN)
        )
    roof = spec.get("roof")
    if roof:
        beam = roof["eave"] - roof.get("entablature", 170.0)
        solid = solid + prism(spec["outline"], beam, roof["eave"])
        if roof["type"] == "gable":
            along, across = roof["along"], roof["across"]
            mid = (across[0] + across[1]) / 2.0
            solid = solid + profile_along(
                roof["axis"],
                [(across[0] - 100.0, roof["eave"]), (across[1] + 100.0, roof["eave"]), (mid, roof["apex"])],
                along[0] - 100.0,
                along[1],
            )
        elif roof["type"] == "hip":
            eave = Polygon(*roof["eave_outline"], align=None).moved(Location((0, 0, roof["eave"])))
            rise = roof["apex"] - roof["eave"]
            solid = solid + extrude(eave, amount=rise, taper=roof.get("taper", 45.0))
        elif roof["type"] == "flat":
            solid = solid + prism(spec["outline"], roof["eave"], roof["eave"] + roof.get("thickness", 200.0))
    return solid


def steps(spec):
    """A flight: 'risers' treads, each lower than the one before, going away from the house along 'out'."""
    (x0, y0), (x1, y1) = spec["box"]
    count = max(1, int(spec["risers"]))
    out = spec["out"]
    solid = None
    for i in range(count):
        top = spec["height"] * (count - i) / count
        if out in ("-y", "+y"):
            run = (y1 - y0) / count
            a, b = (y1 - (i + 1) * run, y1 - i * run) if out == "-y" else (y0 + i * run, y0 + (i + 1) * run)
            tread = Pos(x0, min(a, b), 0) * Box(x1 - x0, abs(b - a) + (0 if i == count - 1 else 1.0), top, align=Align.MIN)
        else:
            run = (x1 - x0) / count
            a, b = (x1 - (i + 1) * run, x1 - i * run) if out == "-x" else (x0 + i * run, x0 + (i + 1) * run)
            tread = Pos(min(a, b), y0, 0) * Box(abs(b - a) + (0 if i == count - 1 else 1.0), y1 - y0, top, align=Align.MIN)
        solid = tread if solid is None else solid + tread
    return solid


def opening(spec):
    """A box through the wall it is in, 'p0' to 'p1' along the wall's outer face, the inside on the left."""
    (ax, ay), (bx, by) = spec["p0"], spec["p1"]
    length = math.hypot(bx - ax, by - ay)
    angle = math.degrees(math.atan2(by - ay, bx - ax))
    out, into = spec["out"], spec["in"]
    if spec.get("round"):
        radius = (spec["head"] - spec["sill"]) / 2.0
        return (
            Pos(ax, ay, spec["sill"] + radius)
            * Rot(0, 0, angle)
            * Pos(length / 2.0, (into - out) / 2.0, 0)
            * Rot(-90, 0, 0)
            * Cylinder(radius, out + into)
        )
    return Pos(ax, ay, spec["sill"]) * Rot(0, 0, angle) * Pos(0, -out, 0) * Box(
        length, out + into, spec["head"] - spec["sill"], align=Align.MIN
    )


def build():
    massive, air = None, None
    for block in DATA["blocks"]:
        m, a = block_solids(block)
        massive = m if massive is None else massive + m
        air = a if air is None else air + a
    for spec in DATA.get("chimneys", []):
        massive = massive + chimney(spec)
    for spec in DATA.get("dormers", []):
        massive = massive + dormer(spec)
    for spec in DATA.get("porches", []):
        massive = massive + porch(spec)
    for spec in DATA.get("steps", []):
        massive = massive + steps(spec)
    for spec in DATA.get("bands", []):
        massive = massive + prism(spec["outline"], spec["z0"], spec["z1"])
    shell = massive - air
    for spec in DATA.get("carve", []):
        face = offset(Polygon(*[tuple(p) for p in spec["outline"]], align=None), amount=spec["grow"], kind=Kind.INTERSECTION)
        shell = shell - extrude(face.moved(Location((0, 0, spec["z0"]))), amount=spec["z1"] - spec["z0"])
    cuts = [opening(spec) for spec in DATA.get("openings", [])]
    for cut in cuts:
        shell = shell - cut
    return shell


# -- Paint -----------------------------------------------------------------------------------------------------


def _inside(points, x, y):
    found = False
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            found = not found
    return found


def colour_of(box, normal):
    """What a face is painted, by the region the whole of it is in: 'box' is its bounding box."""
    (x0, y0, z0), (x1, y1, z1) = box
    paint = DATA["paint"]

    def within(lx, ly, lz, hx, hy, hz):
        return lx - EPS <= x0 and x1 <= hx + EPS and ly - EPS <= y0 and y1 <= hy + EPS and lz - EPS <= z0 and z1 <= hz + EPS

    for spec in DATA.get("steps", []):
        (sx0, sy0), (sx1, sy1) = spec["box"]
        if within(sx0, sy0, -BIG, sx1, sy1, spec["height"]):
            return paint["stone"]
    for spec in DATA.get("openings", []):
        (ax, ay), (bx, by) = spec["p0"], spec["p1"]
        length = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / length, (by - ay) / length
        corners = [(x, y) for x in (x0, x1) for y in (y0, y1)]
        us = [(x - ax) * ux + (y - ay) * uy for x, y in corners]
        vs = [-(x - ax) * uy + (y - ay) * ux for x, y in corners]
        if (
            min(us) >= -EPS
            and max(us) <= length + EPS
            and min(vs) >= -spec["out"] - EPS
            and max(vs) <= spec["in"] + EPS
            and z0 >= spec["sill"] - EPS
            and z1 <= spec["head"] + EPS
        ):
            return paint["trim"]
    for spec in DATA.get("porches", []):
        px = [p[0] for p in spec["outline"]] + [c["x"] for c in spec.get("columns", [])]
        py = [p[1] for p in spec["outline"]] + [c["y"] for c in spec.get("columns", [])]
        reach = max([c["d"] / 2.0 for c in spec.get("columns", [])] + [0.0]) + 100.0
        if within(min(px) - reach, min(py) - reach, -BIG, max(px) + reach, max(py) + reach, BIG):
            if z0 >= spec["floor"] - EPS:
                if normal[2] > 0.3 and abs(z1 - spec["floor"]) <= EPS:
                    return paint["stone"]
                roof = spec.get("roof") or {}
                if normal[2] > 0.3 and z0 > roof.get("eave", BIG) - EPS:
                    return paint["roof"]
                return paint["trim"]
            return paint["walls"]
    for spec in DATA.get("chimneys", []):
        if within(spec["x"] - spec["sx"] / 2.0, spec["y"] - spec["sy"] / 2.0, -BIG, spec["x"] + spec["sx"] / 2.0, spec["y"] + spec["sy"] / 2.0, BIG):
            return paint["walls"]
    for spec in DATA.get("bands", []):
        if z0 >= spec["z0"] - EPS and z1 <= spec["z1"] + EPS:
            return paint["trim"]
    for spec in DATA.get("dormers", []):
        (dx0, dx1), (dy0, dy1) = spec["along"], spec["depth"]
        if within(dx0 - 70.0, dy0 - 70.0, spec["bottom"] - EPS, dx1 + 70.0, dy1 + 70.0, BIG):
            return paint["roof"] if normal[2] > 0.3 else paint["trim"]
    if normal[2] > 0.2 and z0 >= DATA["roof_from"] - 400.0:
        return paint["roof"]
    if normal[2] < -0.2:
        return paint["inside"]
    for block in DATA["blocks"]:
        if block.get("paint"):
            xs, ys = [p[0] for p in block["outline"]], [p[1] for p in block["outline"]]
            if within(min(xs), min(ys), -BIG, max(xs), max(ys), BIG):
                return block["paint"]
    return paint["walls"]


def painted(shape):
    if "set_cmf" not in globals():
        return shape
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.gp import gp_Pnt, gp_Vec

    for face in shape.faces():
        u0, u1, v0, v1 = face._uv_bounds()
        props = BRepGProp_Face(face.wrapped)
        point, normal = gp_Pnt(), gp_Vec()
        props.Normal((u0 + u1) / 2.0, (v0 + v1) / 2.0, point, normal)
        length = normal.Magnitude() or 1.0
        b = face.bounding_box()
        box = ((b.min.X, b.min.Y, b.min.Z), (b.max.X, b.max.Y, b.max.Z))
        colour = colour_of(box, (0, 0, normal.Z() / length))
        set_cmf(face.wrapped, color=colour)  # noqa: F821 - handed in by the script runner
    return shape


result = painted(build())

if "show_object" in locals():
    show_object(result, name="shell")  # noqa: F821
