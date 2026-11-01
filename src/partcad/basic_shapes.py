#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'basic' sketches and parts: shapes a few numbers describe, built without a CAD kernel.

A basic sketch is a face in the XY plane: one outline - a circle, a square, a
rectangle or a slot - with any number of those cut out of it. A basic part is a
solid: a cuboid or a cylinder. Neither has a script or a file behind it, only
the numbers in its declaration, and the geometry those numbers describe is
lines, circles, planes and one cylinder - nothing a kernel has to work out. So
it is written out here, with 'brep_ascii', in the process that asks for it: no
sandbox, no interpreter to start, no OCP to import.

What comes out is what OCCT built from the same numbers, which is the
compatibility this has to keep - 'examples/produce_sketch_basic' is rendered
from it and checked in. A sketch is built the way the OCCT wrapper this replaced
('wrapper_sketch_basic') built it, call for call:

  * Each outline is drawn in the same order from the same points - a polygon
    from its +X+Y corner clockwise, a slot along its top first - so its edges
    run the same way and start in the same places.
  * The face's normal follows the outer outline: +Z for one drawn
    counter-clockwise (a circle), -Z for one drawn clockwise (a square, a
    rectangle, a slot), which is what 'BRepBuilderAPI_MakeFace' made of a wire
    it was given no plane for. A tool path that goes round an outline the way
    its face says it runs goes round it the way it always did.
  * A hole that runs the same way as its outline is turned round - its edges
    reversed, last first - which is what 'ShapeFix_Face' did to it.

A part is a closed shell of outward-facing faces, the shell a solid, so it is
the body every part has to be (see "A part is a body, not a skin" in
'AGENTS.md') by construction rather than after a sandbox has looked at it. Its
'offset' and 'scale' are applied as it is built, into its coordinates, the way
'wrapper_transform' applies them, and claimed in the envelope as a wrapper
claims what it did (see 'Shape.finish_request').

And what it measures - the box, the volume, the centroid and the inertia every
shape's envelope carries - is arithmetic on the same numbers, exact where OCCT
integrates.
"""

import math

from . import brep_ascii as brep
from . import shape_envelope
from .brep_ascii import FORWARD, REVERSED, add, cross, scaled, sub, unit

# What this module reports for what it produces, as a wrapper does (see
# 'partcad.code_version'): raise it with any change that changes a shape it
# builds or what it says about one, and everything built before is built again.
CACHE_VERSION = 1

# The name that version is keyed under.
CODE_NAME = "basic_shapes.py"

# The outlines a sketch may have, and the solids a part may be, by the field
# that declares each.
SKETCH_KEYS = ("circle", "square", "rectangle", "slot", "inner")
PART_KEYS = ("cuboid", "cylinder")

_X = (1.0, 0.0, 0.0)
_Z = (0.0, 0.0, 1.0)
_MINUS_Z = (0.0, 0.0, -1.0)


def _number(value, what) -> float:
    """'value' as a float, or a ValueError that says which field it is.

    A field is a number by the time it gets here: an expression in it has been
    worked out already (see 'SketchFactoryBasic'). What is refused is what the
    old wrapper failed on deep inside OCCT, or quietly took for one ('true').
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("'%s' has to be a number, not %r" % (what, value))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("'%s' has to be a finite number, not %r" % (what, value))
    return value


def _field(config, key, what, default=0.0) -> float:
    return _number(config.get(key, default), "%s.%s" % (what, key))


# --------------------------------------------------------------------------- #
# Sketches                                                                    #
# --------------------------------------------------------------------------- #


def _polygon(points):
    """The edges of a closed polygon through 'points', in order, each from one point to the next."""
    vertices = [brep.Vertex(point) for point in points]
    return [_polygon_edge(start, vertices[(index + 1) % len(vertices)]) for index, start in enumerate(vertices)]


def _polygon_edge(start, end):
    """A straight edge from one vertex to another, as 'BRepBuilderAPI_MakeEdge' makes it."""
    return brep.Edge(
        brep.Line(start.point, sub(end.point, start.point)), 0.0, math.dist(start.point, end.point), start, end
    )


