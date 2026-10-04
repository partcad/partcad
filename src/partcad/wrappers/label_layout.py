#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the names "pc render --with-ports"/"--with-interfaces" draw go.

A port's name used to be written where the port is, and that is the one place a
name cannot be read: on top of the object, and - since ports crowd together on a
projection far more than they do in space - on top of each other too. So the
names are laid out the way a drawing lays out its callouts instead: around the
object, out of its way, each joined to what it names by a leader line.

* Every name goes on a ring just outside the object, and the names are spread
  over that ring at equal distances from one another, in the order the things
  they name go around the object - so that two leaders do not cross on the way
  out, and each name sits on the side of the object its port is on.
* A name that would still land on another name, or on another name's leader, or
  have its own leader cross another name, is moved further out along the
  direction it left the object in, as far as it takes. A leader is as long as it
  has to be, and no longer.

Everything here is in the plane of the picture: 'u' runs to the right and 'v'
runs up, in the units of the object, and the caller turns the answer back into
3D. A name is a box measured from its bottom left corner, which is where
'stroke_text' starts writing.

This module is pure Python and imports nothing. It runs inside the render
sandbox, beside 'stroke_text.py', and is unit-tested directly.
"""

import math

# How far out from the object the ring of names is, and how far apart two names
# are kept, in text heights.
GAP = 1.0
PADDING = 0.4


class Label:
    """One name to be placed.

    'targets' are the points the name is the name of - a leader is drawn out to
    each of them. 'anchor' is the point whose direction from the object decides
    which side of the object the name goes on; it defaults to the middle of the
    targets.
    """

    def __init__(self, width, height, targets, anchor=None):
        self.width = float(width)
        self.height = float(height)
        self.targets = [tuple(target) for target in targets]
        if anchor is None:
            anchor = (
                sum(target[0] for target in self.targets) / len(self.targets),
                sum(target[1] for target in self.targets) / len(self.targets),
            )
        self.anchor = tuple(anchor)
        # Filled in by 'layout()': the bottom left corner of the text, and the
        # point on the edge of its box the leaders start from.
        self.position = None
        self.attach = None
        self.spot = None

    def box(self, padding=0.0):
        u, v = self.position
        return (u - padding, v - padding, u + self.width + padding, v + self.height + padding)


def _bounds(points):
    us = [point[0] for point in points]
    vs = [point[1] for point in points]
    return (min(us), min(vs), max(us), max(vs))


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _segment_hits_box(start, end, box):
    """Whether the segment from 'start' to 'end' passes through 'box'.

    Liang-Barsky clipping: the segment is cut down to the part of it on the
    inside of each of the four sides in turn, and it hits the box if anything is
    left.
    """
    (u0, v0), (u1, v1) = start, end
    du, dv = u1 - u0, v1 - v0
    low, high = 0.0, 1.0
    for p, q in ((-du, u0 - box[0]), (du, box[2] - u0), (-dv, v0 - box[1]), (dv, box[3] - v0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return False
    return True


class _Ring:
    """The rectangle the names are laid out around, walked as one closed path.

    A distance along it starts at the middle of the right side and runs
    anticlockwise, the way an angle does. It is measured in how many names fit
    rather than in length: a name is written across the page, so a side of the
    object holds a column of names a line apart while its top holds a row of
    them a whole name apart. 'across' is how much longer a stretch of the top or
    bottom has to be than a stretch of a side to hold as many - which is what
    makes equal steps along the path come out as names spread evenly around the
    object, rather than crowded along its top and bottom.
    """

    def __init__(self, box, across=1.0):
        self.centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        self.half_width = w = (box[2] - box[0]) / 2.0
        self.half_height = h = (box[3] - box[1]) / 2.0
        cu, cv = self.centre
        # The path in five legs, each a side (or the half of one the path
        # starts and ends in): where it starts, which way it goes, how long it
        # is, which way is out from the object there, and how much each unit of
        # its length counts for.
        self.legs = [
            ((cu + w, cv), (0.0, 1.0), h, (1.0, 0.0), 1.0),
            ((cu + w, cv + h), (-1.0, 0.0), 2 * w, (0.0, 1.0), 1.0 / across),
            ((cu - w, cv + h), (0.0, -1.0), 2 * h, (-1.0, 0.0), 1.0),
            ((cu - w, cv - h), (1.0, 0.0), 2 * w, (0.0, -1.0), 1.0 / across),
            ((cu + w, cv - h), (0.0, 1.0), h, (1.0, 0.0), 1.0),
        ]
        self.length = sum(length * weight for _start, _direction, length, _outward, weight in self.legs)

    def at(self, distance):
        """The point at 'distance' along the path, and which way is out there."""
        distance %= self.length
        for start, direction, length, outward, weight in self.legs:
            if distance <= length * weight or (start, direction) == self.legs[-1][:2]:
                along = min(distance / weight, length)
                return (start[0] + direction[0] * along, start[1] + direction[1] * along), outward
            distance -= length * weight

    def distance_to(self, point):
        """How far along the path a ray from the centre through 'point' meets it."""
        du, dv = point[0] - self.centre[0], point[1] - self.centre[1]
        if abs(du) < 1e-12 and abs(dv) < 1e-12:
            return 0.0
        w, h = self.half_width, self.half_height
        # Scale the ray until it reaches the rectangle, and see which side that
        # is on and how far along that side.
        scale = min(w / abs(du) if du else math.inf, h / abs(dv) if dv else math.inf)
        u, v = du * scale, dv * scale
        if du > 0 and w - u <= 1e-9 * max(w, 1.0):
            leg, along = (0, v) if v >= 0 else (4, h + v)
        elif dv > 0 and h - v <= 1e-9 * max(h, 1.0):
            leg, along = 1, w - u
        elif du < 0 and u + w <= 1e-9 * max(w, 1.0):
            leg, along = 2, h - v
        else:
            leg, along = 3, u + w
        before = sum(length * weight for _start, _direction, length, _outward, weight in self.legs[:leg])
        return before + along * self.legs[leg][4]


def _place(label, point, outward, offset):
    """Put 'label' 'offset' further out than 'point', its near edge facing in."""
    label.spot = (point, outward, offset)
    u = point[0] + outward[0] * offset
    v = point[1] + outward[1] * offset
    if outward[0] > 0:
        label.position = (u, v - label.height / 2.0)
        label.attach = (u, v)
    elif outward[0] < 0:
        label.position = (u - label.width, v - label.height / 2.0)
        label.attach = (u, v)
    elif outward[1] > 0:
        label.position = (u - label.width / 2.0, v)
        label.attach = (u, v)
    else:
        label.position = (u - label.width / 2.0, v - label.height)
        label.attach = (u, v + label.height)
    # The leader stops just short of the text rather than running into it.
    gap = label.height * PADDING
    label.attach = (label.attach[0] - outward[0] * gap, label.attach[1] - outward[1] * gap)


def _clear(label, placed, keep_out):
    """Whether 'label', where it is now, keeps clear of the object and of every
    label in 'placed'."""
    padding = label.height * PADDING
    box = label.box(padding)
    if _overlap(box, keep_out):
        return False
    for other in placed:
        if _overlap(box, other.box(padding)):
            return False
        # A leader is allowed to touch the name it leads to, and no other.
        inner = other.box(0.0)
        if any(_segment_hits_box(label.attach, target, inner) for target in label.targets):
            return False
        inner = label.box(0.0)
        if any(_segment_hits_box(other.attach, target, inner) for target in other.targets):
            return False
    return True


def _segments_cross(a, b, c, d):
    """Whether the segment from 'a' to 'b' crosses the one from 'c' to 'd'.

    Strictly: two leaders that share an end - the same port, named twice - do
    not count as crossing.
    """

    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _crossings(label, others):
    """How many times the leaders of 'label' cross the leaders of 'others'."""
    return sum(
        _segments_cross(label.attach, target, other.attach, other_target)
        for other in others
        if other is not label
        for target in label.targets
        for other_target in other.targets
    )


def _involving(first, second, labels):
    """How many crossings either of two labels' leaders is part of."""
    return _crossings(first, labels) + _crossings(second, labels) - _crossings(first, [second])


