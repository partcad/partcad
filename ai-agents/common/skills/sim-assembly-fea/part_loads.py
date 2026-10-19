#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The loads a simulation measured on the body a part is welded into, in that part's own frame.

Shipped beside the `sim-assembly-fea` skill's `SKILL.md`, which says when to run
it. A simulation reports, in every reading, what acts on each *body* -- its
joints, its contacts, its weight -- in the world's frame, and which body each
*part* is welded into and where it sits there (`result["parts"]`). A stress
analysis of one part wants the same loads in the part's frame, which is
arithmetic on two poses and nothing else -- the arithmetic an agent should not do
by hand. This does it, with the standard library alone:

    python part_loads.py loads <sim.json> <part> [--simulation NAME] [--reading after]
    python part_loads.py point <sim.json> <from part> <to part> X Y Z [--direction]

`<sim.json>` is what `pc --no-ansi sim ... --json` printed (or the result of one
run, `{"before": ..., "after": ...}`); `-` reads it from standard input. A part
is named by its path of labels (`subject/lower/knee-worm-gear/gear`), by the end
of one (`knee-worm-gear/gear`), or by the part it is (`motion/worm_gear_28t`, or
its full name) where only one placement of it is in the run.

`loads` prints JSON: the part, its body and its pose in the world; every load on
the body with `at` in mm, `force` in N and `torque` in N*m about `at`, all in the
part's frame; the part's apparent gravity -- the scene's gravity less the body's
acceleration, `g - a`, m/s^2 in the part's frame -- which is what an `fea:`
section's `gravity:` is; and the sum of the loads, which is the body's mass
times its acceleration if every load was reported. `point` turns a point (mm) --
or with `--direction` a direction -- from one part's frame into another's, at
the same reading: where another part's port is in this part's frame.

Which of the body's loads act on the part itself, and how the rest reach it, is
not arithmetic: see the skill.
"""

import argparse
import json
import math
import sys

# Gravity a reading is under when the result does not say, m/s^2: what MuJoCo
# assumes, and what every engine PartCAD drives defaults to within a percent.
DEFAULT_GRAVITY = (0.0, 0.0, -9.81)

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def conjugate(q):
    return (q[0], -q[1], -q[2], -q[3])


def normalized(q):
    size = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / size for c in q)


def rotate(q, v):
    """'v' turned by the unit quaternion 'q' ('w x y z')."""
    w, x, y, z = q
    vx, vy, vz = v
    # q v q*, expanded.
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def compose(outer, inner):
    """The pose 'inner' is at, stated in the frame 'outer' is a pose in: outer * inner."""
    q1, t1 = outer
    q2, t2 = inner
    turned = rotate(q1, t2)
    return normalized(quat_mul(q1, q2)), tuple(a + b for a, b in zip(t1, turned))


def inverse(pose):
    q, t = pose
    back = conjugate(q)
    return back, tuple(-c for c in rotate(back, t))


def transform_point(pose, point):
    q, t = pose
    return tuple(a + b for a, b in zip(rotate(q, point), t))


def pose_of_placement(placement):
    """PartCAD's packed placement, '[[x, y, z], [ax, ay, az], degrees]' in mm, as a pose; None is the identity."""
    if not placement:
        return IDENTITY
    translation, axis, angle = placement
    size = math.sqrt(sum(float(c) * float(c) for c in axis))
    if size == 0.0 or float(angle) == 0.0:
        return IDENTITY[0], tuple(float(c) for c in translation)
    half = math.radians(float(angle)) / 2.0
    s = math.sin(half) / size
    return (math.cos(half), float(axis[0]) * s, float(axis[1]) * s, float(axis[2]) * s), tuple(
        float(c) for c in translation
    )


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def run_of(document, simulation=None):
    """The result of one run out of 'pc sim --json', or the document itself where it is one."""
    if isinstance(document, dict) and "before" in document and "after" in document:
        return document
    runs = (document or {}).get("simulations") if isinstance(document, dict) else None
    if not runs:
        raise SystemExit("No simulation in this document: it is neither 'pc sim --json' nor a run's result")
    if simulation is not None:
        runs = [run for run in runs if run.get("simulation") == simulation]
        if not runs:
            raise SystemExit("No simulation called '%s' in this document" % simulation)
    if len(runs) > 1:
        raise SystemExit(
            "There are %d simulations here (%s): name one with --simulation"
            % (len(runs), ", ".join(str(run.get("simulation")) for run in runs))
        )
    result = runs[0].get("result")
    if not result:
        raise SystemExit("The simulation '%s' did not run: %s" % (runs[0].get("simulation"), runs[0].get("error")))
    return result


def reading_of(result, which="after"):
    """'before', 'after', or a sample by its index."""
    if which in ("before", "after"):
        return result[which]
    try:
        return result["samples"][int(which)]
    except (KeyError, IndexError, ValueError):
        raise SystemExit("No reading '%s': name 'before', 'after' or a sample's index" % which)


