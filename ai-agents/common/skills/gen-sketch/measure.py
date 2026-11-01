#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Measure the dimensions of a drawing: a PartCAD SVG render, or a raster image.

Shipped beside the `gen-sketch` skill's `SKILL.md`, which says when to run it.
Reading a dimension off a picture by eye is a guess; reading it off the numbers
the picture is made of is a measurement. This does the second, so that a target
dimension and a candidate's dimension are compared as numbers:

    python measure.py svg <drawing.svg> [--layer NAME]... [--all-layers] [--tolerance T]
                          [--digits N] [--limit N] [--json]
    python measure.py image <picture.png> [--row Y]... [--column X]... [--no-bbox]
                            [--crop X0,Y0,X1,Y1] [--threshold N] [--background R,G,B]
                            [--px-per-mm K | --calibrate PX=MM] [--json]

`svg` reads an SVG -- written for what `pc render -t svg` and `pc adhoc render
... x.svg` write, and good for any other SVG too -- and reports, in the drawing's
own units with Y up: the extent; every circle (diameter and centre); every arc
(radius, centre, sweep); every ellipse (both diameters, centre, angle); the
vertical and horizontal edges, grouped by the X or Y they stand at, with what
they span; the other straight edges; and any closed outline nothing else
explains. Positions are also given from the left and from the bottom of the
extent, because where a projection puts its origin depends on the hidden-line
algorithm that drew it, and a distance between two features does not. The page
size the file declares is reported beside them, since that -- not the units --
is the scale PartCAD's `svg` sketch type reads a file at.

In a PartCAD render the units are millimetres of the plane of the view: the
numbers in the file are the model's, and only the `scale(1,-1)` on the outer
group (and the page size on `<svg>`) is about display. A circle the polygonal
projection drew as a polygon is recognized and fitted, and said to be fitted.
Only the `Visible*` layers are read when there are any, so the ports, interfaces
and annotations an overlay adds are not mistaken for geometry.

`image` reads a raster picture (Pillow is needed for it, and for it only) and
reports, in pixels: the bounding box of everything that is not background; and,
along each `--row` and `--column` asked for, every run of ink it crosses, with
its start, its end and its centre (the intensity-weighted centre, so a line's
position is known to a fraction of a pixel). `--calibrate 412=100` says that 412
pixels are 100 mm, and every length is then given in millimetres as well. What
those millimetres mean in a picture that is not an orthographic view -- an
isometric, a perspective photograph -- is the skill's to say, not this script's.
Pixel coordinates are the image's own: X to the right, Y down, from the top-left
corner.

