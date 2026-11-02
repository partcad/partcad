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
    python measure.py compare <first.svg> <second.svg> [--layer NAME]... [--agreement A]
                              [--digits N] [--json]
    python measure.py image <picture.png> [--row Y]... [--column X]... [--no-bbox]
                            [--crop X0,Y0,X1,Y1] [--threshold N] [--background R,G,B]
                            [--px-per-mm K | --calibrate PX=MM] [--json]

`svg` reads an SVG -- written for what `pc render -t svg` and `pc adhoc render
... x.svg` write, and good for any other SVG too -- and reports, in the drawing's
own units with Y up: the extent; every circle (diameter and centre); every arc
(radius, centre, sweep), its pieces put together; every ellipse (both
diameters, centre, angle); the vertical and horizontal edges, grouped by the X
or Y they stand at, with what they span; the other straight edges, each one
however many pieces it was drawn in; the splines (curves drawn as Bezier
curves); and any closed outline nothing else explains. Positions are also given from the left and from the bottom of the
extent, because where a projection puts its origin depends on the hidden-line
algorithm that drew it, and a distance between two features does not. The page
size the file declares is reported beside them, since that -- not the units --
is the scale PartCAD's `svg` sketch type reads a file at.

In a PartCAD render the units are millimetres of the plane of the view: the
numbers in the file are the model's, and only the `scale(1,-1)` on the outer
group (and the page size on `<svg>`) is about display. A circle the polygonal
projection drew as a polygon is recognized and fitted, and said to be fitted --
an ellipse too, and an arc the hidden-line algorithm cut on a chord; a
silhouette, which that projection works out from the triangulation and so draws
only near the curve, is taken as more of the curve whose edge it carries on, or
as an approximate one, and said to be.
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

`compare` reads two SVGs of one object -- in particular the same view rendered
with `reproducible: true` and without it, which draw the same geometry as
different shapes and different numbers of them -- and pairs every feature of
one with the nearest of its kind in the other: it reports each pair that
differs by more than the agreement (5e-4 of the size by default, the polygonal
projection's own error), and each feature only one of them has. It exits 1
when they disagree.

All three print text by default and JSON with `--json`. Nothing but the
standard library is needed for `svg` and `compare`.
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

# Fewest vertices a polygonized arc is fitted through: a circle needs three to
# be any circle at all, an ellipse five; one more, so that the fit is a test.
MIN_ARC_VERTICES = 4
MIN_ELLIPSE_VERTICES = 6

CURVE_SAMPLES = 24


class Drawing:
    """Everything read out of the file, before it is classified."""

    def __init__(self):
        self.segments = []  # [(p, q, straight)]: lines, and the polylines curves were sampled into
        self.conics = []  # every circle, ellipse and arc of either, as _conic() records them
        self.points = []  # every point the extent has to cover
        self.layers = set()
        self.read = set()
        self.page = None
        self.rounding = None  # half the last decimal place the file's numbers are written to


def _add_conic(drawing, transform, center, rx, ry, rotation, t0=0.0, dt=2.0 * math.pi):
    """A circle, an ellipse or an arc of either, given in the element's own coordinates."""
    cos, sin = math.cos(rotation), math.sin(rotation)
    (m00, m01), (m10, m11) = transform.linear()
    # The conic is center + M * R(rotation) * diag(rx, ry) applied to the unit circle.
    shape = (
        (m00 * cos * rx + m01 * sin * rx, -m00 * sin * ry + m01 * cos * ry),
        (m10 * cos * rx + m11 * sin * rx, -m10 * sin * ry + m11 * cos * ry),
    )
    full = abs(abs(dt) - 2.0 * math.pi) < 1e-9
    drawing.conics.append(_conic(transform.point(*center), shape, t0, None if full else dt))


def _conic(center, shape, t0=0.0, dt=None, fit=None):
    """One circle, ellipse, or arc of either: the points center + shape * (cos t, sin t), t from t0 through dt.

    'shape' is a 2x2 matrix, so a circle, an ellipse and either one mapped
    through any transform are all the same record; 'dt' is None for a whole
    one. 'fit' says how a fitted one was fitted, and is None for one the file
    drew as a curve.
    """
    major, minor, angle = singular(shape)
    return {
        "center": center,
        "shape": shape,
        "t0": t0,
        "dt": dt,
        "major": major,
        "minor": minor,
        "angle": angle,
        "fit": fit,
    }


def _conic_point(conic, t):
    (a00, a01), (a10, a11) = conic["shape"]
    c = conic["center"]
    return (c[0] + a00 * math.cos(t) + a01 * math.sin(t), c[1] + a10 * math.cos(t) + a11 * math.sin(t))


def _conic_extremes(conic):
    """The points of a conic farthest left, right, down and up -- within its arc -- and the ends of the arc.

    Exact, where a polygon's vertices or a curve's samples only come close: they
    are what the extent is measured to, so that a circle drawn as a polygon and
    the same circle drawn as itself give the drawing one size.
    """
    (a00, a01), (a10, a11) = conic["shape"]
    candidates = []
    for t in (math.atan2(a01, a00), math.atan2(a11, a10)):
        candidates.extend((t, t + math.pi))
    t0, dt = conic["t0"], conic["dt"]
    if dt is None:
        return [_conic_point(conic, t) for t in candidates]
    inside = []
    for t in candidates:
        along = (t - t0) % (2.0 * math.pi) if dt > 0 else (t0 - t) % (2.0 * math.pi)
        if along <= abs(dt):
            inside.append(t)
    return [_conic_point(conic, t) for t in inside + [t0, t0 + dt]]


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
    seen = set()
    for p, q, *_ in segments:
        a, b = snap.key(p), snap.key(q)
        # The exact projection can draw one edge twice (a chamfer seen edge on
        # is one), and a second copy is not a second edge.
        if a == b or (min(a, b), max(a, b)) in seen:
            continue
        seen.add((min(a, b), max(a, b)))
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


def _fits(residual, size, tolerance):
    """Whether a fitted curve is what the polygon was drawn from, rather than a curve that is merely close.

    A polygon the projection drew from a circle or an ellipse has every vertex
    on it, to the rounding of the numbers the file was written with
    ('tolerance' here); a polygon drawn from a spline does not, and a curve
    through it is a guess. Never looser than a thousandth of the curve's size,
    for a file written with so few decimals that its rounding says nothing.
    """
    return residual <= min(tolerance, 1e-3 * size)


def _solve(matrix, vector):
    """'matrix' x = 'vector' by Gaussian elimination with partial pivoting, or None when it is singular."""
    n = len(vector)
    rows = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda r: abs(rows[r][column]))
        if abs(rows[pivot][column]) < 1e-300:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for r in range(column + 1, n):
            factor = rows[r][column] / rows[column][column]
            for c in range(column, n + 1):
                rows[r][c] -= factor * rows[column][c]
    solution = [0.0] * n
    for r in reversed(range(n)):
        solution[r] = (rows[r][n] - sum(rows[r][c] * solution[c] for c in range(r + 1, n))) / rows[r][r]
    return solution