def _arc(start, middle, end, centre, radius):
    """Half a circle from 'start' through 'middle' to 'end', as 'GC_MakeArcOfCircle' makes it.

    The circle's X axis points at 'start' and it turns towards 'middle', so the
    edge runs from 0 to pi in the direction the three points were given in.
    """
    xdir = sub(start.point, centre)
    normal = cross(xdir, sub(middle, centre))
    return brep.Edge(brep.Circle(centre, normal, xdir, radius), 0.0, math.pi, start, end)


class _Outline:
    """One closed outline in the XY plane."""

    def empty(self) -> bool:
        """Whether it encloses nothing - which, as a hole, was always left out."""
        raise NotImplementedError

    def edges(self) -> list:
        """The edges of a wire that goes once round it, in order, each held forward."""
        raise NotImplementedError


class Circle(_Outline):
    def __init__(self, config):
        self.x = self.y = self.radius = 0.0
        if isinstance(config, dict):
            self.x = _field(config, "x", "circle")
            self.y = _field(config, "y", "circle")
            self.radius = _field(config, "radius", "circle")
        else:
            self.radius = _number(config, "circle")
        if self.radius < 0.0:
            raise ValueError("A circle cannot have a negative radius: %g" % self.radius)

    def empty(self) -> bool:
        return self.radius == 0.0

    def edges(self):
        # One edge, all the way round counter-clockwise from +X, starting and
        # ending at the one vertex there: what 'BRepBuilderAPI_MakeEdge' makes
        # of a 'gp_Circ'.
        vertex = brep.Vertex((self.x + self.radius, self.y, 0.0))
        circle = brep.Circle((self.x, self.y, 0.0), _Z, _X, self.radius)
        return [brep.Edge(circle, 0.0, 2.0 * math.pi, vertex, vertex)]


class Rect(_Outline):
    def __init__(self, config, what="rectangle"):
        self.x = self.y = self.side_x = self.side_y = 0.0
        if isinstance(config, dict):
            self.x = _field(config, "x", what)
            self.y = _field(config, "y", what)
            self.side_x = _field(config, "side-x", what)
            self.side_y = _field(config, "side-y", what)
        elif config is not None:
            raise ValueError("A %s is given as its 'side-x' and 'side-y', not as %r" % (what, config))

    def empty(self) -> bool:
        return self.side_x == 0.0 or self.side_y == 0.0

    def edges(self):
        hx, hy = self.side_x / 2.0, self.side_y / 2.0
        return _polygon(
            [
                (self.x + hx, self.y + hy, 0.0),
                (self.x + hx, self.y - hy, 0.0),
                (self.x - hx, self.y - hy, 0.0),
                (self.x - hx, self.y + hy, 0.0),
            ]
        )


class Square(Rect):
    def __init__(self, config):
        super().__init__(None, "square")
        if isinstance(config, dict):
            self.x = _field(config, "x", "square")
            self.y = _field(config, "y", "square")
            self.side_x = self.side_y = _field(config, "side", "square")
        else:
            self.side_x = self.side_y = _number(config, "square")


