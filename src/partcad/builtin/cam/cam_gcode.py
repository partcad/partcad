#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in G-code route implementation (see '//builtin/cam' in partcad.yaml).

What it produces is a 2.5D route: the object's outline, offset by the radius of
the cutter, cut at a series of depths. That is what a CNC router does to sheet
goods and what a mill does to a plate, and it is arithmetic on the object's own
geometry rather than a simulation of anything - which is why PartCAD ships it,
where it ships no solver.

The outline is a **section**, taken at the bottom of the cut. For a prismatic
object - a panel, a plate, a gasket, anything cut out of stock of one thickness
- that is the same outline at every depth and there is nothing more to say. For
an object whose cross-section changes over the cut, no single outline is right:
following the widest gouges nothing but leaves material, following the narrowest
cuts into the part. This one follows the bottom and says so, as a warning naming
how much the two ends of the cut differ by, because a route produced from an
outline the user did not expect is the one failure that looks like a success all
the way to the machine.

The three operations differ in which side of that outline the tool runs on:

    'profile'   outward by the tool's radius on the outer boundary, inward on
                every hole. The object survives the cut at its nominal size.
                Holes are cut first, so that the part is still held by its stock
                while they are.
    'pocket'    inward by the tool's radius, and then inward again by
                'stepover' of the tool's diameter until nothing is left. Emitted
                innermost ring first, so the wall is cut last and by a tool that
                is only engaged on one side.
    'engrave'   along the outline itself, offset by nothing. What a V-bit or a
                drag knife does.

Every curve is emitted as G1 moves within 'tolerance' of the true curve, rather
than as G2/G3 arcs. An arc word is only an arc while the plane it was written in
survives the post-processor, and 'tolerance' is one number that says exactly what
the approximation costs; two of them (the arc and the tolerance) say less.