def fit_ellipse(points):
    """The least-squares conic through 'points', when it is an ellipse.

    As ((cx, cy), semi-major, semi-minor, angle of the major axis in radians,
    worst residual), the residual being each point's first-order (Sampson)
    distance from the ellipse; None when the conic is not an ellipse.
    """
    n = len(points)
    if n < 6:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    scale = max(max(abs(p[0] - mx), abs(p[1] - my)) for p in points) or 1.0
    rows = []
    for x, y in points:
        u, v = (x - mx) / scale, (y - my) / scale
        rows.append((u * u, u * v, v * v, u, v))
    normal = [[sum(row[i] * row[j] for row in rows) for j in range(5)] for i in range(5)]
    solution = _solve(normal, [sum(row[i] for row in rows) for i in range(5)])
    if solution is None:
        return None
    # a u^2 + b uv + c v^2 + d u + e v = 1, in the centred and scaled coordinates.
    a, b, c, d, e = solution
    det = 4.0 * a * c - b * b
    if det <= 0:
        return None
    u0 = (b * e - 2.0 * c * d) / det
    v0 = (b * d - 2.0 * a * e) / det
    k = 1.0 - (a * u0 * u0 + b * u0 * v0 + c * v0 * v0 + d * u0 + e * v0)
    mean, spread = (a + c) / 2.0, math.hypot((a - c) / 2.0, b / 2.0)
    low, high = mean - spread, mean + spread
    if k <= 0 or low <= 0:
        return None
    major, minor = math.sqrt(k / low) * scale, math.sqrt(k / high) * scale
    angle = 0.5 * math.atan2(b, a - c) + math.pi / 2.0
    center = (mx + u0 * scale, my + v0 * scale)
    cos, sin = math.cos(angle), math.sin(angle)
    worst = 0.0
    for x, y in points:
        along = (x - center[0]) * cos + (y - center[1]) * sin
        across = -(x - center[0]) * sin + (y - center[1]) * cos
        value = (along / major) ** 2 + (across / minor) ** 2 - 1.0
        gradient = 2.0 * math.hypot(along / major**2, across / minor**2)
        worst = max(worst, abs(value) / gradient if gradient else float("inf"))
    return center, major, minor, angle, worst


def _parameter_sweep(conic, points):
    """Where along a conic 'points' start, and how far they run (radians, signed): its t0 and dt."""
    (a00, a01), (a10, a11) = conic["shape"]
    det = a00 * a11 - a01 * a10

    def parameter(p):
        x, y = p[0] - conic["center"][0], p[1] - conic["center"][1]
        # shape^-1 * (x, y) is (cos t, sin t).
        return math.atan2((-a10 * x + a00 * y) / det, (a11 * x - a01 * y) / det)

    ts = [parameter(p) for p in points]
    total = sum((b - a + math.pi) % (2.0 * math.pi) - math.pi for a, b in zip(ts, ts[1:]))
    return ts[0], total


def _sagitta(conic, point):
    """How far a point on one of a conic's polygon chords, near 'point', can stand off the curve.

    The polygonal projection ends a curve's visible piece where something hides
    it, at a point on a chord rather than on the curve; this is how far that
    point can be off: a chord of the polygon's longest step, on the curve's own
    radius of curvature there -- with a factor of two to spare, and no more, so
    that a straight edge carrying on tangent to the curve is not taken for it.
    """
    if not conic["fit"]:
        return 0.0
    a, b = conic["major"], conic["minor"]
    t, _ = _parameter_sweep(conic, [point, point])
    # The parameter is that of 'shape', whose axes need not be the ellipse's own;
    # the radius of curvature only needs the angle from the major axis.
    (a00, _a01), (a10, _a11) = conic["shape"]
    t -= math.atan2(a10, a00) - conic["angle"]
    radius = (a * a * math.sin(t) ** 2 + b * b * math.cos(t) ** 2) ** 1.5 / (a * b) if a and b else 0.0
    step = conic["fit"]["step"]
    return step * step / (4.0 * radius) if radius else 0.0


def _fit_vertices(vertices, closed, fit_tolerance, approximate):
    """A '_conic' record for the circle or ellipse through 'vertices', or None."""
    circle = fit_circle(vertices)
    if circle is not None:
        center, radius, worst = circle
        if _fits(worst, radius, fit_tolerance) or (approximate and worst <= 1e-3 * radius):
            fit = {"residual": worst}
            if not _fits(worst, radius, fit_tolerance):
                fit["approximate"] = True
            return _conic(center, ((radius, 0.0), (0.0, radius)), fit=fit)
    if len(vertices) < (MIN_CIRCLE_SEGMENTS if closed else MIN_ELLIPSE_VERTICES):
        return None
    ellipse = fit_ellipse(vertices)
    if ellipse is None:
        return None
    center, major, minor, angle, worst = ellipse
    if not _fits(worst, major, fit_tolerance):
        return None
    cos, sin = math.cos(angle), math.sin(angle)
    return _conic(center, ((major * cos, -minor * sin), (major * sin, minor * cos)), fit={"residual": worst})