Both print text by default and JSON with `--json`. Nothing but the standard
library is needed for `svg`.
"""

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Plane geometry.


class Affine:
    """A 2D affine map: x' = a*x + c*y + e, y' = b*x + d*y + f (SVG's matrix order)."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    def __matmul__(self, other):
        """self applied after other."""
        return Affine(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )

    def point(self, x, y):
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def linear(self):
        """The linear part as ((m00, m01), (m10, m11)), acting on column vectors."""
        return ((self.a, self.c), (self.b, self.d))


# What every point goes through last: SVG's Y points down the page, a drawing's
# (and PartCAD's) up. A PartCAD render flips its group with 'scale(1,-1)', so
# composing that and then this gives back exactly the numbers in the file.
Y_UP = Affine(1.0, 0.0, 0.0, -1.0, 0.0, 0.0)

_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def numbers(text):
    return [float(token) for token in _NUMBER.findall(text or "")]


def parse_transform(text):
    """An SVG 'transform' attribute as one Affine."""
    result = Affine()
    for name, arguments in _TRANSFORM.findall(text or ""):
        values = numbers(arguments)
        if name == "matrix" and len(values) == 6:
            step = Affine(*values)
        elif name == "translate" and values:
            step = Affine(e=values[0], f=values[1] if len(values) > 1 else 0.0)
        elif name == "scale" and values:
            step = Affine(a=values[0], d=values[1] if len(values) > 1 else values[0])
        elif name == "rotate" and values:
            angle = math.radians(values[0])
            cos, sin = math.cos(angle), math.sin(angle)
            step = Affine(cos, sin, -sin, cos)
            if len(values) == 3:
                cx, cy = values[1], values[2]
                step = Affine(e=cx, f=cy) @ step @ Affine(e=-cx, f=-cy)
        elif name == "skewX" and values:
            step = Affine(c=math.tan(math.radians(values[0])))
        elif name == "skewY" and values:
            step = Affine(b=math.tan(math.radians(values[0])))
        else:
            continue
        result = result @ step
    return result


def singular(m):
    """The semi-axes and the major axis angle of the unit circle mapped by the 2x2 matrix 'm'.

    Returns (major, minor, angle in radians). The closed-form SVD of a 2x2 matrix.
    """
    (p, q), (r, s) = m
    e, f, g, h = (p + s) / 2.0, (p - s) / 2.0, (r + q) / 2.0, (r - q) / 2.0
    big, small = math.hypot(e, h), math.hypot(f, g)
    angle = (math.atan2(h, e) + math.atan2(g, f)) / 2.0
    return big + small, abs(big - small), angle


def distance(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def fit_circle(points):
    """The least-squares circle through 'points' (Kasa's), as ((cx, cy), r, worst residual)."""
    n = float(len(points))
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for x, y in points:
        u, v = x - mx, y - my
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-30:
        return None
    rhs_u = (suuu + suvv) / 2.0
    rhs_v = (svvv + svuu) / 2.0
    uc = (rhs_u * svv - rhs_v * suv) / det
    vc = (suu * rhs_v - suv * rhs_u) / det
    center = (uc + mx, vc + my)
    radius = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    worst = max(abs(distance(p, center) - radius) for p in points)
    return center, radius, worst


def turn(a, b, c):
    """The signed angle the polyline turns through at 'b', in radians."""
    first = math.atan2(b[1] - a[1], b[0] - a[0])
    second = math.atan2(c[1] - b[1], c[0] - b[0])
    return (second - first + math.pi) % (2.0 * math.pi) - math.pi


# ---------------------------------------------------------------------------
# Reading an SVG into primitives, in drawing coordinates with Y up.

# A polygonized curve turns through at most this much at each vertex: OCCT
# meshes to an angular deflection of half a radian by default, and the
# projection PartCAD draws by default is of that mesh.
MAX_ARC_TURN = math.radians(31.0)

# Fewest segments a polygon has to have for it to be read as a whole circle.
MIN_CIRCLE_SEGMENTS = 12

# Fewest vertices a polygonized arc is fitted through.
MIN_ARC_VERTICES = 4

CURVE_SAMPLES = 24


class Drawing:
    """Everything read out of the file, before it is classified."""

    def __init__(self):
        self.segments = []  # [(p, q, straight)]: lines, and the polylines curves were sampled into
        self.ellipses = []  # [{"center", "major", "minor", "angle", "arc": None | (start, end, sweep)}]
        self.points = []  # every point the extent has to cover
        self.layers = set()
        self.read = set()
        self.page = None
        self.rounding = None  # half the last decimal place the file's numbers are written to


def _ellipse_point(center, rx, ry, rotation, t):
    cos, sin = math.cos(rotation), math.sin(rotation)
    x, y = rx * math.cos(t), ry * math.sin(t)
    return (center[0] + x * cos - y * sin, center[1] + x * sin + y * cos)


def _add_conic(drawing, transform, center, rx, ry, rotation, t0=0.0, dt=2.0 * math.pi):
    """A circle, an ellipse or an arc of either, given in the element's own coordinates."""
    cos, sin = math.cos(rotation), math.sin(rotation)
    (m00, m01), (m10, m11) = transform.linear()
    # The conic is center + M * R(rotation) * diag(rx, ry) applied to the unit circle.
    shape = (
        (m00 * cos * rx + m01 * sin * rx, -m00 * sin * ry + m01 * cos * ry),
        (m10 * cos * rx + m11 * sin * rx, -m10 * sin * ry + m11 * cos * ry),
    )
    major, minor, angle = singular(shape)
    count = max(8, int(math.ceil(CURVE_SAMPLES * abs(dt) / (2.0 * math.pi))) * 4)
    samples = [
        transform.point(*_ellipse_point(center, rx, ry, rotation, t0 + dt * i / count)) for i in range(count + 1)
    ]
    drawing.points.extend(samples)
    full = abs(abs(dt) - 2.0 * math.pi) < 1e-9
    arc = None
    if not full:
        start, middle, end = samples[0], samples[count // 2], samples[-1]
        # Which way it runs once mapped: a mirror reverses it.
        direction = 1.0 if (shape[0][0] * shape[1][1] - shape[0][1] * shape[1][0]) * dt > 0 else -1.0
        arc = {"start": start, "middle": middle, "end": end, "sweep": math.degrees(abs(dt)) * direction}
    drawing.ellipses.append(
        {"center": transform.point(*center), "major": major, "minor": minor, "angle": angle, "arc": arc}
    )


def _arc_center(p0, p1, rx, ry, rotation, large, sweep):
    """SVG's endpoint arc as (center, rx, ry, start angle, delta angle): the conversion SVG 1.1 F.6.5 gives."""
    cos, sin = math.cos(rotation), math.sin(rotation)
    dx, dy = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    scale = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if scale > 1.0:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, numerator / denominator)) if denominator else 0.0
    if large == sweep:
        factor = -factor
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    center = (cos * cx1 - sin * cy1 + (p0[0] + p1[0]) / 2.0, sin * cx1 + cos * cy1 + (p0[1] + p1[1]) / 2.0)

    def angle(ux, uy):
        return math.atan2(uy, ux)

    t0 = angle((x1 - cx1) / rx, (y1 - cy1) / ry)
    t1 = angle((-x1 - cx1) / rx, (-y1 - cy1) / ry)
    dt = t1 - t0
    if sweep and dt < 0:
        dt += 2.0 * math.pi
    elif not sweep and dt > 0:
        dt -= 2.0 * math.pi
    return center, rx, ry, t0, dt


def _add_polyline(drawing, transform, points, straight):
    mapped = [transform.point(*p) for p in points]
    drawing.points.extend(mapped)
    for p, q in zip(mapped, mapped[1:]):
        if distance(p, q) > 0:
            drawing.segments.append((p, q, straight))


_PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _bezier(points, t):
    while len(points) > 1:
        points = [((1 - t) * p[0] + t * q[0], (1 - t) * p[1] + t * q[1]) for p, q in zip(points, points[1:])]
    return points[0]


def _add_path(drawing, transform, d):
    tokens = _PATH_TOKEN.findall(d or "")
    i, command = 0, None
    current = start = (0.0, 0.0)
    previous_control = None
    run = []

    def flush():
        if len(run) > 1:
            _add_polyline(drawing, transform, run, True)
        run.clear()

    def take():
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    def take_flag():
        # Arc flags may be written without a separator ("a1,1 0 015,5"), which
        # reads as one number: take its first digit, and leave the rest.
        nonlocal i
        token = tokens[i]
        if token[0] in "01" and len(token) > 1 and "." not in token and "e" not in token.lower():
            tokens[i] = token[1:]
            return token[0] == "1"
        i += 1
        return float(token) != 0.0

    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in "Zz":
                if run:
                    run.append(start)
                flush()
                current = start
                previous_control = None
                continue
        if command is None:
            i += 1
            continue
        relative = command.islower()
        upper = command.upper()
        base = current if relative else (0.0, 0.0)
        try:
            if upper == "M":
                flush()
                current = start = (base[0] + take(), base[1] + take())
                run.append(current)
                command = "l" if relative else "L"
                previous_control = None
            elif upper in "LHV":
                if upper == "L":
                    point = (base[0] + take(), base[1] + take())
                elif upper == "H":
                    point = ((current[0] if relative else 0.0) + take(), current[1])
                else:
                    point = (current[0], (current[1] if relative else 0.0) + take())
                if not run:
                    run.append(current)
                run.append(point)
                current = point
                previous_control = None
            elif upper in "CSQT":
                if upper == "C":
                    controls = [(base[0] + take(), base[1] + take()) for _ in range(3)]
                elif upper == "S":
                    reflected = previous_control or current
                    first = (2 * current[0] - reflected[0], 2 * current[1] - reflected[1])
                    controls = [first] + [(base[0] + take(), base[1] + take()) for _ in range(2)]
                elif upper == "Q":
                    controls = [(base[0] + take(), base[1] + take()) for _ in range(2)]
                else:
                    reflected = previous_control or current
                    first = (2 * current[0] - reflected[0], 2 * current[1] - reflected[1])
                    controls = [first, (base[0] + take(), base[1] + take())]
                flush()
                polygon = [current] + controls
                samples = [_bezier(polygon, k / float(CURVE_SAMPLES)) for k in range(CURVE_SAMPLES + 1)]
                _add_polyline(drawing, transform, samples, False)
                previous_control = controls[-2]
                current = controls[-1]
                run.append(current)
            elif upper == "A":
                rx, ry, rotation = take(), take(), take()
                large, sweep = take_flag(), take_flag()
                end = (base[0] + take(), base[1] + take())
                flush()
                if rx == 0 or ry == 0:
                    _add_polyline(drawing, transform, [current, end], True)
                elif distance(current, end) > 0:
                    center, rx, ry, t0, dt = _arc_center(current, end, rx, ry, math.radians(rotation), large, sweep)
                    _add_conic(drawing, transform, center, rx, ry, math.radians(rotation), t0, dt)
                current = end
                run.append(current)
                previous_control = None
            else:
                i += 1
        except (IndexError, ValueError):
            break
    flush()


def _length(element, name):
    values = numbers(element.get(name))
    return values[0] if values else 0.0


_SKIPPED = {"defs", "text", "title", "desc", "metadata", "clipPath", "mask", "marker", "symbol", "style"}


# Millimetres per unit of an SVG length, CSS's: a unitless length or "px" is 1/96 in.
_UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0, "pc": 25.4 / 6.0, "px": 25.4 / 96.0, "": 25.4 / 96.0}