The file is byte-stable by construction: nothing in it is a timestamp, a host
name or a version, so the same object and the same parameters produce the same
bytes on any machine. That is what makes a route something a repository can hold
and a reviewer can diff.
"""

import math
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize, and 'render_svg.py', which needs
# this for the same reason.
import pyexpat  # noqa: F401

import build123d as b3d

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# Millimetres per inch. The request is in millimetres whatever the configuration
# was written in (see 'partcad.cam'), so this is only ever used on the way out.
MM_PER_INCH = 25.4

# Two points closer than this are the same point, as far as a cutting move goes.
# A micron: finer than any router positions to, and coarser than the noise an
# offset leaves where two edges meet.
TOLERANCE = 1e-6

# How far the section at the top of the cut may differ in area from the one at
# the bottom before the object is called non-prismatic, as a fraction. One
# percent is under what a fillet at the edge of a panel costs and over what
# floating-point noise in two independent sections does.
PRISMATIC_TOLERANCE = 0.01

# How far inside each end of the cut the two sections are taken, as a fraction
# of the cut depth. Sectioning a solid exactly at its own top or bottom face is
# a degenerate intersection, and what comes back from one is not reliably the
# face: a hair inside is the whole of the trick.
SECTION_INSET = 1e-3

# The most rings a pocket may be cleared with, as a multiple of the number the
# stepover implies. A pocket is cleared by offsetting inward until the offset
# comes back empty, and "empty" is the offsetting library's judgement rather
# than ours - so the loop needs a bound that does not depend on it agreeing.
POCKET_RING_LIMIT = 4


def _shape(wrapped):
    """A build123d object around the raw OCCT shape the request carries.

    The same trick '//builtin/render/render_svg.py' uses: build123d has no
    public constructor from a 'TopoDS_Shape', so a throwaway solid is made and
    its 'wrapped' replaced.
    """
    obj = b3d.Solid.make_box(1, 1, 1)
    obj.wrapped = wrapped
    return obj


def _faces_at(obj, z):
    """The object's cross-section at one height, as faces.

    An empty list is an answer rather than a failure: a Z above or below the
    object has no section, and the caller says what that means where it knows
    what it was asking.
    """
    try:
        return list(b3d.section(obj, b3d.Plane.XY.offset(z)).faces())
    except Exception:
        # A section that OCCT cannot take is one there is nothing at. Treated as
        # empty so that the caller's own message - which knows the depth, the
        # object and what it was for - is what the user reads.
        return []


def _planar_faces(obj):
    """An object that is already flat, as the faces it is made of.

    A sketch has no thickness to section: its faces *are* the outline, and
    asking for a cross-section of something that lies in the plane you are
    cutting it with is a degenerate intersection. This is that case.
    """
    return [face for face in obj.faces() if face.area > 0]


def _edge_points(edge, tolerance):
    """One edge as a list of (x, y), within 'tolerance' of the true curve.

    A straight edge is its two ends and nothing else - a line needs no
    approximating, and a linearized one is bytes rather than accuracy.
    """
    if edge.geom_type == b3d.GeomType.LINE:
        start, end = edge.start_point(), edge.end_point()
        return [(start.X, start.Y), (end.X, end.Y)]

    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection

    adaptor = BRepAdaptor_Curve(edge.wrapped)
    sampler = GCPnts_QuasiUniformDeflection(adaptor, tolerance)
    if not sampler.IsDone() or sampler.NbPoints() < 2:
        # Nothing was sampled, so fall back to the ends. A curve that cannot be
        # sampled is one whose chord is the best available answer, and an edge
        # dropped from the path would be a gouge.
        start, end = edge.start_point(), edge.end_point()
        return [(start.X, start.Y), (end.X, end.Y)]

    points = [(sampler.Value(i).X(), sampler.Value(i).Y()) for i in range(1, sampler.NbPoints() + 1)]

    # The sampler follows the underlying curve's parametrization, which is not
    # the edge's orientation: an edge the wire traverses backwards comes back
    # sampled forwards. Whichever end of the samples is nearer the edge's own
    # start point is the end the wire starts from.
    start = edge.start_point()
    if _distance(points[0], (start.X, start.Y)) > _distance(points[-1], (start.X, start.Y)):
        points.reverse()
    return points


def _distance(a, b):
    """Plane distance between two (x, y) points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _ordered_edges(wire):
    """The wire's edges in the order it traverses them, each oriented that way.

    This is what makes the wire a path rather than a set, and it is OCCT's own
    wire explorer rather than build123d's 'order_edges()' on purpose. That one
    sorts the edges by where their midpoints fall along the wire, and a contour
    that came out of 'offset_2d' defeats the projection it sorts by: offsetting
    leaves degenerate arcs a few tens of nanometres long where two of the
    original edges met, and the parameter of a point on one of those is
    something OCCT declines to compute - it raises 'Standard_ConstructionError'
    with no message at all, so what reaches the user is a route that does not
    exist and not a word about why. The explorer walks the wire's own
    topological connectivity instead, which is how the wire was built and needs
    no projection.
    """
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_ShapeEnum

    if wire.wrapped.ShapeType() != TopAbs_ShapeEnum.TopAbs_WIRE:
        # Not a wire, so there is no connectivity to walk and nothing to order:
        # 'offset_2d' hands back a single 'Edge' where the contour came out as
        # one closed curve, which is what the inside of a round hole offset by
        # the tool's radius is.
        return wire.edges()

    explorer = BRepTools_WireExplorer(wire.wrapped)
    edges = []
    while explorer.More():
        edges.append(b3d.Edge(explorer.Current()))
        explorer.Next()
    return edges


def _wire_points(wire, tolerance):
    """One closed wire as the polyline a machine cuts, first point repeated last.

    The degenerate edges '_ordered_edges()' describes need nothing done about
    them here: an edge shorter than 'TOLERANCE' contributes a point the previous
    one already ended at, and that is the point dropped just below.
    """
    points = []
    for edge in _ordered_edges(wire):
        segment = _edge_points(edge, tolerance)
        if points and _distance(points[-1], segment[0]) <= TOLERANCE:
            # The edges meet, so the shared point is one point and not two.
            segment = segment[1:]
        points.extend(segment)

    if len(points) > 1 and _distance(points[0], points[-1]) <= TOLERANCE:
        points = points[:-1]
    if len(points) < 2:
        return []
    # Closed: a contour that does not come back to where it started leaves an
    # uncut sliver exactly where the tool entered.
    return points + [points[0]]


