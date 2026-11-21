#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Writes the package of a historic estate from what was measured of it, 'estate.json'.

    python3 make_estate.py site <estate dir>        # the landscape: fetched, graded, written by gen-landscape
    python3 make_estate.py package <estate dir>     # the house: its shell, its floors, its rooms, its furniture

'estate.json' is what a person read off the Historic American Buildings Survey's
measured drawings of the house (public domain), with where the house is: the
outline and height of each block, its roof, chimneys, dormers, porches, steps
and every door and window of its outside, and each storey's rooms as the
outlines of their floors, with their doors. Everything below is worked out from
it, and nothing is drawn by hand, so that a correction to a measurement is one
edit and one run.

What is written, and why it is the way it is:

  * the ground (the 'landscape' package, by the gen-landscape skill's
    landscape.py): the place's elevation and its OpenStreetMap features, less the
    house's own outline, with a level pad graded where the house stands - so
    that the house stands on the ground a millimetre above it, and nothing of
    the one is inside the other, on ground that is not level;
  * the house's outside ('shell', from shell_template.py): one solid, every face
    painted, with the house's air taken out of it - the footprint inset by the
    shell's thickness, up to the underside of the roof;
  * its inside: a floor per storey, its plan - one sketch of the outlines of
    every room on its level - and the walls of every room, a 'walls' scene on
    the room's outline in that plan, standing outside it, in that air. The
    shell keeps what is left of each outer wall once the rooms' walls stand
    against it, and each storey's rooms' walls are as thick as its thinnest
    partition allows. Under a roof, a room's walls stop below it, as a knee
    wall does;
  * its furniture: models of NVIDIA's ArchVis and SimReady collections, each a
    'basic' part of its measured size - what is collided with, weighed and
    exported - drawn as the model ('visual:'), set against the walls of the
    rooms by what each room is for, clear of its doors and under its roof.

So the house, its rooms, its furniture and the ground share no space, and a
scene of all of them is one an interference check passes.

The scenes nest, each one a picture in the package's README: 'estate' (the
landscape and the house) holds 'house' (the shell and the interior), which holds
a scene per storey, each with a view of it from above beside it; each storey's
plan is a drawing. A storey with more furniture than one picture has memory for
is two scenes - its main block, and the rest - which the storey's scene places,
and each is pictured. What each picture is, and where it goes, is a 'render:' on
the object pictured, and 'render_images.sh' renders them, one at a time.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANDSCAPE = os.path.join(HERE, "..", "..", "ai-agents", "common", "skills", "gen-landscape", "landscape.py")
FURNITURE = os.path.join(HERE, "furniture.json")

# What a surface span of the ground is, and how many of them the graded pad
# reaches past the house: a cubic B-spline is flat wherever the 4 x 4 poles
# under it are equal, so two spans past the outline is flat at the outline.
CELLS = 64
PAD_SPANS = 2.5

SLAB = 200.0  # mm, a floor's thickness under its level
MIN_WALL = 40.0  # mm, the thinnest a room's walls are
GAP = 1.0  # mm between whatever would otherwise touch
ROOF_THICKNESS = 300.0  # mm, measured vertically
WALL_PLASTER = "plaster"

# -- Plane geometry -------------------------------------------------------------------------------------------


def segments(points):
    return list(zip(points, points[1:] + points[:1]))


def area(points):
    return 0.5 * sum(ax * by - bx * ay for (ax, ay), (bx, by) in segments(points))


def ccw(points):
    return list(points) if area(points) > 0 else list(reversed(points))


def centroid(points):
    a = area(points)
    cx = sum((ax + bx) * (ax * by - bx * ay) for (ax, ay), (bx, by) in segments(points)) / (6.0 * a)
    cy = sum((ay + by) * (ax * by - bx * ay) for (ax, ay), (bx, by) in segments(points)) / (6.0 * a)
    return cx, cy


def inside(points, x, y):
    found = False
    for (ax, ay), (bx, by) in segments(points):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            found = not found
    return found


def to_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if not length2 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def gap(p, q):
    """The least distance between two polygons' outlines (0 where they cross)."""
    return min(
        min(to_segment(a, *s) for a in p for s in segments(q)),
        min(to_segment(a, *s) for a in q for s in segments(p)),
    )