class Slot(_Outline):
    """A slot: a rectangle with semicircular ends, which is what a slotted hole is.

    Two arcs and two lines, and the two dimensions a drawing gives it: the
    overall 'length' from one rounded end to the other, and the 'width', which
    is the diameter of those ends and the width of the straight part between
    them. A slot of equal length and width is a circle, which is the degenerate
    case rather than an error - the two lines are simply not there.

    'x' and 'y' place the centre of the **first** rounded end, not the middle of
    the slot, and 'angle' turns it about that point. That is where a slot comes
    from: it is a hole that may also sit somewhere else, so it starts where the
    hole would have been and runs 'length - width' from there. A port that used
    to be a plain circle keeps its coordinates when the opening it marks is
    slotted, and the freedom of movement that goes with it runs from zero
    rather than from half a slot back.
    """

    def __init__(self, config):
        self.x = self.y = self.angle = 0.0
        self.length = self.width = 0.0
        if isinstance(config, dict):
            self.x = _field(config, "x", "slot")
            self.y = _field(config, "y", "slot")
            self.angle = _field(config, "angle", "slot")
            self.length = _field(config, "length", "slot")
            self.width = _field(config, "width", "slot")
        if self.width <= 0.0:
            raise ValueError("A slot needs a width greater than zero")
        if self.length < self.width:
            raise ValueError(
                "A slot %g long cannot be %g wide: its length is measured over its rounded ends"
                % (self.length, self.width)
            )

    def empty(self) -> bool:
        return False

    def _point(self, px, py):
        """One point of the outline, turned by 'angle' and placed on the first end."""
        radians = math.radians(self.angle)
        cos, sin = math.cos(radians), math.sin(radians)
        return (self.x + px * cos - py * sin, self.y + px * sin + py * cos, 0.0)

    def edges(self):
        radius = self.width / 2.0
        # The distance between the centres of the two rounded ends, measured
        # from the first - which is the origin. Zero when the slot is as long as
        # it is wide, which is a circle.
        reach = self.length - self.width

        top_left = brep.Vertex(self._point(0.0, radius))
        bottom_left = brep.Vertex(self._point(0.0, -radius))
        if reach > 0.0:
            top_right = brep.Vertex(self._point(reach, radius))
            bottom_right = brep.Vertex(self._point(reach, -radius))
        else:
            # The two lines would run between identical points, so they are not
            # drawn, and the arcs meet where they would have ended.
            top_right, bottom_right = top_left, bottom_left

        edges = []
        if reach > 0.0:
            edges.append(_polygon_edge(top_left, top_right))
        edges.append(_arc(top_right, self._point(reach + radius, 0.0), bottom_right, self._point(reach, 0.0), radius))
        if reach > 0.0:
            edges.append(_polygon_edge(bottom_right, bottom_left))
        edges.append(_arc(bottom_left, self._point(-radius, 0.0), top_left, self._point(0.0, 0.0), radius))
        return edges


def _outer(config):
    if "circle" in config:
        return Circle(config["circle"])
    if "square" in config:
        return Square(config["square"])
    if "rectangle" in config:
        return Rect(config["rectangle"])
    if "slot" in config:
        return Slot(config["slot"])
    return None


def _inner(config):
    inner = config.get("inner") or {}
    if not isinstance(inner, dict):
        raise ValueError("'inner' lists the shapes cut out of the sketch, not %r" % (inner,))
    shapes = []
    for single, several, kind in (
        ("circle", "circles", Circle),
        ("square", "squares", Square),
        ("rectangle", "rectangles", Rect),
        ("slot", "slots", Slot),
    ):
        if single in inner:
            shapes.append(kind(inner[single]))
        shapes.extend(kind(item) for item in inner.get(several) or [])
    return [shape for shape in shapes if not shape.empty()]


def _signed_area(wire):
    """The area 'wire' - '(orientation, edge)' pairs - goes round in the XY plane: positive counter-clockwise.

    Green's theorem, edge by edge: a straight edge is its term of the shoelace
    formula, and an arc is the shoelace term of its chord plus the segment
    between the chord and the arc, on whichever side the arc turns to.
    """
    total = 0.0
    for orientation, edge in wire:
        start, end = edge.start.point, edge.end.point
        sense = 1.0
        if orientation == REVERSED:
            start, end, sense = end, start, -1.0
        total += (start[0] * end[1] - end[0] * start[1]) / 2.0
        if isinstance(edge.curve, brep.Circle):
            angle = edge.last - edge.first
            turn = sense * edge.curve.normal[2]
            total += turn * edge.curve.radius**2 / 2.0 * (angle - math.sin(angle))
    return total


def _edge_bounds(edge):
    """'(low, high)': the corners of the box round one edge, exactly."""
    low = [min(a, b) for a, b in zip(edge.start.point, edge.end.point)]
    high = [max(a, b) for a, b in zip(edge.start.point, edge.end.point)]
    curve = edge.curve
    if isinstance(curve, brep.Circle):
        span = edge.last - edge.first
        for axis in range(3):
            # Along this axis the circle is 'centre + r A cos(t - phase)': at its
            # highest at 'phase' and its lowest half a turn later, wherever the
            # edge gets that far round.
            amplitude = math.hypot(curve.xdir[axis], curve.ydir[axis])
            if amplitude == 0.0:
                continue
            phase = math.atan2(curve.ydir[axis], curve.xdir[axis])
            for at, sign in ((phase, 1.0), (phase + math.pi, -1.0)):
                if (at - edge.first) % (2.0 * math.pi) <= span:
                    value = curve.centre[axis] + sign * curve.radius * amplitude
                    low[axis] = min(low[axis], value)
                    high[axis] = max(high[axis], value)
    return low, high