def _signed_area(points):
    """Twice the signed area of a closed polyline. Positive is anticlockwise."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        total += x0 * y1 - x1 * y0
    return total


def _oriented(points, clockwise):
    """The same closed path, traversed the way the cut wants it.

    Which way round a contour is cut is climb milling or conventional milling,
    and the difference is real: it decides which side of the tool the chip comes
    off and which edge of the two is the finished one. A right-hand cutter
    climbs when the material is on its right, which is clockwise around the
    outside of a part and anticlockwise around the inside of a hole.
    """
    if (_signed_area(points) < 0) == bool(clockwise):
        return points
    return list(reversed(points))


def _offset(wire, amount, tolerance):
    """One wire offset by 'amount', or None where nothing is left of it.

    A negative offset eventually consumes the wire, and how it reports that
    depends on the geometry: an exception, nothing at all, or something too
    small to cut. All three mean the same thing here - the pocket is cleared -
    so all three come back as None.
    """
    if abs(amount) <= TOLERANCE:
        return wire
    try:
        offset = wire.offset_2d(amount, kind=b3d.Kind.ARC)
    except Exception:
        return None
    if offset is None:
        return None
    try:
        if offset.length <= tolerance:
            return None
    except Exception:
        return None
    return offset


def _profile_paths(faces, radius, tolerance):
    """The contours a profile cut follows: every hole, then every outer boundary.

    Holes first, and not as a matter of taste. A profile cut ends by separating
    the part from its stock, and every hole cut after that is cut in something
    that is no longer held. That is what the group number carries (see
    '_sorted_paths'): 0 is cut before 1, whatever order the faces came back in.
    """
    paths = []
    for face in faces:
        for wire in face.inner_wires():
            # Inward, into the hole: the path is smaller than the hole by the
            # tool's radius, so the hole comes out the size it was drawn.
            offset = _offset(wire, -radius, tolerance)
            if offset is None:
                raise Exception(
                    "A hole of this object is no larger than the %.3f mm tool: "
                    "there is no path around the inside of it" % (radius * 2)
                )
            paths.append((offset, True, 0))
        offset = _offset(face.outer_wire(), radius, tolerance)
        if offset is None:
            raise Exception("The outline of this object could not be offset by the tool's radius")
        paths.append((offset, False, 1))
    return paths


def _pocket_paths(faces, radius, stepover, tolerance):
    """The rings a pocket is cleared with, innermost first.

    Innermost first so that the wall is the last thing cut, by a tool that is
    engaged on one side rather than buried in a slot. The first ring generated
    is the one against the wall, so the list is built outside in and handed back
    reversed.
    """
    paths = []
    for face in faces:
        if face.inner_wires():
            # An island inside a pocket is material that has to be left, and
            # leaving it means knowing where the rings must stop rather than
            # where they run out. Refused rather than cut through: a route that
            # machines away a boss nobody meant to lose is the kind of answer
            # that is only discovered on the machine.
            raise Exception(
                "This object's outline has a hole in it, which would be an island in the middle of the pocket. "
                "'operation: pocket' clears a simple outline; cut the island as a 'profile' of its own"
            )

        outer = face.outer_wire()
        rings = []
        # The offsets go 'radius', 'radius + step', 'radius + 2*step'... until
        # the wire is used up. The bound is what stops a stepover of a
        # thousandth of a millimetre from running until the machine does.
        step = max(stepover, tolerance)
        size = face.bounding_box().size
        limit = int(POCKET_RING_LIMIT * (max(size.X, size.Y) / step + 1))
        amount = radius
        for _ in range(limit):
            offset = _offset(outer, -amount, tolerance)
            if offset is None:
                break
            rings.append(offset)
            amount += step
        if not rings:
            raise Exception(
                "This object's outline is no wider than the %.3f mm tool: nothing can be cleared" % (radius * 2)
            )
        # Reversed, so that group 0 is the innermost ring and the wall is cut
        # last. Two pockets in one section clear ring by ring together, which is
        # the same tool at the same depth either way.
        paths.extend((ring, True, index) for index, ring in enumerate(reversed(rings)))
    return paths


def _engrave_paths(faces):
    """Every contour of the outline, followed exactly.

    No offset, so the diameter of the tool says nothing about where it goes -
    which is what a V-bit and a drag knife want, and what makes this the one
    operation whose path is the object's own geometry.
    """
    paths = []
    for face in faces:
        paths.extend((wire, True, 0) for wire in face.inner_wires())
        paths.append((face.outer_wire(), False, 1))
    return paths


def _sorted_paths(paths):
    """The paths in the order they are cut in.

    The group each path carries is the order its operation asked for -- holes
    before outlines, innermost pocket ring before the wall -- and it is what
    sorts first, because that order is about the part surviving the cut rather
    than about tidiness. Position breaks ties within a group, and only there:
    the faces and wires of a section come back in whatever order the modelling
    kernel built them, and two runs over one object have to produce one file.
    """
    return sorted(
        paths,
        key=lambda path: (
            path[2],
            round(min(point[0] for point in path[0]), 6),
            round(min(point[1] for point in path[0]), 6),
        ),
    )


class Program:
    """The G-code file, accumulated a line at a time.

    Every coordinate goes through 'number()', which is where the output units
    and the precision are applied - once, in one place, so that a file cannot
    come out with its depths in millimetres and its moves in inches.
    """

    def __init__(self, units, precision, comments):
        self.lines = []
        self.scale = 1.0 / MM_PER_INCH if units == "in" else 1.0
        self.precision = int(precision)
        self.comments = bool(comments)
        self.cut_length = 0.0
        self._where = None

    def number(self, value):
        """One length, in the file's units, at the file's precision."""
        # '+ 0.0' turns a negative zero into a zero: '-0.000' is the same place
        # as '0.000' and a diff that says otherwise is noise.
        return "%.*f" % (self.precision, round(value * self.scale, self.precision) + 0.0)

    def feed(self, value):
        """One feed rate, in the file's units per minute.

        Not 'number()': a feed is not a coordinate, and the precision a
        coordinate needs writes '1200.000' where every machine, sender and
        operator writes '1200'. Trailing zeros are dropped for the same reason.
        """
        text = "%.1f" % (value * self.scale)
        return text[:-2] if text.endswith(".0") else text

    def comment(self, text):
        if self.comments:
            # Parentheses are RS-274's own comment, and the one every controller
            # reads. A ')' inside would end it early, so it cannot travel.
            self.lines.append("(%s)" % text.replace("(", "[").replace(")", "]"))

    def code(self, line):
        self.lines.append(line)

    def rapid_z(self, z):
        self.code("G0 Z%s" % self.number(z))
        self._where = None

    def rapid_xy(self, point):
        self.code("G0 X%s Y%s" % (self.number(point[0]), self.number(point[1])))
        self._where = point

    def plunge(self, z, feed):
        self.code("G1 Z%s F%s" % (self.number(z), self.feed(feed)))

    def cut_to(self, point, feed=None) -> bool:
        """One cutting move, dropped if it goes nowhere. True when one was written.

        A contour offset from a wire with several edges meeting at a tangent
        carries points a micron apart, and a move to where the tool already is
        is a line in the file and a dwell on the machine.

        The answer matters because of what carries the feed. A pass writes 'F'
        on its first cutting move and on none of the others, so a caller that
        counts a dropped move as that first one writes no 'F' at all -- and the
        controller keeps the feed from the 'G1 Z' that plunged into the work,
        cutting the whole contour at the plunge rate. Whether the move happened
        is the only thing that can settle it, and only this knows.
        """
        if self._where is not None:
            distance = _distance(self._where, point)
            if distance <= TOLERANCE:
                return False
            self.cut_length += distance
        word = "" if feed is None else " F%s" % self.feed(feed)
        self.code("G1 X%s Y%s%s" % (self.number(point[0]), self.number(point[1]), word))
        self._where = point
        return True

    def text(self):
        # A trailing newline, and Unix line endings: a G-code file is read by
        # senders, editors and diffs, and all three want the same thing.
        return "\n".join(self.lines) + "\n"


def _require(request, key, what):
    """One numeric parameter of the job, or a refusal naming where to set it."""
    value = request.get(key)
    if value is None:
        raise Exception(
            "No '%s' is configured. Set it in this object's 'cam:' section, or for every object of the package "
            "in the package's 'cam: <file type>:' section" % what
        )
    return float(value)


def process(path, request):
    try:
        # Every default below is written as 'or <default>' rather than as the
        # second argument of 'get'. A layer that declares a key with nothing
        # under it ('stepover:' on its own) parses as None, and None is a value
        # 'get' hands back happily and 'float()' dies on - so a package that
        # blanks a parameter would otherwise take down every object it covers
        # rather than falling back to what it blanked. 'comments' is the one
        # exception, because 'false' is a real answer there and 'or' would
        # overrule it.
        units = str(request.get("units") or "mm").lower()
        if units not in ("mm", "in"):
            raise Exception("'units' is 'mm' or 'in', not %r" % request.get("units"))

        operation = str(request.get("operation") or "profile").lower()
        if operation not in ("profile", "pocket", "engrave"):
            raise Exception("'operation' is 'profile', 'pocket' or 'engrave', not %r" % request.get("operation"))

        direction = str(request.get("direction") or "climb").lower()
        if direction not in ("climb", "conventional"):
            raise Exception("'direction' is 'climb' or 'conventional', not %r" % request.get("direction"))

        tool = _require(request, "tool", "tool")
        radius = tool / 2.0
        feed = _require(request, "feed", "feed")
        plunge = float(request.get("plunge") or feed)
        # A clearance, not a coordinate: how far *above the top of the object*
        # the tool travels between contours. The absolute height it becomes is
        # computed once the object's own top is known, below. Writing it out as
        # an absolute Z instead would be right only for an object whose top
        # happens to sit at Z0 and a crash into the work for every other one.
        safe_clearance = _require(request, "safe_z", "safe_z")
        depth_per_pass = _require(request, "depth_per_pass", "depth_per_pass")
        stepover = float(request.get("stepover") or 0.5) * tool
        tolerance = float(request.get("tolerance") or 0.01)
        speed = request.get("speed")

        obj = _shape(request["wrapped"])
        box = obj.bounding_box()
        top = box.max.Z
        height = box.max.Z - box.min.Z

        warnings = []
        depth = request.get("depth")
        if depth is None:
            if height <= TOLERANCE:
                # A sketch, or anything else with no thickness. There is nothing
                # to cut *through*, so how deep to go is not something the object
                # can answer and not something to guess.
                raise Exception(
                    "This object is flat, so there is no thickness to cut through: set 'depth:' in its 'cam:' section"
                )
            depth = height
        depth = float(depth)
        if depth > height + TOLERANCE and height > TOLERANCE:
            warnings.append(
                "the cut is %.3f mm deep and the object is %.3f mm thick, so it goes %.3f mm past the bottom of it"
                % (depth, height, depth - height)
            )

        if height <= TOLERANCE:
            # Flat: the faces are the outline, and there is nothing to section.
            faces = _planar_faces(obj)
        else:
            inset = max(depth * SECTION_INSET, TOLERANCE)
            bottom_of_cut = max(top - depth + inset, box.min.Z + inset)
            faces = _faces_at(obj, bottom_of_cut)
            top_faces = _faces_at(obj, top - inset)
            if faces and top_faces:
                bottom_area = sum(face.area for face in faces)
                top_area = sum(face.area for face in top_faces)
                largest = max(bottom_area, top_area)
                if largest > 0 and abs(top_area - bottom_area) / largest > PRISMATIC_TOLERANCE:
                    warnings.append(
                        "the outline changes over the depth of the cut (%.1f mm2 at the top, %.1f mm2 at the bottom); "
                        "this route follows the one at the bottom" % (top_area, bottom_area)
                    )

        if not faces:
            raise Exception("This object has no outline to cut: its cross-section at the bottom of the cut is empty")

        if operation == "profile":
            wires = _profile_paths(faces, radius, tolerance)
        elif operation == "pocket":
            wires = _pocket_paths(faces, radius, stepover, tolerance)
        else:
            wires = _engrave_paths(faces)

        paths = []
        for wire, inside, group in wires:
            points = _wire_points(wire, tolerance)
            if len(points) < 3:
                continue
            # Climb means the material on the tool's right: clockwise around the
            # outside of the part, anticlockwise around the inside of a hole or
            # a pocket. Conventional is the other way round, both times.
            clockwise = (direction == "climb") != bool(inside)
            paths.append((_oriented(points, clockwise), inside, group))
        if not paths:
            raise Exception("This object's outline produced no cutting path")

        passes = max(1, int(math.ceil(depth / depth_per_pass - 1e-9)))
        depths = [top - min(depth, depth_per_pass * (index + 1)) for index in range(passes)]
        safe_height = top + safe_clearance

        comments = request.get("comments")
        program = Program(units, request.get("precision") or 3, True if comments is None else bool(comments))
        program.comment("PartCAD route")
        name = request.get("shape_name")
        package = request.get("package_name")
        if name:
            program.comment("object: %s" % ("%s:%s" % (package, name) if package else name))
        program.comment(
            "operation: %s %s, tool %s, depth %s in %d passes"
            % (operation, direction, program.number(tool), program.number(depth), passes)
        )
        program.comment("units: %s" % ("millimeters" if units == "mm" else "inches"))

        program.code("G21" if units == "mm" else "G20")
        program.code("G90")
        program.code("G17")
        program.code("G94")
        if speed:
            program.code("M3 S%d" % int(float(speed)))
        program.rapid_z(safe_height)

        for points, _inside, _group in _sorted_paths(paths):
            program.rapid_xy(points[0])
            for z in depths:
                program.plunge(z, plunge)
                first = True
                for point in points[1:]:
                    # Still 'first' until a move is actually written: a dropped
                    # one must not consume the pass's feed word (see 'cut_to').
                    if program.cut_to(point, feed if first else None):
                        first = False
                # Back at the start of the contour, which is where the next
                # pass plunges from - so there is nothing to move before it.
            program.rapid_z(safe_height)

        if speed:
            program.code("M5")
        program.code("M30")

        with open(path, "w", newline="\n") as f:
            f.write(program.text())

        return {
            "success": True,
            "exception": None,
            "warnings": warnings,
            "stats": {
                "operation": operation,
                "paths": len(paths),
                "passes": passes,
                "depth": depth,
                "cut_length": program.cut_length,
            },
        }

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