def crosses(a, b, c, d):
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def rect_corners(cx, cy, w, d, angle):
    c, s = math.cos(angle), math.sin(angle)
    return [(cx + c * u - s * v, cy + s * u + c * v) for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


def rect_in(points, corners, margin):
    """Whether a rectangle is inside a polygon, 'margin' clear of its outline."""
    if not all(inside(points, x, y) for x, y in corners):
        return False
    for a, b in segments(corners):
        for c, d in segments(points):
            if crosses(a, b, c, d):
                return False
    return gap(points, corners) >= margin


def rects_apart(p, q, margin):
    if any(inside(q, *v) for v in p) or any(inside(p, *v) for v in q):
        return False
    for a, b in segments(p):
        for c, d in segments(q):
            if crosses(a, b, c, d):
                return False
    return gap(p, q) >= margin


def inset_polygon(points, d):
    """A counter-clockwise polygon moved in by 'd' along every edge, its corners mitred."""
    lines = []
    for (ax, ay), (bx, by) in segments(points):
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            continue
        nx, ny = -(by - ay) / length, (bx - ax) / length  # to the left: inside
        lines.append(((ax + nx * d, ay + ny * d), (bx - ax, by - ay)))
    found = []
    for (p, u), (q, v) in zip(lines[-1:] + lines[:-1], lines):
        cross = u[0] * v[1] - u[1] * v[0]
        if abs(cross) < 1e-9:
            found.append(q)
            continue
        t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / cross
        found.append((p[0] + u[0] * t, p[1] + u[1] * t))
    return found


def fmt(value):
    text = ("%.3f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# -- Reading estate.json -------------------------------------------------------------------------------------


class Model:
    """A building, in the house's frame (mm): its blocks, their roofs, and everything else of its outside and inside."""

    def __init__(self, estate):
        self.estate = estate
        self.block_paint = {}
        self.blocks = []
        self.chimneys = []
        self.dormers = []
        self.porches = []
        self.steps = []
        self.openings = []
        self.bands = []
        self.storeys = []
        self.paint = {"walls": ":brick", "roof": ":slate", "trim": ":trim", "stone": ":stone"}
        self.colours = {}
        self.extras = []  # landscape features, in the house's frame
        self.shell = None
        self.room_walls = {}

    # The roof's underside over a point: what nothing inside may reach. Of one block, when it is said which.
    def underside(self, x, y, only=None):
        best = None
        for index, block in enumerate(self.blocks):
            if only is not None and index != only:
                continue
            if only is None and not inside(block["outline"], x, y):
                continue
            roof = block["roof"]
            if roof["type"] == "flat":
                z = roof["top"] - roof["thickness"]
            elif roof["type"] == "gable":
                u = y if roof["axis"] == "x" else x
                z = roof["ridge_z"] - roof["slope"] * abs(u - roof["ridge"]) - roof["thickness"]
            else:  # hip: as low as its nearest eave, sloping up
                d = min(to_segment((x, y), a, b) for a, b in segments(roof["eave_outline"]))
                z = min(roof["ridge_z"], roof["eave_z"] + roof["slope"] * d) - roof["thickness"]
            best = z if best is None else max(best, z)
        return best


# What differs between the estates' readings: which way each faces, which wall each side's openings are in,
# what it is built of, and what of its grounds is not on the map. Everything else is read the same way.
PROFILES = {
    "gunston-hall": {
        "sides": {
            "front_land": ("y", "min", 0),
            "back_river": ("y", "max", 0),
            "left_NE_gable": ("x", "min", 0),
            "right_SW_gable": ("x", "max", 0),
        },
        "paint": {"walls": "brick", "roof": "slate", "trim": "trim", "stone": "sandstone"},
        "colours": {
            "brick": ("#9A4E3A", "Brick, laid in Flemish bond."),
            "slate": ("#4D545C", "Slate, as the roof is now."),
            "trim": ("#ECE6D8", "The white of the porches, the cornice, the dormers and the window frames."),
            "sandstone": ("#B9AE98", "Aquia Creek sandstone: the quoins, the steps."),
            "floorboards": ("#A67C52", "Heart pine floorboards."),
        },
    },
    "grant-kohrs-ranch": {
        "sides": {
            "front_east": ("y", "min", 0),
            "left_south_gable_of_front_block": ("x", "min", 0),
            "right_north_gable_of_front_block": ("x", "max", 0),
            "wing_north_side": ("x", "max", 1),
        },
        "paint": {"walls": "clapboard", "roof": "shingle", "trim": "trim", "stone": "fieldstone"},
        "block_walls": {"rear wing": "brick"},
        "colours": {
            "clapboard": ("#EAE3D2", "Painted clapboard over the hewn logs of the 1862 house."),
            "brick": ("#93503B", "The brick veneer of the 1890 wing."),
            "shingle": ("#5E5248", "Wood shingles, weathered."),
            "trim": ("#3F5E4A", "The dark green of the trim, the porch and the window frames."),
            "fieldstone": ("#9C968A", "Stone: the steps and the boardwalk's edge."),
            "floorboards": ("#9E7752", "Fir floorboards."),
        },
    },
    "scottys-castle": {
        "sides": {"front_south": ("y", "min", 0)},
        "skip_kinds": ("porch arcade", "open loggia"),
        "paint": {"walls": "stucco", "roof": "clay-tile", "trim": "timber", "stone": "flagstone"},
        "colours": {
            "stucco": ("#E3CFA6", "Stucco, the colour of the canyon's sand."),
            "clay-tile": ("#B0532C", "Spanish clay roof tiles."),
            "timber": ("#5B3B26", "Dark-stained timber and wrought iron: the frames, the posts, the grilles."),
            "flagstone": ("#B5A486", "Flagstone and tile: the steps, the terraces, the patio."),
            "floorboards": ("#8E6A48", "Oak floors, and tile."),
        },
    },
}

# What a wing is, by its name: steps and terraces are stepped plinths, porches open, the rest are blocks.
STEPS_WORDS = ("steps", "stoop", "terrace", "boardwalk", "patio", "bulkhead")
PORCH_WORDS = ("porch", "loggia", "veranda", "bridge")
OUTSIDE_ROOMS = ("porch", "loggia", "veranda", "open well", "patio")


def number_list(value):
    return value if isinstance(value, list) else [value]


def bearing_of(estate):
    import re

    found = re.search(r"bearing (-?[0-9.]+)", estate["frame"]["x_axis"])
    if not found:
        raise SystemExit("%s: the frame's x_axis says no bearing" % estate["slug"])
    return float(found.group(1))


def roof_entry(estate, name):
    """The roof estate.json states for a block, by its name: the one entry, or the entry whose 'part' it names."""
    roof = estate["exterior"].get("roof")
    if isinstance(roof, dict):
        return roof if name == "main" else None
    for entry in roof or []:
        part = entry.get("part", "").lower()
        if name == "main" and part in ("main", "main block", "front block"):
            return entry
        if part and part != "front block" and part in name:
            return entry
    return None


def gable(outline, entry, eave, ridge_z, overhang, gable_overhang=None):
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    axis = str(entry.get("ridge_axis", "X")).lower() if entry else ("x" if max(xs) - min(xs) >= max(ys) - min(ys) else "y")
    if axis == "x":
        ridge = entry.get("ridge_y_mm", (min(ys) + max(ys)) / 2.0) if entry else (min(ys) + max(ys)) / 2.0
        wall = min(ys)
        along, across = [min(xs), max(xs)], [min(ys), max(ys)]
    else:
        ridge = entry.get("ridge_x_mm", (min(xs) + max(xs)) / 2.0) if entry else (min(xs) + max(xs)) / 2.0
        wall = min(xs)
        along, across = [min(ys), max(ys)], [min(xs), max(xs)]
    run = max(abs(ridge - across[0]), abs(across[1] - ridge))
    slope = (ridge_z - eave) / (run or 1.0)
    go = overhang if gable_overhang is None else gable_overhang
    along = [along[0] - go, along[1] + go]
    across = [across[0] - overhang, across[1] + overhang]
    if axis == "x":
        reach = [(along[0], across[0]), (along[1], across[0]), (along[1], across[1]), (along[0], across[1])]
    else:
        reach = [(across[0], along[0]), (across[1], along[0]), (across[1], along[1]), (across[0], along[1])]
    del wall
    return {
        "type": "gable",
        "axis": axis,
        "ridge": ridge,
        "ridge_z": ridge_z,
        "slope": slope,
        "thickness": ROOF_THICKNESS,
        "along": along,
        "across": across,
        "overhang_outline": reach,
    }


def flat(outline, top):
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    return {"type": "flat", "top": top, "thickness": min(ROOF_THICKNESS, 250.0), "reach": [min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1], "overhang": 150.0}


def hip(outline, eave, ridge_z):
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    half = min(max(xs) - min(xs), max(ys) - min(ys)) / 2.0
    eave_outline = grow(outline, 200.0)
    return {
        "type": "hip",
        "eave_z": eave,
        "ridge_z": ridge_z,
        "slope": max(0.2, (ridge_z - eave) / max(half, 1.0)),
        "thickness": min(ROOF_THICKNESS, 250.0),
        "eave_outline": eave_outline,
        "overhang_outline": eave_outline,
    }


def read_estate(estate):
    """An estate.json as a Model: one reading for the three, with what differs in PROFILES."""
    profile = PROFILES[estate["slug"]]
    m = Model(estate)
    ext = estate["exterior"]
    thick = ext.get("wall_thickness_mm") or {}
    main = estate["footprint"]["main_block"]
    outline = ccw([tuple(p) for p in main["polygon"]])
    entry = roof_entry(estate, "main")
    eave = (entry or {}).get("eaves_mm") or main.get("eaves_mm") or ext.get("eaves_height_mm")
    if isinstance(eave, dict):
        eave = next(iter(eave.values()))
    ridge_z = (entry or {}).get("ridge_height_mm") or main.get("ridge_mm")
    overhang = (entry or {}).get("eaves_overhang_mm", (entry or {}).get("overhang_mm", 300.0))
    roof = gable(outline, entry, eave, ridge_z, overhang, (entry or {}).get("gable_overhang_mm"))
    main_thick = first_number(thick, ("first_floor", "front_block", "exterior"), 300.0)
    m.blocks.append({"name": "main", "outline": outline, "roof": roof, "wall_top": main.get("wall_top_mm", eave), "thick": main_thick})
    m.anchor = centroid(outline)
    m.bearing = bearing_of(estate)
    m.size = 400.0

    for w in estate["footprint"]["wings_porches"]:
        name = w["name"].lower()
        head = name.split("(")[0]  # what it is; what follows says where
        poly = ccw([tuple(p) for p in w["polygon"]])
        px, py = [p[0] for p in poly], [p[1] for p in poly]
        box = [(min(px), min(py)), (max(px), max(py))]
        if any(word in head for word in STEPS_WORDS):
            out = side_away(m.blocks[0]["outline"], box)
            flight = "steps" in name or "stoop" in name
            height = w.get("height_mm", 150.0)
            risers = max(2, int(math.ceil(height / 170.0))) if flight else 1
            m.steps.append({"box": box, "height": height, "out": out, "risers": risers})
            continue
        if any(word in head for word in PORCH_WORDS):
            m.porches.append(porch_of(w, poly, box, m))
            continue
        # A block: its own walls and roof.
        roof_text = str(w.get("roof", "")).lower()
        entry = roof_entry(estate, name)
        top = w.get("ridge_mm") or w.get("height_mm") or 3000.0
        eave = w.get("eaves_mm") or (top - 600.0 if "hip" in roof_text or "pyramid" in roof_text else top)
        if entry or ("gable" in roof_text and "small" not in roof_text):
            r = gable(poly, entry, eave, entry.get("ridge_height_mm", top) if entry else top, (entry or {}).get("overhang_mm", 300.0))
        elif "hip" in roof_text or "pyramid" in roof_text or "octagon" in roof_text:
            r = hip(poly, eave, top)
        else:
            r = flat(poly, w.get("eaves_mm") or top)
        block_thick = first_number(thick, ("rear_wing",), main_thick) if "wing" in name else main_thick
        m.blocks.append({"name": name, "outline": poly, "roof": r, "wall_top": eave, "thick": min(block_thick, 300.0)})

    for c in ext.get("chimneys", []):
        xs, ys = number_list(c["x_mm"]), number_list(c["y_mm"])
        if len(xs) == 2:
            m.chimneys.append({"x": sum(xs) / 2.0, "y": sum(ys) / 2.0, "sx": abs(xs[1] - xs[0]), "sy": abs(ys[1] - ys[0]), "top": c["top_mm"]})
        else:
            m.chimneys.append({"x": xs[0], "y": ys[0], "sx": c["size_x_mm"], "sy": c["size_y_mm"], "top": c["top_mm"]})
    tower = ext.get("tower")
    if tower:
        (x0, x1), (y0, y1) = tower["x_mm"], tower["y_mm"]
        m.chimneys.append({"x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0, "sx": x1 - x0, "sy": y1 - y0, "top": tower["shaft_top_mm"]})
        m.chimneys.append(
            {"x": (x0 + x1) / 2.0, "y": (y0 + y1) / 2.0, "sx": (x1 - x0) * 0.6, "sy": (y1 - y0) * 0.6, "top": tower.get("cupola_top_mm", tower["shaft_top_mm"])}
        )

    dormers(m, ext.get("dormers"), roof, outline)
    openings(m, ext.get("openings") or {}, profile)
    cornice = (entry or {}).get("modillion_cornice") if isinstance(estate["exterior"].get("roof"), dict) else None
    cornice = cornice or (ext.get("roof") or {}).get("modillion_cornice") if isinstance(ext.get("roof"), dict) else cornice
    if cornice:
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        m.bands.append(
            {
                "outline": [(min(xs) - 150.0, min(ys) - 150.0), (max(xs) + 150.0, min(ys) - 150.0), (max(xs) + 150.0, max(ys) + 150.0), (min(xs) - 150.0, max(ys) + 150.0)],
                "inner": outline,
                "z0": cornice["bottom_mm"],
                "z1": cornice["top_mm"] - 1.0,
            }
        )

    for st in estate["storeys"]:
        rooms = [r for r in st.get("rooms") or [] if not any(word in r["name"].lower() for word in OUTSIDE_ROOMS)]
        if not rooms or st["floor_level_mm"] < 0:
            continue
        m.storeys.append({"name": st["name"], "level": st["floor_level_mm"], "height": st["ceiling_height_mm"], "rooms": rooms})

    paint = profile["paint"]
    m.paint = {key: ":" + value for key, value in paint.items()}
    m.paint["inside"] = ":" + WALL_PLASTER
    m.block_paint = {k: ":" + v for k, v in profile.get("block_walls", {}).items()}
    m.colours = dict(profile["colours"])
    m.colours[WALL_PLASTER] = ("#E4DCCB", "Plastered walls, inside.")
    m.colours["wood"] = ("#8B6A45", "A piece of furniture's stand-in, where it is not drawn as its model.")
    m.extras = extras_of(estate, outline)
    return m


def first_number(table, keys, default):
    for key in keys:
        if isinstance(table, dict) and isinstance(table.get(key), (int, float)):
            return float(table[key])
    return default


def side_away(outline, box):
    """Which way a flight of steps goes: away from the side of the house it stands against."""
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    (x0, y0), (x1, y1) = box
    distances = {"-y": abs(y1 - min(ys)) if y1 <= min(ys) + 1.0 else float("inf")}
    distances["+y"] = abs(y0 - max(ys)) if y0 >= max(ys) - 1.0 else float("inf")
    distances["-x"] = abs(x1 - min(xs)) if x1 <= min(xs) + 1.0 else float("inf")
    distances["+x"] = abs(x0 - max(xs)) if x0 >= max(xs) - 1.0 else float("inf")
    best = min(distances, key=distances.get)
    if distances[best] == float("inf"):
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        mx, my = centroid(outline)
        best = ("+x" if cx > mx else "-x") if abs(cx - mx) > abs(cy - my) else ("+y" if cy > my else "-y")
    return best


def porch_of(w, poly, box, m):
    floor = w.get("floor_mm", 150.0)
    height = w.get("height_mm", floor + 2800.0)
    spec = {"outline": poly, "floor": floor}
    if floor > 2500.0:
        spec["slab"] = 300.0  # raised: a floor on what holds it up, not a plinth from the ground
    columns = w.get("columns")
    if columns:
        spec["columns"] = [
            {"x": c["x_mm"], "y": c["y_mm"], "d": c.get("diameter_mm", c.get("size_mm", 250.0)), "top": c.get("top_mm", height - 170.0)}
            for c in columns
        ]
        eave = max(c["top"] for c in spec["columns"]) + 171.0
    else:
        eave = height
        cx, cy = centroid(poly)
        main = m.blocks[0]["outline"]
        spec["columns"] = []
        for x, y in poly:
            if any(to_segment((x, y), a, b) < 50.0 for a, b in segments(main)):
                continue  # against the house: it holds this up
            dx, dy = cx - x, cy - y
            n = math.hypot(dx, dy) or 1.0
            spec["columns"].append({"x": x + dx / n * 250.0, "y": y + dy / n * 250.0, "d": 300.0, "top": eave - 170.0})
    roof_text = str(w.get("roof", "")).lower()
    (x0, y0), (x1, y1) = box
    if "gable" in roof_text:
        axis = "y" if "along y" in roof_text or (y1 - y0) > (x1 - x0) and "along x" not in roof_text else "x"
        along, across = ([y0, y1], [x0, x1]) if axis == "y" else ([x0, x1], [y0, y1])
        spec["roof"] = {"type": "gable", "axis": axis, "along": along, "across": across, "eave": eave, "apex": height, "entablature": 171.0}
    elif "hip" in roof_text or "octagon" in roof_text:
        spec["roof"] = {"type": "hip", "eave": eave - 600.0, "apex": eave, "eave_outline": poly, "taper": 40.0}
    else:
        spec["roof"] = {"type": "flat", "eave": eave, "thickness": 200.0, "entablature": 171.0}
    return spec


def dormers(m, d, roof, outline):
    if not d:
        return
    ys = [p[1] for p in outline]
    depth = max(ys)

    def from_ridge(z):
        return (roof["ridge_z"] - z) / roof["slope"]

    front = roof["ridge"] - from_ridge(d["sill_mm"] - 150.0)
    back = roof["ridge"] - from_ridge(d["pediment_apex_mm"]) + 150.0
    for x0, x1 in d["x_ranges_mm"]:
        mid = (x0 + x1) / 2.0
        common = {
            "along": [x0, x1],
            "sill": d["sill_mm"],
            "head": d["window_head_mm"],
            "apex": d["pediment_apex_mm"],
            "bottom": d["sill_mm"] - 400.0,
            "window": (mid - 400.0, mid + 400.0),
        }
        if "front" in d["sides"]:
            m.dormers.append(dict(common, depth=[front, back], front="min"))
        if "back" in d["sides"]:
            m.dormers.append(dict(common, depth=[depth - back, depth - front], front="max"))


def openings(m, table, profile):
    skip = profile.get("skip_kinds", ())
    for side, (axis, which, block) in profile["sides"].items():
        outline = m.blocks[block]["outline"]
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        wall_top = m.blocks[block]["wall_top"]
        for w in table.get(side) or []:
            if w["kind"] in skip:
                continue
            if w["kind"] == "round window":
                c, r = w["centre_y_mm"], w["diameter_mm"] / 2.0
                a, b, sill, head, rnd = c - r, c + r, w["centre_height_mm"] - r, w["centre_height_mm"] + r, True
            else:
                a = w.get("x0_mm", w.get("y0_mm"))
                b = w.get("x1_mm", w.get("y1_mm"))
                sill, head, rnd = max(w["sill_mm"], 1.0), w["head_mm"], False
                if axis == "y" and m.dormers and sill >= wall_top:
                    continue  # a dormer's window: the dormer has it
            if axis == "y":
                c = min(ys) if which == "min" else max(ys)
                p0, p1 = ((a, c), (b, c)) if which == "min" else ((b, c), (a, c))
            else:
                c = min(xs) if which == "min" else max(xs)
                p0, p1 = ((c, b), (c, a)) if which == "min" else ((c, a), (c, b))
            spec = {"p0": p0, "p1": p1, "sill": sill, "head": head, "thick": m.blocks[block]["thick"]}
            if rnd:
                spec["round"] = True
            m.openings.append(spec)


def extras_of(estate, outline):
    """What the HABS site plan shows of the grounds that OpenStreetMap does not, as landscape features."""
    land = estate.get("landscape") or {}
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    found = []
    avenue = land.get("magnolia_avenue")
    if avenue:
        x = (min(xs) + max(xs)) / 2.0
        off = avenue["tree_rows_offset_m"] * 1000.0
        for dx in (-off, off):
            found.append({"kind": "tree_row", "points": [(x + dx, -12000.0), (x + dx, -avenue["length_m"] * 1000.0)]})
    allee = land.get("boxwood_allee")
    if allee:
        for x in allee["x_mm"]:
            found.append({"kind": "hedge", "layer": "hedges", "width": 800.0, "thickness": 1200.0, "points": [(x, allee["y_mm"][0]), (x, allee["y_mm"][1])]})
    yard = land.get("front_yard")
    if yard and estate["slug"] == "grant-kohrs-ranch":
        # A fenced yard ~45 x 50 m in front of the house, a path from the porch steps to its gate.
        mid = (min(xs) + max(xs)) / 2.0
        x0, x1, y0, y1 = mid - 22500.0, mid + 22500.0, -6000.0, -50000.0
        fence = {"kind": "fence", "layer": "fences", "width": 50.0, "thickness": 1200.0}
        found.append(dict(fence, points=[(x0, y0), (x0, y1), (mid - 1500.0, y1)]))
        found.append(dict(fence, points=[(mid + 1500.0, y1), (x1, y1), (x1, y0)]))
        found.append({"kind": "path", "layer": "paths", "width": 1500.0, "thickness": 50.0, "points": [(mid, -4000.0), (mid, y1 - 3000.0)]})
    return found


def model_of(estate_dir):
    with open(os.path.join(estate_dir, "estate.json"), encoding="utf-8") as f:
        estate = json.load(f)
    if estate["slug"] not in PROFILES:
        raise SystemExit("no profile for '%s': add one to PROFILES" % estate["slug"])
    m = read_estate(estate)
    plan(m)
    return m


# -- Fitting the inside into the outside -----------------------------------------------------------------------


def block_of(m, x, y):
    for index, block in enumerate(m.blocks):
        if inside(block["outline"], x, y):
            return index
    return None


def convex(points):
    turns = [(bx - ax) * (cy - by) - (by - ay) * (cx - bx) for (ax, ay), (bx, by), (cx, cy) in zip(points, points[1:] + points[:1], points[2:] + points[:2])]
    return all(turn >= -1e-6 for turn in turns) or all(turn <= 1e-6 for turn in turns)


def clip(points, window):
    """'points' clipped to the convex, counter-clockwise polygon 'window' (Sutherland and Hodgman)."""
    found = list(points)
    for (ax, ay), (bx, by) in segments(window):
        def side(p):
            return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

        def meet(p, q):
            sp, sq = side(p), side(q)
            t = sp / (sp - sq)
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)

        given, found = found, []
        for p, q in segments(given) if given else []:
            if side(q) >= 0.0:
                if side(p) < 0.0:
                    found.append(meet(p, q))
                found.append(q)
            elif side(p) >= 0.0:
                found.append(meet(p, q))
    return found


def within_walls(m, room, t):
    """'room', or the part of it inside the inner face of the outside walls of the one block it is drawn in.

    A room's walls may stand in the outside wall, and are carved out of it (see 'shell_data'), as long as
    the outside is left: a room drawn out to its block's outline - the survey's dimension of a small wing is
    often its outside - would have its walls carved through it, and from outside the house would have a
    hole there. So a room inside one block is kept back from that block's outline by its walls, a gap, and
    the thinnest wall there is (MIN_WALL) of the outside left standing. A room across two blocks, or in a
    block that is not convex, is left as it is drawn.
    """
    index = block_of(m, *centroid(room))
    if index is None:
        return room
    block = m.blocks[index]
    outline = ccw([tuple(p) for p in block["outline"]])
    if not convex(outline) or not all(inside(outline, x, y) or min(to_segment((x, y), *e) for e in segments(outline)) < 1.0 for x, y in room):
        return room
    window = inset_polygon(outline, t + GAP + MIN_WALL)
    if all(inside(window, x, y) for x, y in room):
        return room
    kept = clip(room, window)
    return ccw(kept) if len(kept) >= 3 and area(ccw(kept)) > 0.0 else room


def plan(m):
    """Each storey's rooms' wall thickness, which blocks its floor is in, and each room's height.

    A storey's walls are as thick as its thinnest partition lets two rooms' walls be, back to back. Its floor
    is in the blocks its rooms are in. A room's walls stop a millimetre under the next floor over the block it
    is in, and under the roof's underside wherever they stand - a knee wall, under a slope.
    """
    for st in m.storeys:
        rooms = [ccw([tuple(p) for p in r["polygon"]]) for r in st["rooms"]]
        pairs = [(gap(rooms[i], rooms[j]), i, j) for i in range(len(rooms)) for j in range(i + 1, len(rooms))]
        # Rooms drawn closer than two thin walls are rooms open to each other, or drawn edge to edge: they are
        # pulled apart below. The storey's walls are as thick as the rest of its partitions let them be.
        least = min([g for g, _, _ in pairs if g >= 2.0 * MIN_WALL + 2.0 * GAP] or [2.0 * 114.3 + 2.0 * GAP])
        t = min(114.3, math.floor((least - 2.0 * GAP) / 2.0))
        need = 2.0 * t + 2.0 * GAP
        short = {}
        for g, i, j in pairs:
            if g < need:
                for k in (i, j):
                    short[k] = max(short.get(k, 0.0), (need - g) / 2.0 + 0.5)
        for k, by in short.items():
            print("note: %s: %s moved in %s mm, clear of a room drawn against it" % (st["name"], st["rooms"][k]["name"], fmt(by)), file=sys.stderr)
            rooms[k] = inset_polygon(rooms[k], by)
        for k, room in enumerate(rooms):
            kept = within_walls(m, room, t)
            if kept is not room:
                print("note: %s: %s kept back from the outside, which its walls would carve through" % (st["name"], st["rooms"][k]["name"]), file=sys.stderr)
                rooms[k] = kept
        st["outlines"] = rooms
        st["thickness"] = t
        st["blocks"] = []
        st["room_blocks"] = []
        for room, r in zip(rooms, st["rooms"]):
            index = block_of(m, *centroid(room))
            if index is None:
                print("warning: %s: %s is in none of the blocks" % (st["name"], r["name"]), file=sys.stderr)
            st["room_blocks"].append(index)
            if index is not None and index not in st["blocks"]:
                st["blocks"].append(index)
    for st in m.storeys:
        st["heights"], st["ceilings"] = [], []
        for room, index in zip(st["outlines"], st["room_blocks"]):
            ceiling = st["level"] + st["height"]
            for above in m.storeys:
                if above["level"] <= st["level"]:
                    continue
                # Under the floor above, over the block it is in; and under any room above, from whichever block,
                # whose walls come near its own.
                near = any(gap(room, other) < st["thickness"] + above["thickness"] + 2.0 * GAP or polygons_meet(room, other) for other in above["outlines"])
                if index in above["blocks"] or near:
                    ceiling = min(ceiling, above["level"] - SLAB - GAP)
            top = ceiling
            for x, y in sample_ring(room, st["thickness"] + GAP):
                z = m.underside(x, y, only=index)
                if z is not None:
                    top = min(top, z - GAP)
            st["ceilings"].append(ceiling)
            st["heights"].append(math.floor(top - st["level"] - GAP))


def sample_ring(points, t):
    """Points along an outline and along the outer face of the walls standing on it, 't' thick: where they reach.

    The outer face is the outline moved out along every edge, its corners mitred as the walls' are - a corner
    of it reaches farther out than any point moved out from the middle does - and every corner is sampled.
    """
    found = []
    for ring in (points, inset_polygon(ccw(points), -t)):
        for (ax, ay), (bx, by) in segments(ring):
            for i in range(10):
                found.append((ax + (bx - ax) * i / 10.0, ay + (by - ay) * i / 10.0))
    return found


# -- Furniture -------------------------------------------------------------------------------------------------

A = "//pub/collection/openusd/nvidia/assets/archvis-residential:"
R = "//pub/collection/openusd/nvidia/assets/simready:"

# Who sits where: (part, against a wall or in the middle, count). The model's front is -Y.
KITS = [
    (("dining",), [("Dellwood_DiningTable", "middle", 1), ("Dellwood_DiningChair", "around", 6), ("AftonConsole", "wall", 1)]),
    (
        ("parlor", "parlour", "drawing", "living", "sitting", "palladian", "music", "library"),
        [("Crestwood_Sofa", "wall", 1), ("Appleseed_CoffeeTable", "middle", 1), ("Crestwood_Chair", "wall", 2), ("EurekaConsole", "wall", 1)],
    ),
    (
        ("chamber", "bedroom", "bed room", "nursery"),
        [("Daybed", "wall", 1), ("Appleseed_EndTable", "wall", 1), (R + "cabinet_b01", "wall", 1), ("Sappington_Chair", "wall", 1)],
    ),
    (("kitchen", "pantry"), [("stove", "wall", 1), ("EastRural_Table", "middle", 1), ("EastRural_Chair", "wall", 2)]),
    (("office", "study", "den", "library", "school"), [("Desk_01", "wall", 1), ("Chair_Desk", "wall", 1), ("CornerShelf_Square", "wall", 1)]),
    (("billiard", "game"), [("BilliardTable", "middle", 1)]),
    (("passage", "hall", "stair", "vestibule", "entry", "corridor", "foyer"), [("Jennings_Bench", "wall", 1), ("AftonConsole", "wall", 1)]),
]


# Rooms that hold nothing a catalogue has: a bath, a closet, a store, a landing, a well open to the floor below.
EMPTY = ("bath", "closet", "trunk", "store room", "storeroom", "stair (down)", "open well", "telephone")


def kit(name):
    lower = name.lower()
    if any(word in lower for word in EMPTY):
        return []
    for words, items in KITS:
        if any(w in lower for w in words):
            return items
    return [("Armchair", "wall", 1), ("Appleseed_EndTable", "wall", 1)]


# Which way a model faces, where it is not -Y: what turns its front into the room.
FRONT = {"Desk_01": (-1.0, 0.0), "cabinet_b01": (-1.0, 0.0), "EastRural_Bench": (-1.0, 0.0), "Roxana_DiningBench": (-1.0, 0.0)}


def front_of(part):
    return FRONT.get(part.rsplit(":", 1)[-1], (0.0, -1.0))


def heading_for(part, nx, ny):
    """The turn, in degrees, that faces 'part' along (nx, ny)."""
    fx, fy = front_of(part)
    return (math.degrees(math.atan2(ny, nx) - math.atan2(fy, fx))) % 360.0


def full(part):
    return part if part.startswith("//") else A + part


def short(part):
    return full(part).rsplit(":", 1)[1].lower().replace("_", "-")


def furnish(m, sizes):
    """Every room's furniture: (part, x, y, z, heading in degrees), in the house's frame."""
    placed = {}
    for k, st in enumerate(m.storeys):
        for i, (room, outline) in enumerate(zip(st["rooms"], st["outlines"])):
            st["_ceiling"] = st["ceilings"][i]
            st["_block"] = st["room_blocks"][i]
            items, zone, table = [], [], None
            taken = [door_zone(door) for door in room.get("doors") or [] if door.get("center_mm")]
            for part, where, count in kit(room["name"]):
                box = sizes.get(full(part))
                if not box:
                    continue
                w, d, h = box[3] - box[0], box[4] - box[1], box[5] - box[2]
                if where == "middle":
                    spot = middle(m, st, outline, w, d, h, taken)
                    if spot:
                        items.append((part,) + spot)
                        taken.append(rect_corners(spot[0], spot[1], w, d, math.radians(spot[3])))
                        # Room to walk round it, which what stands against the walls leaves.
                        zone = [rect_corners(spot[0], spot[1], w + 1300.0, d + 1300.0, math.radians(spot[3]))]
                        table = (spot, w, d)
                    continue
                if where == "around":
                    if table:
                        for spot in around(m, st, outline, table, part, w, d, h, count, taken):
                            items.append((part,) + spot)
                            taken.append(rect_corners(spot[0], spot[1], w, d, math.radians(spot[3])))
                    continue
                for _ in range(count):
                    spot = against_wall(m, st, outline, part, w, d, h, taken + zone)
                    if not spot:
                        break
                    items.append((part,) + spot)
                    taken.append(rect_corners(spot[0], spot[1], w, d, math.radians(spot[3])))
            placed[(k, i)] = items
    return placed


def door_zone(door):
    x, y = door["center_mm"]
    w = door.get("width_mm", 900.0)
    # Clear in front of a door on both sides of it: a square a door wide and deep.
    return rect_corners(x, y, w + 600.0, w + 600.0, 0.0)


def clear_overhead(m, st, corners, h, ceiling=None):
    top = st["level"] + GAP + h
    if ceiling is not None and top > ceiling - 20.0:
        return False
    for x, y in corners:
        z = m.underside(x, y, only=st.get("_block"))
        if z is not None and top > z - 20.0:
            return False
    return True


def fits(m, st, outline, corners, h, taken, margin=60.0):
    return (
        rect_in(outline, corners, margin)
        and all(rects_apart(corners, other, 60.0) for other in taken)
        and clear_overhead(m, st, corners, h, st.get("_ceiling"))
    )


def against_wall(m, st, outline, part, w, d, h, taken):
    """Back to a wall, its front into the room, at the first place along the room's walls where it fits."""
    fx, fy = front_of(part)
    along, deep = (w, d) if abs(fy) > abs(fx) else (d, w)
    walls = sorted(segments(outline), key=lambda s: -math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
    for (ax, ay), (bx, by) in walls:
        length = math.hypot(bx - ax, by - ay)
        if length < along + 200.0:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length
        nx, ny = -uy, ux  # into the room: the outline runs counter-clockwise
        heading = heading_for(part, nx, ny)
        steps = int((length - along - 200.0) // 150.0) + 1
        order = sorted(range(steps), key=lambda i: abs(i - steps / 2.0))
        for i in order:
            s = 100.0 + along / 2.0 + i * 150.0
            cx = ax + ux * s + nx * (deep / 2.0 + 80.0)
            cy = ay + uy * s + ny * (deep / 2.0 + 80.0)
            corners = rect_corners(cx, cy, w, d, math.radians(heading))
            if fits(m, st, outline, corners, h, taken):
                return (round(cx, 1), round(cy, 1), st["level"] + GAP, round(heading, 3))
    return None


def middle(m, st, outline, w, d, h, taken):
    cx, cy = centroid(outline)
    xs, ys = [p[0] for p in outline], [p[1] for p in outline]
    heading = 0.0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 90.0
    for dx, dy in ((0, 0), (300, 0), (-300, 0), (0, 300), (0, -300)):
        corners = rect_corners(cx + dx, cy + dy, w, d, math.radians(heading))
        if fits(m, st, outline, corners, h, taken, margin=600.0):
            return (round(cx + dx, 1), round(cy + dy, 1), st["level"] + GAP, heading)
    return None


def around(m, st, outline, table, part, w, d, h, count, taken):
    """Chairs facing a table: along its long sides, then at its ends."""
    (tx, ty, _, heading), tw, td = table
    a = math.radians(heading)
    ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    spots = []
    per_side = max(1, min(count // 2, int(tw // (w + 150.0))))
    for side in (-1, 1):
        for i in range(per_side):
            s = (i - (per_side - 1) / 2.0) * (w + 150.0)
            off = td / 2.0 + d / 2.0 + 60.0
            cx, cy = tx + ux * s + nx * off * side, ty + uy * s + ny * off * side
            spots.append((cx, cy, heading_for(part, -nx * side, -ny * side)))
    for side in (-1, 1):
        off = tw / 2.0 + d / 2.0 + 60.0
        cx, cy = tx + ux * off * side, ty + uy * off * side
        spots.append((cx, cy, heading_for(part, -ux * side, -uy * side)))
    found = []
    for cx, cy, face in spots:
        if len(found) >= count:
            break
        corners = rect_corners(cx, cy, w, d, math.radians(face))
        if fits(m, st, outline, corners, h, taken + [rect_corners(c[0], c[1], w, d, math.radians(c[3])) for c in found]):
            found.append((round(cx, 1), round(cy, 1), st["level"] + GAP, round(face % 360.0, 3)))
    return found


# -- Where the house is in the landscape --------------------------------------------------------------------------


def to_land(m, x, y):
    """A point of the house's frame in the landscape's (mm, X east, Y north, the house's anchor at the origin)."""
    b = math.radians(m.bearing)
    ex, ey = math.sin(b), math.cos(b)  # +X of the house
    nx, ny = -ey, ex  # +Y of the house: +X turned a quarter anticlockwise
    dx, dy = x - m.anchor[0], y - m.anchor[1]
    return ex * dx + nx * dy, ey * dx + ny * dy


def turn(m):
    """The house's +X, anticlockwise from east, in degrees."""
    return 90.0 - m.bearing


def hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def house_outline(m):
    """Everything the house stands on, in its own frame: blocks, porches, steps."""
    points = [p for b in m.blocks for p in b["outline"]]
    points += [p for porch in m.porches for p in porch["outline"]]
    for st in m.steps:
        (x0, y0), (x1, y1) = st["box"]
        points += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return hull(points)


def grow(points, by):
    cx, cy = centroid(points)
    return [(x + (x - cx) / (math.hypot(x - cx, y - cy) or 1.0) * by, y + (y - cy) / (math.hypot(x - cx, y - cy) or 1.0) * by) for x, y in points]


# -- site: the landscape ------------------------------------------------------------------------------------------


def site(estate_dir, offline=False):
    m = model_of(estate_dir)
    work = os.path.join(estate_dir, "landscape")
    os.makedirs(work, exist_ok=True)
    raw = os.path.join(work, "site.json")
    lat, lon = m.estate["location"]["lat"], m.estate["location"]["lon"]
    if not offline or not os.path.exists(raw):
        run([sys.executable, LANDSCAPE, "fetch", "--center", "%.6f,%.6f" % (lat, lon), "--size", fmt(m.size), "--cells", str(CELLS), "-o", raw])
    with open(raw, encoding="utf-8") as f:
        data = json.load(f)
    if "graded" in data:
        raise SystemExit("%s is graded already: fetch it again (without --offline)" % raw)
    footprint = [to_land(m, x, y) for x, y in house_outline(m)]
    keep_clear = grow(footprint, 1500.0)
    features = data["features"]
    # The house's own outline is the house: what is drawn there is its shell.
    features["areas"] = [
        a for a in features["areas"] if not (a["kind"] == "building" and polygons_meet(a["outline"], keep_clear))
    ]
    features["points"] = [p for p in features["points"] if not inside(keep_clear, p["x"], p["y"])]
    lines = []
    for line in features["lines"] + [extra(m, e) for e in m.extras]:
        for run_ in clip_out(line["points"], keep_clear):
            if len(run_) >= 2:
                lines.append(dict(line, points=run_))
    features["lines"] = lines
    level = grade(data["surface"], footprint)
    data["graded"] = {
        "level": level,
        "outline": [[round(x, 1), round(y, 1)] for x, y in footprint],
        "note": "the poles under the house and %s spans around it set to one height, so that the ground under it is level" % PAD_SPANS,
    }
    with open(raw, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    run([sys.executable, LANDSCAPE, "package", raw, "-o", work, "--force", "--site-dir", work])
    mark_slow(os.path.join(work, "partcad.yaml"))
    print("graded at %s mm; the house stands on it" % fmt(level))


def extra(m, e):
    line = dict(e)
    line["points"] = [list(to_land(m, x, y)) for x, y in e["points"]]
    return line


def polygons_meet(p, q):
    return any(inside(q, *v) for v in p) or any(inside(p, *v) for v in q) or any(
        crosses(a, b, c, d) for a, b in segments(p) for c, d in segments(q)
    )


def clip_out(points, polygon, step=500.0):
    """The runs of a line outside a polygon, the line sampled every 'step' mm."""
    runs, current = [], []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) // step))
        for i in range(n + 1):
            x, y = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
            if inside(polygon, x, y):
                if len(current) >= 2:
                    runs.append(current)
                current = []
            elif not current or (current[-1][0], current[-1][1]) != (x, y):
                current.append([x, y])
    if len(current) >= 2:
        runs.append(current)
    return [simplify(r) for r in runs]


def simplify(points):
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for p, q in zip(points[1:], points[2:]):
        a = kept[-1]
        if abs((p[0] - a[0]) * (q[1] - a[1]) - (p[1] - a[1]) * (q[0] - a[0])) > 1e-3 * max(1.0, math.hypot(q[0] - a[0], q[1] - a[1])) ** 2:
            kept.append(p)
    kept.append(points[-1])
    return kept


def grade(surface, footprint):
    """Level the poles under and around the house to their middle height there; the height, in mm."""
    x0, y0, x1, y1 = surface["extent"]
    poles = surface["poles"]
    nx, ny = len(poles), len(poles[0])
    span = (x1 - x0) / (nx - 3)

    def at(i, j):
        # Greville abscissae of a uniform clamped cubic: the poles' places.
        def g(k, n, lo, hi):
            m = n - 3
            knots = [0.0] * 4 + [t / m for t in range(1, m)] + [1.0] * 4
            return lo + (hi - lo) * sum(knots[k + 1 : k + 4]) / 3.0

        return g(i, nx, x0, x1), g(j, ny, y0, y1)

    # The pad is every pole within PAD_SPANS spans of the footprint, measured from its outline - not the
    # footprint's corners pushed away from its middle, which moves the long sides of a long house hardly at
    # all - and the blend the two spans past that.
    pad, blend = PAD_SPANS * span, (PAD_SPANS + 2.0) * span

    def reach(x, y):
        return 0.0 if inside(footprint, x, y) else min(to_segment((x, y), a, b) for a, b in segments(footprint))

    under = sorted(poles[i][j] for i in range(nx) for j in range(ny) if inside(footprint, *at(i, j)))
    if not under:
        under = sorted(poles[i][j] for i in range(nx) for j in range(ny) if reach(*at(i, j)) <= pad)
    level = round(under[len(under) // 2], 1)
    for i in range(nx):
        for j in range(ny):
            d = reach(*at(i, j))
            if d <= pad:
                poles[i][j] = level
            elif d <= blend:
                w = min(1.0, (d - pad) / (2.0 * span))
                poles[i][j] = round(level * (1.0 - w) + poles[i][j] * w, 1)
    return level


def mark_slow(path):
    """The landscape's scene declares what it takes, so that a sweep with '--fast-only' passes it over."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if "timeout:" not in text:
        text = text.replace("    type: assy\n    path: landscape.assy\n", "    type: assy\n    path: landscape.assy\n    timeout: 1800\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def run(command):
    print("+ " + " ".join(command), file=sys.stderr)
    subprocess.run(command, check=True)


# -- package: the house -----------------------------------------------------------------------------------------


def shell_data(m):
    """What shell.py is built from: the outside, and the inside it must leave room for."""
    roof_from = min(b.get("wall_top", 0.0) for b in m.blocks)
    openings = []
    for o in m.openings:
        spec = {k: v for k, v in o.items() if k != "thick"}
        spec["out"], spec["in"] = 200.0, o["thick"] + 50.0
        openings.append(spec)
    # Each room, as far as its walls reach and as high as they stand: carved out of the shell, so that where
    # a room's measured outline comes nearer the outside than the wall is thick, its walls take the wall's place.
    carve = []
    for st in m.storeys:
        for outline, height in zip(st["outlines"], st["heights"]):
            carve.append({"outline": outline, "grow": st["thickness"] + GAP, "z0": st["level"], "z1": st["level"] + height + 2.0 * GAP})
    blocks = []
    for b in m.blocks:
        spec = {"outline": b["outline"], "roof": b["roof"], "shell": b["thick"]}
        for words, paint in m.block_paint.items():
            if words in b["name"]:
                spec["paint"] = paint
        blocks.append(spec)
    return {
        "blocks": blocks,
        "chimneys": m.chimneys,
        "dormers": m.dormers,
        "porches": m.porches,
        "steps": m.steps,
        "openings": openings,
        "bands": m.bands,
        "carve": carve,
        "paint": m.paint,
        "roof_from": roof_from,
    }


def literal(value):
    """A Python literal of 'value', for a script to hold its data in."""
    import pprint

    return pprint.pformat(value, width=110, sort_dicts=True)


FLOOR_SCRIPT = """#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A storey's floor: the blocks its rooms are in, inside their walls and a
# millimetre clear of them, %(slab)s mm thick under the storey's level - or one of
# the parts of it a storey too large for one picture is pictured in ('main', the
# main block's, then 'wings', the rest - or 'wing', the largest wing, before
# them). Written by
# '../make_estate.py' from 'estate.json'; run that again rather than edit it.

from build123d import Kind, Location, Polygon, extrude, offset

DATA = %(data)s

storey = 1
part = ""


def floor(index):
    found = None
    level = DATA["levels"][index]
    for outline, inset in zip(DATA["outlines"][index], DATA["insets"][index]):
        face = offset(Polygon(*[tuple(p) for p in outline], align=None), amount=-inset, kind=Kind.INTERSECTION)
        slab = extrude(face.moved(Location((0, 0, level - DATA["slab"]))), amount=DATA["slab"])
        found = slab if found is None else found + slab
    if not part:
        return found
    # Part by part: each the floor within its blocks' outlines, less what the parts before it took, and the last
    # whatever is left - so that the parts are the whole floor, and share nothing.
    parts = DATA["parts"][index]
    taken = None
    for name, outlines in parts:
        region = None
        for outline in outlines:
            face = Polygon(*[tuple(p) for p in outline], align=None).moved(Location((0, 0, level - DATA["slab"] - 1)))
            prism = extrude(face, amount=DATA["slab"] + 2)
            region = prism if region is None else region + prism
        if name == part:
            piece = found if name == parts[-1][0] else found & region
            return piece if taken is None else piece - taken
        taken = region if taken is None else taken + region
    raise ValueError("storey %%s is not pictured in parts, and has no part '%%s'" %% (storey, part))


result = floor(int(storey) - 1)

if "show_object" in locals():
    show_object(result, name="floor-%%s" %% storey)  # noqa: F821
"""

ROOMS_SCRIPT = """#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A storey's plan, seen from above: the outlines of its rooms, which their walls
# stand on, as HABS measured them - every room of the storey, all of them on its
# level, or the one 'room' names ('2-3' is the third of the second storey).
# Written by '../make_estate.py' from 'estate.json'; run that again rather than
# edit it.

from build123d import Compound, Polygon

ROOMS = %(rooms)s

storey = 1
room = ""


def outline(name):
    return Polygon(*[tuple(p) for p in ROOMS[name]], align=None)


def order(name):
    return tuple(int(n) for n in name.split("-"))


if room:
    result = outline(room)
else:
    # Side by side: an outline is its room's inside face, and walls stand
    # between rooms, so no two outlines touch.
    result = Compound([outline(name) for name in sorted(ROOMS, key=order) if order(name)[0] == int(storey)])

if "show_object" in locals():
    show_object(result, name=room or "plan-%%s" %% storey)  # noqa: F821
"""


def package(estate_dir):
    m = model_of(estate_dir)
    with open(FURNITURE, encoding="utf-8") as f:
        sizes = json.load(f)["sizes"]
    with open(os.path.join(HERE, "shell_template.py"), encoding="utf-8") as f:
        template = f.read()
    write(os.path.join(estate_dir, "shell.py"), template.replace('"@DATA@"', literal(shell_data(m))))
    furniture = furnish(m, sizes)
    floors = {
        "levels": [st["level"] for st in m.storeys],
        "outlines": [[m.blocks[i]["outline"] for i in st["blocks"]] for st in m.storeys],
        "insets": [[m.blocks[i]["thick"] + GAP for i in st["blocks"]] for st in m.storeys],
        "parts": [
            [[part, [m.blocks[b]["outline"] for b in blocks]] for part, _, blocks, _ in parts_of(m, st, k, furniture) if part]
            for k, st in enumerate(m.storeys, 1)
        ],
        "slab": SLAB,
    }
    write(os.path.join(estate_dir, "floor.py"), FLOOR_SCRIPT % {"slab": fmt(SLAB), "data": literal(floors)})
    rooms = {}
    for k, st in enumerate(m.storeys, 1):
        for i, outline in enumerate(st["outlines"], 1):
            rooms["%d-%d" % (k, i)] = [[round(x, 1), round(y, 1)] for x, y in outline]
    write(os.path.join(estate_dir, "rooms.py"), ROOMS_SCRIPT % {"rooms": literal(rooms)})
    graded = landscape_level(estate_dir)
    write_scenes(m, estate_dir, furniture, graded, sizes)
    write(os.path.join(estate_dir, "partcad.yaml"), package_yaml(m, estate_dir, furniture, sizes, graded))


def landscape_level(estate_dir):
    path = os.path.join(estate_dir, "landscape", "site.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("graded", {}).get("level")


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s" % os.path.relpath(path), file=sys.stderr)


def location(x, y, z, angle=0.0):
    return "[[%s, %s, %s], [0, 0, 1], %s]" % (fmt(x), fmt(y), fmt(z), fmt(angle))


def room_links(st, k, i, furniture, sizes):
    """The links of room 'i' (1 is the first) of storey 'k': its walls, and its furniture where it stands."""
    room = st["rooms"][i - 1]
    lines = []
    lines += [
        "  - scene: room-%d-%d" % (k, i),
        "    name: room-%d-%d" % (k, i),
        "    description: %s" % yaml_string(room["name"]),
        "    location: %s" % location(0, 0, st["level"] + GAP),
        "    fixed: true",
    ]
    counts = {}
    for part, x, y, z, heading in furniture.get((k - 1, i - 1), []):
        name = short(part)
        counts[name] = counts.get(name, 0) + 1
        # Placed by its model's origin: the middle of its footprint, less the turned offset of its box.
        x0, y0, z0, x1, y1, z1 = sizes[full(part)]
        a = math.radians(heading)
        bx, by = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        ox, oy = x - (math.cos(a) * bx - math.sin(a) * by), y - (math.sin(a) * bx + math.cos(a) * by)
        lines += [
            "  - part: %s" % name,
            "    name: room-%d-%d-%s-%d" % (k, i, name, counts[name]),
            "    location: %s" % location(round(ox, 1), round(oy, 1), round(z - z0, 1), heading),
            "    fixed: true",
        ]
    return lines


# What one picture has memory for: a furnished storey is drawn with every model of its furniture loaded at once - 29
# pieces took 11 GB, and 32, Scotty's Castle's first floor, are the most drawn here in 16 (34 of Grant-Kohrs' were
# not). A storey with more is pictured a part at a time, each part a scene of its own, which the storey's scene
# places: its rooms in the house's main block ('main'), then the rest ('wings') - or, where the rest is more than
# that still, its largest wing ('wing') before the rest. Named so that the README, which sorts them, lists them so.
MAX_PICTURED = 32


def block_label(m, b):
    """A block's name, short: 'rear wing (1890 kohrs addition, ...)' is the rear wing."""
    return m.blocks[b]["name"].split("(")[0].split(",")[0].strip()


def parts_of(m, st, k, furniture):
    """'[(part, room indices, blocks, label)]': the scenes storey 'k' is pictured as; one, with part None, if whole."""
    rooms = list(range(len(st["rooms"])))

    def pieces(chosen):
        return sum(len(furniture.get((k - 1, i), [])) for i in chosen)

    by_block = {}
    for i in rooms:
        by_block.setdefault(st["room_blocks"][i], []).append(i)
    if pieces(rooms) <= MAX_PICTURED or 0 not in by_block or None in by_block or len(by_block) < 2:
        return [(None, rooms, sorted(by_block, key=str), st["name"])]
    others = sorted((b for b in by_block if b != 0), key=lambda b: (-pieces(by_block[b]), b))
    rest = sorted(i for b in others for i in by_block[b])
    parts = [("main", by_block[0], [0], "main block")]
    if pieces(rest) <= MAX_PICTURED or len(others) < 2:
        return parts + [("wings", rest, others, "wings")]
    wing, small = others[0], others[1:]
    return parts + [
        ("wing", by_block[wing], [wing], block_label(m, wing)),
        ("wings", sorted(i for b in small for i in by_block[b]), small, "other wings"),
    ]


def part_title(st, part, label):
    return st["name"] if part is None else "%s (%s)" % (st["name"], label)


def above(estate_dir, m, scene, title):
    """The scene of 'scene' seen from above: it alone, for a picture of it as a plan."""
    write(
        os.path.join(estate_dir, "%s-above.assy" % scene),
        "\n".join(
            [
                "# %s of %s, seen from above: for a picture of it as a plan. Written by '../make_estate.py'." % (title, m.estate["name"]),
                "links:",
                "  - scene: %s" % scene,
                "    name: %s" % scene,
                "    fixed: true",
            ]
        )
        + "\n",
    )
    return "%s-above.assy" % scene


def write_scenes(m, estate_dir, furniture, graded, sizes):
    written = set()
    for k, st in enumerate(m.storeys, 1):
        parts = parts_of(m, st, k, furniture)
        for part, rooms, _, label in parts:
            scene = "storey-%d" % k if part is None else "storey-%d-%s" % (k, part)
            title = part_title(st, part, label)
            lines = [
                "# %s of %s: its floor, its rooms' walls, its furniture. Written by '../make_estate.py'." % (title, m.estate["name"]),
                "links:",
                "  - part: floor",
                "    name: floor",
                "    params: {storey: %d}" % k if part is None else "    params: {storey: %d, part: %s}" % (k, part),
                "    fixed: true",
            ]
            for i in rooms:
                lines += room_links(st, k, i + 1, furniture, sizes)
            write(os.path.join(estate_dir, "%s.assy" % scene), "\n".join(lines) + "\n")
            written |= {"%s.assy" % scene, above(estate_dir, m, scene, title)}
        if parts[0][0] is not None:
            lines = ["# %s of %s: its parts. Written by '../make_estate.py'." % (st["name"], m.estate["name"]), "links:"]
            for part, *_ in parts:
                lines += ["  - scene: storey-%d-%s" % (k, part), "    name: storey-%d-%s" % (k, part), "    fixed: true"]
            write(os.path.join(estate_dir, "storey-%d.assy" % k), "\n".join(lines) + "\n")
            written.add("storey-%d.assy" % k)
    # What an earlier run wrote of a storey and this one did not.
    for name in os.listdir(estate_dir):
        if name.startswith("storey-") and name.endswith(".assy") and name not in written:
            os.remove(os.path.join(estate_dir, name))
    lines = ["# The inside of %s: every storey. Written by '../make_estate.py'." % m.estate["name"], "links:"]
    for k, st in enumerate(m.storeys, 1):
        lines += ["  - scene: storey-%d" % k, "    name: storey-%d" % k, "    fixed: true"]
    write(os.path.join(estate_dir, "interior.assy"), "\n".join(lines) + "\n")
    write(
        os.path.join(estate_dir, "house.assy"),
        "\n".join(
            [
                "# %s: its outside, and its inside in the air its outside leaves. Written by '../make_estate.py'." % m.estate["name"],
                "links:",
                "  - part: shell",
                "    name: shell",
                "    fixed: true",
                "  - scene: interior",
                "    name: interior",
                "    fixed: true",
            ]
        )
        + "\n",
    )
    # Retired: 'estate' is pictured as this was, by leaving out of its picture the inside nobody outside sees.
    retired = os.path.join(estate_dir, "outside.assy")
    if os.path.exists(retired):
        os.remove(retired)
    if graded is None:
        return
    tx, ty = to_land(m, 0.0, 0.0)
    write(
        os.path.join(estate_dir, "estate.assy"),
        "\n".join(
            [
                "# %s where it stands: the landscape around it, graded level under the house, and the house a" % m.estate["name"],
                "# millimetre above it. Written by '../make_estate.py'.",
                "links:",
                "  - package: landscape",
                "    scene: landscape",
                "    name: landscape",
                "    fixed: true",
                "  - scene: house",
                "    name: house",
                "    location: %s" % location(tx, ty, graded + GAP, turn(m)),
                "    fixed: true",
            ]
        )
        + "\n",
    )


def yaml_string(text):
    return json.dumps(text)


# The pictures in the README, each a 'render:' on the object pictured: rendered by 'render_images.sh', one at a time,
# since the scenes declare 'timeout:' and the examples' CI sweep ('--fast-only') passes them over. A furnished storey
# is drawn through the walls nearest the camera (see '//builtin/building:wall'), from the front right, above.
PICTURE_SIZE = "1600x1000"
VIEWS = {"iso": ([100, -100, 100], [0, 0, 1]), "top": ([0, 0, 100], [0, 1, 0])}


def picture(view, keep=None):
    """The lines of a scene's 'render:': a shaded PNG from 'view', of the links 'keep' names ('pc render --filter')."""
    origin, up = VIEWS[view]
    lines = [
        "    render:",
        "      png:",
        "        prefix: images",
        "        style: shaded",
        "        size: %s" % PICTURE_SIZE,
        "        viewport_origin: %s" % json.dumps(origin),
        "        viewport_up: %s" % json.dumps(up),
    ]
    if keep:
        lines += ["        filter: %s" % keep]
    return lines


# A plan is a drawing, and is rendered by the examples' CI as everything else there is: the same bytes every time.
DRAWING = ["    render:", "      svg:", "        prefix: images", "        reproducible: true"]


def package_yaml(m, estate_dir, furniture, sizes, graded):
    e = m.estate
    out = [
        "# %s, generated by '../make_estate.py' from 'estate.json': run it again rather than edit this." % e["name"],
        "desc: %s" % yaml_string(desc_of(m)),
        "url: %s" % e.get("url", e["sources"][0]["url"]),
        "",
        "docs:",
        "  name: %s" % yaml_string(e["name"]),
    ]
    split = [st["name"] for k, st in enumerate(m.storeys, 1) if parts_of(m, st, k, furniture)[0][0] is not None]
    intro, usage = usage_of(m, graded, estate_dir, split)
    out += ["  intro: |"] + ["    " + line if line else "" for line in intro.split("\n")]
    out += ["  usage: |"] + ["    " + line if line else "" for line in usage.split("\n")]
    out += [
        "",
        "# A house that stands, painted to be looked at: nothing here is made.",
        "manufacturable: false",
        "",
        "colors:",
    ]
    for name, (display, desc) in sorted(m.colours.items()):
        out += ["  %s:" % name, "    desc: %s" % yaml_string(desc), '    display: "%s"' % display, "    manufacturable: false"]
    out += ["", "sketches:"]
    for k, st in enumerate(m.storeys, 1):
        # One plan for the storey: its rooms are all on its level (each stands at the storey's 'level').
        rooms = "; ".join("%d-%d %s" % (k, i, room["name"]) for i, room in enumerate(st["rooms"], 1))
        out += [
            "  plan-%d:" % k,
            "    type: build123d",
            "    path: rooms.py",
            "    desc: %s" % yaml_string("%s, its plan: the outlines of its rooms, which their walls stand on - %s." % (st["name"], rooms)),
            "    parameters:",
            "      storey: {type: int, default: %d, desc: %s}" % (k, yaml_string("Which storey's plan, from 1 to %d." % len(m.storeys))),
            '      room: {type: string, default: "", desc: "One room of it alone, as \'%d-1\'; every room by default."}' % k,
        ] + DRAWING
    out += [
        "",
        "parts:",
        "  shell:",
        "    type: build123d",
        "    path: shell.py",
        "    desc: %s" % yaml_string(
            "The outside of %s, as one solid painted face by face: walls, roof, chimneys, dormers, porches, steps, every "
            "door and window, and none of its inside." % e["name"]
        ),
        "  floor:",
        "    type: build123d",
        "    path: floor.py",
        "    desc: A storey's floor, inside the shell.",
        "    parameters:",
        "      storey: {type: int, default: 1, desc: %s}" % yaml_string("Which storey's, from 1 to %d." % len(m.storeys)),
        '      part: {type: string, default: "", desc: "All of it, or a part a storey too large for one picture is pictured in: \'main\', \'wing\' or \'wings\'."}',
        '      color: {type: string, default: ":floorboards"}',
    ]
    used = sorted({short(p) for items in furniture.values() for p, *_ in items})
    by_short = {short(p): full(p) for items in furniture.values() for p, *_ in items}
    for name in used:
        part = by_short[name]
        x0, y0, z0, x1, y1, z1 = sizes[part]
        w, d, h = x1 - x0, y1 - y0, z1 - z0
        # The box is where the model is, in the model's own frame, so the model is drawn as it is: no part of this
        # package stands between the two, and the model is checked in its own package, not here.
        out += [
            "  %s:" % name,
            "    type: basic",
            "    desc: %s" % yaml_string("A stand-in for %s, its box as large as it is and where it is; drawn as it." % part.rsplit(":", 1)[1]),
            "    cuboid: [%s, %s, %s]" % (fmt(round(w, 1)), fmt(round(d, 1)), fmt(round(h, 1))),
            "    offset: %s" % location(round((x0 + x1) / 2.0, 2), round((y0 + y1) / 2.0, 2), round((z0 + z1) / 2.0, 2)),
            "    visual: %s" % yaml_string(part),
            "    parameters:",
            '      color: {type: string, default: ":wood"}',
        ]
    out += ["", "scenes:"]
    for k, st in enumerate(m.storeys, 1):
        for i, room in enumerate(st["rooms"], 1):
            out += [
                "  room-%d-%d:" % (k, i),
                "    type: walls",
                "    desc: %s" % yaml_string("The walls of %s, %s." % (room["name"], st["name"].lower())),
                "    sketch: %s" % yaml_string("plan-%d;room=%d-%d" % (k, k, i)),
                "    height: %s" % fmt(st["heights"][i - 1]),
                "    thickness: %s" % fmt(st["thickness"]),
                "    parameters:",
                '      color: {type: string, default: ":%s"}' % WALL_PLASTER,
            ]
    slow = ["    # Furnished: longer to build and to check than PartCAD waits by default.", "    timeout: 1800"]
    for k, st in enumerate(m.storeys, 1):
        parts = parts_of(m, st, k, furniture)
        if parts[0][0] is not None:
            # Too much furniture for one picture: the storey places its parts, and they are pictured.
            out += [
                "  storey-%d:" % k,
                "    type: assy",
                "    path: storey-%d.assy" % k,
                "    desc: %s" % yaml_string(
                    "%s, furnished, as the scenes of its parts - %s - one picture having memory for none of it whole."
                    % (st["name"], ", ".join(label for _, _, _, label in parts))
                ),
            ] + slow
        for part, _, _, label in parts:
            scene = "storey-%d" % k if part is None else "storey-%d-%s" % (k, part)
            title = part_title(st, part, label)
            out += [
                "  %s:" % scene,
                "    type: assy",
                "    path: %s.assy" % scene,
                "    desc: %s" % yaml_string("%s, furnished: its floor, its rooms' walls, its furniture." % title),
            ]
            out += slow + picture("iso")
            out += [
                "  %s-above:" % scene,
                "    type: assy",
                "    path: %s-above.assy" % scene,
                "    desc: %s" % yaml_string("%s from above: its rooms' walls and furniture, as a plan." % title),
            ]
            out += slow + picture("top")
    out += ["  interior:", "    type: assy", "    path: interior.assy", "    desc: Every storey, furnished."] + slow
    # The house as it is seen: its shell. Its inside is built, and left out of the picture, which it is not in.
    out += [
        "  house:",
        "    type: assy",
        "    path: house.assy",
        "    desc: %s" % yaml_string("%s: its outside, one solid painted face by face, and its furnished inside within it." % e["name"]),
    ]
    out += slow + picture("iso", "{shell: null}")
    if graded is not None:
        out += [
            "  estate:",
            "    type: assy",
            "    path: estate.assy",
            "    desc: %s" % yaml_string("%s where it stands: the landscape, graded under the house, and the house." % e["name"]),
            "    gravity: [0, 0, -9.81]",
        ]
        out += slow + picture("iso", "{landscape: null, house: {shell: null}}")
    out += ["", "render:", "  readme:", ""]
    return "\n".join(out)


def desc_of(m):
    e = m.estate
    return "%s (%s acres), its house as the Historic American Buildings Survey measured it: the outside one solid, the inside its rooms' walls and furniture, on the ground where it stands." % (
        e["name"],
        fmt(e["acres"]),
    )


def usage_of(m, graded, estate_dir, split=()):
    """'(intro, usage)': the README's text before its usage, and the usage, each within what the schema takes.

    The intro is what the estate is - what of it is where, and what of it is approximate - and the usage how it
    is used, rendered and replaced, with the sources everything was read from.
    """
    e = m.estate
    loc = e["location"]
    lines = [
        "%s: %s acres, at %.5f, %.5f (%s)." % (e["name"], fmt(e["acres"]), loc["lat"], loc["lon"], e["acres_source"].split(";")[0].split(" (")[0]),
        "Its house as the Historic American Buildings Survey measured it, everything worked out by",
        "`../make_estate.py` from `estate.json` - what was read off the survey's drawings - and the ground",
        "around it from the gen-landscape skill.",
        "",
        "Its scenes nest, and each is pictured below: %s," % ("`estate`, the whole of it where it stands, then the house" if graded is not None else "the house"),
        "then each storey furnished and the same storey from above (`storey-<n>`, `storey-<n>-above`);",
        "each storey's plan is a sketch, `plan-<n>`.",
        "",
    ]
    if split:
        lines += [
            "%s %s more furniture than one picture has memory for, and %s pictured in parts, each a scene"
            % (" and ".join(split), "has" if len(split) == 1 else "have", "is" if len(split) == 1 else "are"),
            "which the storey's own places: its rooms in the house's main block (`storey-<n>-main`), its",
            "largest wing (`-wing`) where the rest is more than one picture too, and the rest (`-wings`).",
            "",
        ]
    lines += [
        "- `shell` is the outside, one solid painted face by face: everything solid of the house -",
        "  walls, roof, chimneys, dormers, porches, steps - less the air its rooms stand in, with every door",
        "  and window cut through it. It is the house as it looks from outside, and stays as it is.",
        "- Each storey's plan, `plan-<storey>`, is the outlines of all of its rooms, which are on its",
        "  level; `plan-<storey>;room=<storey>-<n>` is one of them alone.",
        "- Each room is a `walls` scene on its outline (`room-<storey>-<n>`): its walls as thick as its",
        "  storey's thinnest partition lets them be, and under a roof only as high as the roof lets them",
        "  stand. Where a room's walls reach into the outside walls, they are carved out of the shell, so the",
        "  two never share space.",
        "- Its furniture is NVIDIA's ArchVis and SimReady models from `//pub/collection/openusd`: each a",
        "  `basic` part as large as `pc info` measured it and where it is - what a check collides with and a",
        "  simulation moves - drawn as the model, set against the walls by what each room is for, clear of",
        "  its doors.",
    ]
    if graded is not None:
        lines += [
            "- `landscape` is the ground around it and what OpenStreetMap maps on it (the gen-landscape",
            "  skill)%s, less the house's own outline, with a level pad graded under the house at %s mm."
            % (", with what the survey's site plan shows of the grounds" if m.extras else "", fmt(graded)),
            "  The house stands a millimetre above it.",
        ]
    lines += ["", "### What is approximate", ""]
    lines += ["- " + note for note in e["notes"]]
    moved = [(st["name"], r["name"]) for st in m.storeys for r, o in zip(st["rooms"], st["outlines"]) if o != ccw([tuple(p) for p in r["polygon"]])]
    if moved:
        lines.append(
            "- %d rooms drawn edge to edge, nearer each other than two thin walls, or out to the house's own outline,"
            " are moved in by up to a few centimetres, so that each has walls of its own and the outside stays whole."
            % len(moved)
        )
    lines.append(
        "- The rooms' walls are whole: a `walls` scene stands a wall on every edge of its outline and has no doorways"
        " yet, so a room's doors are measured - its furniture keeps clear of them - but not cut through its walls."
    )
    intro = "\n".join(lines)
    lines = [
        "```shell",
        "pc render -t png --style shaded -S estate     # the house where it stands",
        "pc render -t png --style shaded -S interior   # its rooms, furnished",
        "pc qual test -S house                         # nothing inside it shares space with anything else",
        "```",
        "",
        "The scenes declare `timeout:`, so the examples' CI sweep (`--fast-only`) passes over them and their",
        "pictures: render them here, where nothing is left out, with `./render_images.sh %s`, beside"
        % os.path.basename(os.path.abspath(estate_dir)),
        "`make_estate.py`. Each picture is a `render:` on the object it is of: `house` and `estate` leave",
        "the inside out of theirs (`filter:`), which nobody outside sees.",
        "",
        "### The ground from Google Earth instead",
        "",
        "With a Google Maps Platform key of your own (`pc login //pub/collection/google-earth:google_earth_repo`;",
        "see [partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth)), the ground",
        "can be what Google Earth shows here, fetched with your key whenever it is built and kept nowhere:",
        "link",
        "`//pub/collection/google-earth/places:surface;lat=%.6f,lon=%.6f,size=%s` in place of `landscape`."
        % (loc["lat"], loc["lon"], fmt(m.size)),
        "Its frame is this landscape's - X east, Y north, the house's middle at the origin - so the house's",
        "`location` holds; stand it at the height `pc info` measures for the surface there.",
    ]
    lines += ["", "### Sources", ""]
    import re

    for source in e["sources"]:
        # The drawing's file where it was read is no use to a reader: what it is and where it is published are.
        what = re.sub(r"\s*\((local: ?)?[\w.-]+\.(png|jpe?g|tiff?)\)$", "", source["what"].split(" (local")[0])
        lines.append("- [%s](%s): %s" % (what[0].upper() + what[1:], source["url"], source.get("licence", "")))
    return intro, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("site", help="fetch and grade the landscape, and write its package")
    a.add_argument("estate")
    a.add_argument("--offline", action="store_true", help="grade the site.json there is, fetching nothing")
    b = sub.add_parser("package", help="write the house's package")
    b.add_argument("estate")
    args = parser.parse_args()
    if args.command == "site":
        site(args.estate, offline=args.offline)
    else:
        package(args.estate)


if __name__ == "__main__":
    main()
