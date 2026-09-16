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


def _wire_points(wire, tolerance):
    """One closed wire as the polyline a machine cuts, first point repeated last.

    'order_edges()' is what makes this a path rather than a set: it hands the
    edges back in the order the wire traverses them, each oriented the way the
    wire goes through it.
    """
    points = []
    for edge in wire.order_edges():
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


def _cnc(request, obj, units):
    """The route a CNC router or mill cuts: contours, offset, at stepped depths.

    What `pc cam` has always written, and what a `subtractive` part that names
    no machine still gets -- unchanged, byte for byte, which is the point.
    """
    # Every default below is written as 'or <default>' rather than as the
    # second argument of 'get'. A layer that declares a key with nothing
    # under it ('stepover:' on its own) parses as None, and None is a value
    # 'get' hands back happily and 'float()' dies on - so a package that
    # blanks a parameter would otherwise take down every object it covers
    # rather than falling back to what it blanked. 'comments' is the one
    # exception, because 'false' is a real answer there and 'or' would
    # overrule it.
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

    return (
        program,
        warnings,
        {
            "machine": "cnc",
            "operation": operation,
            "paths": len(paths),
            "passes": passes,
            "depth": depth,
            "cut_length": program.cut_length,
        },
    )


def _orient(obj, tool_axis_vector):
    """The shape as it sits on the machine, with the tool axis pointing down.

    Everything below this line works in the machine's own frame: Z is the tool
    axis, G17 is the plane the contours are in, and "the top of the object" is
    its highest Z. A part that declares it is cut along some other axis is not a
    different problem -- it is the same part fixtured differently -- so it is
    rotated into that frame once, here, and the rest of the file needs to know
    nothing about it.

    The default '-Z' is the identity, deliberately and testably: a part that
    names no machine, or names one that works the usual way down, produces
    exactly the bytes it produced before any of this existed.
    """
    if not tool_axis_vector:
        return obj
    x, y, z = (float(component) for component in tool_axis_vector)
    length = math.sqrt(x * x + y * y + z * z)
    if length <= TOLERANCE:
        raise Exception("the tool axis is a zero vector")
    x, y, z = x / length, y / length, z / length

    # Already pointing down: nothing to do, and nothing to perturb.
    if abs(x) <= TOLERANCE and abs(y) <= TOLERANCE and z < 0:
        return obj

    # The rotation that takes the declared axis onto -Z. Written as the six
    # axis cases rather than as a general rotation because these are the only
    # six a 'direction:' can name, and an exact quarter turn keeps coordinates
    # exact -- a general formula would put 6.123e-17 into a file that is
    # supposed to be byte-stable.
    if abs(z) > 0.5:
        # +Z: the part is cut from below, so it is turned over.
        rotation = b3d.Rotation(180, 0, 0)
    elif abs(x) > 0.5:
        rotation = b3d.Rotation(0, -90, 0) if x > 0 else b3d.Rotation(0, 90, 0)
    else:
        rotation = b3d.Rotation(90, 0, 0) if y > 0 else b3d.Rotation(-90, 0, 0)
    return rotation * obj