def _bounds(edges):
    low = [math.inf] * 3
    high = [-math.inf] * 3
    for edge in edges:
        edge_low, edge_high = _edge_bounds(edge)
        low = [min(a, b) for a, b in zip(low, edge_low)]
        high = [max(a, b) for a, b in zip(high, edge_high)]
    return low + high


def sketch(config):
    """'(brep, measurements)': the face a basic sketch's declaration describes.

    'brep' is the uncompressed payload, ASCII BREP; 'measurements' the section
    every encoded shape carries (see 'shape_envelope.METADATA_MEASUREMENTS').
    """
    outer = _outer(config)
    if outer is None:
        raise ValueError("Cannot build a sketch face: the config names no supported outer shape")
    if outer.empty():
        raise ValueError("Cannot build a sketch face: its outer shape encloses nothing")

    outline = [(FORWARD, edge) for edge in outer.edges()]
    area = _signed_area(outline)
    if area == 0.0:
        raise ValueError("Cannot build a sketch face: its outer shape encloses nothing")
    box = _bounds([edge for _orientation, edge in outline])

    wires = [(FORWARD, brep.Wire(outline))]
    for hole in _inner(config):
        wire = [(FORWARD, edge) for edge in hole.edges()]
        if (_signed_area(wire) > 0.0) == (area > 0.0):
            wire = [(REVERSED, edge) for _orientation, edge in reversed(wire)]
        wires.append((FORWARD, brep.Wire(wire)))

    # No curve on the plane is written for any edge: OCCT works one out from
    # the edge whenever it is asked for, and 'BRepBuilderAPI_MakeFace' stores
    # none either.
    centre = ((box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0, 0.0)
    plane = brep.Plane(centre, _Z if area > 0.0 else _MINUS_Z)
    face = brep.Face(plane, wires)

    measurements = {"bbox": box, "volume": None, "solids": 0, "freeShells": 0}
    return brep.write(face), measurements


# --------------------------------------------------------------------------- #
# Parts                                                                       #
# --------------------------------------------------------------------------- #


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _rotation(axis, angle):
    """The rotation of 'angle' degrees about 'axis', as the 3x3 matrix 'gp_Mat::SetRotation' builds."""
    x, y, z = unit(axis)
    radians = math.radians(angle)
    sin, cos = math.sin(radians), math.cos(radians)
    turn = 1.0 - cos
    return (
        (1.0 + turn * (-z * z - y * y), -z * sin + turn * x * y, y * sin + turn * x * z),
        (z * sin + turn * x * y, 1.0 + turn * (-x * x - z * z), -x * sin + turn * y * z),
        (-y * sin + turn * x * z, x * sin + turn * y * z, 1.0 + turn * (-x * x - y * y)),
    )


def _apply(matrix, vector):
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3))


def _multiplied(a, b):
    return tuple(tuple(sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3)) for row in range(3))