def _fitted_conic(points, closed, fit_tolerance, approximate=False):
    """The circle or ellipse a polygonized run of 'points' was drawn from, as a '_conic' record, or None.

    An open run may end at a point the hidden-line algorithm put on a chord (see
    '_sagitta'), so when the whole run does not fit, it is fitted without its
    end vertices, and they are taken back if they are off by no more than that.
    """
    vertices = points[:-1] if closed else points
    trims = [(0, 0)] if closed else [(0, 0), (1, 0), (0, 1), (1, 1)]
    for head, tail in trims:
        inner = vertices[head : len(vertices) - tail]
        if len(inner) < MIN_ARC_VERTICES:
            continue
        record = _fit_vertices(inner, closed, fit_tolerance, approximate)
        if record is None:
            continue
        record["fit"]["segments"] = len(points) - 1
        record["fit"]["step"] = max(distance(p, q) for p, q in zip(points, points[1:]))
        ends = vertices[:head] + vertices[len(vertices) - tail :]
        if any(_on_conic(record, p) > max(fit_tolerance, _sagitta(record, p)) for p in ends):
            continue
        if not closed:
            record["t0"], record["dt"] = _parameter_sweep(record, points)
        return record
    return None


def _arc_runs(points, closed, tolerance, fit_tolerance):
    """Split a polyline into the circles and ellipses it was polygonized from, and what is left.

    Returns (curves, straight segments, unfitted runs): an unfitted run is a
    stretch that bends like a polygonized curve but is not on one to the file's
    precision -- a silhouette, which the polygonal projection works out from the
    triangulation rather than from an edge, or a spline -- and 'analyse' decides
    what it is.
    """
    count = len(points) - 1
    if count < 2:
        return [], [(points[0], points[-1])] if count == 1 else [], []
    turns = [turn(points[i - 1], points[i], points[i + 1]) for i in range(1, count)]
    if closed:
        turns = [turn(points[-2], points[0], points[1])] + turns
    else:
        turns = [None] + turns
    # turns[i] is the turn at vertex i (between segment i-1 and segment i).
    lengths = [distance(points[i], points[i + 1]) for i in range(count)]

    def bends(i):
        """Whether segment i and segment i-1 could be two pieces of one polygonized curve."""
        t = turns[i % count] if closed or i > 0 else None
        if t is None or abs(t) > MAX_ARC_TURN or abs(t) < 1e-9:
            return False
        a, b = lengths[(i - 1) % count], lengths[i % count]
        return max(a, b) <= 3.0 * min(a, b)

    if closed:
        corners = [i for i in range(count) if not bends(i)]
        if not corners:
            if len({t > 0 for t in turns}) == 1 and count >= MIN_CIRCLE_SEGMENTS:
                # A closed curve that turns one way all round and is round to a
                # thousandth of its radius is a circle drawn some other way --
                # as Bezier curves, the way most drawing programs write one --
                # and is said to be approximate. An open run is not given that
                # benefit: a short piece of any smooth curve is round to that.
                found = _fitted_conic(points, True, fit_tolerance, approximate=True)
                if found is not None:
                    return [found], [], []
        elif corners[0] != 0:
            # Start at a corner, so that no curve is cut in two where the loop happens to begin.
            k = corners[0]
            return _arc_runs(points[k:-1] + points[: k + 1], closed, tolerance, fit_tolerance)

    curves, straight, unfitted = [], [], []
    i = 0
    while i < count:
        j = i + 1
        while j < count and bends(j) and (turns[j] > 0) == (turns[i + 1] > 0 if i + 1 < count else True):
            j += 1
        run = points[i : j + 1]
        if len(run) >= MIN_ARC_VERTICES:
            found = _fitted_conic(run, False, fit_tolerance)
            if found is not None:
                curves.append(found)
                i = j
                continue
            if len(run) >= MIN_ELLIPSE_VERTICES:
                unfitted.append(run)
                i = j
                continue
        straight.append((points[i], points[i + 1]))
        i += 1
    return curves, straight, unfitted


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


def _on_conic(conic, point):
    """How far 'point' is from a conic's curve (to first order), whatever the arc."""
    (a00, a01), (a10, a11) = conic["shape"]
    det = a00 * a11 - a01 * a10
    if det == 0:
        return float("inf")
    x, y = point[0] - conic["center"][0], point[1] - conic["center"][1]
    u, v = (a11 * x - a01 * y) / det, (-a10 * x + a00 * y) / det
    return abs(math.hypot(u, v) - 1.0) * conic["minor"]


def _carries(conic, run, fit_tolerance):
    """Whether every vertex of 'run' is on 'conic' -- to the polygonal projection's own error -- so it is more of it.

    What a silhouette is: the outline of a sphere carrying on from the edge
    where the sphere meets something, worked out from the triangulation and so
    only near the curve, and often a polygon step away from the end of the arc
    the edge gave.
    """
    return all(_on_conic(conic, p) <= max(fit_tolerance, _sagitta(conic, p)) for p in run)


