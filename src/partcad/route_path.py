#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The centreline of a routed part (issue #975), in pure Python.

A route is an ordered list of *stops*: frames ('EndFrame', from a connected
port or a free end's 'location:') and 'via' points. The first and the last stop
are the route's two ends; frames between them are its 'through' entries, ports
the cable passes through (a grommet, a clip). The path is a cubic Hermite spline through knots made of them: each
end's origin, and its lead point (origin + lead * Z) when it gives a lead, and
each 'via' point.

* The tangent at an end is its Z axis. At the last end it is reversed, so the
  path arrives along it. At a 'through' entry it is whichever sign of Z points
  on along the route.
* The tangent at a 'via' point is the Catmull-Rom one: the direction from the
  knot before it to the knot after it.
* Each segment scales both of its tangents to its own chord length, which keeps
  it from looping. A segment whose two tangents lie along its chord is straight:
  that is what a lead is.

What comes out is a dense sample with frames carried along it (rotation-
minimizing from the first end's X axis, then rolled to meet the X axis of every
'through' entry and of the second end, the roll spread evenly along each
stretch), the arc length, the tightest bend, and
the closest approach of the path to itself: everything the feasibility checks
('check_route') and 'pc qual test' measure. Nothing here needs OCCT, so it is
the same on a cache hit and testable in the core. The geometry is built from it
in the sandbox.
"""

import json
import math
from typing import List, Optional, Sequence, Tuple, Union

Vector = Tuple[float, float, float]

# Two knots closer than this, in millimetres, are one point: no direction is
# defined between them.
KNOT_TOLERANCE = 1e-3
# What the canonical form of a route rounds its coordinates to, in millimetres.
CANONICAL_DIGITS = 6
# The default distance between samples, in millimetres.
DEFAULT_STEP = 0.5
# The fewest samples a segment is cut into, however short it is.
MIN_SEGMENT_SAMPLES = 8


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n == 0.0:
        raise ValueError("route_path: a direction of zero length")
    return (a[0] / n, a[1] / n, a[2] / n)


def _dist(a, b):
    return _norm(_sub(a, b))


def _vec(value) -> Vector:
    return (float(value[0]), float(value[1]), float(value[2]))


class EndFrame:
    """An end of a route: where the end face is ('origin'), the axis the route
    leaves along ('z', which points into the part at a connected end), the X
    axis its profile is turned by ('x'), and the straight 'lead' in millimetres
    the path runs along 'z' before it bends. 'z' and 'x' are normalized, and 'x'
    is made perpendicular to 'z'."""

    def __init__(self, origin, z, x=None, lead: float = 0.0):
        self.origin = _vec(origin)
        self.z = _unit(_vec(z))
        if x is None:
            # Any perpendicular will do when the profile is round.
            helper = (1.0, 0.0, 0.0) if abs(self.z[0]) < 0.9 else (0.0, 1.0, 0.0)
            x = _cross(helper, self.z)
        x = _vec(x)
        self.x = _unit(_sub(x, _mul(self.z, _dot(x, self.z))))
        self.lead = float(lead or 0.0)
        if self.lead < 0:
            raise ValueError("route_path: a lead cannot be negative (%g)" % self.lead)

    @classmethod
    def from_location(cls, location, lead: float = 0.0) -> "EndFrame":
        """The end frame of a 'geom.Location' (a port's, or a free end's)."""
        rotation = _rotation_matrix(location._q)
        return cls(
            location.translation,
            (rotation[0][2], rotation[1][2], rotation[2][2]),
            (rotation[0][0], rotation[1][0], rotation[2][0]),
            lead,
        )

    def as_dict(self) -> dict:
        return {"origin": list(self.origin), "z": list(self.z), "x": list(self.x), "lead": self.lead}


def _rotation_matrix(q):
    w, x, y, z = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


Stop = Union[EndFrame, Sequence[float]]


class Knot:
    """A point the path passes through, with the direction it passes in (None
    for a 'via' point, whose direction is worked out from its neighbours), and
    what it came from: ('end', 0 or 1), ('through', index), or ('via', the
    source of the entry it leads to, index among that entry's points); an end's
    or a 'through' entry's lead point adds 'lead'."""

    def __init__(self, point: Vector, direction: Optional[Vector], source: tuple):
        self.point = point
        self.direction = direction
        self.source = source


def describe_source(source: tuple) -> str:
    """A knot's source in the words of the YAML: 'end 2', 'through 1', 'via
    point 2 of end 2', 'end 1's lead point'."""
    kind = source[0]
    if kind == "via":
        return "via point %d of %s" % (source[2] + 1, describe_source(source[1]))
    what = "%s %d" % (kind, source[1] + 1)
    return what + "'s lead point" if len(source) > 2 and source[2] == "lead" else what


def _entry_sources(stops) -> list:
    """The source of each frame among 'stops': ('end', 0), ('through', k) ...,
    ('end', 1)."""
    frames = [i for i, stop in enumerate(stops) if isinstance(stop, EndFrame)]
    sources = {}
    for k, i in enumerate(frames):
        if k == 0:
            sources[i] = ("end", 0)
        elif k == len(frames) - 1:
            sources[i] = ("end", 1)
        else:
            sources[i] = ("through", k - 1)
    return sources


def build_knots(stops: Sequence[Stop]) -> List[Knot]:
    """The knots of a route through 'stops', in order. Raises ValueError unless
    the first and the last stop are frames: the route's two ends."""
    stops = [stop if isinstance(stop, EndFrame) else _vec(stop) for stop in stops]
    if len(_ends_of(stops)) < 2:
        raise ValueError("route_path: a route needs two ends, it has %d" % len(_ends_of(stops)))
    if not isinstance(stops[0], EndFrame) or not isinstance(stops[-1], EndFrame):
        raise ValueError("route_path: a route starts and finishes at an end, not at a 'via' point")

    sources = _entry_sources(stops)
    # The bare points, to decide the direction of travel at 'through' entries.
    points = [stop.origin if isinstance(stop, EndFrame) else stop for stop in stops]
    knots: List[Knot] = []
    last = len(stops) - 1
    pending_via = []
    for i, stop in enumerate(stops):
        if not isinstance(stop, EndFrame):
            pending_via.append((i, stop))
            continue
        source = sources[i]
        # The 'via' points just passed belong to this entry: the one they lead to.
        for n, (_, point) in enumerate(pending_via):
            knots.append(Knot(point, None, ("via", source, n)))
        pending_via = []
        lead = _mul(stop.z, stop.lead)
        if i == 0:
            knots.append(Knot(stop.origin, stop.z, source))
            if stop.lead > 0:
                knots.append(Knot(_add(stop.origin, lead), stop.z, source + ("lead",)))
        elif i == last:
            arrive = _mul(stop.z, -1.0)
            if stop.lead > 0:
                knots.append(Knot(_add(stop.origin, lead), arrive, source + ("lead",)))
            knots.append(Knot(stop.origin, arrive, source))
        else:
            onwards = _sub(points[i + 1], points[i - 1])
            direction = stop.z if _dot(stop.z, onwards) >= 0 else _mul(stop.z, -1.0)
            if stop.lead > 0:
                knots.append(Knot(_sub(stop.origin, _mul(direction, stop.lead)), direction, source + ("lead",)))
            knots.append(Knot(stop.origin, direction, source))
            if stop.lead > 0:
                knots.append(Knot(_add(stop.origin, _mul(direction, stop.lead)), direction, source + ("lead",)))
    return knots


def _knot_tangents(knots: List[Knot]) -> List[Vector]:
    tangents = []
    for k, knot in enumerate(knots):
        if knot.direction is not None:
            tangents.append(knot.direction)
            continue
        across = _sub(knots[k + 1].point, knots[k - 1].point)
        if _norm(across) < KNOT_TOLERANCE:
            # A 'via' point the path turns straight back at: no Catmull-Rom
            # direction, so take the one to the next knot.
            across = _sub(knots[k + 1].point, knot.point)
        tangents.append(_unit(across))
    return tangents


# The most a tangent is lengthened beyond its segment's chord: beyond this a
# segment that has to turn far would bulge out rather than turn.
MAX_TANGENT_SCALE = 2.0


def _tangent_magnitude(p0, p1, t0, t1) -> float:
    """The length both tangents of a segment are given: its chord, lengthened as
    a circular arc needs. An arc that leaves its chord at the angle 'a' is drawn
    by a cubic whose tangents are 1 / cos^2(a / 2) times the chord, so a route
    through points on a circle bends at that circle's radius, and a segment whose
    tangents lie along its chord (a lead) stays straight."""
    chord = _sub(p1, p0)
    length = _norm(chord)
    direction = _mul(chord, 1.0 / length)
    angle = (
        math.acos(max(-1.0, min(1.0, _dot(t0, direction)))) + math.acos(max(-1.0, min(1.0, _dot(t1, direction))))
    ) / 2
    return length * min(MAX_TANGENT_SCALE, 1.0 / math.cos(angle / 2) ** 2)


class _Segment:
    """One cubic Hermite segment, p(t) for t in [0, 1]."""

    def __init__(self, p0, p1, m0, m1):
        self.p0, self.p1, self.m0, self.m1 = p0, p1, m0, m1

    def _combine(self, a, b, c, d):
        p0, p1, m0, m1 = self.p0, self.p1, self.m0, self.m1
        return (
            a * p0[0] + b * m0[0] + c * p1[0] + d * m1[0],
            a * p0[1] + b * m0[1] + c * p1[1] + d * m1[1],
            a * p0[2] + b * m0[2] + c * p1[2] + d * m1[2],
        )

    def point(self, t):
        t2, t3 = t * t, t * t * t
        return self._combine(2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2)

    def d1(self, t):
        t2 = t * t
        return self._combine(6 * t2 - 6 * t, 3 * t2 - 4 * t + 1, -6 * t2 + 6 * t, 3 * t2 - 2 * t)

    def d2(self, t):
        return self._combine(12 * t - 6, 6 * t - 4, -12 * t + 6, 6 * t - 2)

    def speed(self, t):
        return _norm(self.d1(t))

    def curvature(self, t):
        d1 = self.d1(t)
        speed = _norm(d1)
        if speed == 0.0:
            return math.inf
        return _norm(_cross(d1, self.d2(t))) / speed**3


class RoutePath:
    """The sampled centreline of a route.

    'points', 'tangents' (unit) and 'frames' (an (x, y, z) triple of unit axes
    per sample, z the tangent) are parallel lists. 'arc' is the arc length from
    the first end to each sample, 'length' the whole of it. 'knot_samples' is the
    sample index of each knot. 'min_radius' is the tightest radius of curvature,
    at the sample 'min_radius_index'.
    """

    def __init__(self, stops: Sequence[Stop], step: float = DEFAULT_STEP):
        if step <= 0:
            raise ValueError("route_path: the sample step must be positive")
        self.knots = build_knots(stops)
        for a, b in zip(self.knots, self.knots[1:]):
            if _dist(a.point, b.point) < KNOT_TOLERANCE:
                raise ValueError(
                    "route_path: %s and %s are at the same point"
                    % (describe_source(a.source), describe_source(b.source))
                )
        tangents = _knot_tangents(self.knots)
        self.segments = []
        for k in range(len(self.knots) - 1):
            p0, p1 = self.knots[k].point, self.knots[k + 1].point
            magnitude = _tangent_magnitude(p0, p1, tangents[k], tangents[k + 1])
            self.segments.append(_Segment(p0, p1, _mul(tangents[k], magnitude), _mul(tangents[k + 1], magnitude)))

        self.points: List[Vector] = []
        self.tangents: List[Vector] = []
        self.arc: List[float] = []
        self.knot_samples: List[int] = []
        curvatures: List[float] = []
        travelled = 0.0
        for s, segment in enumerate(self.segments):
            chord = _dist(segment.p0, segment.p1)
            n = max(MIN_SEGMENT_SAMPLES, int(math.ceil(chord / step)))
            ts = [k / n for k in range(n + 1)]
            if s == 0:
                self.knot_samples.append(0)
            previous_t = 0.0
            previous_speed = segment.speed(0.0)
            for k, t in enumerate(ts):
                kappa = segment.curvature(t)
                if k == 0:
                    if s == 0:
                        self.points.append(segment.p0)
                        self.tangents.append(_unit(segment.d1(0.0)))
                        self.arc.append(0.0)
                        curvatures.append(kappa)
                    else:
                        # The knot two segments share: the tighter of the bends
                        # either side of it.
                        curvatures[-1] = max(curvatures[-1], kappa)
                    continue
                # Simpson's rule over each sample interval: the samples are
                # dense enough that its error is far below the rounding.
                middle = (previous_t + t) / 2
                speed = segment.speed(t)
                travelled += (t - previous_t) / 6.0 * (previous_speed + 4 * segment.speed(middle) + speed)
                previous_speed = speed
                previous_t = t
                self.points.append(segment.p1 if k == n else segment.point(t))
                self.tangents.append(_unit(segment.d1(t)))
                self.arc.append(travelled)
                curvatures.append(kappa)
            self.knot_samples.append(len(self.points) - 1)
        self.length = travelled
        self.curvatures = curvatures
        peak = max(range(len(curvatures)), key=lambda i: curvatures[i])
        self.min_radius_index = peak
        self.min_radius = math.inf if curvatures[peak] <= 1e-12 else 1.0 / curvatures[peak]
        self.frames = self._roll(self._transport(_ends_of(stops)[0].x), _ends_of(stops))

    @property
    def min_radius_point(self) -> Vector:
        return self.points[self.min_radius_index]

    def _transport(self, x0) -> List[Tuple[Vector, Vector, Vector]]:
        """Rotation-minimizing frames by double reflection (Wang et al., 2008)."""
        frames = []
        t = self.tangents[0]
        r = _unit(_sub(x0, _mul(t, _dot(x0, t))))
        frames.append((r, _cross(t, r), t))
        for i in range(len(self.points) - 1):
            v1 = _sub(self.points[i + 1], self.points[i])
            c1 = _dot(v1, v1)
            t_next = self.tangents[i + 1]
            if c1 > 0.0:
                r_l = _sub(r, _mul(v1, 2.0 / c1 * _dot(v1, r)))
                t_l = _sub(t, _mul(v1, 2.0 / c1 * _dot(v1, t)))
                v2 = _sub(t_next, t_l)
                c2 = _dot(v2, v2)
                r = _sub(r_l, _mul(v2, 2.0 / c2 * _dot(v2, r_l))) if c2 > 0.0 else r_l
            t = t_next
            r = _unit(_sub(r, _mul(t, _dot(r, t))))
            frames.append((r, _cross(t, r), t))
        return frames

    def _roll(self, frames, entries):
        """The carried frames, rolled about the path so that the profile's X meets
        the X axis of each 'through' entry and of the second end.

        Carrying a frame along is a rotation-minimizing transport, and rolling the
        starting frame about the tangent rolls every carried frame by the same
        angle, so the roll each entry asks for can be worked out from the frames
        as carried and spread evenly by arc length over the stretch before it.
        Each step is the smallest one, within half a turn either way.
        """
        anchors = [self.knot_samples[k] for k, knot in enumerate(self.knots) if _is_frame(knot.source)]
        wanted = [0.0]
        for sample, entry in zip(anchors[1:], entries[1:]):
            x, y, t = frames[sample]
            target = _sub(entry.x, _mul(t, _dot(entry.x, t)))
            angle = math.atan2(_dot(target, y), _dot(target, x))
            # Unwrapped against the roll already reached, so a stretch turns the
            # short way round.
            previous = wanted[-1]
            angle += 2 * math.pi * round((previous - angle) / (2 * math.pi))
            wanted.append(angle)
        self.rolls = wanted
        rolled = list(frames)
        for (a, b), (ra, rb) in zip(zip(anchors, anchors[1:]), zip(wanted, wanted[1:])):
            span = self.arc[b] - self.arc[a]
            for i in range(a + 1, b + 1):
                share = 1.0 if span <= 0 else (self.arc[i] - self.arc[a]) / span
                rolled[i] = _rolled(frames[i], ra + (rb - ra) * share)
        return rolled

    def closest_approach(self, within: float):
        """Where the path comes closest to another stretch of itself, as
        (distance, sample i, sample j), or (inf, None, None) when it never comes
        within 'within' millimetres.

        A pair counts when, seen from sample i, sample j is the nearest of the
        samples around it: a straight stretch moves steadily away from every
        point on it, and so never counts, while the other leg of a hairpin, or a
        stretch the path crosses, has a nearest point. Only pairs closer than
        'within' are looked at, through a grid of that cell size, and only pairs
        further apart along the path than 'within': nearer than that, it is one
        stretch bending, which is what the bend check is for.
        """
        if within <= 0:
            return math.inf, None, None
        points = self.points
        arc = self.arc
        n = len(points)
        cells = {}
        for i, p in enumerate(points):
            cells.setdefault(
                (int(math.floor(p[0] / within)), int(math.floor(p[1] / within)), int(math.floor(p[2] / within))), []
            ).append(i)
        best = (math.inf, None, None)
        within2 = within * within
        for (cx, cy, cz), members in cells.items():
            near = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        near.extend(cells.get((cx + dx, cy + dy, cz + dz), ()))
            for i in members:
                pi = points[i]
                for j in near:
                    # Nearer along the path than 'within' is the same stretch
                    # bending, which the bend check is about.
                    if j <= i + 1 or arc[j] - arc[i] <= within:
                        continue
                    pj = points[j]
                    d2 = (pi[0] - pj[0]) ** 2 + (pi[1] - pj[1]) ** 2 + (pi[2] - pj[2]) ** 2
                    if d2 >= within2 or d2 >= best[0] ** 2:
                        continue
                    before = points[j - 1]
                    if (pi[0] - before[0]) ** 2 + (pi[1] - before[1]) ** 2 + (pi[2] - before[2]) ** 2 <= d2:
                        continue
                    if j + 1 < n:
                        after = points[j + 1]
                        if (pi[0] - after[0]) ** 2 + (pi[1] - after[1]) ** 2 + (pi[2] - after[2]) ** 2 < d2:
                            continue
                    best = (math.sqrt(d2), i, j)
        return best


def _rolled(frame, angle):
    """'frame' rolled by 'angle' about its own z."""
    if angle == 0.0:
        return frame
    x, y, z = frame
    c, s = math.cos(angle), math.sin(angle)
    x2 = _add(_mul(x, c), _mul(y, s))
    return (x2, _cross(z, x2), z)


def _is_frame(source) -> bool:
    """Whether a knot is an end's or a 'through' entry's origin."""
    return source[0] != "via" and len(source) == 2


def _ends_of(stops):
    return [stop for stop in stops if isinstance(stop, EndFrame)]


# -- The canonical form ---------------------------------------------------------


def _round(value: float) -> float:
    rounded = round(float(value), CANONICAL_DIGITS)
    return 0.0 if rounded == 0 else rounded  # no '-0.0'


def _round_vec(value) -> List[float]:
    return [_round(v) for v in value]


def canonical_stops(stops: Sequence[Stop]) -> List[Stop]:
    """'stops' with every coordinate rounded to 1e-6 mm, the form a route is
    built from: two routes that round the same are the same route, sample for
    sample, rather than merely close."""
    result = []
    for stop in stops:
        if isinstance(stop, EndFrame):
            result.append(EndFrame(_round_vec(stop.origin), _round_vec(stop.z), _round_vec(stop.x), _round(stop.lead)))
        else:
            result.append(tuple(_round_vec(stop)))
    return result


def canonical_json(stops: Sequence[Stop], step: float = DEFAULT_STEP) -> str:
    """The route as the JSON a routed part is given (D5), every number rounded to
    1e-6 mm and every key sorted, so that equal routes are byte-identical and an
    unchanged route keeps its cache key.

    'ends' and 'through' mirror the YAML (D12, D14): each entry's frame and
    lead, and the 'via' points passed on the way to it. 'path' is the sampled centreline: 'points',
    the tangent 'z' and the profile's 'x' axis at each, the sample index of each
    knot in 'knots', and the 'length'.
    """
    stops = canonical_stops(stops)
    path = RoutePath(stops, step)
    entries = []
    via = []
    for stop in stops:
        if isinstance(stop, EndFrame):
            entry = stop.as_dict()
            entry["via"] = via
            entries.append(entry)
            via = []
        else:
            via.append(list(stop))
    del entries[0]["via"]  # nothing comes before the first end
    document = {
        "ends": [entries[0], entries[-1]],
        "through": entries[1:-1],
        "path": {
            "points": [_round_vec(p) for p in path.points],
            "z": [_round_vec(frame[2]) for frame in path.frames],
            "x": [_round_vec(frame[0]) for frame in path.frames],
            "knots": path.knot_samples,
            "length": _round(path.length),
        },
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


# -- Feasibility (D9, before any sweep) -----------------------------------------


class Refusal:
    """Why a route cannot be built: a 'reason' code, the 'point' on the path it
    is about (in the frame the stops are given in), the 'values' measured, and a
    'remedy' - what to change."""

    def __init__(self, reason: str, point, values: dict, remedy: str, message: str):
        self.reason = reason
        self.point = None if point is None else tuple(point)
        self.values = values
        self.remedy = remedy
        self._message = message

    @property
    def message(self) -> str:
        at = "" if self.point is None else " at (%.3f, %.3f, %.3f)" % self.point
        text = self._message + at
        return text + ": " + self.remedy if self.remedy else text

    def __repr__(self):
        return "Refusal(%r, %s)" % (self.reason, self.message)


def check_route(stops: Sequence[Stop], outer_radius: float, step: float = DEFAULT_STEP):
    """The D9 checks of a route whose profile reaches 'outer_radius' from its
    centre, before anything is swept: (path, refusals). The path is None when
    the knots alone already make it impossible."""
    stops = [stop if isinstance(stop, EndFrame) else _vec(stop) for stop in stops]
    refusals: List[Refusal] = []

    sources = _entry_sources(stops)
    ends = [(i, stop) for i, stop in enumerate(stops) if isinstance(stop, EndFrame)]
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            if _dist(ends[a][1].origin, ends[b][1].origin) < KNOT_TOLERANCE:
                refusals.append(
                    Refusal(
                        "ends-coincide",
                        ends[a][1].origin,
                        {"distance": _dist(ends[a][1].origin, ends[b][1].origin)},
                        "move one of them, or place the part another way",
                        "%s and %s are at the same point"
                        % (describe_source(sources[ends[a][0]]), describe_source(sources[ends[b][0]])),
                    )
                )

    knots = build_knots(stops)
    for k in range(len(knots) - 1):
        a, b = knots[k], knots[k + 1]
        distance = _dist(a.point, b.point)
        # Two frames at one point are reported once, above.
        if distance < KNOT_TOLERANCE and not (_is_frame(a.source) and _is_frame(b.source)):
            refusals.append(
                Refusal(
                    "knots-coincide",
                    a.point,
                    {"distance": distance},
                    "remove or move %s" % describe_source(b.source if b.source[0] == "via" else a.source),
                    "%s and %s are at the same point" % (describe_source(a.source), describe_source(b.source)),
                )
            )
    if refusals:
        return None, refusals

    path = RoutePath(stops, step)
    if path.min_radius < outer_radius:
        refusals.append(
            Refusal(
                "bend-tighter-than-profile",
                path.min_radius_point,
                {"radius": path.min_radius, "profileRadius": outer_radius},
                _bend_remedy(path),
                "the path bends at a radius of %.3f mm, tighter than the profile's radius of %.3f mm"
                % (path.min_radius, outer_radius),
            )
        )
    diameter = 2.0 * outer_radius
    distance, i, j = path.closest_approach(diameter)
    if distance < diameter:
        refusals.append(
            Refusal(
                "path-crosses-itself",
                path.points[i],
                {"distance": distance, "profileDiameter": diameter, "otherPoint": list(path.points[j])},
                "move the 'via' points so that the path keeps clear of itself",
                "the path comes within %.3f mm of itself, less than the profile's diameter of %.3f mm"
                % (distance, diameter),
            )
        )
    return path, refusals


def _bend_remedy(path: RoutePath) -> str:
    """What to change for the tightest bend: the 'via' point at either end of
    the segment it is in, or else the room the path has near the end there.
    A 'lead' is not suggested: it moves where the bend starts, not how tight it
    is."""
    index = path.min_radius_index
    segment = next(s for s in range(len(path.segments)) if path.knot_samples[s + 1] >= index)
    pair = (path.knots[segment], path.knots[segment + 1])
    vias = [knot for knot in pair if knot.source[0] == "via"]
    nearest = min(vias or pair, key=lambda knot: _dist(knot.point, path.points[index]))
    if vias:
        return "move %s further from its neighbours" % describe_source(nearest.source)
    end = nearest.source
    return "give the path room to turn near %s: add or move a 'via' point, or move the parts" % describe_source(end[:2])