def _laser(request, obj, units):
    """The route a laser cutter follows: one pass, offset by half the kerf.

    A laser is not a cutter that happens to be thin. It differs from a router in
    three ways that the file has to reflect rather than approximate:

    * **It cuts through in one pass.** There is no depth stepping and no plunge,
      so `depth_per_pass` and `plunge` mean nothing here and are not read. The
      head stays at its focus height and the whole program is one Z.
    * **Its width is the kerf, not a tool diameter.** The offset that makes the
      part come out at its nominal size is half the kerf, and the kerf is a
      property of the machine and the material rather than of the job -- which
      is why it is declared in `manufacturing: laser:` and not in `cam:`. A part
      that names no kerf is cut on its outline, which is what a machine with a
      negligible one wants.
    * **The beam is gated rather than spun.** `M3 S<power>`/`M5` around each
      contour, with no spindle to start or stop.

    There is no `tool:` here, and asking for one would be wrong: the cutter
    diameter that a router cannot be run without is a thing a laser does not
    have.
    """
    tolerance = float(request.get("tolerance") or 0.01)
    feed = _require(request, "feed", "feed")
    power = request.get("power")
    kerf = float(request.get("kerf") or 0.0)
    if kerf < 0:
        raise Exception("'kerf' cannot be negative: %r" % request.get("kerf"))

    box = obj.bounding_box()
    top = box.max.Z
    height = box.max.Z - box.min.Z

    warnings = []
    if height <= TOLERANCE:
        faces = _planar_faces(obj)
    else:
        # The outline halfway down. A laser's beam is very nearly parallel, so
        # the part it produces has the one cross-section all the way through --
        # and a part whose section changes is one this machine cannot make. The
        # check that says so is 'manufacturability-laser'; here the middle is
        # simply the most representative single answer.
        faces = _faces_at(obj, top - height / 2.0)
        top_faces = _faces_at(obj, top - max(height * SECTION_INSET, TOLERANCE))
        if faces and top_faces:
            middle_area = sum(face.area for face in faces)
            top_area = sum(face.area for face in top_faces)
            largest = max(middle_area, top_area)
            if largest > 0 and abs(top_area - middle_area) / largest > PRISMATIC_TOLERANCE:
                warnings.append(
                    "the outline changes over the thickness (%.1f mm2 at the top, %.1f mm2 halfway down); "
                    "a laser cuts one section through, so this route follows the middle one" % (top_area, middle_area)
                )
    if not faces:
        raise Exception("This object has no outline to cut: its cross-section is empty")

    # The same geometry a profile uses, with the beam's half-width in place of
    # the cutter's radius: outward around the part, inward around every hole.
    wires = _profile_paths(faces, kerf / 2.0, tolerance)

    direction = str(request.get("direction") or "climb").lower()
    if direction not in ("climb", "conventional"):
        raise Exception("'direction' is 'climb' or 'conventional', not %r" % request.get("direction"))

    paths = []
    for wire, inside, group in wires:
        points = _wire_points(wire, tolerance)
        if len(points) < 3:
            continue
        clockwise = (direction == "climb") != bool(inside)
        paths.append((_oriented(points, clockwise), inside, group))
    if not paths:
        raise Exception("This object's outline produced no cutting path")

    comments = request.get("comments")
    program = Program(units, request.get("precision") or 3, True if comments is None else bool(comments))
    program.comment("PartCAD route")
    name = request.get("shape_name")
    package = request.get("package_name")
    if name:
        program.comment("object: %s" % ("%s:%s" % (package, name) if package else name))
    program.comment("machine: laser, kerf %s, through %s" % (program.number(kerf), program.number(height)))
    program.comment("units: %s" % ("millimeters" if units == "mm" else "inches"))

    program.code("G21" if units == "mm" else "G20")
    program.code("G90")
    program.code("G17")
    program.code("G94")

    for points, _inside, _group in _sorted_paths(paths):
        program.rapid_xy(points[0])
        # The beam is off while it travels and on while it cuts, which is the
        # whole of a laser's Z axis.
        program.code("M3 S%d" % int(float(power)) if power else "M3")
        first = True
        for point in points[1:]:
            if program.cut_to(point, feed if first else None):
                first = False
        program.code("M5")

    program.code("M30")

    return (
        program,
        warnings,
        {
            "machine": "laser",
            "operation": "cut",
            "paths": len(paths),
            "passes": 1,
            "depth": height,
            "cut_length": program.cut_length,
        },
    )