def _extend(conic, run):
    """Take 'run' into a fitted curve: as more of the same arc, or as another piece of the same curve.

    A run one polygon step or less from the arc's end carries the arc on -- the
    step between them is one the polygonal projection dropped where an edge
    turns into a silhouette. Further away, what lies between is hidden behind
    something, and the run is a piece of its own, which is how the exact
    projection draws it too: the curve's sweep is the pieces' added up, and the
    hidden stretch is in none of them. Returns the new piece, or None.
    """
    added = len(run) - 1
    if conic["dt"] is not None:
        full = 2.0 * math.pi
        direction = 1.0 if conic["dt"] > 0 else -1.0
        length = abs(conic["dt"])
        # The angle one step of the arc's polygon turns through, and a half more.
        bridge = 1.5 * length / max(1, conic["fit"]["segments"])
        start, sweep = _parameter_sweep(conic, run)
        low = ((start - conic["t0"]) * direction) % full
        high = low + sweep * direction
        low, high = min(low, high), max(low, high)
        if low <= length + bridge:  # it overlaps the arc, or carries it on from its end
            length = max(length, high)
        elif full - high <= bridge:  # it carries the arc on back from its start
            conic["t0"] -= (full - low) * direction
            length += full - low
        else:  # something hides what lies between: a piece of its own
            fit = {"segments": added, "residual": 0.0, "near": added, "step": conic["fit"]["step"]}
            return dict(conic, t0=start, dt=sweep, fit=fit)
        conic["dt"] = None if length >= full - 1e-9 else length * direction
    conic["fit"]["segments"] += added
    conic["fit"]["near"] = conic["fit"].get("near", 0) + added
    return None


def _approximate_arc(run):
    """A long run round to a thousandth of its radius, as an approximate arc: a silhouette with no edge to carry on."""
    if len(run) <= MIN_CIRCLE_SEGMENTS:
        return None
    circle = fit_circle(run)
    if circle is None:
        return None
    center, radius, worst = circle
    if worst > 1e-3 * radius:
        return None
    step = max(distance(p, q) for p, q in zip(run, run[1:]))
    fit = {"segments": len(run) - 1, "residual": worst, "approximate": True, "step": step}
    record = _conic(center, ((radius, 0.0), (0.0, radius)), fit=fit)
    record["t0"], record["dt"] = _parameter_sweep(record, run)
    return record


def _collinear(first, second, tolerance):
    """Whether two segments lie on one line."""
    (p, q), (r, s) = first, second
    length = distance(p, q)
    if length == 0:
        return False
    return all(
        abs((q[0] - p[0]) * (p[1] - point[1]) - (p[0] - point[0]) * (q[1] - p[1])) / length <= tolerance
        for point in (r, s)
    )


def _absorb(conics, straight, tolerance, fit_tolerance):
    """Extend each fitted arc over the short segments that carry it on past where its run was cut.

    A hidden-line junction -- a third edge meeting the curve -- ends a run, and
    a piece of polygon between two junctions can be too short to be fitted on
    its own: left as it is, it is a scatter of tiny straight edges, and the arc
    beside it is short by that much. A segment whose far end is on the arc, a
    small step further along it, is more of the arc. Returns the segments left.
    """
    snap = Points(tolerance)
    ends = {}
    nodes = []
    for k, (p, q) in enumerate(straight):
        a, b = snap.key(p), snap.key(q)
        nodes.append((a, b))
        ends.setdefault(a, []).append(k)
        ends.setdefault(b, []).append(k)
    used = set()
    for conic in conics:
        if conic["fit"] is None or conic["dt"] is None:
            continue
        for forward in (True, False):
            while True:
                t = conic["t0"] + conic["dt"] if forward else conic["t0"]
                node = snap.key(_conic_point(conic, t))
                extended = False
                for k in ends.get(node, ()):
                    if k in used:
                        continue
                    a, b = nodes[k]
                    far = straight[k][1] if a == node else straight[k][0]
                    if _on_conic(conic, far) > max(fit_tolerance, _sagitta(conic, far)):
                        continue
                    # A segment that a straight edge carries on from in the same
                    # direction is a piece of that edge, however near the arc it ends.
                    if any(
                        _collinear(straight[k], straight[other], tolerance)
                        for other in ends.get(b if a == node else a, ())
                        if other != k and other not in used
                    ):
                        continue
                    start, step = _parameter_sweep(conic, [_conic_point(conic, t), far])
                    # On along the arc, the way it runs, by no more than one polygon step.
                    ahead = step * conic["dt"] > 0 if forward else step * conic["dt"] < 0
                    if not ahead or abs(step) > MAX_ARC_TURN:
                        continue
                    used.add(k)
                    if forward:
                        conic["dt"] += step
                    else:
                        conic["t0"] += step
                        conic["dt"] -= step
                    conic["fit"]["segments"] += 1
                    extended = True
                    break
                if not extended or abs(conic["dt"]) >= 2.0 * math.pi:
                    break
    return [segment for k, segment in enumerate(straight) if k not in used]


def _merge_collinear(segments, tolerance):
    """Straight segments that lie on one line and touch or overlap, as one segment each.

    The two projections break a straight edge in different places -- the exact
    one hardly at all, the polygonal one wherever another edge or a mesh vertex
    touches it -- so it is the merged edge that both agree on.
    """
    buckets = {}
    merged = []
    for p, q in segments:
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        angle = math.atan2(dy, dx) % math.pi
        if angle > math.pi - 1e-9:
            angle -= math.pi
        ux, uy = math.cos(angle), math.sin(angle)
        offset = -uy * p[0] + ux * p[1]
        s0, s1 = sorted((ux * p[0] + uy * p[1], ux * q[0] + uy * q[1]))
        key = int(round(angle * 1000.0))
        for line in (line for k in (key - 1, key, key + 1) for line in buckets.get(k, ())):
            span = max(line[3] - line[2], s1 - s0)
            if (
                abs(math.sin(angle - line[0])) * span <= tolerance
                and abs(offset - line[1]) <= tolerance
                and s0 <= line[3] + tolerance
                and s1 >= line[2] - tolerance
            ):
                line[2], line[3] = min(line[2], s0), max(line[3], s1)
                break
        else:
            line = [angle, offset, s0, s1]
            merged.append(line)
            buckets.setdefault(key, []).append(line)
    result = []
    for angle, offset, s0, s1 in merged:
        ux, uy = math.cos(angle), math.sin(angle)
        result.append(((ux * s0 - uy * offset, uy * s0 + ux * offset), (ux * s1 - uy * offset, uy * s1 + ux * offset)))
    return result


def _round(conic, tolerance):
    return conic["major"] - conic["minor"] <= max(tolerance, 1e-9 * conic["major"])


