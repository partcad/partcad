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

DATA = {'bands': [],
 'blocks': [{'outline': [(0, 0), (20193, 0), (20193, 6330), (0, 6330)],
             'roof': {'across': [-300, 6630],
                      'along': [-300, 20493],
                      'axis': 'x',
                      'overhang_outline': [(-300, -300), (20493, -300), (20493, 6630), (-300, 6630)],
                      'ridge': 3165,
                      'ridge_z': 6700,
                      'slope': 0.7582938388625592,
                      'thickness': 300.0,
                      'type': 'gable'},
             'shell': 230.0},
            {'outline': [(5281, 6330), (12366, 6330), (12366, 27300), (5281, 27300)],
             'paint': ':brick',
             'roof': {'across': [4981, 12666],
                      'along': [6030, 27600],
                      'axis': 'y',
                      'overhang_outline': [(4981, 6030), (12666, 6030), (12666, 27600), (4981, 27600)],
                      'ridge': 8824,
                      'ridge_z': 8100,
                      'slope': 0.4403048264182896,
                      'thickness': 300.0,
                      'type': 'gable'},
             'shell': 300.0},
            {'outline': [(0, 6330), (5281, 6330), (5281, 9923), (0, 9923)],
             'roof': {'overhang': 150.0,
                      'reach': [-1, 6329, 5282, 9924],
                      'thickness': 250.0,
                      'top': 3500,
                      'type': 'flat'},
             'shell': 230.0},
            {'outline': [(12366, 6330), (20193, 6330), (20193, 10000), (12366, 10000)],
             'roof': {'overhang': 150.0,
                      'reach': [12365, 6329, 20194, 10001],
                      'thickness': 250.0,
                      'top': 3500,
                      'type': 'flat'},
             'shell': 230.0},
            {'outline': [(20151, 6164), (22685, 6164), (22685, 9969), (20151, 9969)],
             'roof': {'overhang': 150.0,
                      'reach': [20150, 6163, 22686, 9970],
                      'thickness': 250.0,
                      'top': 3300,
                      'type': 'flat'},
             'shell': 230.0},
            {'outline': [(-1781, 9847), (5220, 9847), (5220, 11674), (-1781, 11674)],
             'roof': {'overhang': 150.0,
                      'reach': [-1782, 9846, 5221, 11675],
                      'thickness': 250.0,
                      'top': 3000,
                      'type': 'flat'},
             'shell': 230.0},
            {'outline': [(5281, 19322),
                         (4459, 19017),
                         (3934, 18371),
                         (3934, 16468),
                         (4459, 15859),
                         (5281, 15524)],
             'roof': {'eave_outline': [(5342.2978781681395, 19512.37481485765),
                                       (4432.417812623855, 19215.22559702092),
                                       (3810.5929035185213, 18528.387065980693),
                                       (3812.2869780629085, 16309.299211435668),
                                       (4432.152950956198, 15660.810101272442),
                                       (5341.887739595788, 15333.493613842173)],
                      'eave_z': 3000.0,
                      'overhang_outline': [(5342.2978781681395, 19512.37481485765),
                                           (4432.417812623855, 19215.22559702092),
                                           (3810.5929035185213, 18528.387065980693),
                                           (3812.2869780629085, 16309.299211435668),
                                           (4432.152950956198, 15660.810101272442),
                                           (5341.887739595788, 15333.493613842173)],
                      'ridge_z': 3600,
                      'slope': 0.89086859688196,
                      'thickness': 250.0,
                      'type': 'hip'},
             'shell': 230.0},
            {'outline': [(12366, 21757), (14276, 21757), (14276, 24245), (12366, 24245)],
             'roof': {'overhang': 150.0,
                      'reach': [12365, 21756, 14277, 24246],
                      'thickness': 250.0,
                      'top': 3300,
                      'type': 'flat'},
             'shell': 230.0},
            {'outline': [(12366, 13036), (14276, 13036), (14276, 15387), (12366, 15387)],
             'roof': {'overhang': 150.0,
                      'reach': [12365, 13035, 14277, 15388],
                      'thickness': 250.0,
                      'top': 3300,
                      'type': 'flat'},
             'shell': 230.0}],
 'carve': [{'grow': 42.0,
            'outline': [(199.0, 282.0), (5760.0, 282.0), (5760.0, 6087.0), (199.0, 6087.0)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(5845.0, 282.0), (8918.0, 282.0), (8918.0, 6087.0), (5845.0, 6087.0)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(9019.0, 282.0), (11209.0, 282.0), (11209.0, 6087.0), (9019.0, 6087.0)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(11316, 266), (15760, 266), (15760, 4467), (11316, 4467)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(11332.0, 4574.0), (14215.0, 4574.0), (14215.0, 6087.0), (11332.0, 6087.0)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(15852, 266), (19931, 266), (19931, 6103), (15852, 6103)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(214.0, 6412.0), (5199.0, 6412.0), (5199.0, 9778.0), (214.0, 9778.0)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 42.0,
            'outline': [(5701.0, 6195.0), (12015.0, 6195.0), (12015.0, 13195.0), (5701.0, 13195.0)],
            'z0': 300,
            'z1': 2800.0},
           {'grow': 42.0,
            'outline': [(12290, 6332), (15334, 6332), (15334, 9794), (12290, 9794)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 42.0,
            'outline': [(15418.0, 6412.0), (19984.0, 6412.0), (19984, 9794), (15418, 9794)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 42.0,
            'outline': [(20233.0, 6246.0), (22603.0, 6246.0), (22603.0, 9887.0), (20233.0, 9887.0)],
            'z0': 300,
            'z1': 3050.0},
           {'grow': 42.0,
            'outline': [(-1699.0, 9929.0), (5138.0, 9929.0), (5138.0, 11592.0), (-1699.0, 11592.0)],
            'z0': 300,
            'z1': 2750.0},
           {'grow': 42.0,
            'outline': [(5601.0, 22937.0), (12023.0, 22937.0), (12023.0, 27076.0), (5601.0, 27076.0)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 42.0,
            'outline': [(5635.5, 20756.5), (10116.5, 20756.5), (10116.5, 22817.5), (5635.5, 22817.5)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 42.0,
            'outline': [(5632.0, 13280.0), (10052.0, 13280.0), (10052.0, 20607.0), (5632.0, 20607.0)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 42.0,
            'outline': [(10201.5, 13283.5), (11988.5, 13283.5), (11988.5, 22817.5), (10201.5, 22817.5)],
            'z0': 300,
            'z1': 3051.0},
           {'grow': 45.0,
            'outline': [(213, 365), (5555, 365), (5555, 6164), (213, 6164)],
            'z0': 3000,
            'z1': 4091.0},
           {'grow': 45.0,
            'outline': [(5647, 365), (8911, 365), (8911, 5890), (5647, 5890)],
            'z0': 3000,
            'z1': 4242.0},
           {'grow': 45.0,
            'outline': [(9048.5, 2039.5), (10136.5, 2039.5), (10136.5, 5213.5), (9048.5, 5213.5)],
            'z0': 3000,
            'z1': 4812.0},
           {'grow': 45.0,
            'outline': [(10227.5, 410.5), (13119.5, 410.5), (13119.5, 4307.5), (10227.5, 4307.5)],
            'z0': 3000,
            'z1': 4277.0},
           {'grow': 45.0,
            'outline': [(13257, 365), (16430, 365), (16430, 4170), (13257, 4170)],
            'z0': 3000,
            'z1': 4242.0},
           {'grow': 45.0,
            'outline': [(16521, 365), (19961, 365), (19961, 5981), (16521, 5981)],
            'z0': 3000,
            'z1': 4230.0},
           {'grow': 45.0,
            'outline': [(10227.5, 4466.5), (16384.5, 4466.5), (16384.5, 6118.5), (10227.5, 6118.5)],
            'z0': 3000,
            'z1': 4126.0},
           {'grow': 45.0,
            'outline': [(5366.0, 23788.5), (9139.5, 23788.5), (9139.5, 26954.5), (5366.0, 26954.5)],
            'z0': 3650,
            'z1': 6257.0},
           {'grow': 45.0,
            'outline': [(9230.5, 25691.5), (11947.5, 25691.5), (11947.5, 27046.5), (9230.5, 27046.5)],
            'z0': 3650,
            'z1': 6351.0},
           {'grow': 45.0,
            'outline': [(5366.0, 20250.5), (10136.5, 20250.5), (10136.5, 23606.5), (5366.0, 23606.5)],
            'z0': 3650,
            'z1': 6257.0},
           {'grow': 45.0,
            'outline': [(5366.0, 15090.5), (10136.5, 15090.5), (10136.5, 18987.5), (5366.0, 18987.5)],
            'z0': 3650,
            'z1': 6257.0},
           {'grow': 45.0,
            'outline': [(5366.0, 11194.5), (10136.5, 11194.5), (10136.5, 14816.5), (5366.0, 14816.5)],
            'z0': 3650,
            'z1': 6257.0},
           {'grow': 45.0,
            'outline': [(5366.0, 6415.0), (10136.5, 6415.0), (10136.5, 10106.5), (5366.0, 10106.5)],
            'z0': 3650,
            'z1': 6257.0},
           {'grow': 45.0,
            'outline': [(10227.5, 6415.0), (11955.5, 6415.0), (11955.5, 25600.5), (10227.5, 25600.5)],
            'z0': 3650,
            'z1': 6351.0}],
 'chimneys': [{'sx': 430, 'sy': 821, 'top': 8370, 'x': 215.0, 'y': 3122.5},
              {'sx': 423, 'sy': 821, 'top': 8370, 'x': 19981.5, 'y': 3122.5},
              {'sx': 826, 'sy': 600, 'top': 8600, 'x': 5418.0, 'y': 6500.0},
              {'sx': 772, 'sy': 600, 'top': 8600, 'x': 12484.0, 'y': 6500.0},
              {'sx': 660, 'sy': 600, 'top': 9620, 'x': 8824.0, 'y': 7200.0},
              {'sx': 600, 'sy': 600, 'top': 8700, 'x': 8824.0, 'y': 10000.0},
              {'sx': 600, 'sy': 600, 'top': 8700, 'x': 8824.0, 'y': 14900.0},
              {'sx': 600, 'sy': 600, 'top': 8700, 'x': 8824.0, 'y': 16400.0},
              {'sx': 600, 'sy': 600, 'top': 8700, 'x': 8824.0, 'y': 20300.0},
              {'sx': 600, 'sy': 600, 'top': 8700, 'x': 8824.0, 'y': 26800.0}],
 'dormers': [],
 'openings': [{'head': 2326, 'in': 280.0, 'out': 200.0, 'p0': (1466, 0), 'p1': (2416, 0), 'sill': 745},
              {'head': 2326, 'in': 280.0, 'out': 200.0, 'p0': (4631, 0), 'p1': (5581, 0), 'sill': 745},
              {'head': 2326, 'in': 280.0, 'out': 200.0, 'p0': (7881, 0), 'p1': (8831, 0), 'sill': 745},
              {'head': 2400, 'in': 280.0, 'out': 200.0, 'p0': (9520, 0), 'p1': (10509, 0), 'sill': 300},
              {'head': 2326, 'in': 280.0, 'out': 200.0, 'p0': (11305, 0), 'p1': (12255, 0), 'sill': 745},
              {'head': 2326, 'in': 280.0, 'out': 200.0, 'p0': (14464, 0), 'p1': (15414, 0), 'sill': 745},
              {'head': 2326, 'in': 280.0, 'out': 200.0, 'p0': (17797, 0), 'p1': (18747, 0), 'sill': 745},
              {'head': 4370, 'in': 280.0, 'out': 200.0, 'p0': (1417, 0), 'p1': (2267, 0), 'sill': 3420},
              {'head': 4370, 'in': 280.0, 'out': 200.0, 'p0': (4674, 0), 'p1': (5524, 0), 'sill': 3420},
              {'head': 4370, 'in': 280.0, 'out': 200.0, 'p0': (8015, 0), 'p1': (8865, 0), 'sill': 3420},
              {'head': 4370, 'in': 280.0, 'out': 200.0, 'p0': (11477, 0), 'p1': (12327, 0), 'sill': 3420},
              {'head': 4370, 'in': 280.0, 'out': 200.0, 'p0': (14605, 0), 'p1': (15455, 0), 'sill': 3420},
              {'head': 4370, 'in': 280.0, 'out': 200.0, 'p0': (17908, 0), 'p1': (18758, 0), 'sill': 3420},
              {'head': 2160, 'in': 280.0, 'out': 200.0, 'p0': (0, 2000), 'p1': (0, 1285), 'sill': 681},
              {'head': 2160, 'in': 280.0, 'out': 200.0, 'p0': (0, 4960), 'p1': (0, 4190), 'sill': 681},
              {'head': 4159, 'in': 280.0, 'out': 200.0, 'p0': (0, 2060), 'p1': (0, 1350), 'sill': 3249},
              {'head': 4159, 'in': 280.0, 'out': 200.0, 'p0': (0, 4920), 'p1': (0, 4205), 'sill': 3249},
              {'head': 2160,
               'in': 280.0,
               'out': 200.0,
               'p0': (20193, 1285),
               'p1': (20193, 2000),
               'sill': 681},
              {'head': 2160,
               'in': 280.0,
               'out': 200.0,
               'p0': (20193, 4190),
               'p1': (20193, 4960),
               'sill': 681},
              {'head': 4159,
               'in': 280.0,
               'out': 200.0,
               'p0': (20193, 1350),
               'p1': (20193, 2060),
               'sill': 3249},
              {'head': 4159,
               'in': 280.0,
               'out': 200.0,
               'p0': (20193, 4205),
               'p1': (20193, 4920),
               'sill': 3249},
              {'head': 3160,
               'in': 350.0,
               'out': 200.0,
               'p0': (12366, 10648),
               'p1': (12366, 12152),
               'sill': 1058},
              {'head': 3160,
               'in': 350.0,
               'out': 200.0,
               'p0': (12366, 17664),
               'p1': (12366, 18665),
               'sill': 1058},
              {'head': 3160,
               'in': 350.0,
               'out': 200.0,
               'p0': (12366, 24432),
               'p1': (12366, 25312),
               'sill': 1058},
              {'head': 6160,
               'in': 350.0,
               'out': 200.0,
               'p0': (12366, 11776),
               'p1': (12366, 12649),
               'sill': 4070},
              {'head': 6160,
               'in': 350.0,
               'out': 200.0,
               'p0': (12366, 17664),
               'p1': (12366, 18545),
               'sill': 4070},
              {'head': 6160,
               'in': 350.0,
               'out': 200.0,
               'p0': (12366, 24560),
               'p1': (12366, 25312),
               'sill': 4070}],
 'paint': {'inside': ':plaster',
           'roof': ':shingle',
           'stone': ':fieldstone',
           'trim': ':trim',
           'walls': ':clapboard'},
 'porches': [{'columns': [{'d': 150, 'top': 2570, 'x': 7214, 'y': -1700},
                          {'d': 150, 'top': 2570, 'x': 9162, 'y': -1700},
                          {'d': 150, 'top': 2570, 'x': 11103, 'y': -1700},
                          {'d': 150, 'top': 2570, 'x': 13051, 'y': -1700}],
              'floor': 185,
              'outline': [(7131, -1788), (13135, -1788), (13135, 0), (7131, 0)],
              'roof': {'eave': 2741.0, 'entablature': 171.0, 'thickness': 200.0, 'type': 'flat'}},
             {'columns': [{'d': 300.0, 'top': 2930.0, 'x': 1353.7819559209297, 'y': 20171.88745766698},
                          {'d': 300.0, 'top': 2930.0, 'x': 5160.21804407907, 'y': 20171.88745766698},
                          {'d': 300.0, 'top': 2930.0, 'x': 5160.21804407907, 'y': 27070.11254233302},
                          {'d': 300.0, 'top': 2930.0, 'x': 1353.7819559209297, 'y': 27070.11254233302}],
              'floor': 300,
              'outline': [(1233, 19953), (5281, 19953), (5281, 27289), (1233, 27289)],
              'roof': {'eave': 3100, 'entablature': 171.0, 'thickness': 200.0, 'type': 'flat'}}],
 'roof_from': 3000,
 'steps': [{'box': [(9581, -2800), (10852, -1788)], 'height': 185, 'out': '-y', 'risers': 2},
           {'box': [(61, -1446), (20402, -350)], 'height': 50, 'out': '-y', 'risers': 1}]}

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