class Placement:
    """Where a part's own coordinates end up: turned by 'rotation', scaled by 'factor', moved by 'translation'.

    A point goes to 'factor * rotation * p + translation', which is what an
    'offset' and then a 'scale' make of it - the order 'Shape.finish_request'
    asks for them in.
    """

    def __init__(self):
        self.rotation = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        self.factor = 1.0
        self.translation = (0.0, 0.0, 0.0)

    def moved(self, offset) -> None:
        """Move by a packed '[[x, y, z], [ax, ay, az], angle]' offset, as 'wrapper_transform.relocate' does.

        The rotation is about the axis through the origin, and then the
        translation is added - build123d's 'Location(*offset)'. Any other form
        is refused, for the core to hand to build123d itself.
        """
        if not isinstance(offset, (list, tuple)) or len(offset) != 3:
            raise ValueError("not a '[[x, y, z], [ax, ay, az], angle]' location: %r" % (offset,))
        translation, axis, angle = offset
        for vector in (translation, axis):
            if not isinstance(vector, (list, tuple)) or len(vector) != 3 or not all(map(_is_number, vector)):
                raise ValueError("not a '[[x, y, z], [ax, ay, az], angle]' location: %r" % (offset,))
        if not _is_number(angle):
            raise ValueError("not a '[[x, y, z], [ax, ay, az], angle]' location: %r" % (offset,))
        rotation = _rotation([float(value) for value in axis], float(angle))
        self.rotation = _multiplied(rotation, self.rotation)
        self.translation = add(_apply(rotation, self.translation), tuple(float(value) for value in translation))

    def scaled(self, factor) -> None:
        """Scale by a number about the origin, as 'wrapper_transform.scale' does a part that was moved there.

        A factor that is not a number greater than zero is refused: anything
        else turns a solid inside out or flattens it, and is left to the core
        to hand to build123d.
        """
        if not _is_number(factor) or not factor > 0:
            raise ValueError("only a number greater than zero is applied here, not %r" % (factor,))
        self.factor *= float(factor)
        self.translation = scaled(self.translation, float(factor))

    def point(self, point):
        return add(scaled(_apply(self.rotation, point), self.factor), self.translation)

    def axes(self):
        """Where the X, Y and Z axes point: the columns of the rotation."""
        return tuple(tuple(self.rotation[row][col] for row in range(3)) for col in range(3))

    def length(self, length) -> float:
        return self.factor * length


def _finish(request):
    """'(placement, claim)': what of 'Shape.finish_request()' is done as the part is built, and the claim to make.

    The same steps, in the same order and with the same echo, as
    'wrapper_common._finish', so the core takes the claim exactly as it takes a
    wrapper's: a part built here is a solid by construction, so it is
    validated, with nothing wrong with it; then its offset and its scale go
    into its coordinates, as far as they can, and whatever cannot is left to
    the core, which says why it stopped.
    """
    placement = Placement()
    claim = {}
    if not request:
        return placement, claim
    validate = request.get("validate")
    if isinstance(validate, dict):
        claim["validated"] = {"solidify": bool(validate.get("solidify")), "problems": []}
    for operation in ("offset", "scale"):
        if operation not in request:
            continue
        try:
            if operation == "offset":
                placement.moved(request[operation])
            else:
                placement.scaled(request[operation])
        except ValueError as e:
            claim["declined"] = "%s: %s" % (operation, e)
            break
        claim[operation] = request[operation]
    return placement, claim


def _dimension(config, key, what) -> float:
    if key not in config:
        raise ValueError("A %s needs its '%s'" % (what, key))
    value = _field(config, key, what)
    if not value > 0.0:
        raise ValueError("A %s needs a '%s' greater than zero, not %g" % (what, key, value))
    return value


def _turned(tensor, axes):
    """'tensor', stated about a part's own axes, about the world's ('mass_properties.turned')."""
    # Late, because 'physics' imports half of PartCAD and this module is
    # imported as the factories are registered.
    from .physics import mass_properties

    matrix = tuple(tuple(axes[col][row] for col in range(3)) for row in range(3))
    return mass_properties.turned(tensor, matrix)


def _edge_key(axis, signs):
    """An edge of a cuboid, by the axis it runs along and which side of the other two it is on."""
    return tuple(None if index == axis else sign for index, sign in enumerate(signs))