def _uncross(labels, keep_out):
    """Swap the spots of two names wherever that takes crossings away.

    The order the names go around the ring keeps most leaders apart, but not
    all: an interface leads to several ports, and a name's spot may have been
    moved to make room. So every pair whose leaders cross is tried the other
    way round, and kept that way if neither name then lands on anything and
    fewer leaders cross. Each swap removes at least one crossing, so this ends.
    """
    improved = True
    while improved:
        improved = False
        for first_index, first in enumerate(labels):
            for second in labels[first_index + 1 :]:
                if not _crossings(first, [second]):
                    continue
                before = _involving(first, second, labels)
                spots = (first.spot, second.spot)
                _place(first, *spots[1])
                _place(second, *spots[0])
                rest = [label for label in labels if label is not first and label is not second]
                if (
                    _clear(first, rest, keep_out)
                    and _clear(second, rest + [first], keep_out)
                    and _involving(first, second, labels) < before
                ):
                    improved = True
                else:
                    _place(first, *spots[0])
                    _place(second, *spots[1])


def _leader_length(label):
    return sum(math.hypot(target[0] - label.attach[0], target[1] - label.attach[1]) for target in label.targets)


def layout(labels, keep_out):
    """Place every one of 'labels' around the box 'keep_out', in place.

    'keep_out' is (u_min, v_min, u_max, v_max): the object, which no name may be
    written over. The targets of the labels are added to it, so that a port that
    sits off the object - a mounting point out in space - is kept clear too.
    Returns 'labels', each with its 'position' and 'attach' filled in.
    """
    if not labels:
        return labels
    points = [(keep_out[0], keep_out[1]), (keep_out[2], keep_out[3])]
    points.extend(target for label in labels for target in label.targets)
    box = _bounds(points)
    height = max(label.height for label in labels)
    row = height * (1 + 2 * PADDING)
    gap = height * GAP
    keep_out = (box[0] - gap / 2.0, box[1] - gap / 2.0, box[2] + gap / 2.0, box[3] + gap / 2.0)
    across = (sum(label.width for label in labels) / len(labels) + gap) / row
    ring = _Ring((box[0] - gap, box[1] - gap, box[2] + gap, box[3] + gap), across)

    # Equal steps along the ring, in the order the anchors go around it, turned
    # as a whole to sit as close as it can to where each anchor would put its
    # own name: the circular mean of how far each name is from its own spot.
    order = sorted(labels, key=lambda label: ring.distance_to(label.anchor))
    step = ring.length / len(order)
    sin_sum = cos_sum = 0.0
    for index, label in enumerate(order):
        angle = 2 * math.pi * (ring.distance_to(label.anchor) - index * step) / ring.length
        sin_sum += math.sin(angle)
        cos_sum += math.cos(angle)
    turn = math.atan2(sin_sum, cos_sum) * ring.length / (2 * math.pi) if (sin_sum or cos_sum) else 0.0

    # Each name goes in its own slot if it can. If it cannot - it would land on
    # a name already placed, or a leader would cross one - it is tried a little
    # either way along the ring, never further than halfway to the next slot,
    # and then a row further out, and so on: the first row that has room for it
    # is the one it goes in, at whichever spot in that row gives it the
    # shortest leader. The bound on rows is only there so that something
    # degenerate cannot loop forever, and is far beyond any real picture.
    slides = [0.0] + [sign * step * fraction / 8.0 for fraction in range(1, 5) for sign in (1, -1)]
    placed = []
    for index, label in enumerate(order):
        slot = turn + index * step
        for offset in [row * level for level in range(4 * len(labels) + 20)]:
            best = None
            for slide in slides:
                point, outward = ring.at(slot + slide)
                _place(label, point, outward, offset)
                if _clear(label, placed, keep_out):
                    length = _leader_length(label)
                    if best is None or length < best[0]:
                        best = (length, label.spot)
            if best is not None:
                _place(label, *best[1])
                break
        else:
            _place(label, *ring.at(slot), offset)
        placed.append(label)
    _uncross(order, keep_out)
    return labels