def _rounding(root):
    """Half the last decimal place the coordinates are written to: how far a written number is from the true one."""
    decimals = 0
    for element in root.iter():
        for name in ("d", "points", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "x", "y", "width", "height"):
            for token in _NUMBER.findall(element.get(name) or ""):
                mantissa = token.lower().split("e")[0]
                if "." in mantissa:
                    decimals = max(decimals, len(mantissa.split(".")[1]))
    return 0.5 * 10.0 ** -min(decimals, 15)


def _page(root):
    """The size the <svg> says it is printed at, and what that makes one unit of its drawing, in mm."""
    page = {}
    for name in ("width", "height"):
        match = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)", root.get(name) or "")
        if match and match.group(2) in _UNITS:
            page[name] = float(match.group(1)) * _UNITS[match.group(2)]
    box = numbers(root.get("viewBox"))
    if len(box) == 4:
        page["viewBox"] = box
        if page.get("width") and box[2]:
            page["mm_per_unit"] = page["width"] / box[2]
    return page or None


def _wanted(layer, names, visible_only):
    """Whether an element on 'layer' is read."""
    layer = layer or ""
    if names:
        return any(layer == name or layer.startswith(name) for name in names)
    return layer.startswith("Visible") if visible_only else True


def read_svg(path, layers=None, all_layers=False):
    """The drawing in 'path', reading only the layers chosen (see the module docstring)."""
    tree = ET.parse(path)
    root = tree.getroot()
    found = []

    def walk(element, transform, layer):
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in _SKIPPED:
            return
        transform = transform @ parse_transform(element.get("transform"))
        if tag == "g" and element.get("id"):
            layer = element.get("id")
        if tag in ("line", "polyline", "polygon", "rect", "circle", "ellipse", "path"):
            found.append((element, tag, transform, layer))
        for child in element:
            walk(child, transform, layer)

    walk(root, Y_UP, None)
    drawing = Drawing()
    drawing.page = _page(root)
    drawing.rounding = _rounding(root)
    drawing.layers = sorted({layer for _e, _t, _m, layer in found if layer})
    visible_only = not all_layers and any((layer or "").startswith("Visible") for _e, _t, _m, layer in found)
    for element, tag, transform, layer in found:
        if not _wanted(layer, layers, visible_only):
            continue
        if layer:
            drawing.read.add(layer)
        if tag == "line":
            ends = [(_length(element, "x1"), _length(element, "y1")), (_length(element, "x2"), _length(element, "y2"))]
            _add_polyline(drawing, transform, ends, True)
        elif tag in ("polyline", "polygon"):
            values = numbers(element.get("points"))
            points = list(zip(values[0::2], values[1::2]))
            if tag == "polygon" and points:
                points.append(points[0])
            _add_polyline(drawing, transform, points, True)
        elif tag == "rect":
            x, y = _length(element, "x"), _length(element, "y")
            w, h = _length(element, "width"), _length(element, "height")
            _add_polyline(drawing, transform, [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)], True)
        elif tag == "circle":
            r = _length(element, "r")
            if r > 0:
                center = (_length(element, "cx"), _length(element, "cy"))
                _add_conic(drawing, transform, center, r, r, 0.0)
        elif tag == "ellipse":
            rx, ry = _length(element, "rx"), _length(element, "ry")
            if rx > 0 and ry > 0:
                center = (_length(element, "cx"), _length(element, "cy"))
                _add_conic(drawing, transform, center, rx, ry, 0.0)
        elif tag == "path":
            _add_path(drawing, transform, element.get("d"))
    drawing.read = sorted(drawing.read)
    return drawing


