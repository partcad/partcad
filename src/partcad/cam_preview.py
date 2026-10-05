#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A route file, drawn: the path the tool takes, seen from above.

What `pc cam` writes is a program for a machine, and a program is read by
running it. Before anybody does, the question a person asks of it is whether it
goes where the part is - around the outline, inside the pocket - and that is a
question a picture answers at a glance and a page of `G1 X... Y...` does not.

So this reads the program back and draws its moves on the plane the contours are
cut in (G17, the plane `//builtin/cam` writes in): every cutting move as a solid
line, shaded by how deep it is - the deeper, the darker - and every rapid move
as a thin dashed one. It is a reading of the file, not of the part: what is drawn
is whatever the program says, which is the point of looking at it.

Only what describes motion is read: G0/G1, the arcs G2/G3 (by I/J or R, flattened
into segments), G20/G21 and G90/G91. Everything else - the spindle, coolant, a
tool change - is not a place the tool goes and is skipped. A dialect that moves
by some other word is drawn as far as these go, which is a picture that is
missing lines rather than one that is wrong.

Plain SVG with nothing a renderer may not support, because two very different
ones draw it: the IDE's viewer shows it through an <img>, and the instruction
book's PDF goes through svglib - so line widths are in the drawing's own units
rather than 'vector-effect', which svglib ignores.
"""

import math
import re

MM_PER_INCH = 25.4

# How finely an arc is flattened: one segment per this many degrees at most.
ARC_STEP_DEGREES = 5.0

# The size the picture is drawn at, in its own units, before a margin.
VIEW_SIZE = 400.0

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_COMMENT = re.compile(r"\([^)]*\)")


def parse(text: str) -> list:
    """The moves of a program, as (kind, start, end, depth) in millimetres.

    'kind' is "rapid" or "cut"; 'start' and 'end' are (x, y) and 'depth' is the
    Z the move ends at. Arcs come back as several "cut" moves.
    """
    moves = []
    scale = 1.0
    absolute = True
    motion = None
    x = y = z = 0.0
    for raw in text.splitlines():
        line = _COMMENT.sub("", raw.split(";", 1)[0]).strip()
        if not line:
            continue
        words = [(letter.upper(), float(value)) for letter, value in _WORD.findall(line)]
        values = {}
        for letter, value in words:
            if letter == "G":
                code = int(round(value))
                if code in (0, 1, 2, 3):
                    motion = code
                elif code == 20:
                    scale = MM_PER_INCH
                elif code == 21:
                    scale = 1.0
                elif code == 90:
                    absolute = True
                elif code == 91:
                    absolute = False
            else:
                values[letter] = value * (1.0 if letter in ("F", "S", "P", "M", "N", "T") else scale)
        if motion is None or not any(axis in values for axis in ("X", "Y", "Z")):
            continue

        def target(axis, current):
            if axis not in values:
                return current
            return values[axis] if absolute else current + values[axis]

        nx, ny, nz = target("X", x), target("Y", y), target("Z", z)
        if motion in (0, 1):
            if (nx, ny) != (x, y) or nz != z:
                moves.append(("rapid" if motion == 0 else "cut", (x, y), (nx, ny), nz))
        else:
            moves.extend(_arc((x, y), (nx, ny), z, nz, values, clockwise=motion == 2))
        x, y, z = nx, ny, nz
    return moves


def _arc(start, end, z0, z1, values, clockwise):
    """An arc move, flattened into straight cutting moves."""
    if "I" in values or "J" in values:
        cx, cy = start[0] + values.get("I", 0.0), start[1] + values.get("J", 0.0)
    elif "R" in values:
        cx, cy = _center_from_radius(start, end, values["R"], clockwise)
    else:
        return [("cut", start, end, z1)]
    radius = math.hypot(start[0] - cx, start[1] - cy)
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    sweep = a1 - a0
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    elif not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    steps = max(1, int(math.ceil(abs(math.degrees(sweep)) / ARC_STEP_DEGREES)))
    moves = []
    previous = start
    for step in range(1, steps + 1):
        angle = a0 + sweep * step / steps
        point = end if step == steps else (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        moves.append(("cut", previous, point, z0 + (z1 - z0) * step / steps))
        previous = point
    return moves


def _center_from_radius(start, end, radius, clockwise):
    dx, dy = end[0] - start[0], end[1] - start[1]
    chord = math.hypot(dx, dy)
    if chord == 0 or abs(radius) < chord / 2:
        return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    h = math.sqrt(radius * radius - chord * chord / 4)
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    # A negative R is the longer of the two arcs; the side flips with direction.
    side = 1 if (radius > 0) != clockwise else -1
    return (mx - side * h * dy / chord, my + side * h * dx / chord)


def _number(value: float) -> str:
    return ("%.3f" % value).rstrip("0").rstrip(".") or "0"


def _shade(depth: float, top: float, bottom: float) -> str:
    """The colour of a cut at 'depth': light near the top, dark at the bottom."""
    fraction = 0.0 if bottom >= top else (top - depth) / (top - bottom)
    fraction = min(1.0, max(0.0, fraction))
    # From a light blue to a deep one: legible on a white page and in a dark
    # editor alike, since the viewer shows the picture on a light card.
    light, dark = (120, 170, 235), (16, 48, 140)
    channel = [round(light[i] + (dark[i] - light[i]) * fraction) for i in range(3)]
    return "rgb(%d,%d,%d)" % tuple(channel)


def svg(text: str):
    """The program drawn from above, as SVG text, or None when nothing moves.

    Returns '(svg, stats)', where 'stats' counts what was drawn: the cutting
    moves, the rapid ones, and the length of the cutting moves in millimetres.
    """
    moves = parse(text)
    cuts = [move for move in moves if move[0] == "cut"]
    if not moves:
        return None, {"cuts": 0, "rapids": 0, "cut_length": 0.0}

    xs = [point[0] for move in moves for point in (move[1], move[2])]
    ys = [point[1] for move in moves for point in (move[1], move[2])]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    extent = max(max_x - min_x, max_y - min_y) or 1.0
    scale = VIEW_SIZE / extent
    margin = VIEW_SIZE * 0.04
    width = (max_x - min_x) * scale + 2 * margin
    height = (max_y - min_y) * scale + 2 * margin

    def point(p):
        # Y up on the machine, down on a page.
        return (margin + (p[0] - min_x) * scale, margin + (max_y - p[1]) * scale)

    depths = [move[3] for move in cuts] or [0.0]
    top, bottom = max(depths), min(depths)

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="%s" height="%s" viewBox="0 0 %s %s">'
        % (_number(width), _number(height), _number(width), _number(height)),
        '<rect x="0" y="0" width="%s" height="%s" fill="#ffffff"/>' % (_number(width), _number(height)),
    ]
    rapid_width = VIEW_SIZE / 600.0
    lines.append(
        '<g fill="none" stroke="rgb(170,170,170)" stroke-width="%s" stroke-dasharray="%s %s" id="Rapid">'
        % (_number(rapid_width), _number(rapid_width * 6), _number(rapid_width * 4))
    )
    for kind, start, end, _depth in moves:
        if kind != "rapid":
            continue
        a, b = point(start), point(end)
        lines.append(
            '<line x1="%s" y1="%s" x2="%s" y2="%s"/>' % (_number(a[0]), _number(a[1]), _number(b[0]), _number(b[1]))
        )
    lines.append("</g>")
    lines.append('<g fill="none" stroke-width="%s" stroke-linecap="round" id="Cut">' % _number(VIEW_SIZE / 250.0))
    # Shallowest first, so that the deepest pass - the one that decides the
    # part - is drawn on top.
    for kind, start, end, depth in sorted(cuts, key=lambda move: -move[3]):
        a, b = point(start), point(end)
        lines.append(
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s"/>'
            % (_number(a[0]), _number(a[1]), _number(b[0]), _number(b[1]), _shade(depth, top, bottom))
        )
    lines.append("</g>")
    lines.append("</svg>")

    stats = {
        "cuts": len(cuts),
        "rapids": len(moves) - len(cuts),
        "cut_length": sum(math.hypot(m[2][0] - m[1][0], m[2][1] - m[1][1]) for m in cuts),
        "size": (max_x - min_x, max_y - min_y),
        "depth": (top, bottom),
    }
    return "\n".join(lines) + "\n", stats
