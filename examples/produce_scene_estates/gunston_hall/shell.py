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

DATA = {'bands': [{'inner': [(0, 0), (18542, 0), (18542, 12484), (0, 12484)],
            'outline': [(-150.0, -150.0), (18692.0, -150.0), (18692.0, 12634.0), (-150.0, 12634.0)],
            'z0': 4605,
            'z1': 5065.0}],
 'blocks': [{'outline': [(0, 0), (18542, 0), (18542, 12484), (0, 12484)],
             'roof': {'across': [-330, 12814],
                      'along': [-207, 18749],
                      'axis': 'x',
                      'overhang_outline': [(-207, -330), (18749, -330), (18749, 12814), (-207, 12814)],
                      'ridge': 6242,
                      'ridge_z': 10074,
                      'slope': 0.8023069528997117,
                      'thickness': 300.0,
                      'type': 'gable'},
             'shell': 475.0}],
 'carve': [{'grow': 105.0,
            'outline': [(1259, 485), (6699, 485), (6699, 5191), (1259, 5191)],
            'z0': 965,
            'z1': 4596.0},
           {'grow': 105.0,
            'outline': [(1201, 7270), (6676, 7270), (6676, 12011), (1201, 12011)],
            'z0': 965,
            'z1': 4596.0},
           {'grow': 105.0,
            'outline': [(447, 5401), (6676, 5401), (6676, 7059), (447, 7059)],
            'z0': 965,
            'z1': 4596.0},
           {'grow': 105.0,
            'outline': [(7093, 485), (10910, 485), (10910, 12011), (7093, 12011)],
            'z0': 965,
            'z1': 4596.0},
           {'grow': 105.0,
            'outline': [(11351, 6277), (17336, 6277), (17336, 12011), (11351, 12011)],
            'z0': 965,
            'z1': 4596.0},
           {'grow': 105.0,
            'outline': [(11351, 485), (17383, 485), (17383, 5927), (11351, 5927)],
            'z0': 965,
            'z1': 4596.0},
           {'grow': 58.0,
            'outline': [(1019, 1766), (5359, 1766), (5359, 5235), (440, 5235), (440, 3997), (1019, 3997)],
            'z0': 4978,
            'z1': 6136.0},
           {'grow': 58.0,
            'outline': [(5532, 1766), (9375, 1766), (9375, 5235), (5532, 5235)],
            'z0': 4978,
            'z1': 6136.0},
           {'grow': 58.0,
            'outline': [(9525, 1766), (13403, 1766), (13403, 5235), (9525, 5235)],
            'z0': 4978,
            'z1': 6136.0},
           {'grow': 58.0,
            'outline': [(13542, 1766), (17454, 1766), (17454, 5235), (13542, 5235)],
            'z0': 4978,
            'z1': 6136.0},
           {'grow': 58.0,
            'outline': [(440, 7127), (6169, 7127), (6169, 10758), (961, 10758), (961, 8423), (440, 8423)],
            'z0': 4978,
            'z1': 6104.0},
           {'grow': 58.0,
            'outline': [(6285, 7127), (10972, 7127), (10972, 10758), (6285, 10758)],
            'z0': 4978,
            'z1': 6104.0},
           {'grow': 58.0,
            'outline': [(11099, 7127), (17454, 7127), (17454, 10758), (11099, 10758)],
            'z0': 4978,
            'z1': 6104.0},
           {'grow': 58.0,
            'outline': [(440, 5433), (18032, 5433), (18032, 6928), (440, 6928)],
            'z0': 4978,
            'z1': 7579.0}],
 'chimneys': [{'sx': 610, 'sy': 1600, 'top': 11920, 'x': 477, 'y': 3144},
              {'sx': 610, 'sy': 1600, 'top': 11920, 'x': 477, 'y': 9176},
              {'sx': 610, 'sy': 1600, 'top': 11920, 'x': 18216, 'y': 3144},
              {'sx': 610, 'sy': 1600, 'top': 11920, 'x': 18216, 'y': 9176}],
 'dormers': [{'along': [2197, 3255],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [744.1042332268371, 3590.079872204473],
              'front': 'min',
              'head': 7032,
              'sill': 5813,
              'window': (2326.0, 3126.0)},
             {'along': [2197, 3255],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [8893.920127795527, 11739.895766773163],
              'front': 'max',
              'head': 7032,
              'sill': 5813,
              'window': (2326.0, 3126.0)},
             {'along': [4520, 5578],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [744.1042332268371, 3590.079872204473],
              'front': 'min',
              'head': 7032,
              'sill': 5813,
              'window': (4649.0, 5449.0)},
             {'along': [4520, 5578],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [8893.920127795527, 11739.895766773163],
              'front': 'max',
              'head': 7032,
              'sill': 5813,
              'window': (4649.0, 5449.0)},
             {'along': [8487, 9557],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [744.1042332268371, 3590.079872204473],
              'front': 'min',
              'head': 7032,
              'sill': 5813,
              'window': (8622.0, 9422.0)},
             {'along': [8487, 9557],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [8893.920127795527, 11739.895766773163],
              'front': 'max',
              'head': 7032,
              'sill': 5813,
              'window': (8622.0, 9422.0)},
             {'along': [12501, 13570],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [744.1042332268371, 3590.079872204473],
              'front': 'min',
              'head': 7032,
              'sill': 5813,
              'window': (12635.5, 13435.5)},
             {'along': [12501, 13570],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [8893.920127795527, 11739.895766773163],
              'front': 'max',
              'head': 7032,
              'sill': 5813,
              'window': (12635.5, 13435.5)},
             {'along': [15077, 16135],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [744.1042332268371, 3590.079872204473],
              'front': 'min',
              'head': 7032,
              'sill': 5813,
              'window': (15206.0, 16006.0)},
             {'along': [15077, 16135],
              'apex': 7826,
              'bottom': 5413.0,
              'depth': [8893.920127795527, 11739.895766773163],
              'front': 'max',
              'head': 7032,
              'sill': 5813,
              'window': (15206.0, 16006.0)}],
 'openings': [{'head': 3651, 'in': 525.0, 'out': 200.0, 'p0': (2169, 0), 'p1': (3132, 0), 'sill': 1616},
              {'head': 3651, 'in': 525.0, 'out': 200.0, 'p0': (4483, 0), 'p1': (5469, 0), 'sill': 1616},
              {'head': 2886, 'in': 525.0, 'out': 200.0, 'p0': (7360, 0), 'p1': (7987, 0), 'sill': 1906},
              {'head': 3398, 'in': 525.0, 'out': 200.0, 'p0': (8404, 0), 'p1': (9599, 0), 'sill': 1167},
              {'head': 2886, 'in': 525.0, 'out': 200.0, 'p0': (10063, 0), 'p1': (10747, 0), 'sill': 1906},
              {'head': 3651, 'in': 525.0, 'out': 200.0, 'p0': (12521, 0), 'p1': (13501, 0), 'sill': 1616},
              {'head': 3651, 'in': 525.0, 'out': 200.0, 'p0': (15178, 0), 'p1': (16153, 0), 'sill': 1616},
              {'head': 520, 'in': 525.0, 'out': 200.0, 'p0': (2185, 0), 'p1': (3208, 0), 'sill': 60},
              {'head': 520, 'in': 525.0, 'out': 200.0, 'p0': (4519, 0), 'p1': (5531, 0), 'sill': 60},
              {'head': 520, 'in': 525.0, 'out': 200.0, 'p0': (12443, 0), 'p1': (13478, 0), 'sill': 60},
              {'head': 520, 'in': 525.0, 'out': 200.0, 'p0': (15076, 0), 'p1': (16100, 0), 'sill': 60},
              {'head': 3651,
               'in': 525.0,
               'out': 200.0,
               'p0': (3068, 12484),
               'p1': (2129, 12484),
               'sill': 1616},
              {'head': 3651,
               'in': 525.0,
               'out': 200.0,
               'p0': (5446, 12484),
               'p1': (4495, 12484),
               'sill': 1616},
              {'head': 2886,
               'in': 525.0,
               'out': 200.0,
               'p0': (7952, 12484),
               'p1': (7372, 12484),
               'sill': 1906},
              {'head': 3398,
               'in': 525.0,
               'out': 200.0,
               'p0': (9512, 12484),
               'p1': (8427, 12484),
               'sill': 1167},
              {'head': 2886,
               'in': 525.0,
               'out': 200.0,
               'p0': (10602, 12484),
               'p1': (9982, 12484),
               'sill': 1906},
              {'head': 3651,
               'in': 525.0,
               'out': 200.0,
               'p0': (13491, 12484),
               'p1': (12516, 12484),
               'sill': 1616},
              {'head': 3651,
               'in': 525.0,
               'out': 200.0,
               'p0': (16083, 12484),
               'p1': (15097, 12484),
               'sill': 1616},
              {'head': 3565, 'in': 525.0, 'out': 200.0, 'p0': (0, 6823), 'p1': (0, 5597), 'sill': 897},
              {'head': 7103, 'in': 525.0, 'out': 200.0, 'p0': (0, 5066), 'p1': (0, 4266), 'sill': 5810},
              {'head': 7103, 'in': 525.0, 'out': 200.0, 'p0': (0, 6614), 'p1': (0, 5814), 'sill': 5810},
              {'head': 7103, 'in': 525.0, 'out': 200.0, 'p0': (0, 8162), 'p1': (0, 7362), 'sill': 5810},
              {'head': 9378.0,
               'in': 525.0,
               'out': 200.0,
               'p0': (0, 6817.0),
               'p1': (0, 5667.0),
               'round': True,
               'sill': 8228.0},
              {'head': 1440,
               'in': 525.0,
               'out': 200.0,
               'p0': (18542, 5700),
               'p1': (18542, 6780),
               'sill': 1.0},
              {'head': 7103,
               'in': 525.0,
               'out': 200.0,
               'p0': (18542, 4266),
               'p1': (18542, 5066),
               'sill': 5810},
              {'head': 7103,
               'in': 525.0,
               'out': 200.0,
               'p0': (18542, 5814),
               'p1': (18542, 6614),
               'sill': 5810},
              {'head': 7103,
               'in': 525.0,
               'out': 200.0,
               'p0': (18542, 7362),
               'p1': (18542, 8162),
               'sill': 5810},
              {'head': 9378.0,
               'in': 525.0,
               'out': 200.0,
               'p0': (18542, 5667.0),
               'p1': (18542, 6817.0),
               'round': True,
               'sill': 8228.0}],
 'paint': {'inside': ':plaster', 'roof': ':slate', 'stone': ':sandstone', 'trim': ':trim', 'walls': ':brick'},
 'porches': [{'columns': [{'d': 350, 'top': 3400, 'x': 7023, 'y': -2750},
                          {'d': 350, 'top': 3400, 'x': 8183, 'y': -2750},
                          {'d': 350, 'top': 3400, 'x': 9761, 'y': -2750},
                          {'d': 350, 'top': 3400, 'x': 10921, 'y': -2750}],
              'floor': 1100,
              'outline': [(6687, -2984), (11235, -2984), (11235, 0), (6687, 0)],
              'roof': {'across': [6687, 11235],
                       'along': [-2984, 0],
                       'apex': 4548,
                       'axis': 'y',
                       'eave': 3571.0,
                       'entablature': 171.0,
                       'type': 'gable'}},
             {'columns': [{'d': 300.0, 'top': 4493.0, 'x': 10792.697354518827, 'y': 14274.931954898451},
                          {'d': 300.0, 'top': 4493.0, 'x': 9831.914645051325, 'y': 15338.123916870194},
                          {'d': 300.0, 'top': 4493.0, 'x': 8166.195892295567, 'y': 15335.898730159382},
                          {'d': 300.0, 'top': 4493.0, 'x': 7152.724632144715, 'y': 14223.963002298755}],
              'floor': 965,
              'outline': [(6907, 12484),
                          (11037, 12484),
                          (11037, 14328),
                          (9958, 15554),
                          (8044, 15554),
                          (6907, 14270)],
              'roof': {'apex': 4663,
                       'eave': 4063.0,
                       'eave_outline': [(6907, 12484),
                                        (11037, 12484),
                                        (11037, 14328),
                                        (9958, 15554),
                                        (8044, 15554),
                                        (6907, 14270)],
                       'taper': 40.0,
                       'type': 'hip'}}],
 'roof_from': 4605,
 'steps': [{'box': [(8045, -4560), (9668, -2984)], 'height': 1100, 'out': '-y', 'risers': 7},
           {'box': [(8044, 15554), (9784, 17283)], 'height': 965, 'out': '+y', 'risers': 6},
           {'box': [(-1300, 5300), (0, 7100)], 'height': 965, 'out': '-x', 'risers': 6},
           {'box': [(18542, 6125), (20224, 8051)], 'height': 2300, 'out': '+x', 'risers': 1}]}

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