def _cuboid(config, placement):
    if isinstance(config, dict):
        sides = [_dimension(config, key, "cuboid") for key in ("side-x", "side-y", "side-z")]
        centre = tuple(_field(config, key, "cuboid") for key in ("x", "y", "z"))
    else:
        side = _number(config, "cuboid")
        if not side > 0.0:
            raise ValueError("A cuboid needs a side greater than zero, not %g" % side)
        sides = [side] * 3
        centre = (0.0, 0.0, 0.0)

    origin = placement.point(centre)
    axes = placement.axes()
    half = [placement.length(side / 2.0) for side in sides]

    def corner(signs):
        point = origin
        for axis, sign in enumerate(signs):
            point = add(point, scaled(axes[axis], sign * half[axis]))
        return point

    vertices = {}
    for i in (-1, 1):
        for j in (-1, 1):
            for k in (-1, 1):
                vertices[(i, j, k)] = brep.Vertex(corner((i, j, k)))

    # An edge along each axis between every pair of corners that differ only
    # along it, running from the - corner to the + one; known by its axis and
    # the signs of the other two.
    edges = {}
    for axis in range(3):
        for signs in vertices:
            if signs[axis] != -1:
                continue
            end = list(signs)
            end[axis] = 1
            start = vertices[signs]
            edges[_edge_key(axis, signs)] = brep.Edge(
                brep.Line(start.point, axes[axis]), 0.0, 2.0 * half[axis], start, vertices[tuple(end)]
            )

    faces = []
    for axis in range(3):
        # The other two axes, in the order that makes them a right-handed pair
        # with this one.
        u, v = (axis + 1) % 3, (axis + 2) % 3
        for side in (-1, 1):
            # On the + side the plane's X and Y are u and v; on the - side v
            # and u, so that its normal points out of the solid either way.
            along_x, along_y = (u, v) if side > 0 else (v, u)
            normal = scaled(axes[axis], float(side))
            plane = brep.Plane(add(origin, scaled(axes[axis], side * half[axis])), normal, axes[along_x])
            # Counter-clockwise about the outward normal, corner by corner.
            corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            wire = []
            for index, (sx, sy) in enumerate(corners):
                nx, ny = corners[(index + 1) % 4]
                signs = [0, 0, 0]
                signs[axis], signs[along_x], signs[along_y] = side, sx, sy
                moving = along_x if nx != sx else along_y
                edge = edges[_edge_key(moving, signs)]
                going_up = (nx > sx) if moving == along_x else (ny > sy)
                wire.append((FORWARD if going_up else REVERSED, edge))
                # The same edge on this plane, from its own start: in the
                # plane's coordinates, measured from its centre.
                start = [0.0, 0.0]
                start[0] = -half[along_x] if moving == along_x else sx * half[along_x]
                start[1] = -half[along_y] if moving == along_y else sy * half[along_y]
                direction = (1.0, 0.0) if moving == along_x else (0.0, 1.0)
                edge.on(plane, brep.Line(start, direction))
            faces.append(brep.Face(plane, [(FORWARD, brep.Wire(wire))]))

    solid = brep.Solid([(FORWARD, brep.Shell([(FORWARD, face) for face in faces]))])

    extent = [sum(half[axis] * abs(axes[axis][world]) for axis in range(3)) for world in range(3)]
    volume = 8.0 * half[0] * half[1] * half[2]
    a, b, c = half
    inertia = (
        (volume * (b * b + c * c) / 3.0, 0.0, 0.0),
        (0.0, volume * (a * a + c * c) / 3.0, 0.0),
        (0.0, 0.0, volume * (a * a + b * b) / 3.0),
    )
    return solid, origin, extent, volume, _turned(inertia, axes)