# ---------------------------------------------------------------------------
# Classifying what was read.


class Points:
    """Points snapped together when they are within 'tolerance' of each other."""

    def __init__(self, tolerance):
        self.tolerance = tolerance
        self.cells = {}
        self.points = []

    def key(self, point):
        cx, cy = int(math.floor(point[0] / self.tolerance)), int(math.floor(point[1] / self.tolerance))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in self.cells.get((cx + dx, cy + dy), ()):
                    if distance(self.points[index], point) <= self.tolerance:
                        return index
        self.points.append(point)
        self.cells.setdefault((cx, cy), []).append(len(self.points) - 1)
        return len(self.points) - 1


def chains(segments, tolerance):
    """The segments joined end to end, as [(points, closed)], broken wherever more than two meet."""
    snap = Points(tolerance)
    edges = []
    neighbours = {}
    for p, q, _straight in segments:
        a, b = snap.key(p), snap.key(q)
        if a == b:
            continue
        edges.append((a, b))
        neighbours.setdefault(a, []).append(len(edges) - 1)
        neighbours.setdefault(b, []).append(len(edges) - 1)
    used = [False] * len(edges)

    def follow(node, edge):
        path = [node]
        while True:
            used[edge] = True
            a, b = edges[edge]
            node = b if a == node else a
            path.append(node)
            if len(neighbours[node]) != 2:
                return path
            following = [e for e in neighbours[node] if not used[e]]
            if not following:
                return path
            edge = following[0]

    result = []
    for node, touching in neighbours.items():
        if len(touching) != 2:
            for edge in touching:
                if not used[edge]:
                    result.append(([snap.points[n] for n in follow(node, edge)], False))
    for edge, done in enumerate(used):
        if not done:
            path = follow(edges[edge][0], edge)
            closed = path[0] == path[-1]
            result.append(([snap.points[n] for n in path], closed))
    return result