def find_part(result, name):
    """(label, entry) of the one part 'name' names in the run's 'parts'."""
    parts = result.get("parts")
    if not parts:
        raise SystemExit(
            "This run says nothing about which body each part is in ('parts'): the simulation plugin does not "
            "report loads, or was asked not to ('loads: false'). Update the plugin, or run it with loads."
        )
    if name in parts:
        return name, parts[name]
    found = [
        (label, entry)
        for label, entry in parts.items()
        if label.endswith("/" + name)
        or entry.get("part") == name
        or str(entry.get("part") or "").rpartition(":")[2] == name
    ]
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit("No part '%s' in this run. Its parts: %s" % (name, ", ".join(sorted(parts))))
    raise SystemExit(
        "'%s' is %d placements in this run; name one by its path: %s"
        % (name, len(found), ", ".join(sorted(label for label, _ in found)))
    )


def part_pose(reading, entry):
    """Where the part is in the world at 'reading': its body's pose, then its placement in the body."""
    body = reading["bodies"].get(entry["body"])
    if body is None:
        raise SystemExit("The body '%s' is not in this reading" % entry["body"])
    world = (normalized(tuple(body["quat"])), tuple(body["pos"]))
    return compose(world, pose_of_placement(entry.get("placement"))), body


def loads(document, part, simulation=None, which="after"):
    """Everything 'loads' prints, as data (see the module docstring)."""
    result = run_of(document, simulation)
    reading = reading_of(result, which)
    label, entry = find_part(result, part)
    pose, body = part_pose(reading, entry)
    if "loads" not in body:
        raise SystemExit("The body '%s' says nothing about its loads in this reading" % entry["body"])
    back = inverse(pose)
    rotation = back[0]

    def here(load):
        at = transform_point(back, load["at"])
        return {
            "kind": load.get("kind"),
            "from": load.get("from"),
            "joint": load.get("joint"),
            "at": [round(c, 6) for c in at],
            "force": [round(c, 9) for c in rotate(rotation, load["force"])],
            "torque": [round(c, 9) for c in rotate(rotation, load["torque"])],
            **({"contacts": load["contacts"]} if "contacts" in load else {}),
        }

    gravity = tuple(result.get("gravity") or DEFAULT_GRAVITY)
    acceleration = tuple(body.get("acc") or (0.0, 0.0, 0.0))
    apparent = tuple(g - a for g, a in zip(gravity, acceleration))
    stated = [here(load) for load in body["loads"]]
    force = [sum(load["force"][i] for load in stated) for i in range(3)]
    moment = [0.0, 0.0, 0.0]
    for load in stated:
        lever = cross([c / 1000.0 for c in load["at"]], load["force"])
        moment = [moment[i] + load["torque"][i] + lever[i] for i in range(3)]
    return {
        "reading": which,
        "time": reading.get("time"),
        "part": {"label": label, "name": entry.get("part"), "body": entry["body"], "placement": entry.get("placement")},
        "pose": {"pos": list(pose[1]), "quat": list(pose[0])},
        "mass": body.get("mass"),
        "gravity": [round(c, 9) for c in rotate(rotation, gravity)],
        "acceleration": [round(c, 9) for c in rotate(rotation, acceleration)] if "acc" in body else None,
        # What an 'fea:' section's 'gravity:' is: the weight a part carries of
        # itself, and what its acceleration flings it by, per kilogram.
        "apparent_gravity": [round(c, 9) for c in rotate(rotation, apparent)],
        "angular_velocity": ([round(c, 9) for c in rotate(rotation, body["angvel"])] if "angvel" in body else None),
        "loads": stated,
        # The loads added up, about the part's origin: the body's mass times its
        # acceleration, when every load on it was reported.
        "total": {"force": [round(c, 9) for c in force], "torque": [round(c, 9) for c in moment]},
        "warnings": list(result.get("warnings") or []),
    }


def point(document, source, target, xyz, direction=False, simulation=None, which="after"):
    """'xyz' in the frame of part 'source', in the frame of part 'target', at one reading."""
    result = run_of(document, simulation)
    reading = reading_of(result, which)
    from_pose, _ = part_pose(reading, find_part(result, source)[1])
    to_pose, _ = part_pose(reading, find_part(result, target)[1])
    relative = compose(inverse(to_pose), from_pose)
    if direction:
        return list(rotate(relative[0], xyz))
    return list(transform_point(relative, xyz))


def _read(path):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 'pc sim --json' can be captured with the log on the same stream: the
    # document is from the first line that opens it.
    start = text.find("{\n")
    return json.loads(text[start:] if start > 0 else text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("loads", help="the loads on a part's body, in the part's frame")
    first.add_argument("document")
    first.add_argument("part")
    second = commands.add_parser("point", help="a point of one part's frame in another's")
    second.add_argument("document")
    second.add_argument("source")
    second.add_argument("target")
    second.add_argument("xyz", nargs=3, type=float)
    second.add_argument("--direction", action="store_true", help="turn a direction rather than move a point")
    for command in (first, second):
        command.add_argument("--simulation", help="which simulation, where the document holds several")
        command.add_argument("--reading", default="after", help="'before', 'after' (the default) or a sample's index")
    arguments = parser.parse_args(argv)
    document = _read(arguments.document)
    if arguments.command == "loads":
        answer = loads(document, arguments.part, arguments.simulation, arguments.reading)
    else:
        answer = point(
            document,
            arguments.source,
            arguments.target,
            arguments.xyz,
            arguments.direction,
            arguments.simulation,
            arguments.reading,
        )
    json.dump(answer, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