def _cylinder(config, placement):
    if not isinstance(config, dict):
        raise ValueError("A cylinder is given as its 'radius' and 'height', not as %r" % (config,))
    radius = _dimension(config, "radius", "cylinder")
    height = _dimension(config, "height", "cylinder")
    centre = tuple(_field(config, key, "cylinder") for key in ("x", "y", "z"))

    origin = placement.point(centre)
    xdir, ydir, axis = placement.axes()
    radius = placement.length(radius)
    height = placement.length(height)
    base = add(origin, scaled(axis, -height / 2.0))
    top = add(base, scaled(axis, height))

    # What 'BRepPrimAPI_MakeCylinder' makes: one face round the side, with a
    # seam up it at u = 0, and a disc at either end. The side is parametrized
    # by the angle from X and the height above the base.
    side = brep.Cylinder(base, axis, xdir, radius)
    top_plane = brep.Plane(top, axis, xdir)
    base_plane = brep.Plane(base, axis, xdir)

    top_vertex = brep.Vertex(add(top, scaled(xdir, radius)))
    base_vertex = brep.Vertex(add(base, scaled(xdir, radius)))

    top_edge = brep.Edge(brep.Circle(top, axis, xdir, radius), 0.0, 2.0 * math.pi, top_vertex, top_vertex)
    top_edge.on(side, brep.Line((0.0, height), (1.0, 0.0)))
    top_edge.on(top_plane, brep.Circle2d((0.0, 0.0), radius))

    seam = brep.Edge(brep.Line(base_vertex.point, axis), 0.0, height, base_vertex, top_vertex)
    seam.on(side, brep.Line((2.0 * math.pi, 0.0), (0.0, 1.0)), brep.Line((0.0, 0.0), (0.0, 1.0)))

    base_edge = brep.Edge(brep.Circle(base, axis, xdir, radius), 0.0, 2.0 * math.pi, base_vertex, base_vertex)
    base_edge.on(side, brep.Line((0.0, 0.0), (1.0, 0.0)))
    base_edge.on(base_plane, brep.Circle2d((0.0, 0.0), radius))

    # Round the side counter-clockwise in (u, v): along the base, up the seam
    # at u = 2 pi, back along the top and down the seam at u = 0.
    side_face = brep.Face(
        side,
        [(FORWARD, brep.Wire([(REVERSED, top_edge), (FORWARD, seam), (FORWARD, base_edge), (REVERSED, seam)]))],
    )
    top_face = brep.Face(top_plane, [(FORWARD, brep.Wire([(FORWARD, top_edge)]))])
    # The base's plane faces up, into the solid, so the shell holds it reversed.
    base_face = brep.Face(base_plane, [(REVERSED, brep.Wire([(REVERSED, base_edge)]))])
    shell = brep.Shell([(FORWARD, side_face), (FORWARD, top_face), (REVERSED, base_face)])
    solid = brep.Solid([(FORWARD, shell)])

    extent = [
        height / 2.0 * abs(axis[world]) + radius * math.sqrt(max(0.0, 1.0 - axis[world] ** 2)) for world in range(3)
    ]
    volume = math.pi * radius * radius * height
    across = volume * (3.0 * radius * radius + height * height) / 12.0
    inertia = ((across, 0.0, 0.0), (0.0, across, 0.0), (0.0, 0.0, volume * radius * radius / 2.0))
    return solid, origin, extent, volume, _turned(inertia, (xdir, ydir, axis))


def part(config, finish=None):
    """'(brep, measurements, claim)': the solid a basic part's declaration describes.

    'finish' is the part's 'finish_request()', and 'claim' what of it was done
    as the solid was built, for the envelope's 'finished' section (see
    'shape_envelope.METADATA_FINISHED').
    """
    named = [key for key in PART_KEYS if key in config]
    if len(named) != 1:
        raise ValueError(
            "A basic part is one of %s, and this one names %s"
            % (" or ".join(PART_KEYS), " and ".join(named) if named else "neither")
        )
    placement, claim = _finish(finish)
    build = _cuboid if named[0] == "cuboid" else _cylinder
    solid, centre, extent, volume, inertia = build(config[named[0]], placement)

    measurements = {
        "bbox": [centre[axis] - extent[axis] for axis in range(3)] + [centre[axis] + extent[axis] for axis in range(3)],
        "volume": volume,
        "solids": 1,
        "freeShells": 0,
        "centroid": list(centre),
        "unitInertia": [list(row) for row in inertia],
    }
    return brep.write(solid), measurements, claim


def envelope(payload, measurements, name=None, label=None, claim=None) -> dict:
    """The shape envelope a factory hands back for what 'sketch()' or 'part()' wrote.

    The payload compressed as every payload is carried, and the measurements -
    and, for a part, the claim of what was done of its 'finish_request()' - in
    the metadata, exactly where a wrapper's encoder puts them
    ('ocp_serialize.encode_shape', 'wrapper_common.finished'), so nothing
    downstream can tell which of the two made it.
    """
    shape = shape_envelope.make_shape(shape_envelope.brep_compressed(payload), name=name, label=label)
    metadata = {shape_envelope.METADATA_MEASUREMENTS: measurements}
    if claim:
        metadata[shape_envelope.METADATA_FINISHED] = claim
    shape[shape_envelope.KEY_METADATA] = metadata
    return shape