def straighten(points, closed, tolerance):
    """The vertices of a polyline with the ones collinear with their neighbours dropped."""
    if len(points) < 3:
        return points
    kept = [points[0]]
    for i in range(1, len(points) - 1):
        a, b, c = kept[-1], points[i], points[i + 1]
        length = distance(a, c)
        if length == 0:
            continue
        # How far b stands off the line from a to c.
        off = abs((c[0] - a[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (c[1] - a[1])) / length
        if off > tolerance:
            kept.append(b)
    kept.append(points[-1])
    if closed and len(kept) > 3:
        a, b, c = kept[-2], kept[0], kept[1]
        length = distance(a, c)
        if length and abs((c[0] - a[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (c[1] - a[1])) / length <= tolerance:
            kept = kept[1:-1] + [kept[1]]
    return kept


def _fits(fit, tolerance):
    """Whether a fitted circle is what the polygon was drawn from, rather than a curve that is merely round.

    A polygon the projection drew from a circle has every vertex on the circle,
    to the rounding of the numbers the file was written with ('tolerance' here);
    a polygon drawn from an ellipse or a spline does not, and a circle through
    it is a guess. Never looser than a thousandth of the radius, for a file
    written with so few decimals that its rounding says nothing.
    """
    return fit is not None and fit[2] <= min(tolerance, 1e-3 * fit[1])


def _arc_runs(points, closed, tolerance, fit_tolerance):
    """Split a polyline into (arcs it was polygonized from, the segments left straight)."""
    count = len(points) - 1
    if count < 2:
        return [], [(points[0], points[-1])] if count == 1 else []
    turns = [turn(points[i - 1], points[i], points[i + 1]) for i in range(1, count)]
    if closed:
        turns = [turn(points[-2], points[0], points[1])] + turns
    else:
        turns = [None] + turns
    # turns[i] is the turn at vertex i (between segment i-1 and segment i).
    lengths = [distance(points[i], points[i + 1]) for i in range(count)]

    def bends(i):
        """Whether segment i and segment i-1 could be two pieces of one polygonized arc."""
        t = turns[i % count] if closed or i > 0 else None
        if t is None or abs(t) > MAX_ARC_TURN or abs(t) < 1e-9:
            return False
        a, b = lengths[(i - 1) % count], lengths[i % count]
        return max(a, b) <= 3.0 * min(a, b)

    if closed:
        corners = [i for i in range(count) if not bends(i)]
        if not corners:
            signs = {t > 0 for t in turns}
            fit = fit_circle(points[:-1]) if len(signs) == 1 and count >= MIN_CIRCLE_SEGMENTS else None
            if _fits(fit, fit_tolerance):
                return [{"points": points, "fit": fit, "closed": True}], []
            # A closed curve that turns one way all round and is round to a
            # thousandth of its radius is a circle drawn some other way -- as
            # Bezier curves, the way most drawing programs write one -- and is
            # said to be approximate. An open run is not given that benefit: a
            # short piece of any smooth curve is round to that much.
            if fit is not None and fit[2] <= 1e-3 * fit[1]:
                return [{"points": points, "fit": fit, "closed": True, "approximate": True}], []
        elif corners[0] != 0:
            # Start at a corner, so that no arc is cut in two where the loop happens to begin.
            k = corners[0]
            return _arc_runs(points[k:-1] + points[: k + 1], closed, tolerance, fit_tolerance)

    arcs, straight = [], []
    i = 0
    while i < count:
        j = i + 1
        while j < count and bends(j) and (turns[j] > 0) == (turns[i + 1] > 0 if i + 1 < count else True):
            j += 1
        run = points[i : j + 1]
        if len(run) >= MIN_ARC_VERTICES:
            fit = fit_circle(run)
            if _fits(fit, fit_tolerance):
                arcs.append({"points": run, "fit": fit, "closed": False})
                i = j
                continue
        straight.append((points[i], points[i + 1]))
        i += 1
    return arcs, straight


def _merge_intervals(intervals, tolerance):
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1] + tolerance:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([low, high])
    return merged


def _group(values, tolerance):
    """[(value, items)] grouped by values within 'tolerance' of the group's first."""
    groups = []
    for value, item in sorted(values, key=lambda pair: pair[0]):
        if groups and value - groups[-1][0] <= tolerance:
            groups[-1][1].append((value, item))
        else:
            groups.append((value, [(value, item)]))
    return [(sum(v for v, _ in members) / len(members), [item for _, item in members]) for _, members in groups]


def _gather(items, same):
    """'items' in groups of the ones 'same' says belong together (with the first of a group)."""
    groups = []
    for item in items:
        for group in groups:
            if same(group[0], item):
                group.append(item)
                break
        else:
            groups.append([item])
    return groups


def _slack(a, b, tolerance):
    """How close two arc pieces have to be to be pieces of one circle: looser for a fitted one."""
    if a.get("fit") or b.get("fit"):
        return max(tolerance, 1e-3 * max(a["radius"], b["radius"]))
    return tolerance


def _mean_point(points):
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _to_segment(point, p, q):
    """How far 'point' is from the segment p-q."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0] - p[0]) * dx + (point[1] - p[1]) * dy) / length))
    return distance(point, (p[0] + t * dx, p[1] + t * dy))


def _sweep_of(center, points):
    """The signed sweep in degrees of an arc through 'points' about 'center'."""
    total = 0.0
    for p, q in zip(points, points[1:]):
        a = math.atan2(p[1] - center[1], p[0] - center[0])
        b = math.atan2(q[1] - center[1], q[0] - center[0])
        total += (b - a + math.pi) % (2.0 * math.pi) - math.pi
    return math.degrees(total)


def analyse(drawing, tolerance=None):
    """Classify a drawing into the features the module docstring lists, as a JSON-ready dict."""
    if not drawing.points:
        return {"extent": None, "layers": drawing.layers, "read": drawing.read, "page": drawing.page}
    xs = [p[0] for p in drawing.points]
    ys = [p[1] for p in drawing.points]
    extent = {"xmin": min(xs), "xmax": max(xs), "ymin": min(ys), "ymax": max(ys)}
    extent["width"], extent["height"] = extent["xmax"] - extent["xmin"], extent["ymax"] - extent["ymin"]
    size = max(extent["width"], extent["height"]) or 1.0
    if tolerance is None:
        tolerance = 1e-5 * size
    # What a polygon's vertices may stand off the circle it was drawn from: the
    # file's rounding, with room for the arithmetic of the fit.
    fit_tolerance = max(20.0 * (drawing.rounding or 0.0), 1e-9 * size)

    def place(point):
        return {
            "x": point[0],
            "y": point[1],
            "from_left": point[0] - extent["xmin"],
            "from_bottom": point[1] - extent["ymin"],
        }

    circles, arcs, ellipses = [], [], []
    # Every piece of a circle or of an ellipse, before the pieces of one are put
    # together: a full circle is written as two arcs, and a circle the hidden-line
    # algorithm cut is several.
    round_pieces, oval_pieces = [], []
    for conic in drawing.ellipses:
        if conic["major"] - conic["minor"] <= max(tolerance, 1e-9 * conic["major"]):
            if conic["arc"] is None:
                circles.append({**place(conic["center"]), "diameter": 2.0 * conic["major"], "source": "exact"})
            else:
                round_pieces.append({"center": conic["center"], "radius": conic["major"], **conic["arc"], "fit": None})
        else:
            oval_pieces.append(conic)

    straight, loops = [], []
    for points, closed in chains(drawing.segments, tolerance):
        points = straighten(points, closed, tolerance)
        found, rest = _arc_runs(points, closed, tolerance, fit_tolerance)
        for arc in found:
            center, radius, worst = arc["fit"]
            fitted = {"source": "fitted", "segments": len(arc["points"]) - 1, "residual": worst}
            if arc.get("approximate"):
                fitted["approximate"] = True
            if arc["closed"]:
                circles.append({**place(center), "diameter": 2.0 * radius, **fitted})
            else:
                round_pieces.append(
                    {
                        "center": center,
                        "radius": radius,
                        "start": arc["points"][0],
                        "end": arc["points"][-1],
                        "sweep": _sweep_of(center, arc["points"]),
                        "fit": fitted,
                    }
                )
        straight.extend(rest)
        if closed and not found and len(points) > 5 and len(rest) == len(points) - 1:
            lengths = [distance(p, q) for p, q in rest]
            if max(lengths) <= 3.0 * min(lengths):
                lx = [p[0] for p in points]
                ly = [p[1] for p in points]
                center = ((min(lx) + max(lx)) / 2.0, (min(ly) + max(ly)) / 2.0)
                loops.append(
                    {
                        **place(center),
                        "width": max(lx) - min(lx),
                        "height": max(ly) - min(ly),
                        # Across the corners, and across the flats: a hexagon's two sizes.
                        "widest": 2.0 * max(distance(p, center) for p in points),
                        "narrowest": 2.0 * min(_to_segment(center, p, q) for p, q in rest),
                        "segments": len(rest),
                    }
                )

    def near(a, b, slack):
        return abs(a - b) <= slack

    for group in _gather(
        round_pieces,
        lambda a, b: distance(a["center"], b["center"]) <= _slack(a, b, tolerance)
        and near(a["radius"], b["radius"], _slack(a, b, tolerance)),
    ):
        center = _mean_point([piece["center"] for piece in group])
        radius = sum(piece["radius"] for piece in group) / len(group)
        fitted = [piece["fit"] for piece in group if piece["fit"]]
        how = {"source": "exact"}
        if fitted:
            how = {
                "source": "fitted",
                "segments": sum(f["segments"] for f in fitted),
                "residual": max(f["residual"] for f in fitted),
            }
        total = sum(abs(piece["sweep"]) for piece in group)
        if total >= 360.0 - (0.1 if fitted else 1e-6):
            circles.append({**place(center), "diameter": 2.0 * radius, **how})
            continue
        arcs.append(
            {
                **place(center),
                "radius": radius,
                "sweep": total,
                "pieces": [
                    {"start": list(piece["start"]), "end": list(piece["end"]), "sweep": piece["sweep"]}
                    for piece in group
                ],
                **how,
            }
        )
    for group in _gather(
        oval_pieces,
        lambda a, b: distance(a["center"], b["center"]) <= tolerance
        and near(a["major"], b["major"], tolerance)
        and near(a["minor"], b["minor"], tolerance)
        and near(math.sin(a["angle"] - b["angle"]), 0.0, 1e-6),
    ):
        first = group[0]
        sweep = 360.0 if any(c["arc"] is None for c in group) else sum(abs(c["arc"]["sweep"]) for c in group)
        ellipses.append(
            {
                **place(first["center"]),
                "major": 2.0 * first["major"],
                "minor": 2.0 * first["minor"],
                "angle": math.degrees(first["angle"]) % 180.0,
                "sweep": min(sweep, 360.0),
                "pieces": len(group),
                "source": "exact",
            }
        )

    vertical, horizontal, other = [], [], []
    for p, q in straight:
        dx, dy = q[0] - p[0], q[1] - p[1]
        if abs(dx) <= tolerance:
            vertical.append(((p[0] + q[0]) / 2.0, (min(p[1], q[1]), max(p[1], q[1]))))
        elif abs(dy) <= tolerance:
            horizontal.append(((p[1] + q[1]) / 2.0, (min(p[0], q[0]), max(p[0], q[0]))))
        else:
            other.append(
                {
                    "start": list(p),
                    "end": list(q),
                    "length": distance(p, q),
                    "angle": math.degrees(math.atan2(dy, dx)) % 180.0,
                }
            )

    def stations(found, origin):
        result = []
        for value, spans in _group(found, tolerance):
            merged = _merge_intervals(spans, tolerance)
            result.append(
                {
                    "at": value,
                    "from_origin": value - origin,
                    "spans": merged,
                    "length": sum(high - low for low, high in merged),
                }
            )
        return result

    circles.sort(key=lambda c: (-round(c["diameter"] / tolerance), c["x"], c["y"]))
    arcs.sort(key=lambda a: (-round(a["radius"] / tolerance), a["x"], a["y"]))
    other.sort(key=lambda line: -line["length"])
    return {
        "layers": drawing.layers,
        "read": drawing.read,
        "page": drawing.page,
        "tolerance": tolerance,
        "extent": extent,
        "circles": circles,
        "arcs": arcs,
        "ellipses": ellipses,
        "vertical": stations(vertical, extent["xmin"]),
        "horizontal": stations(horizontal, extent["ymin"]),
        "lines": other,
        "loops": loops,
    }


def format_svg(report, digits=4, limit=40):
    """The report as text for a reader."""

    def n(value):
        text = "%.*f" % (digits, value)
        return "0." + "0" * digits if text.lstrip("-") == "0." + "0" * digits else text

    out = []
    if report.get("extent") is None:
        out.append("nothing drawn on the layers read (%s); the file has: %s" % (report["read"], report["layers"]))
        return "\n".join(out)
    e = report["extent"]
    out.append("layers read: %s (of %s); Y is up" % (", ".join(report["read"]) or "all", report["layers"] or "none"))
    page = report.get("page") or {}
    if any(layer.startswith("Visible") for layer in report["layers"]):
        out.append("a PartCAD render: the numbers below are the model's mm, and its page size is for display only")
    elif page.get("mm_per_unit"):
        out.append(
            "page: %s x %s mm over a viewBox %s wide, so %s mm per unit as printed -- the scale an `svg` sketch"
            " reads this file at; the numbers below are its units"
            % (
                n(page["width"]),
                n(page["height"]) if "height" in page else "?",
                n(page["viewBox"][2]),
                n(page["mm_per_unit"]),
            )
        )
    out.append(
        "extent: width %s  height %s   (x %s .. %s, y %s .. %s)"
        % (n(e["width"]), n(e["height"]), n(e["xmin"]), n(e["xmax"]), n(e["ymin"]), n(e["ymax"]))
    )

    def where(item):
        return "centre (%s, %s), from left %s, from bottom %s" % (
            n(item["x"]),
            n(item["y"]),
            n(item["from_left"]),
            n(item["from_bottom"]),
        )

    def how(item):
        if item.get("approximate"):
            return (
                "  [approximate: a closed curve round to within %s, not drawn as a circle; fitted to %d segments]"
                % (
                    n(item["residual"]),
                    item["segments"],
                )
            )
        if item.get("source") == "fitted":
            return "  [fitted to %d segments, residual %s]" % (item["segments"], n(item["residual"]))
        return ""

    def more(items):
        if len(items) > limit:
            out.append("  ... and %d more (--limit, or --json for every one)" % (len(items) - limit))

    if report["circles"]:
        out.append("circles (%d):" % len(report["circles"]))
        for i, c in enumerate(report["circles"][:limit], 1):
            out.append("  C%d  diameter %s  %s%s" % (i, n(c["diameter"]), where(c), how(c)))
        more(report["circles"])
    if report["arcs"]:
        out.append("arcs, by the circle they are of (%d):" % len(report["arcs"]))
        for i, a in enumerate(report["arcs"][:limit], 1):
            pieces = a["pieces"]
            if len(pieces) == 1:
                run = "from (%s, %s) to (%s, %s)" % (
                    n(pieces[0]["start"][0]),
                    n(pieces[0]["start"][1]),
                    n(pieces[0]["end"][0]),
                    n(pieces[0]["end"][1]),
                )
            else:
                run = "in %d pieces" % len(pieces)
            out.append(
                "  A%d  radius %s  sweep %.2f deg %s  %s%s" % (i, n(a["radius"]), a["sweep"], run, where(a), how(a))
            )
        more(report["arcs"])
    if report["ellipses"]:
        out.append("ellipses (%d):" % len(report["ellipses"]))
        for i, el in enumerate(report["ellipses"][:limit], 1):
            sweep = "" if el["sweep"] >= 360.0 else "  sweep %.2f deg in %d pieces" % (el["sweep"], el["pieces"])
            out.append(
                "  E%d  major %s  minor %s  major axis at %.2f deg%s  %s"
                % (i, n(el["major"]), n(el["minor"]), el["angle"], sweep, where(el))
            )
        more(report["ellipses"])
    for key, label, axis, across, name in (
        ("vertical", "vertical edges, by x", "x", "y", "V"),
        ("horizontal", "horizontal edges, by y", "y", "x", "H"),
    ):
        if report[key]:
            out.append("%s (%d):" % (label, len(report[key])))
            for i, s in enumerate(report[key][:limit], 1):
                spans = ", ".join("%s .. %s" % (n(low), n(high)) for low, high in s["spans"])
                side = "left" if axis == "x" else "bottom"
                out.append(
                    "  %s%d  %s %s  (from %s %s)  spans %s %s  (length %s)"
                    % (name, i, axis, n(s["at"]), side, n(s["from_origin"]), across, spans, n(s["length"]))
                )
            more(report[key])
    if report["lines"]:
        shown = report["lines"][:limit]
        out.append("other straight edges (%d, longest first):" % len(report["lines"]))
        for i, line in enumerate(shown, 1):
            out.append(
                "  L%d  length %s  at %.3f deg  (%s, %s) -> (%s, %s)"
                % (
                    i,
                    n(line["length"]),
                    line["angle"],
                    n(line["start"][0]),
                    n(line["start"][1]),
                    n(line["end"][0]),
                    n(line["end"][1]),
                )
            )
        more(report["lines"])
    if report["loops"]:
        out.append("closed outlines nothing above explains (%d):" % len(report["loops"]))
        for i, loop in enumerate(report["loops"][:limit], 1):
            out.append(
                "  O%d  %s x %s, across %s .. %s through the middle, %d segments  %s"
                % (
                    i,
                    n(loop["width"]),
                    n(loop["height"]),
                    n(loop["narrowest"]),
                    n(loop["widest"]),
                    loop["segments"],
                    where(loop),
                )
            )
        more(report["loops"])
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Raster pictures.


def _pillow():
    """Pillow's Image module, or an exit that says how to get it."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit(
            "Measuring a raster image needs Pillow, which this Python does not have. "
            "Run this with a Python that has it, or install it: python -m pip install pillow"
        )
    return Image


def ink_of(picture, background=None):
    """The picture as ink: per pixel, how far it is from the background, 0..255, and that background.

    The background is the commonest colour of the picture unless it is given --
    in a drawing it is what is left between the lines, and a drawing reaches
    the edge of its frame often enough that the border is no guide -- and a
    transparent pixel is white.
    """
    Image = _pillow()
    from PIL import ImageChops

    rgba = picture.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat = Image.alpha_composite(white, rgba).convert("RGB")
    if background is None:
        colours = flat.getcolors(flat.size[0] * flat.size[1])
        background = max(colours)[1]
    background = tuple(int(channel) for channel in background)
    red, green, blue = ImageChops.difference(flat, Image.new("RGB", flat.size, background)).split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue), background


def _runs(values, threshold):
    """[(start, end, centre)] of the runs of 'values' at or above 'threshold'; 'values' is [(position, ink)]."""
    runs, current = [], []
    for position, value in values:
        if value >= threshold:
            current.append((position, value))
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    result = []
    for run in runs:
        weight = float(sum(value for _p, value in run))
        centre = sum(p * value for p, value in run) / weight
        result.append({"start": run[0][0], "end": run[-1][0], "width": run[-1][0] - run[0][0] + 1, "centre": centre})
    return result


def measure_image(path, rows=(), columns=(), bbox=True, crop=None, threshold=64, px_per_mm=None, background=None):
    Image = _pillow()
    picture = Image.open(path)
    mask, background = ink_of(picture, background)
    width, height = mask.size
    x0, y0, x1, y1 = crop if crop else (0, 0, width - 1, height - 1)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(width - 1, int(x1)), min(height - 1, int(y1))
    report = {
        "size": [width, height],
        "background": list(background),
        "crop": [x0, y0, x1, y1],
        "threshold": threshold,
        "px_per_mm": px_per_mm,
    }
    if bbox:
        region = mask.crop((x0, y0, x1 + 1, y1 + 1)).point(lambda value: 255 if value >= threshold else 0)
        found = region.getbbox()
        report["bbox"] = (
            None
            if found is None
            else {
                "left": x0 + found[0],
                "top": y0 + found[1],
                "right": x0 + found[2] - 1,
                "bottom": y0 + found[3] - 1,
                "width": found[2] - found[0],
                "height": found[3] - found[1],
            }
        )
    ink = mask.load()
    report["rows"] = [
        {"row": int(row), "runs": _runs([(x, ink[x, int(row)]) for x in range(x0, x1 + 1)], threshold)}
        for row in rows
        if 0 <= int(row) < height
    ]
    report["columns"] = [
        {"column": int(column), "runs": _runs([(y, ink[int(column), y]) for y in range(y0, y1 + 1)], threshold)}
        for column in columns
        if 0 <= int(column) < width
    ]
    return report


def format_image(report):
    k = report["px_per_mm"]

    def mm(pixels):
        return "" if not k else " (%.3f mm)" % (pixels / k)

    out = [
        "image %d x %d px, background rgb%s, ink at %d or more from it, inside %s"
        % (report["size"][0], report["size"][1], tuple(report["background"]), report["threshold"], report["crop"])
    ]
    if k:
        out.append("scale: %.6f px per mm (%.6f mm per px)" % (k, 1.0 / k))
    if "bbox" in report:
        b = report["bbox"]
        if b is None:
            out.append("bbox: no ink")
        else:
            out.append(
                "bbox: left %d, top %d, right %d, bottom %d -> width %d px%s, height %d px%s"
                % (
                    b["left"],
                    b["top"],
                    b["right"],
                    b["bottom"],
                    b["width"],
                    mm(b["width"]),
                    b["height"],
                    mm(b["height"]),
                )
            )
    for kind, key in (("row", "rows"), ("column", "columns")):
        for line in report[key]:
            out.append("%s %d: %d run(s) of ink" % (kind, line[kind], len(line["runs"])))
            previous = None
            for i, run in enumerate(line["runs"], 1):
                step = ""
                if previous is not None:
                    gap = run["centre"] - previous["centre"]
                    step = "  centre to previous centre %.2f px%s" % (gap, mm(gap))
                out.append(
                    "  R%d  %d .. %d  (%d px%s), centre %.2f%s"
                    % (i, run["start"], run["end"], run["width"], mm(run["width"]), run["centre"], step)
                )
                previous = run
            if len(line["runs"]) > 1:
                span = line["runs"][-1]["end"] - line["runs"][0]["start"] + 1
                out.append("  first start to last end: %d px%s" % (span, mm(span)))
    return "\n".join(out)


# ---------------------------------------------------------------------------


def _pair(text, separator):
    values = [float(v) for v in text.split(separator)]
    if len(values) != 2 or values[1] == 0:
        raise argparse.ArgumentTypeError("expected <pixels>%s<millimetres>, not %r" % (separator, text))
    return values[0] / values[1]


def _colour(text):
    values = [int(v) for v in text.split(",")]
    if len(values) != 3 or not all(0 <= v <= 255 for v in values):
        raise argparse.ArgumentTypeError("expected R,G,B from 0 to 255, not %r" % text)
    return values


def _box(text):
    values = [float(v) for v in text.split(",")]
    if len(values) != 4:
        raise argparse.ArgumentTypeError("expected X0,Y0,X1,Y1, not %r" % text)
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    svg = sub.add_parser("svg", help="Measure an SVG drawing exactly, from the numbers it is made of")
    svg.add_argument("file")
    svg.add_argument("--layer", action="append", help="Read only this layer (an id of a <g>); repeat for several")
    svg.add_argument("--all-layers", action="store_true", help="Read the overlays too, not only the Visible* layers")
    svg.add_argument("--tolerance", type=float, help="When two numbers are the same (default 1e-5 of the extent)")
    svg.add_argument("--digits", type=int, default=4, help="Decimal places to print (default 4)")
    svg.add_argument("--limit", type=int, default=40, help="Other straight edges to print (default 40)")
    svg.add_argument("--json", action="store_true")

    image = sub.add_parser("image", help="Measure a raster image in pixels, along rows and columns")
    image.add_argument("file")
    image.add_argument("--row", type=float, action="append", default=[], help="Scan along this pixel row")
    image.add_argument("--column", type=float, action="append", default=[], help="Scan along this pixel column")
    image.add_argument("--no-bbox", action="store_true", help="Skip the bounding box of the ink")
    image.add_argument("--crop", type=_box, help="Look only inside X0,Y0,X1,Y1 (pixels, inclusive)")
    image.add_argument("--threshold", type=int, default=64, help="How far from the background ink is (0-255)")
    image.add_argument("--background", type=_colour, help="R,G,B of the background (default: the commonest colour)")
    scale = image.add_mutually_exclusive_group()
    scale.add_argument("--px-per-mm", type=float, help="The picture's scale, to report millimetres too")
    scale.add_argument("--calibrate", type=lambda t: _pair(t, "="), help="PX=MM: that many pixels are that many mm")
    image.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "svg":
        report = analyse(read_svg(args.file, args.layer, args.all_layers), args.tolerance)
        text = json.dumps(report, indent=1) if args.json else format_svg(report, args.digits, args.limit)
    else:
        report = measure_image(
            args.file,
            rows=args.row,
            columns=args.column,
            bbox=not args.no_bbox,
            crop=args.crop,
            threshold=args.threshold,
            px_per_mm=args.px_per_mm or args.calibrate,
            background=args.background,
        )
        text = json.dumps(report, indent=1) if args.json else format_image(report)
    try:
        print(text)
    except BrokenPipeError:
        # Read through 'head': what was wanted has been printed.
        sys.stderr.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
