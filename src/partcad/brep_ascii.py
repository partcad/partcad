#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""OCCT's ASCII BREP format, written in plain Python.

The core process never touches a CAD kernel: every shape it holds is BREP bytes
in an envelope, and every shape it is asked to build is built in a sandbox that
has OCCT. That is the right trade for a script or a file, whose geometry only a
kernel can work out. It is the wrong one for a shape that is nothing but a few
numbers - a circle of radius 5, a 10 mm cube - where starting an interpreter
and importing OCP costs seconds and the geometry itself is a handful of lines
and planes anybody can write down. This module is what writes them down.

It writes the format 'BRepTools::Write' writes and 'BRepTools::Read' reads -
every reader of a payload reads ASCII as well as binary (see
'ocp_serialize.shape_from_brep') - and only the part of it such shapes need:

  * Geometry: lines and circles in 3D and on a surface ('pcurves'), planes and
    cylinders. No locations: what a shape is placed at is in its coordinates,
    which is where 'wrapper_transform.relocate' puts an offset too.
  * Topology: vertices, edges, wires, faces, shells and solids, each written
    once however many shapes hold it, before the first shape that holds it,
    and referred to by its position counted from the end of the list - which
    is how OCCT numbers them, so the shape written last is '1'.

Version 1 of the format, the one every OCCT release reads: it is the version
that carries no UV points on a curve on a surface, and a reader of version 1
works them out itself as it reads each face ('BRepTools::Update').

Every number is written with 'repr()', which is the shortest text that reads
back as the same double: nothing is rounded on the way through, where OCCT's own
ASCII writer rounds a parameter to fifteen digits.

And every number is the same on every machine, because what is written is
digested and the digest is a cache key machines share (see
'shape_envelope.payload_digest'). So nothing here, or in 'basic_shapes', reaches
for an operation whose last bit depends on the platform or on the Python: only
what IEEE 754 rounds correctly (+, -, *, /, sqrt), 'math.fsum' - exactly rounded,
where 'sum()' of floats became compensated in Python 3.12 and so answers 3.11
differently - and trigonometry worked out in 'decimal' ('basic_shapes.cos_sin')
rather than by the C library, which Linux, macOS and Windows each implement
their own way.

