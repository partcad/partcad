#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part's `manufacturing:` section, written out as instructions a person follows.

The assembly instruction book opens with the parts that have to be made before
anything can be put together, and each of those comes with how to make it. That
is this: the declaration read back as sentences -- what the part is made from,
on which machine, and for a saw where every cut goes.

Text, for now, and deliberately the whole of the declaration rather than a
summary of it: the reader has nothing else to go on until PartCAD can draw each
method, and a setting left out of the text is a setting nobody applies.
"""

from . import cam as pc_cam
from .part_config_manufacturing import (
    MACHINE_CNC,
    MACHINE_CUT,
    MACHINE_DRILL,
    MACHINE_LASER,
    METHOD_ADDITIVE,
    METHOD_FORMING,
    METHOD_SHEET_METAL,
    METHOD_SUBTRACTIVE,
    PartConfigManufacturing,
)

MM_PER_INCH = 25.4

# The machine, as the sentence introducing it names it.
_MACHINE_PHRASES = {
    MACHINE_CNC: "on a CNC router or mill",
    MACHINE_LASER: "on a laser cutter",
    MACHINE_DRILL: "on a drilling machine",
    MACHINE_CUT: "with a saw",
}

# How each job setting reads, and the unit its parsed value is in.
_SETTING_NAMES = {
    "operation": ("operation", None),
    "direction": ("direction", None),
    "diameter": ("cutter diameter", "mm"),
    "depth": ("depth", "mm"),
    "depth_per_pass": ("depth per pass", "mm"),
    "safe_z": ("clearance", "mm"),
    "peck": ("peck", "mm"),
    "kerf": ("kerf", "mm"),
    "feed": ("feed", "mm/min"),
    "plunge": ("plunge", "mm/min"),
    "speed": ("spindle speed", "rpm"),
    "stepover": ("stepover", None),
    "power": ("power", None),
}

_AXIS_NAMES = {
    (1.0, 0.0, 0.0): "X",
    (-1.0, 0.0, 0.0): "X",
    (0.0, 1.0, 0.0): "Y",
    (0.0, -1.0, 0.0): "Y",
    (0.0, 0.0, 1.0): "Z",
    (0.0, 0.0, -1.0): "Z",
}


def _number(value: float) -> str:
    """A number without the noise of floating point: 743.7, not 743.6874999."""
    return ("%.3f" % float(value)).rstrip("0").rstrip(".") or "0"


def _length(mm: float) -> str:
    """A length in millimetres and inches, because a board is measured in either."""
    return "%s mm (%s in)" % (_number(mm), _number(mm / MM_PER_INCH))


def _vector(values) -> str:
    return "(%s)" % ", ".join(_number(value) for value in values)


def _axis(normal) -> str | None:
    """'X', 'Y' or 'Z' for a normal along one of them, None for anything else."""
    return _AXIS_NAMES.get(tuple(round(float(value), 9) + 0.0 for value in normal))


def _cut_sentence(cut: dict) -> str:
    """Where one saw cut goes."""
    normal = cut["normal"]
    axis = _axis(normal)
    if cut.get("length") is not None:
        if axis is not None:
            where = "across %s" % axis
            end = "the %s%s end" % ("-" if max(normal, key=abs) > 0 else "+", axis)
        else:
            where = "square to %s" % _vector(normal)
            end = "the end it starts from"
        return "Cut %s, %s from %s of the stock." % (where, _length(cut["length"]), end)
    return "Cut along the plane through %s mm facing %s; what is on the side it faces is the offcut." % (
        _vector(cut["origin"]),
        _vector(normal),
    )


def _settings(options: dict) -> str | None:
    """The job settings of one machine, as a clause."""
    parsers = pc_cam.value_parsers()
    parts = []
    for key, (name, unit) in _SETTING_NAMES.items():
        value = options.get(key)
        if value is None:
            continue
        if key in parsers:
            try:
                value = _number(parsers[key](value, key))
            except ValueError:
                value = str(value)
        parts.append("%s %s%s" % (name, value, " " + unit if unit else ""))
    return ", ".join(parts) or None


def _machine_lines(data: PartConfigManufacturing, kind: str) -> list:
    """How the part is made on one machine."""
    machine = data.machines[kind]
    phrase = _MACHINE_PHRASES.get(kind, "on a '%s'" % kind)
    lines = []
    if kind == MACHINE_CUT:
        lines.append("Cut it to size %s:" % phrase)
        for number, cut in enumerate(machine.cuts, 1):
            lines.append("%d. %s" % (number, _cut_sentence(cut)))
    else:
        sentence = "Make it %s" % phrase
        if machine.tool_axis:
            sentence += ", working along %s" % machine.tool_axis
        # Shared settings first, the machine's own over them: the same layering
        # 'cam.declared_config' applies when it writes the program.
        options = dict(data.job)
        options.update(machine.options)
        settings = _settings(options)
        lines.append(sentence + ("; %s." % settings if settings else "."))
    if machine.options.get("desc"):
        lines.append(str(machine.options["desc"]).strip())
    return lines


def describe(data: PartConfigManufacturing, stock: str | None = None) -> list:
    """The manufacturing instructions of a part, one paragraph per entry.

    'stock' is the fully qualified name of what it is made from, where the
    caller has resolved it; otherwise the reference is quoted as written.
    """
    lines = []
    source = stock or data.source
    if data.method == METHOD_SUBTRACTIVE:
        lines.append("Made by taking material away from `%s`." % source if source else "Made by taking material away.")
    elif data.method == METHOD_SHEET_METAL:
        sentence = "Bent from `%s`" % source if source else "Bent from a flat blank"
        if data.instructions:
            sentence += ", along the bends drawn in `%s`" % data.instructions
        lines.append(sentence + ".")
    elif data.method == METHOD_ADDITIVE:
        lines.append("Made additively (3D printed).")
    elif data.method == METHOD_FORMING:
        lines.append("Formed: molded, cast or pressed.")

    if data.job.get("desc"):
        lines.append(str(data.job["desc"]).strip())

    if data.machine_error:
        lines.append("The machine it is made on cannot be read: %s." % data.machine_error)
        return lines

    kinds = data.machine_choices()
    declared = [kind for kind in kinds if data.machines[kind].declared]
    if len(declared) > 1:
        lines.append("It can be made any one of %d ways:" % len(declared))
    for kind in declared:
        lines += _machine_lines(data, kind)
    return lines