def _holes(obj, tolerance):
    """Every round hole through the object along Z, as (x, y, diameter, top, bottom).

    A drill makes one feature, and this is how it is recognised: a cylindrical
    face whose axis is Z. Each becomes one drilled hole at its centre.

    Read off the surface type rather than sampled the way
    'wrapper_manufacturability.wall_alignment' does, and the difference is what
    each is for: that one asks whether a wall is something a machine *could*
    make and must not be fooled by an extruded spline, while this one has to
    know a radius and a centre, which only an actual cylinder has.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_SurfaceType

    holes = {}
    for face in obj.faces():
        # Asked of the OCCT surface rather than of build123d's wrapper: the
        # radius and the axis are what this needs, and only the adaptor carries
        # them.
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cylinder = adaptor.Cylinder()
        axis = cylinder.Axis().Direction()
        if abs(abs(axis.Z()) - 1.0) > 1e-6:
            continue
        location = cylinder.Location()
        box = face.bounding_box()
        # Rounded into a key so that the two half-cylinders OCCT often splits a
        # hole into become one hole rather than two coincident ones.
        key = (
            round(location.X() / max(tolerance, 1e-6)),
            round(location.Y() / max(tolerance, 1e-6)),
            round(cylinder.Radius() / max(tolerance, 1e-6)),
        )
        existing = holes.get(key)
        if existing is None:
            holes[key] = [location.X(), location.Y(), cylinder.Radius() * 2.0, box.max.Z, box.min.Z]
        else:
            existing[3] = max(existing[3], box.max.Z)
            existing[4] = min(existing[4], box.min.Z)
    # Sorted so the file is the same on every run and the machine travels
    # predictably: by Y then X, which is how a bed is read.
    return sorted((tuple(hole) for hole in holes.values()), key=lambda hole: (hole[1], hole[0]))


def _drilling(request, obj, units):
    """The route a drilling machine follows: plunge, retract, once per hole.

    A drill does not follow a path at all, so nothing here is a contour. It goes
    to a centre, goes in, and comes out; `peck:` breaks that into steps for a
    deep hole, which is what clears the swarf.

    Written as explicit G0/G1 moves rather than as G81/G83 canned cycles, for
    the reason this file emits G1 rather than G2/G3: a canned cycle means what
    the controller says it means, and the moves mean the same thing on all of
    them.

    `tool:` is the drill in the spindle, and it is checked against the holes
    rather than used to offset anything: a 5 mm drill does not make a 6 mm hole,
    and a route that quietly produced one would be found out at the bench.
    """
    tolerance = float(request.get("tolerance") or 0.01)
    tool = _require(request, "tool", "tool")
    plunge = _require(request, "plunge", "plunge")
    safe_clearance = _require(request, "safe_z", "safe_z")
    peck = request.get("peck")
    speed = request.get("speed")

    box = obj.bounding_box()
    top = box.max.Z

    holes = _holes(obj, tolerance)
    if not holes:
        raise Exception("This object has no round hole along the drilling axis, so there is nothing to drill")

    warnings = []
    mismatched = [hole for hole in holes if abs(hole[2] - tool) > tolerance]
    if mismatched:
        warnings.append(
            "%d of the %d holes are not the diameter of the drill (%.3f mm): %s. "
            "They are drilled at the centre anyway, at the size the drill actually is"
            % (
                len(mismatched),
                len(holes),
                tool,
                ", ".join(sorted({"%.3f mm" % hole[2] for hole in mismatched})),
            )
        )

    comments = request.get("comments")
    program = Program(units, request.get("precision") or 3, True if comments is None else bool(comments))
    program.comment("PartCAD route")
    name = request.get("shape_name")
    package = request.get("package_name")
    if name:
        program.comment("object: %s" % ("%s:%s" % (package, name) if package else name))
    program.comment("machine: drilling, %d holes, drill %s" % (len(holes), program.number(tool)))
    program.comment("units: %s" % ("millimeters" if units == "mm" else "inches"))

    program.code("G21" if units == "mm" else "G20")
    program.code("G90")
    program.code("G17")
    program.code("G94")
    if speed:
        program.code("M3 S%d" % int(float(speed)))

    safe_height = top + safe_clearance
    program.rapid_z(safe_height)

    deepest = 0.0
    for x, y, diameter, hole_top, hole_bottom in holes:
        program.rapid_xy((x, y))
        program.rapid_z(hole_top)
        depth = hole_top - hole_bottom
        deepest = max(deepest, depth)
        steps = [hole_bottom]
        if peck:
            step = float(peck)
            if step > 0:
                count = max(1, int(math.ceil(depth / step - 1e-9)))
                steps = [hole_top - min(depth, step * (index + 1)) for index in range(count)]
        for z in steps:
            program.plunge(z, plunge)
            if len(steps) > 1:
                # Out to the top of the hole between pecks, which is what
                # carries the swarf out with it.
                program.rapid_z(hole_top)
        program.rapid_z(safe_height)

    if speed:
        program.code("M5")
    program.code("M30")

    return (
        program,
        warnings,
        {
            "machine": "drilling",
            "operation": "drill",
            "holes": len(holes),
            "passes": 1,
            "depth": deepest,
            "cut_length": program.cut_length,
        },
    )


# Which emitter writes the program, by the machine the part says it is made on.
# A part that says nothing is a CNC part: that is what every object routed
# before machines existed meant, and it is the machine that can make anything
# the other two can.
MACHINES = {
    "cnc": _cnc,
    "laser": _laser,
    "drilling": _drilling,
}


def process(path, request):
    try:
        units = str(request.get("units") or "mm").lower()
        if units not in ("mm", "in"):
            raise Exception("'units' is 'mm' or 'in', not %r" % request.get("units"))

        machine = str(request.get("machine") or "cnc").lower()
        if machine not in MACHINES:
            raise Exception("'machine' is one of %s, not %r" % (", ".join(sorted(MACHINES)), request.get("machine")))

        obj = _shape(request["wrapped"])
        # Into the machine's frame, where the tool axis is Z, before anything
        # measures the object. The default is the identity (see '_orient').
        obj = _orient(obj, request.get("tool_axis_vector"))

        program, warnings, stats = MACHINES[machine](request, obj, units)

        with open(path, "w", newline="\n") as f:
            f.write(program.text())

        return {"success": True, "exception": None, "warnings": warnings, "stats": stats}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