Nothing here knows what a sketch or a part is; 'basic_shapes' does.
"""

import math

# The line a reader looks for before anything else (see
# 'TopTools_ShapeSet::Read'), of the version this module writes.
HEADER = "CASCADE Topology V1, (c) Matra-Datavision"

# OCCT's 'Precision::Confusion()', which is the tolerance it gives every
# vertex, edge and face it builds from exact geometry.
TOLERANCE = 1e-7

FORWARD = "+"
REVERSED = "-"

# The continuity across a seam, as 'BRepTools_ShapeSet' spells it.
CONTINUITY = ("C0", "G1", "C1", "G2", "C2", "C3", "CN")


# --------------------------------------------------------------------------- #
# Numbers and vectors                                                         #
# --------------------------------------------------------------------------- #


def real(value) -> str:
    """A double as text that reads back as the same double.

    Zero is written '0' whatever its sign, and an integral value without its
    '.0', which is all the tidying there is: the rest is 'repr()'. A value that
    is not finite has no place in a BREP and is refused.
    """
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("a BREP cannot hold %r" % value)
    if value == 0.0:
        return "0"
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _reals(values) -> str:
    return " ".join(real(value) for value in values)


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def scaled(a, factor):
    return tuple(x * factor for x in a)


def dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    """'a' divided by its length, as 'gp_Dir' makes it; a vector of no length is refused, as there."""
    length = math.sqrt(math.fsum(x * x for x in a))
    if length <= 1e-300 or not math.isfinite(length):
        raise ValueError("a direction needs a length: %r" % (tuple(a),))
    return tuple(x / length for x in a)


def default_xdir(normal):
    """The X direction OCCT gives a frame it is handed only a normal for ('gp_Ax2(P, V)').

    Which of the infinitely many perpendiculars a plane or a circle gets when
    nothing says, chosen the way OCCT chooses it - so that a face built here is
    parametrized the way the same face built by 'BRepBuilderAPI_MakeFace' is.
    """
    a, b, c = normal
    aa, ab, ac = abs(a), abs(b), abs(c)
    if ab <= aa and ab <= ac:
        direction = (-c, 0.0, a) if aa > ac else (c, 0.0, -a)
    elif aa <= ab and aa <= ac:
        direction = (0.0, -c, b) if ab > ac else (0.0, c, -b)
    else:
        direction = (-b, a, 0.0) if aa > ab else (b, -a, 0.0)
    return unit(direction)


def _frame(normal, xdir):
    """A right-handed orthonormal frame '(normal, X, Y)' from a normal and a direction near X.

    X is made perpendicular to the normal the way 'gp_Ax2' makes it, so a
    direction that is off by a rounding error is corrected rather than written
    off square.
    """
    normal = unit(normal)
    xdir = unit(cross(cross(normal, xdir), normal))
    return normal, xdir, cross(normal, xdir)


# --------------------------------------------------------------------------- #
# Geometry                                                                    #
# --------------------------------------------------------------------------- #


class Line:
    """A line, in 3D or on a surface: a point and a unit direction, parametrized by length."""

    def __init__(self, point, direction):
        self.point = tuple(float(x) for x in point)
        self.direction = unit(direction)

    def record(self) -> str:
        return "1 %s %s" % (_reals(self.point), _reals(self.direction))


class Circle:
    """A circle in 3D, parametrized by angle from 'xdir', turning about 'normal'."""

    def __init__(self, centre, normal, xdir, radius):
        self.centre = tuple(float(x) for x in centre)
        self.normal, self.xdir, self.ydir = _frame(normal, xdir)
        self.radius = float(radius)
        if not self.radius > 0.0:
            raise ValueError("a circle needs a radius greater than zero, not %r" % radius)

    def record(self) -> str:
        return "2 %s %s %s %s %s" % (
            _reals(self.centre),
            _reals(self.normal),
            _reals(self.xdir),
            _reals(self.ydir),
            real(self.radius),
        )


class Circle2d:
    """A circle on a surface, counter-clockwise in its (u, v) space, parametrized by angle."""

    def __init__(self, centre, radius):
        self.centre = tuple(float(x) for x in centre)
        self.radius = float(radius)

    def record(self) -> str:
        return "2 %s 1 0 0 1 %s" % (_reals(self.centre), real(self.radius))


class Plane:
    """A plane: an origin and a right-handed frame whose third axis is the normal."""

    def __init__(self, origin, normal, xdir=None):
        self.origin = tuple(float(x) for x in origin)
        self.normal, self.xdir, self.ydir = _frame(normal, default_xdir(unit(normal)) if xdir is None else xdir)

    def record(self) -> str:
        return "1 %s %s %s %s" % (_reals(self.origin), _reals(self.normal), _reals(self.xdir), _reals(self.ydir))


class Cylinder:
    """A cylindrical surface about 'axis': u is the angle from 'xdir', v the height above 'origin'."""

    def __init__(self, origin, axis, xdir, radius):
        self.origin = tuple(float(x) for x in origin)
        self.axis, self.xdir, self.ydir = _frame(axis, xdir)
        self.radius = float(radius)

    def record(self) -> str:
        return "2 %s %s %s %s %s" % (
            _reals(self.origin),
            _reals(self.axis),
            _reals(self.xdir),
            _reals(self.ydir),
            real(self.radius),
        )


class _Table:
    """One geometry section: each object written once, numbered from 1 in the order it was first met."""

    def __init__(self, title):
        self.title = title
        self._records = []
        self._index = {}

    def __call__(self, geometry) -> int:
        key = id(geometry)
        if key not in self._index:
            self._records.append(geometry.record())
            self._index[key] = len(self._records)
        return self._index[key]

    def text(self) -> str:
        return "%s %d\n%s" % (self.title, len(self._records), "".join(line + " \n" for line in self._records))


class _Tables:
    def __init__(self):
        self.curves2d = _Table("Curve2ds")
        self.curves = _Table("Curves")
        self.surfaces = _Table("Surfaces")


# --------------------------------------------------------------------------- #
# Topology                                                                    #
# --------------------------------------------------------------------------- #


class _Shape:
    """A topological shape: what it is, what it holds and how, and how it is written."""

    KIND = ""
    # Free, modified, checked, orientable, closed, infinite, convex - the flags
    # OCCT writes for a shape of this kind that something else holds. The one
    # written last holds nothing above it and is written free instead.
    FLAGS = "0100000"

    def __init__(self, children=()):
        self.children = [(orientation, child) for orientation, child in children]
        for orientation, _child in self.children:
            if orientation not in (FORWARD, REVERSED):
                raise ValueError("an orientation is '+' or '-', not %r" % orientation)

    def flags(self) -> str:
        return self.FLAGS

    def geometry(self, tables) -> str:
        return ""


class Vertex(_Shape):
    KIND = "Ve"
    FLAGS = "0101101"

    def __init__(self, point, tolerance=TOLERANCE):
        super().__init__()
        self.point = tuple(float(x) for x in point)
        self.tolerance = tolerance

    def geometry(self, tables) -> str:
        # The point, and no representation of it on any curve or surface: a
        # vertex that bounds an edge is read off the edge's range.
        return "%s\n%s\n0 0\n" % (real(self.tolerance), _reals(self.point))


class Edge(_Shape):
    """An edge along 'curve' from 'start' (at 'first') to 'end' (at 'last').

    'on()' adds its curve on each face it bounds, which a reader needs for
    anything but a plane - OCCT works a curve on a plane out for itself - and
    two of them on the one surface for a seam, the first for the edge as the
    face holds it forward and the second for it reversed.
    """

    KIND = "Ed"

    def __init__(self, curve, first, last, start, end, tolerance=TOLERANCE):
        super().__init__([(FORWARD, start), (REVERSED, end)])
        self.curve = curve
        self.first = float(first)
        self.last = float(last)
        self.start = start
        self.end = end
        self.tolerance = tolerance
        self.pcurves = []

    def flags(self) -> str:
        # Closed when it starts where it ends: a whole circle.
        return "0101100" if self.start is self.end else "0101000"

    def on(self, surface, pcurve, reversed_pcurve=None, continuity="CN") -> "Edge":
        if continuity not in CONTINUITY:
            raise ValueError("unknown continuity %r" % continuity)
        self.pcurves.append((surface, pcurve, reversed_pcurve, continuity))
        return self

    def geometry(self, tables) -> str:
        # Tolerance, same parameter, same range, degenerated.
        lines = [" %s 1 1 0" % real(self.tolerance)]
        span = "%s %s" % (real(self.first), real(self.last))
        lines.append("1  %d 0 %s" % (tables.curves(self.curve), span))
        for surface, pcurve, reversed_pcurve, continuity in self.pcurves:
            if reversed_pcurve is None:
                lines.append("2  %d %d 0 %s" % (tables.curves2d(pcurve), tables.surfaces(surface), span))
            else:
                lines.append(
                    "3  %d %d %s %d 0 %s"
                    % (
                        tables.curves2d(pcurve),
                        tables.curves2d(reversed_pcurve),
                        continuity,
                        tables.surfaces(surface),
                        span,
                    )
                )
        lines.append("0")
        return "\n".join(lines) + "\n"


class Wire(_Shape):
    KIND = "Wi"
    FLAGS = "0101100"


class Face(_Shape):
    """A face of 'surface' bounded by 'wires', the outer one first.

    Each wire runs counter-clockwise about the surface's normal as the face
    holds it - the outer one, that is; a hole runs the other way - and a face
    held reversed by its shell is one whose material is on the other side.
    """

    KIND = "Fa"
    FLAGS = "0111000"

    def __init__(self, surface, wires, tolerance=TOLERANCE):
        super().__init__(wires)
        self.surface = surface
        self.tolerance = tolerance

    def geometry(self, tables) -> str:
        # Natural restriction, tolerance, surface, location.
        return "0  %s %d 0\n" % (real(self.tolerance), tables.surfaces(self.surface))


class Shell(_Shape):
    KIND = "Sh"
    FLAGS = "0101100"


class Solid(_Shape):
    KIND = "So"
    FLAGS = "0100000"


def write(shape) -> bytes:
    """'shape' as the bytes 'BRepTools::Write' writes and 'BRepTools::Read' reads.

    Each shape is written once, after everything it holds; geometry is
    numbered in the order the shapes are written, which is the order a reader
    meets it in.
    """
    order = []
    position = {}

    pending = [(shape, False)]
    while pending:
        current, expanded = pending.pop()
        if id(current) in position:
            continue
        if expanded:
            order.append(current)
            position[id(current)] = len(order)
            continue
        pending.append((current, True))
        for _orientation, child in reversed(current.children):
            if id(child) not in position:
                pending.append((child, False))

    count = len(order)

    def reference(orientation, child):
        return "%s%d 0 " % (orientation, count - position[id(child)] + 1)

    tables = _Tables()
    records = []
    for current in order:
        flags = current.flags()
        if current is shape:
            flags = "1" + flags[1:]
        children = "".join(reference(orientation, child) for orientation, child in current.children)
        records.append("%s\n%s\n%s\n%s*\n" % (current.KIND, current.geometry(tables), flags, children))

    text = "".join(
        [
            "\n%s\n" % HEADER,
            "Locations 0\n",
            tables.curves2d.text(),
            tables.curves.text(),
            "Polygon3D 0\n",
            "PolygonOnTriangulations 0\n",
            tables.surfaces.text(),
            "Triangulations 0\n",
            "\nTShapes %d\n" % count,
            "".join(records),
            "\n%s\n" % reference(FORWARD, shape),
        ]
    )
    return text.encode("ascii")