def _same_curve(a, b, tolerance):
    """Whether two conic pieces are pieces of one circle or one ellipse."""
    slack = tolerance
    if a["fit"] or b["fit"]:
        slack = max(tolerance, 1e-3 * max(a["major"], b["major"]))
    if distance(a["center"], b["center"]) > slack:
        return False
    if abs(a["major"] - b["major"]) > slack or abs(a["minor"] - b["minor"]) > slack:
        return False
    if _round(a, slack) and _round(b, slack):
        return True
    return abs(math.sin(a["angle"] - b["angle"])) <= 1e-3


def _to_segment(point, p, q):
    """How far 'point' is from the segment p-q."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0] - p[0]) * dx + (point[1] - p[1]) * dy) / length))
    return distance(point, (p[0] + t * dx, p[1] + t * dy))


def _signed_sweep(conic):
    """The sweep of an arc in degrees, positive when it runs anticlockwise (Y up)."""
    (a00, a01), (a10, a11) = conic["shape"]
    direction = 1.0 if (a00 * a11 - a01 * a10) * conic["dt"] > 0 else -1.0
    return math.degrees(abs(conic["dt"])) * direction


def analyse(drawing, tolerance=None):
    """Classify a drawing into the features the module docstring lists, as a JSON-ready dict."""
    if not drawing.points and not drawing.conics:
        return {"extent": None, "layers": drawing.layers, "read": drawing.read, "page": drawing.page}
    points = list(drawing.points)
    for conic in drawing.conics:
        points.extend(_conic_extremes(conic))
    size = max(
        max(p[0] for p in points) - min(p[0] for p in points), max(p[1] for p in points) - min(p[1] for p in points)
    )
    size = size or 1.0
    if tolerance is None:
        tolerance = 1e-5 * size
    # What a polygon's vertices may stand off the curve it was drawn from: the
    # file's rounding, with room for the arithmetic of the fit -- and never less
    # than a millionth of the drawing, which is about what the polygonal
    # hidden-line algorithm's own arithmetic moves a vertex by in a slanted
    # view. Looser than that, pieces of silhouettes start to fit curves that
    # are not there; a curve this misses is left as segments, and said to be.
    fit_tolerance = max(20.0 * (drawing.rounding or 0.0), 1e-6 * size)

    conics = list(drawing.conics)
    straight, loops, splines = [], [], []
    # A curve the file drew as Bezier curves is a spline -- build123d writes a
    # circle or an ellipse as an arc, and anything else as Beziers -- so it is
    # reported as one, and nothing is fitted to it: over a short enough run a
    # smooth curve is close to some ellipse. The one exception is a closed one
    # that is round, which is how most drawing programs write a circle.
    polygon = [(p, q) for p, q, flat in drawing.segments if flat]
    for chain, closed in chains([(p, q) for p, q, flat in drawing.segments if not flat], tolerance):
        flattened = straighten(chain, closed, tolerance)
        if len(flattened) == 2:
            polygon.append((flattened[0], flattened[1]))  # a Bezier that is a straight line
            continue
        if closed and len(chain) > MIN_CIRCLE_SEGMENTS:
            round_ = fit_circle(chain[:-1])
            if round_ is not None and round_[2] <= 1e-3 * round_[1]:
                center, radius, worst = round_
                fit = {"segments": len(chain) - 1, "residual": worst, "approximate": True, "step": 0.0}
                conics.append(_conic(center, ((radius, 0.0), (0.0, radius)), fit=fit))
                continue
        xs_, ys_ = [p[0] for p in chain], [p[1] for p in chain]
        splines.append(
            {
                "start": list(chain[0]),
                "end": list(chain[-1]),
                "closed": closed,
                "length": sum(distance(p, q) for p, q in zip(chain, chain[1:])),
                "box": [min(xs_), min(ys_), max(xs_), max(ys_)],
                "x": (min(xs_) + max(xs_)) / 2.0,
                "y": (min(ys_) + max(ys_)) / 2.0,
            }
        )
    # One straight edge, however the projection broke it, before anything is
    # chained: a piece of it left on its own beside an arc reads as more arc.
    segments = _merge_collinear(polygon, tolerance)
    pending = []
    for chain, closed in chains(segments, tolerance):
        chain = straighten(chain, closed, tolerance)
        found, rest, unfitted = _arc_runs(chain, closed, tolerance, fit_tolerance)
        conics.extend(found)
        straight.extend(rest)
        pending.extend(unfitted)
        if closed and not found and len(chain) > 5 and len(rest) == len(chain) - 1:
            lengths = [distance(p, q) for p, q in rest]
            if max(lengths) <= 3.0 * min(lengths):
                lx = [p[0] for p in chain]
                ly = [p[1] for p in chain]
                center = ((min(lx) + max(lx)) / 2.0, (min(ly) + max(ly)) / 2.0)
                loops.append(
                    {
                        "x": center[0],
                        "y": center[1],
                        "width": max(lx) - min(lx),
                        "height": max(ly) - min(ly),
                        # Across the corners, and across the flats: a hexagon's two sizes.
                        "widest": 2.0 * max(distance(p, center) for p in chain),
                        "narrowest": 2.0 * min(_to_segment(center, p, q) for p, q in rest),
                        "segments": len(rest),
                    }
                )
    for run in pending:
        host = next((c for c in conics if c["fit"] and _carries(c, run, fit_tolerance)), None)
        if host is not None:
            piece = _extend(host, run)
            if piece is not None:
                conics.append(piece)
            continue
        approximate = _approximate_arc(run)
        if approximate is not None:
            conics.append(approximate)
            continue
        straight.extend(zip(run, run[1:]))
    straight = _merge_collinear(_absorb(conics, straight, tolerance, fit_tolerance), tolerance)
    # The extent, now that a fitted curve's own extremes are known too.
    for conic in conics:
        if conic["fit"]:
            points.extend(_conic_extremes(conic))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    extent = {"xmin": min(xs), "xmax": max(xs), "ymin": min(ys), "ymax": max(ys)}
    extent["width"], extent["height"] = extent["xmax"] - extent["xmin"], extent["ymax"] - extent["ymin"]

    circles, arcs, ellipses = [], [], []
    # The pieces of one curve are put together: a full circle is written as two
    # arcs, and one the hidden-line algorithm cut, or a polygon broke where
    # another edge meets it, is several.
    for group in _gather(conics, lambda a, b: _same_curve(a, b, tolerance)):
        first = group[0]
        n = float(len(group))
        center = (sum(c["center"][0] for c in group) / n, sum(c["center"][1] for c in group) / n)
        major = sum(c["major"] for c in group) / n
        minor = sum(c["minor"] for c in group) / n
        fitted = [c["fit"] for c in group if c["fit"]]
        how = {"source": "exact"}
        if fitted:
            how = {
                "source": "fitted",
                "segments": sum(f["segments"] for f in fitted),
                "residual": max(f["residual"] for f in fitted),
            }
            if any(f.get("approximate") for f in fitted):
                how["approximate"] = True
            if any(f.get("near") for f in fitted):
                how["near"] = sum(f.get("near", 0) for f in fitted)
        whole = any(c["dt"] is None for c in group)
        total = 360.0 if whole else sum(math.degrees(abs(c["dt"])) for c in group)
        whole = whole or total >= 360.0 - (0.1 if fitted else 1e-6)
        pieces = [] if whole else [c for c in group if c["dt"] is not None]
        if _round(first, max(tolerance, 1e-3 * major) if fitted else tolerance):
            if whole:
                circles.append({"x": center[0], "y": center[1], "diameter": major + minor, **how})
                continue
            arcs.append(
                {
                    "x": center[0],
                    "y": center[1],
                    "radius": (major + minor) / 2.0,
                    "sweep": total,
                    "pieces": [
                        {
                            "start": list(_conic_point(c, c["t0"])),
                            "end": list(_conic_point(c, c["t0"] + c["dt"])),
                            "sweep": _signed_sweep(c),
                        }
                        for c in pieces
                    ],
                    **how,
                }
            )
            continue
        ellipses.append(
            {
                "x": center[0],
                "y": center[1],
                "major": 2.0 * major,
                "minor": 2.0 * minor,
                "angle": math.degrees(first["angle"]) % 180.0,
                "sweep": min(total, 360.0),
                "pieces": len(pieces) or 1,
                **how,
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

    # Where each feature is from the left and the bottom of the drawing, which
    # does not depend on where the projection put the model's origin.
    for feature in circles + arcs + ellipses + loops + splines:
        feature["from_left"] = feature["x"] - extent["xmin"]
        feature["from_bottom"] = feature["y"] - extent["ymin"]
    circles.sort(key=lambda c: (-round(c["diameter"] / tolerance), c["x"], c["y"]))
    arcs.sort(key=lambda a: (-round(a["radius"] / tolerance), a["x"], a["y"]))
    ellipses.sort(key=lambda e: (-round(e["major"] / tolerance), e["x"], e["y"]))
    other.sort(key=lambda line: -line["length"])
    splines.sort(key=lambda curve: -curve["length"])
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
        "splines": splines,
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
                "  [approximate: round to within %s but not on a circle -- a silhouette, or Bezier curves; %d segments]"
                % (
                    n(item["residual"]),
                    item["segments"],
                )
            )
        if item.get("source") == "fitted" and item.get("near"):
            return "  [fitted to %d segments, residual %s; %d more only near it: a silhouette]" % (
                item["segments"] - item["near"],
                n(item["residual"]),
                item["near"],
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
                "  E%d  major %s  minor %s  major axis at %.2f deg%s  %s%s"
                % (i, n(el["major"]), n(el["minor"]), el["angle"], sweep, where(el), how(el))
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
    if report.get("splines"):
        out.append("splines -- curves drawn as Bezier curves, longest first (%d):" % len(report["splines"]))
        for i, curve in enumerate(report["splines"][:limit], 1):
            box = curve["box"]
            out.append(
                "  S%d  length %s%s  from (%s, %s) to (%s, %s), within x %s .. %s, y %s .. %s"
                % (
                    i,
                    n(curve["length"]),
                    ", closed" if curve["closed"] else "",
                    n(curve["start"][0]),
                    n(curve["start"][1]),
                    n(curve["end"][0]),
                    n(curve["end"][1]),
                    n(box[0]),
                    n(box[2]),
                    n(box[1]),
                    n(box[3]),
                )
            )
        more(report["splines"])
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
# Two renders of one object, read against each other.

# What each kind of feature is paired by, and what is compared once it is:
# (key in the report, label, how to read its position, its sizes).
_KINDS = (
    ("circles", "circle", lambda f: (f["x"], f["y"]), ("diameter",)),
    ("arcs", "arc", lambda f: (f["x"], f["y"]), ("radius", "sweep")),
    ("ellipses", "ellipse", lambda f: (f["x"], f["y"]), ("major", "minor", "sweep")),
    # An edge standing at an X has no Y to be compared by, and one at a Y no X.
    ("vertical", "vertical edge", lambda f: (f["at"], None), ("length",)),
    ("horizontal", "horizontal edge", lambda f: (None, f["at"]), ("length",)),
    ("loops", "outline", lambda f: (f["x"], f["y"]), ("width", "height")),
    (
        "lines",
        "straight edge",
        lambda f: ((f["start"][0] + f["end"][0]) / 2.0, (f["start"][1] + f["end"][1]) / 2.0),
        ("length", "angle"),
    ),
)

# A sweep is compared in degrees rather than millimetres: what a sweep is
# allowed to differ by.
SWEEP_AGREEMENT = 0.5


def _apart(pa, pb, shift):
    """How far apart two positions are once 'shift' is taken off, over the coordinates both have."""
    return math.sqrt(sum((a - b - s) ** 2 for a, b, s in zip(pa, pb, shift) if a is not None and b is not None))


def _pairs(first, second, position, sizes, shift, slack):
    """Greedy nearest pairs of two lists of features: (pairs, only in first, only in second)."""
    candidates = []
    for i, a in enumerate(first):
        pa = position(a)
        for j, b in enumerate(second):
            pb = position(b)
            apart = _apart(pa, pb, shift)
            differ = max(abs(a[s] - b[s]) for s in sizes if s not in ("sweep", "angle"))
            if apart <= slack and differ <= slack:
                candidates.append((apart + differ, i, j))
    taken_a, taken_b, pairs = set(), set(), []
    for _score, i, j in sorted(candidates):
        if i not in taken_a and j not in taken_b:
            taken_a.add(i)
            taken_b.add(j)
            pairs.append((first[i], second[j]))
    return (
        pairs,
        [a for i, a in enumerate(first) if i not in taken_a],
        [b for j, b in enumerate(second) if j not in taken_b],
    )


def _polygons(lines, slack):
    """Short straight edges grouped by the polygon they are steps of: count, total length and box of each."""
    groups = []
    for chain, _closed in chains([(tuple(f["start"]), tuple(f["end"])) for f in lines], slack):
        xs, ys = [p[0] for p in chain], [p[1] for p in chain]
        groups.append(
            {
                "segments": len(chain) - 1,
                "length": sum(distance(p, q) for p, q in zip(chain, chain[1:])),
                "box": [min(xs), min(ys), max(xs), max(ys)],
            }
        )
    return groups


def compare(first, second, agreement=None):
    """Read two reports of one drawing -- the same object rendered two ways -- against each other.

    Every feature of one is paired with the nearest of the same kind in the
    other, and each pair is compared. 'agreement' is how far apart two readings
    of one dimension may be and still agree; by default 5e-4 of the drawing's
    size, which is how far the polygonal projection lets a curve's polygon
    stand off the curve. Positions are compared as they are, or with the two
    extents' corners lined up -- whichever pairs more features -- because the
    two hidden-line algorithms need not put the model's origin in one place.
    """
    ea, eb = first["extent"], second["extent"]
    size = max(ea["width"], ea["height"], eb["width"], eb["height"]) or 1.0
    if agreement is None:
        agreement = 5e-4 * size
    slack = max(4.0 * agreement, 1e-6 * size)
    shifts = [(0.0, 0.0), (ea["xmin"] - eb["xmin"], ea["ymin"] - eb["ymin"])]

    def matched(shift):
        return sum(
            len(_pairs(first[key], second[key], position, sizes, shift, slack)[0])
            for key, _label, position, sizes in _KINDS
        )

    shift = max(shifts, key=matched)
    result = {
        "agreement": agreement,
        "shift": list(shift),
        "extent": {
            name: {"first": ea[name], "second": eb[name], "difference": ea[name] - eb[name]}
            for name in ("width", "height")
        },
        "kinds": {},
        "agree": True,
    }
    for name in ("width", "height"):
        if abs(ea[name] - eb[name]) > agreement:
            result["agree"] = False
    shortest = 0.01 * size  # a straight edge shorter than this is a polygon's, not a feature
    for key, label, position, sizes in _KINDS:
        a_items, b_items = first[key], second[key]
        if key == "lines":
            a_items = [f for f in a_items if f["length"] >= shortest]
            b_items = [f for f in b_items if f["length"] >= shortest]
        pairs, only_first, only_second = _pairs(a_items, b_items, position, sizes, shift, slack)
        polygons = {}
        if key == "lines":
            # Straight edges much shorter than the drawing that only one side has
            # are the steps of a curve that side drew as a polygon it could not
            # fit: one entry per polygon, rather than one per step.
            for side, items in (("first", only_first), ("second", only_second)):
                short = [f for f in items if f["length"] < 0.05 * size]
                polygons[side] = _polygons(short, slack)
                items[:] = [f for f in items if f["length"] >= 0.05 * size]
        differing = []
        for a, b in pairs:
            deltas = {s: a[s] - b[s] for s in sizes}
            pa, pb = position(a), position(b)
            deltas["position"] = _apart(pa, pb, shift)
            limits = {s: (SWEEP_AGREEMENT if s in ("sweep", "angle") else agreement) for s in deltas}
            if any(abs(deltas[s]) > limits[s] for s in deltas):
                differing.append({"first": a, "second": b, "differences": deltas})
        if differing or only_first or only_second or any(polygons.values()):
            result["agree"] = False
        result["kinds"][key] = {
            "label": label,
            "paired": len(pairs),
            "differing": differing,
            "only_first": only_first,
            "only_second": only_second,
        }
        if polygons:
            result["kinds"][key]["polygons"] = polygons
    return result


def _describe(feature, key, n):
    if key == "circles":
        return "diameter %s at (%s, %s)" % (n(feature["diameter"]), n(feature["x"]), n(feature["y"]))
    if key == "arcs":
        return "radius %s sweeping %.2f deg about (%s, %s)" % (
            n(feature["radius"]),
            feature["sweep"],
            n(feature["x"]),
            n(feature["y"]),
        )
    if key == "ellipses":
        return "%s x %s sweeping %.2f deg about (%s, %s)" % (
            n(feature["major"]),
            n(feature["minor"]),
            feature["sweep"],
            n(feature["x"]),
            n(feature["y"]),
        )
    if key in ("vertical", "horizontal"):
        return "%s %s, %s long" % ("x" if key == "vertical" else "y", n(feature["at"]), n(feature["length"]))
    if key == "loops":
        return "%s x %s at (%s, %s)" % (n(feature["width"]), n(feature["height"]), n(feature["x"]), n(feature["y"]))
    return "%s long at %.2f deg, (%s, %s) -> (%s, %s)" % (
        n(feature["length"]),
        feature["angle"],
        n(feature["start"][0]),
        n(feature["start"][1]),
        n(feature["end"][0]),
        n(feature["end"][1]),
    )


def format_compare(result, names, digits=4):
    def n(value):
        text = "%.*f" % (digits, value)
        return "0." + "0" * digits if text.lstrip("-") == "0." + "0" * digits else text

    first, second = names
    out = ["first: %s" % first, "second: %s" % second]
    out.append("agreement: %s (and %.1f deg for a sweep)" % (n(result["agreement"]), SWEEP_AGREEMENT))
    if any(result["shift"]):
        out.append("positions compared with the second moved by (%s, %s)" % tuple(n(v) for v in result["shift"]))
    for name, values in result["extent"].items():
        mark = "" if abs(values["difference"]) <= result["agreement"] else "   <-- differs"
        out.append(
            "extent %s: %s vs %s (difference %s)%s"
            % (name, n(values["first"]), n(values["second"]), n(values["difference"]), mark)
        )
    for key, kind in result["kinds"].items():
        if not (kind["paired"] or kind["only_first"] or kind["only_second"] or any(kind.get("polygons", {}).values())):
            continue
        polygons = kind.get("polygons", {})
        out.append(
            "%ss: %d paired, %d differing, %d only in the first, %d only in the second"
            % (
                kind["label"],
                kind["paired"],
                len(kind["differing"]),
                len(kind["only_first"]) + len(polygons.get("first", [])),
                len(kind["only_second"]) + len(polygons.get("second", [])),
            )
        )
        for item in kind["differing"]:
            deltas = ", ".join(
                "%s %s" % (s, ("%.2f deg" % d) if s in ("sweep", "angle") else n(d))
                for s, d in item["differences"].items()
            )
            out.append(
                "  differs: %s  vs  %s  (%s)"
                % (_describe(item["first"], key, n), _describe(item["second"], key, n), deltas)
            )
        for item in kind["only_first"]:
            out.append("  only in the first: %s" % _describe(item, key, n))
        for item in kind["only_second"]:
            out.append("  only in the second: %s" % _describe(item, key, n))
        for side, groups in kind.get("polygons", {}).items():
            for group in groups:
                box = group["box"]
                out.append(
                    "  only in the %s: %d short steps, %s long in all, within x %s .. %s, y %s .. %s"
                    " -- a curve drawn as a polygon this could not fit a circle or an ellipse to"
                    % (side, group["segments"], n(group["length"]), n(box[0]), n(box[2]), n(box[1]), n(box[3]))
                )
    out.append(
        "the two agree on every feature"
        if result["agree"]
        else "the two disagree: resolve each line above before trusting a dimension it touches"
    )
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


def _above_zero(text):
    """A length that something is divided by or compared within: more than zero."""
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError("expected a number above 0, not %r" % text)
    return value


def _not_negative(text):
    """A difference two readings may have: zero means they must agree exactly."""
    value = float(text)
    if not value >= 0:
        raise argparse.ArgumentTypeError("expected a number of 0 or more, not %r" % text)
    return value


def _ink_threshold(text):
    """How far from the background a pixel is to be ink: at 0 every pixel is, and a run weighs nothing."""
    value = int(text)
    if not 1 <= value <= 255:
        raise argparse.ArgumentTypeError("expected a whole number from 1 to 255, not %r" % text)
    return value


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
    svg.add_argument("--tolerance", type=_above_zero, help="When two numbers are the same (default 1e-5 of the extent)")
    svg.add_argument("--digits", type=int, default=4, help="Decimal places to print (default 4)")
    svg.add_argument("--limit", type=int, default=40, help="Other straight edges to print (default 40)")
    svg.add_argument("--json", action="store_true")

    both = sub.add_parser("compare", help="Read two SVG renders of one object against each other")
    both.add_argument("first")
    both.add_argument("second")
    both.add_argument("--layer", action="append", help="Read only this layer (an id of a <g>); repeat for several")
    both.add_argument(
        "--agreement", type=_not_negative, help="How far two readings may differ (default 5e-4 of the size)"
    )
    both.add_argument("--digits", type=int, default=4, help="Decimal places to print (default 4)")
    both.add_argument("--json", action="store_true")

    image = sub.add_parser("image", help="Measure a raster image in pixels, along rows and columns")
    image.add_argument("file")
    image.add_argument("--row", type=float, action="append", default=[], help="Scan along this pixel row")
    image.add_argument("--column", type=float, action="append", default=[], help="Scan along this pixel column")
    image.add_argument("--no-bbox", action="store_true", help="Skip the bounding box of the ink")
    image.add_argument("--crop", type=_box, help="Look only inside X0,Y0,X1,Y1 (pixels, inclusive)")
    image.add_argument(
        "--threshold", type=_ink_threshold, default=64, help="How far from the background ink is (1-255)"
    )
    image.add_argument("--background", type=_colour, help="R,G,B of the background (default: the commonest colour)")
    scale = image.add_mutually_exclusive_group()
    scale.add_argument("--px-per-mm", type=float, help="The picture's scale, to report millimetres too")
    scale.add_argument("--calibrate", type=lambda t: _pair(t, "="), help="PX=MM: that many pixels are that many mm")
    image.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (OSError, ET.ParseError) as e:
        sys.exit("measure.py: %s" % e)


def _run(args):
    code = 0
    if args.command == "svg":
        report = analyse(read_svg(args.file, args.layer, args.all_layers), args.tolerance)
        text = json.dumps(report, indent=1) if args.json else format_svg(report, args.digits, args.limit)
    elif args.command == "compare":
        reports = [analyse(read_svg(path, args.layer)) for path in (args.first, args.second)]
        if any(report.get("extent") is None for report in reports):
            sys.exit("Nothing is drawn on the layers read of %s" % " or ".join((args.first, args.second)))
        result = compare(*reports, agreement=args.agreement)
        text = (
            json.dumps(result, indent=1)
            if args.json
            else format_compare(result, (args.first, args.second), args.digits)
        )
        code = 0 if result["agree"] else 1
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
    return code


if __name__ == "__main__":
    sys.exit(main())
