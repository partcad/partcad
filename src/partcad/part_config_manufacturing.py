#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

import json
import math
import re

from . import cam as pc_cam
from . import logging as pc_logging

METHOD_NONE: None = None
# Note: The assigned numbers are used in APIs and must never change unless the old method is deprecated.
METHOD_ADDITIVE: int = 100
METHOD_SUBTRACTIVE: int = 200
METHOD_FORMING: int = 300
METHOD_SHEET_METAL: int = 400

# These are ways of making a part, and a part only: an assembly is put together
# rather than made, and has its own single method (see AssemblyConfigManufacturing).
_METHOD_MAP: dict[str, int] = {
    "additive": METHOD_ADDITIVE,
    "subtractive": METHOD_SUBTRACTIVE,
    "forming": METHOD_FORMING,
    "sheet_metal": METHOD_SHEET_METAL,
}

_METHOD_NAMES: dict[int, str] = {value: name for name, value in _METHOD_MAP.items()}

# What a sheet metal part has to say beyond naming the method, and what each of
# them is.
#
# Bending is not something done to a block of stock: it is done to a flat piece
# that already has its outline and its holes, and the result is that piece in
# another shape. So the declaration names two things rather than describing one:
#
# * 'source' - the part that goes into the brake. It is a part rather than a
#   drawing because it is a part: somebody makes it, it has a thickness, a
#   material and a tolerance, and it is manufactured by a process of its own
#   (see the documentation - it is expected to be subtractive: laser cut,
#   waterjet, routed).
# * 'instructions' - the sketch that says where the bends are and what each of
#   them is. A sketch rather than a file, so that what states it is PartCAD's
#   own object and not one format (see 'Sketch.get_annotations'); the sketch's
#   own layer parameters pick the bend layers out of a drawing that also holds
#   the outline: 'instructions: bends;include=BEND_UP,BEND_DOWN'.
#
# Both are references, resolved against the package the part is declared in like
# every other reference a part makes.
SHEET_METAL_REQUIRED = ("source", "instructions")

# What a subtractive part has to say beyond naming the method.
#
# The stock it is cut out of. Subtraction is defined by what it starts from --
# cutting only ever removes material, so a subtractive part is not a shape
# somebody arrived at, it is what is left of a piece that existed first -- and a
# declaration that names no stock has not said what the method means. It is
# required for that reason and not for symmetry with 'sheet_metal': the check
# has something to check because the declaration has something to claim.
#
# A part that is genuinely made from no stock is a part made some other way: it
# is bought (`vendor`/`sku`), or it is `additive`, or `forming`.
SUBTRACTIVE_REQUIRED = ("source",)

# What an `additive` part may say beyond naming the method, and what each is.
#
# Printing is the one method whose `source:` is not something that goes into
# the machine. A blank goes into a brake and stock goes onto a router, but
# nothing goes into a printer except the material: what it is handed is a
# *design*, and what comes out is that design as the process can make it --
# walls a few lines thick, a top and a bottom a few layers deep, and the inside
# filled at the density the print says. So the two are different objects, and
# the declaration names both:
#
# * 'source' - the design: the solid the designer had in mind. It is what the
#   print is measured against (its tolerance is the design's), what a slicer is
#   handed, and what the printed part is drawn as. Optional: a part that names
#   none is its own design, which is what every `additive` part written before
#   this meant and still means.
# * 'visual' - what the part is drawn as, where that is not the design: a mesh
#   with the layer lines on it, a cheaper model of a heavy one. Only for a part
#   with no geometry of its own; one with a `type:` is drawn as what it is.
#
# A part that names a `source:` needs no geometry of its own -- it is the design,
# printed -- so it may leave `type:` out, and is then drawn, placed and exported
# as its visual (see 'implied_type'). The process settings that turn the design
# into the printed part (walls, infill...) are the process' own subsection, as a
# subtractive machine's are (see 'PROCESSES').
#
# Neither is required: printing is defined by its material, not by anything a
# part names.
ADDITIVE_REQUIRED: tuple = ()

# The keys an `additive` section holds besides a process' subsection.
_ADDITIVE_SECTION_KEYS = ("method", "source", "visual")

# The processes an `additive` part may be printed by, each named by adding its
# own subsection -- the way a subtractive part names its machine, and for the
# same reason: the processes do not take the same settings. Fused filament
# fabrication (ISO/ASTM 52900 "material extrusion", what most people call FDM)
# is the one PartCAD reads today; resin and powder processes take settings of
# their own and get subsections of their own when something reads them.
#
# Several are alternatives, as machines are: a part that could be printed either
# way says so, and whoever prints it picks.
PROCESS_FFF = "fff"
PROCESSES = (PROCESS_FFF,)

# What each process' subsection may hold. Named after the settings every slicer
# has, in PartCAD's camelCase rather than in any one slicer's spelling
# (PrusaSlicer's `perimeters` is Cura's `wall_line_count` is `walls` here).
#
# Each is what decides the printed part's *geometry*: how thick its skin is and
# how full its inside. Speeds, temperatures and cooling decide whether the print
# succeeds, not what shape it is, and are left to whoever prints it.
PROCESS_LENGTH_KEYS = ("layerHeight", "lineWidth", "nozzle")
PROCESS_COUNT_KEYS = ("walls", "topLayers", "bottomLayers")
PROCESS_KEYS: dict[str, tuple] = {
    PROCESS_FFF: PROCESS_LENGTH_KEYS + PROCESS_COUNT_KEYS + ("infill", "infillPattern", "desc"),
}

# What a setting is taken to be where a process subsection does not say, for
# whatever has to assume one (the weight of a print, the printed geometry). The
# values most slicers ship for a 0.4 mm nozzle; a part that cares says its own.
# Never applied where nothing is printed: a part that names no process has no
# infill to assume, and is weighed as the solid it is.
PROCESS_DEFAULTS: dict[str, dict] = {
    PROCESS_FFF: {
        "nozzle": 0.4,
        "layerHeight": 0.2,
        "lineWidth": 0.45,
        "walls": 2,
        "topLayers": 4,
        "bottomLayers": 4,
        "infill": 0.15,
        "infillPattern": "grid",
    },
}

# Every key that belongs in a process subsection, for telling a setting written
# one level too high from a key nobody has heard of.
_PROCESS_SETTING_KEYS = frozenset(key for keys in PROCESS_KEYS.values() for key in keys if key != "desc")

# The machines a `subtractive` part may be made on, and which one a declaration
# means.
#
# Subtraction is one idea -- material is taken away from a piece of stock until
# what is left is the part -- but the machines that do it are not
# interchangeable, and what they *cannot* do is the useful thing to know. A
# router will cut any 2.5D shape; a laser cuts a sheet with a beam that does not
# tilt; a drill makes round holes and nothing else. So the machine decides which
# `pc qual test` check applies and what `pc cam` writes.
#
# It is named by adding that machine's own subsection rather than by a `machine:`
# key, because the machines do not take the same options and a key would leave
# them all in one namespace with nothing to say which belongs to which. A
# declaration with none of them is a CNC one: that is the machine that can make
# anything the other two can, so it is the answer that is never wrong, and it is
# what every `subtractive` part written before this existed meant.
#
# The fourth, `cut:`, is the most limited of all and the most common: a saw that
# cuts a piece of stock across, to length, and does nothing else. A stud cut
# from an eight foot 2x4, a shelf cut from a sheet of plywood. It follows no
# outline, so it is described by *where* it cuts: for each cut, the axis the saw
# travels along ('toolAxis:', as for every other machine here) and how far into
# the stock it goes before it cuts across. The only thing it can produce is the
# stock with everything beyond those cuts taken off. That is what
# `manufacturability-cut` checks, and it is why a cut part names its stock in
# `source:` in the same coordinate space the part itself is modelled in.
MACHINE_CNC = "cnc"
MACHINE_DRILL = "drill"
MACHINE_LASER = "laser"
MACHINE_CUT = "cut"
MACHINES = (MACHINE_CNC, MACHINE_DRILL, MACHINE_LASER, MACHINE_CUT)

# The machines `pc cam` writes a program for. A cut is not one of them: a saw
# cutting stock to length runs no program, and what it needs to be told -- where
# to cut -- is already the whole of its declaration. `pc cam` passes over a part
# that is only cut, and refuses `-m cut` with a sentence rather than handing a
# router emitter a part that has no router.
ROUTED_MACHINES = (MACHINE_CNC, MACHINE_DRILL, MACHINE_LASER)

# What each machine's subsection may hold, in two halves.
#
# 'MACHINE_OWN_KEYS' are the machine itself: the axis it works along, and for a
# laser the kerf its beam removes. 'MACHINE_JOB_KEYS' are the cut -- the keys
# that used to live in a separate 'cam:' section, and which now sit beside the
# machine they are about.
#
# The job half is not the same for the three, and that is the point of naming it
# per machine rather than keeping one flat list. It is derived from what each
# emitter in '//builtin/cam' actually reads, so a key a machine has no use for
# is a key that machine refuses:
#
# * a laser has no 'diameter:' -- it has no cutter, and 'kerf:' is what it
#   removes -- and no 'depth:' or 'safe_z:', because it cuts through in one pass
#   and never moves in Z. One flat namespace could not say any of that, and a
#   cutter diameter written on a laser was a value silently ignored.
# * a drill has no 'depth:' (how deep each hole goes is the geometry's to say),
#   no 'feed:' (it never travels while cutting) and no 'operation:'.
#
# 'toolAxis' is common to all four, because it is the one thing every
# subtractive machine has: the axis the tool, the beam, the drill or the saw approaches
# along. It is what "all cut walls are vertical" is measured against -- vertical
# meaning parallel to it -- and it is why a part that is cut from the other side
# is a different part to the machine even though it is the same solid.
#
# 'along' is the same key under another name, for every machine and for each
# of a saw's cuts: "the laser cuts along -Z" and "cut along Y" are how these
# are said. One or the other, never both -- two spellings of one axis that
# could disagree are a declaration with no one answer. See 'written_axis'.
#
# Not 'direction', which is the one word this configuration cannot afford to
# reuse: it already means climb or conventional, which way round a contour is
# cut, and both would reach one implementation in one request.
MACHINE_OWN_KEYS: dict[str, tuple] = {
    MACHINE_CNC: ("toolAxis", "along"),
    MACHINE_DRILL: ("toolAxis", "along"),
    # 'kerf' is the width the beam itself removes. It belongs to the machine
    # rather than to the cut because it is a property of that machine and its
    # material, and because the check that the part fits its stock has to know
    # it: a part cut to its nominal outline comes off a laser half a kerf small
    # all round.
    MACHINE_LASER: ("toolAxis", "along", "kerf"),
    # A saw travels along its 'toolAxis:' like the others -- to the length of
    # each cut, and everything beyond is the offcut -- and takes the cuts. A cut
    # may name an axis of its own; the machine's is what one that does not
    # travels along. See 'parse_cuts'.
    MACHINE_CUT: ("toolAxis", "along", "cuts"),
}

MACHINE_JOB_KEYS: dict[str, tuple] = {
    MACHINE_CNC: (
        "diameter",
        "depth",
        "depth_per_pass",
        "safe_z",
        "feed",
        "plunge",
        "speed",
        "stepover",
        "operation",
        "direction",
    ),
    MACHINE_LASER: ("power", "feed", "direction"),
    MACHINE_DRILL: ("diameter", "safe_z", "peck", "plunge", "speed"),
    # Nothing: no emitter reads a cut, so any job key written in 'cut:' would be
    # a number nobody acts on.
    MACHINE_CUT: (),
}

# Two keys every machine takes, because they are about the route rather than
# about the cut: who writes it, and what it is.
MACHINE_ROUTE_KEYS = ("implementation", "desc")


def machine_keys(kind: str) -> tuple:
    """Every key one machine's subsection may hold."""
    if kind not in ROUTED_MACHINES:
        # No route is written for it, so there is nobody for 'implementation:'
        # to name.
        return MACHINE_OWN_KEYS[kind] + MACHINE_JOB_KEYS[kind] + ("desc",)
    return MACHINE_OWN_KEYS[kind] + MACHINE_JOB_KEYS[kind] + MACHINE_ROUTE_KEYS


# What may be written directly under 'manufacturing:', shared by every machine
# the part names. The union of the three job vocabularies, because the shared
# scope is "for whichever machine reads it": a 'feed:' written here covers the
# router and the laser and is simply not read by the drill.
#
# That is the difference between the two scopes, and it is deliberate. Writing
# 'diameter:' here is legal and means "the cutter, wherever there is one";
# writing it under 'laser:' is a mistake, because a laser has no cutter and
# saying so in its own subsection can only be an error.
SHARED_JOB_KEYS = tuple(pc_cam.KEYS)

# What the section holds besides a job and a machine: what is being described
# rather than how it is cut.
_SECTION_KEYS = ("method", "source", "instructions")

# The axis names a 'toolAxis:' may be written as, and the unit vector each
# means. Written as a name rather than as three numbers because these are the
# only six a machine of this kind works along, and "-Z" is what a machinist
# says: the tool comes down.
_AXES: dict[str, tuple] = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}

# What a machine works along when the declaration does not say. Down: the part
# sits on the bed and the tool comes to it from above, which is what all three
# of these machines do unless somebody has gone out of their way.
DEFAULT_TOOL_AXIS = "-Z"


# The two names one axis may be written under. 'toolAxis' first: it is the one
# every message names.
AXIS_KEYS = ("toolAxis", "along")


def written_axis(entry: dict, what: str):
    """The axis 'entry' names, under 'toolAxis:' or 'along:', or None where neither.

    Raises:
        ValueError: it names both. Refused rather than preferring one, because
            the two can disagree and neither reading is safer than the other.
    """
    named = [key for key in AXIS_KEYS if entry.get(key) is not None]
    if len(named) > 1:
        raise ValueError("%s says both 'toolAxis:' and 'along:', which are one thing; write one" % what)
    return entry[named[0]] if named else None


def tool_axis_vector(name: str) -> tuple:
    """The unit vector one 'toolAxis:' means.

    Raises:
        ValueError: the name is not one of the six axes. Raised rather than
            defaulted, because an axis that was meant and misspelt is the
            one input here whose wrong value produces a check that passes.
    """
    key = str(name).strip().lower()
    if key in _AXES:
        return _AXES[key]
    # 'z' and 'Z' read as '+z', which is what somebody writing an axis without a
    # sign means everywhere else.
    if "+" + key in _AXES:
        return _AXES["+" + key]
    raise ValueError("'%s' is not an axis; write one of %s" % (name, ", ".join(sorted(_AXES))))


# '$name' (or '${name}') in a cut stands for the value of the part's own
# parameter 'name'. A part cut to length is nearly always a parametric one -- a
# leg as long as the desk is high -- and a cut written as a number would be
# right for one instance and wrong for every other.
_PARAMETER_REFERENCE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def parameter_values(final_config: dict) -> dict:
    """The value of each parameter of an object, by name, as it was instantiated."""
    values = {}
    for name, declaration in (final_config.get("parameters") or {}).items():
        if isinstance(declaration, dict):
            values[name] = declaration.get("default")
        else:
            values[name] = declaration
    return values


def _substitute(value, parameters: dict, what: str):
    """'value' with every '$name' in it replaced by that parameter's value."""
    if not isinstance(value, str) or "$" not in value:
        return value

    def replace(match):
        name = match.group(1) or match.group(2)
        if name not in parameters or parameters[name] is None:
            raise ValueError(
                "%s refers to the parameter '%s', which the part does not have%s"
                % (
                    what,
                    name,
                    "; it has %s" % ", ".join("'%s'" % one for one in sorted(parameters)) if parameters else "",
                )
            )
        return str(parameters[name])

    return _PARAMETER_REFERENCE.sub(replace, value)


def _direction(value, what: str) -> list:
    """A direction as a unit vector: an axis name ('+Y') or three numbers."""
    if isinstance(value, str):
        return list(tool_axis_vector(value))
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("%s is not a direction: %r. Write an axis ('+Y') or three numbers" % (what, value))
    if any(isinstance(component, bool) for component in value):
        raise ValueError("%s is not a direction: %r" % (what, value))
    try:
        vector = [float(component) for component in value]
    except (TypeError, ValueError) as e:
        raise ValueError("%s is not a direction: %r" % (what, value)) from e
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 0.0:
        raise ValueError("%s is a zero vector, which faces no way at all" % what)
    return [component / length for component in vector]


def parse_cuts(value, parameters: dict | None = None, tool_axis: str = DEFAULT_TOOL_AXIS) -> list:
    """The cuts one 'cut:' subsection declares, as plain data.

    A cut is written the way every other subtractive machine is: by the axis the
    tool travels along. The saw starts where the stock starts along that axis,
    travels ``length:`` into it, and cuts across; everything further along the
    axis is the offcut, and what is behind the saw is the part::

        cut:
          toolAxis: +Y            # for every cut that does not say
          cuts:
            - length: $length in  # along +Y
            - toolAxis: -X        # or 'along: -X', which says the same
              length: 36 in

    So ``length:`` is always there -- it is the whole of *where* -- and the
    direction is optional: a cut's own ``toolAxis:`` or ``along:`` (one or the
    other; 'along' is how a saw cut is usually said), else the machine's
    ``toolAxis:``, else the default every machine has, '-Z'. The direction is an
    axis ('+Y') or three numbers; a length is measured from the end of the stock,
    which is the only way a cut to length is measured on a saw.

    Any number may be written as '$name', the value of the part's own parameter
    of that name, with or without a unit after it ('$length in').

    What comes back is a list of ``{"normal": [...], "length": ...}``: the unit
    vector the tool travels along, which is also the normal of the plane it cuts
    and points at the offcut, and millimetres. A length is only turned into a
    plane where the stock is known, which is not here.

    Raises:
        ValueError: anything that cannot be read as a cut, naming the cut it is
            about.
    """
    parameters = parameters or {}
    if value is None:
        raise ValueError("'cut:' names no 'cuts:', so it does not say where to cut")
    if isinstance(value, dict):
        # One cut, written without the list around it.
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("'cut: cuts:' is not a list of cuts: %r" % (value,))

    cuts = []
    for index, entry in enumerate(value):
        what = "'cut: cuts:' #%d" % (index + 1)
        if not isinstance(entry, dict):
            raise ValueError(
                "%s is not a cut: %r. Write 'length:', and optionally 'toolAxis:' or 'along:'" % (what, entry)
            )
        keys = set(entry)
        unknown = keys - {"length", "toolAxis", "along"}
        if unknown:
            raise ValueError(
                "%s says %s. A cut is 'length:', and optionally 'toolAxis:' or 'along:'"
                % (what, ", ".join("'%s:'" % key for key in sorted(unknown)))
            )
        if "length" not in keys:
            raise ValueError("%s says no 'length:', so it does not say where the saw goes" % what)
        axis = written_axis(entry, what)
        if axis is not None:
            normal = _direction(axis, "%s '%s:'" % (what, "toolAxis" if "toolAxis" in keys else "along"))
        else:
            normal = list(tool_axis_vector(tool_axis))
        length_what = "%s 'length:'" % what
        cuts.append(
            {
                "normal": normal,
                "length": pc_cam.parse_length(_substitute(entry["length"], parameters, length_what), length_what),
            }
        )
    return cuts


class MachineConfig:
    """One subtractive machine, as a part declares it.

    Attributes:
        kind: which machine, one of 'MACHINES'.
        tool_axis: the axis it works along, as written.
        vector: that axis as a unit vector.
        declared: whether the part named this machine, or whether it is the CNC
            default standing in. What the difference buys is that the two
            machine-specific checks apply only to a part that asked for them:
            'manufacturability-laser' must not start failing every subtractive
            part that has been in a package for a year.
        options: the rest of what the subsection said, by key.
    """

    def __init__(self, kind: str, config: dict | None, declared: bool = True, parameters: dict | None = None) -> None:
        """Read one machine subsection.

        'parameters' are the part's own parameter values, which a cut may refer
        to as '$name'. No other machine reads them.

        Raises:
            ValueError: the axis is not one of the six, or a length is not a
                length. Raised rather than recorded because the caller --
                '_read_machine' -- is what turns either into the 'machine_error'
                a check reports, and it adds the machine's name on the way.
        """
        self.kind = kind
        self.declared = declared
        self.options = dict(config or {})
        # The cuts a saw makes, for a cut and for nothing else.
        self.cuts: list = []
        written_key = "along" if self.options.get("along") is not None else "toolAxis"
        written = written_axis(self.options, "'%s:'" % kind)
        for key in AXIS_KEYS:
            self.options.pop(key, None)
        self.tool_axis = str(written or DEFAULT_TOOL_AXIS)
        try:
            self.vector = tool_axis_vector(self.tool_axis)
        except ValueError as e:
            # Named here rather than by the caller, so that every message out of
            # this class says which machine and which key without the caller
            # having to guess which of them already did.
            raise ValueError("'%s: %s:' %s" % (kind, written_key, e)) from e
        if kind == MACHINE_CUT:
            # Each cut resolved against the machine's axis here, so what a cut
            # travels along is decided once and everything downstream -- the
            # check, the cache key, the instructions -- reads the same vector.
            self.cuts = parse_cuts(self.options.pop("cuts", None), parameters, self.tool_axis)
            return
        # Every value read the way PartCAD reads that kind of value, so "6",
        # "6 mm" and "0.25 in" are one cutter. 'CamConfigError' is a
        # 'ValueError', which is what the caller already catches to turn a bad
        # number into a recorded message rather than a package that will not
        # load.
        for key, parse in pc_cam.value_parsers().items():
            if self.options.get(key) is not None:
                self.options[key] = parse(self.options[key], "'%s: %s:'" % (kind, key))

    def key(self) -> str:
        """What distinguishes this machine's claim from another, for a cache key.

        The axis for the three that work along one, and the cuts for a saw --
        each is the whole of what moving the declaration changes about the
        verdict, and neither moves the part's own hash.
        """
        if self.kind == MACHINE_CUT:
            return json.dumps(self.cuts, sort_keys=True)
        return str(self.tool_axis)

    def get(self, key: str, default=None):
        """One machine option, or 'default' where the subsection did not say."""
        value = self.options.get(key)
        return default if value is None else value

    def job_options(self) -> dict:
        """What this subsection said about the *cut*, not about the machine.

        Separated from `to_data` because the two sit at different heights in the
        request. A job key is the part's own answer and an explicit
        `route_async(feed=...)` outranks it; the machine's identity outranks
        everything, because a route written for the wrong machine is the failure
        that reaches the shop floor.
        """
        allowed = MACHINE_JOB_KEYS[self.kind] + MACHINE_ROUTE_KEYS
        return {key: value for key, value in self.options.items() if key in allowed and value is not None}

    def to_data(self) -> dict:
        """This machine as the parameters an implementation is handed.

        The kind and the axis always, because every implementation needs to
        know what it is writing for and which way is down, plus the machine's
        own properties -- a laser's kerf. Not the job keys: those are
        `job_options`, and they are merged further down.
        """
        if self.kind == MACHINE_CUT:
            return {"machine": self.kind, "tool_axis": self.tool_axis, "cuts": self.cuts}
        data = {"machine": self.kind, "tool_axis": self.tool_axis, "tool_axis_vector": list(self.vector)}
        own = MACHINE_OWN_KEYS[self.kind]
        data.update({key: value for key, value in self.options.items() if key in own and value is not None})
        return data

    def __str__(self) -> str:
        """The machine and its axis, which are what distinguish two of these."""
        if self.kind == MACHINE_CUT:
            return "MachineConfig(kind=%s, cuts=%d)" % (self.kind, len(self.cuts))
        return "MachineConfig(kind=%s, toolAxis=%s)" % (self.kind, self.tool_axis)


def parse_fraction(value, what: str) -> float:
    """A share of something, from 0 to 1: '20%', or 0.2.

    A bare number above 1 is refused rather than read as a percentage. '20' is
    twenty percent to whoever wrote it and two thousand to the arithmetic, and
    neither reading is safer than the other.

    Raises:
        ValueError: the value is not a fraction, or not between none and all.
    """
    if isinstance(value, bool):
        raise ValueError("%s is not a fraction: %r" % (what, value))
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            try:
                amount = float(text[:-1].strip()) / 100.0
            except ValueError as e:
                raise ValueError("%s is not a percentage: %r" % (what, value)) from e
        else:
            try:
                amount = float(text)
            except ValueError as e:
                raise ValueError("%s is not a fraction: %r. Write '20%%' or 0.2" % (what, value)) from e
            if amount > 1.0:
                raise ValueError(
                    "%s is %r, which is more than all of it. Write '%s%%' or %s" % (what, value, text, amount / 100.0)
                )
    elif isinstance(value, (int, float)):
        amount = float(value)
        if amount > 1.0:
            raise ValueError(
                "%s is %r, which is more than all of it. Write '%s%%' or %s" % (what, value, value, amount / 100.0)
            )
    else:
        raise ValueError("%s is not a fraction: %r. Write '20%%' or 0.2" % (what, value))
    if not 0.0 <= amount <= 1.0 or math.isnan(amount):
        raise ValueError("%s is not between 0%% and 100%%: %r" % (what, value))
    return amount


def _parse_count(value, what: str) -> int:
    """How many of something: a whole number, none or more."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value) or value < 0:
        raise ValueError("%s is not a count: %r. Write a whole number, 0 or more" % (what, value))
    return int(value)


class PrintProcess:
    """One additive process, as a part declares it: what turns the design into the print.

    Attributes:
        kind: which process, one of 'PROCESSES'.
        options: what the subsection said, each value read into its unit --
            millimetres for a length, a fraction for the infill, a whole number
            for a count. Only what was said: 'settings()' fills in the rest.
    """

    def __init__(self, kind: str, config) -> None:
        """Read one process subsection.

        Raises:
            ValueError: a key the process does not take, or a value that cannot
                be read. Raised rather than recorded, as 'MachineConfig' does,
                because the caller is what turns it into the 'process_error' a
                check reports.
        """
        self.kind = kind
        if config is not None and not isinstance(config, dict):
            raise ValueError("'%s:' is not a section: %r" % (kind, config))
        allowed = PROCESS_KEYS[kind]
        unknown = [key for key in (config or {}) if key not in allowed]
        if unknown:
            raise ValueError(
                "'%s:' does not take %s; it takes %s"
                % (
                    kind,
                    ", ".join("'%s:'" % key for key in sorted(unknown)),
                    ", ".join("'%s:'" % key for key in allowed),
                )
            )
        self.options: dict = {}
        for key, value in (config or {}).items():
            if value is None:
                continue
            what = "'%s: %s:'" % (kind, key)
            if key in PROCESS_LENGTH_KEYS:
                self.options[key] = pc_cam.parse_length(value, what)
            elif key in PROCESS_COUNT_KEYS:
                self.options[key] = _parse_count(value, what)
            elif key == "infill":
                self.options[key] = parse_fraction(value, what)
            elif key == "infillPattern":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("%s is not the name of a pattern: %r" % (what, value))
                self.options[key] = value.strip().lower()
            else:
                self.options[key] = value

    def get(self, key: str, default=None):
        """One setting as the subsection said it, or 'default' where it did not."""
        value = self.options.get(key)
        return default if value is None else value

    def settings(self) -> dict:
        """Every setting that decides the printed geometry, the defaults filling what was not said.

        What the weight of a print and its geometry are worked out from, so
        that both assume the same thing about a setting nobody stated. 'desc'
        is not one of them.
        """
        settings = dict(PROCESS_DEFAULTS.get(self.kind, {}))
        settings.update({key: value for key, value in self.options.items() if key != "desc"})
        return settings

    def key(self) -> str:
        """What distinguishes this process' claim from another, for a cache key."""
        return json.dumps({"kind": self.kind, "settings": self.settings()}, sort_keys=True)

    def to_data(self) -> dict:
        """This process as the parameters an implementation is handed: the kind and every setting."""
        data = {"process": self.kind}
        data.update(self.settings())
        return data

    def __str__(self) -> str:
        return "PrintProcess(kind=%s, %s)" % (
            self.kind,
            ", ".join("%s=%s" % (key, value) for key, value in sorted(self.options.items()) if key != "desc"),
        )


# The marker 'implied_type' leaves on a declaration it gave a type to: that the
# `type: alias` it has was not written. What tells "drawn as its visual" from a
# reference somebody wrote, which has a geometry of its own to be drawn as and so
# takes no `visual:` (see 'manufacturability-additive').
IMPLIED_TYPE_KEY = "implied_type"


def implied_type(config) -> dict | None:
    """What a printed part with no geometry of its own is, as the keys to add to its declaration; None otherwise.

    A part that says `manufacturing: method: additive` and names a `source:`
    design needs no `type:`: it is that design, printed. It is then drawn,
    placed in an assembly and exported as its visual -- `visual:`, else the
    design -- which is exactly what a reference to that object is: `type:
    alias` pointing at it, with this part's own `manufacturing:` section, which
    a reference restates rather than inherits (see 'PartFactoryAlias').

    None for anything else, including a part that wrote a `type:` (its geometry
    is its own) and one that wrote a top-level `source:` without one (an alias
    missing its type, which is reported as it always was).
    """
    if not isinstance(config, dict) or config.get("type") is not None or config.get("source") is not None:
        return None
    section = config.get("manufacturing")
    if not isinstance(section, dict) or section.get("method") != "additive":
        return None
    design = section.get("source")
    visual = section.get("visual")
    drawn_as = visual if isinstance(visual, str) and visual else design
    if not isinstance(drawn_as, str) or not drawn_as or not isinstance(design, str) or not design:
        return None
    return {"type": "alias", "source": drawn_as, IMPLIED_TYPE_KEY: "additive"}


class PartConfigManufacturing:
    method: int | None

    # The part that is worked on, and the sketch that says how, for the methods
    # that are defined in terms of another object. None for every other method,
    # which describes a part made from stock and has nothing to point at.
    #
    # For `additive` the source is the *design* instead -- what is printed,
    # rather than what goes into the machine -- and `visual` what the part is
    # drawn as where that is not the design (see 'ADDITIVE_REQUIRED').
    source: str | None
    instructions: str | None
    visual: str | None

    def __init__(self, final_config: dict) -> None:
        """Read a part's 'manufacturing:' section, without refusing any of it.

        Nothing here raises. An unknown method is logged and read as none, and a
        machine subsection that cannot be made sense of is recorded in
        'machine_error' -- because loading a package must not fail over one
        part's declaration, and a part whose manufacturing section is wrong is
        still a part that can be listed, rendered and exported. What is wrong
        with it is 'pc qual test's to report, against the part it belongs to.
        """
        manufacturing_config = final_config.get("manufacturing", {}) or {}
        # Whether the object said anything at all, which is not the same as
        # whether it named a method. A *sketch* that is engraved or scored has a
        # `manufacturing:` section and no method in it: a drawing is not made,
        # it is a path a machine follows, so there is no stock for it to be cut
        # from and nothing for `method:` to say. An object with no section at
        # all is the other case entirely, and gets no machine -- which is what
        # keeps an implementation handed nothing writing what it always wrote.
        self.declared_section = bool(manufacturing_config)
        method_string = manufacturing_config.get("method", None)
        self.method = _METHOD_MAP.get(method_string, METHOD_NONE)
        if self.method == METHOD_NONE and method_string is not None:
            pc_logging.error(
                f"Unknown manufacturing method '{method_string}'. Supported methods: {list(_METHOD_MAP.keys())}."
            )
        self.source = manufacturing_config.get("source", None)
        self.instructions = manufacturing_config.get("instructions", None)
        self.visual = manufacturing_config.get("visual", None)
        self.machine_error: str | None = None
        # The same for a printed part's process subsection: what in it could
        # not be read, and the processes it could be printed by. Kept apart from
        # the machines because nothing *routes* a print yet: 'pc cam' visits a
        # part whose 'machine_error' is set, and a typo in an infill is not
        # something it has anything to say about. 'pc qual test' is what reports
        # it (see 'manufacturability-additive').
        self.process_error: str | None = None
        self.processes: dict[str, PrintProcess] = {}
        # Every machine this part could be made on, by kind. Several is not a
        # sequence: they are alternatives, and `pc cam` writes a program for the
        # one that is chosen. A part that really is machined in stages is a
        # chain of parts, each naming the previous one as its `source`, because
        # each stage has its own geometry and its own stock.
        self.machines: dict[str, MachineConfig] = {}
        # What was written directly under `manufacturing:`, shared by all of
        # them. Raw: the machine that reads a key is what parses it, so a key
        # here is parsed once per machine it reaches rather than once for a
        # machine nobody chose.
        self.job: dict = {}
        # What a cut's '$name' refers to: the part's own parameter values, as
        # this instance of it was made with.
        self.parameters = parameter_values(final_config)
        self._read_machines(manufacturing_config)
        if self.method == METHOD_ADDITIVE:
            self._read_processes(manufacturing_config)

    def _read_processes(self, manufacturing_config: dict) -> None:
        """What a printed part says beyond its method: its design, its visual and its process.

        Recorded rather than raised, for the reason '_read_machines' gives. The
        keys a cut takes are not this method's to judge: '_read_machines'
        refuses them already, in the words every other method hears.
        """
        misplaced = sorted(key for key in manufacturing_config if key in _PROCESS_SETTING_KEYS)
        if misplaced:
            # Written one level too high. Said as such rather than as an
            # unknown key, because it is a known one: it is a process' setting,
            # and the process is what decides what it means.
            self.process_error = "%s is a setting of the process it is printed by; write it under %s" % (
                ", ".join("'%s:'" % key for key in misplaced),
                " or ".join("'%s:'" % kind for kind in PROCESSES),
            )
            return
        unknown = sorted(
            key
            for key in manufacturing_config
            if key not in _ADDITIVE_SECTION_KEYS
            and key not in PROCESSES
            and key not in SHARED_JOB_KEYS
            and key not in MACHINES
            and key not in _SECTION_KEYS
        )
        if unknown:
            self.process_error = "'manufacturing:' does not take %s" % ", ".join("'%s:'" % key for key in unknown)
            return
        for field in ("source", "visual"):
            value = manufacturing_config.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                self.process_error = "'%s:' is not a reference to a part: %r" % (field, value)
                return
        if self.visual and not self.source:
            # A part drawn as something with no design behind it: there is
            # nothing for the visual to stand for.
            self.process_error = "'visual:' says what the design is drawn as, and there is no 'source:' design"
            return
        for kind in PROCESSES:
            if kind not in manufacturing_config:
                continue
            try:
                self.processes[kind] = PrintProcess(kind, manufacturing_config.get(kind))
            except ValueError as e:
                self.processes = {}
                self.process_error = str(e)
                return

    @property
    def design(self) -> str | None:
        """What a printed part is a print of, as written, or None where it is its own design.

        Only for `additive`: every other method's `source:` is what goes into
        the machine, which is not a design but a piece of material.
        """
        if self.method != METHOD_ADDITIVE:
            return None
        return self.source or None

    def print_data(self) -> dict | None:
        """What a print service is told about printing this part, or None for anything that is not printed.

        The method, the design it is a print of where it names one, and each
        process' settings *as the part states them*: a service fills in what is
        left out with its own defaults, which are better than PartCAD's guess at
        them (see 'PROCESS_DEFAULTS', which is for working out a weight). None
        as well for a declaration that cannot be read, which is nothing to
        quote: 'pc qual test' is what says why.
        """
        if self.method != METHOD_ADDITIVE or self.process_error:
            return None
        data: dict = {"method": "additive"}
        if self.design:
            data["design"] = self.design
        if self.processes:
            data["processes"] = {
                kind: {key: value for key, value in process.options.items() if key != "desc"}
                for kind, process in sorted(self.processes.items())
            }
        return data

    @property
    def process(self) -> PrintProcess | None:
        """The process a printed part is printed by, where it names exactly one."""
        if len(self.processes) == 1:
            return next(iter(self.processes.values()))
        return None

    def _read_machines(self, manufacturing_config: dict) -> None:
        """Which machines this part could be made on, and the job they share.

        Nothing for a method that is not 'subtractive': a machine is what takes
        material away, and nothing else here does. A sketch is the exception --
        it declares the section with no 'method:' in it, because a drawing is
        not made out of anything, and what it says is the path a machine
        follows.

        A bad declaration is *recorded* rather than raised, the same way
        'missing_fields()' is read rather than raised on. Loading a package must
        not fail over it -- a part whose machine subsection is wrong is still a
        part, and everything that is not about making it goes on working. The
        check is what reports it, against the one part it belongs to.
        """
        if self.method != METHOD_SUBTRACTIVE and not (self.declared_section and self.method == METHOD_NONE):
            # Refused rather than quietly dropped. Nothing here reads a cut from
            # an 'additive' part, so a 'diameter:' written on one is a number
            # somebody chose and nothing acts on -- which is the exact failure
            # the move out of 'cam:' was for, reappearing one level down. A
            # printed part has feeds and speeds too, and the day PartCAD writes
            # a program for a printer they will be a printer's keys under a
            # printer's subsection rather than a router's read by accident.
            stray = [key for key in manufacturing_config if key in SHARED_JOB_KEYS or key in MACHINES]
            if stray:
                self.machine_error = "'method: %s' describes no cut, so it does not take %s" % (
                    self._method_string(),
                    ", ".join("'%s:'" % key for key in sorted(stray)),
                )
            return

        if self.method == METHOD_NONE and MACHINE_CUT in manufacturing_config:
            # A sketch is a path a machine follows, and a saw follows none: it
            # cuts a solid across, which a drawing is not.
            self.machine_error = "'cut:' cuts a solid piece of stock to size, and a drawing is not one"
            return

        shared = {key: value for key, value in manufacturing_config.items() if key in SHARED_JOB_KEYS}
        unknown = [
            key
            for key in manufacturing_config
            if key not in SHARED_JOB_KEYS and key not in MACHINES and key not in _SECTION_KEYS
        ]
        if unknown:
            self.machine_error = "'manufacturing:' does not take %s" % ", ".join(sorted(unknown))
            return
        self.job = shared

        named = [kind for kind in MACHINES if kind in manufacturing_config]
        if not named:
            # The answer that is never wrong, and what every 'subtractive' part
            # written before machines could be named meant: a router does
            # anything the other two do.
            machine = self._read_machine(MACHINE_CNC, None, declared=False)
            if machine is not None:
                self.machines[MACHINE_CNC] = machine
            return

        for kind in named:
            machine = self._read_machine(kind, manufacturing_config.get(kind))
            if machine is None:
                # The first bad subsection is the one reported. A part with two
                # mistakes in it has one to fix first, and naming both says less
                # than naming one clearly.
                self.machines = {}
                return
            self.machines[kind] = machine

    def _read_machine(self, kind: str, config, declared: bool = True) -> MachineConfig | None:
        """One machine subsection, checked against what that machine takes."""
        allowed = machine_keys(kind)
        if config is not None and not isinstance(config, dict):
            self.machine_error = "'%s:' is not a section: %r" % (kind, config)
            return None
        unknown = [key for key in (config or {}) if key not in allowed]
        if unknown:
            self.machine_error = "'%s:' does not take %s; it takes %s" % (
                kind,
                ", ".join(sorted(unknown)),
                ", ".join("'%s:'" % key for key in allowed),
            )
            return None
        try:
            return MachineConfig(kind, config, declared=declared, parameters=self.parameters)
        except ValueError as e:
            # Every message out of 'MachineConfig' already names the machine and
            # the key, so naming the machine again here is how
            # "'cnc:' 'cnc: diameter:' is not a length" gets written.
            self.machine_error = str(e)
            return None

    @property
    def machine(self) -> MachineConfig | None:
        """The machine to use when nobody chose one.

        The single alternative where there is one, and None where the part named
        several -- that is not a default anybody can pick on the part's behalf,
        and 'pc cam' asks rather than guessing. A part that named none has the
        undeclared CNC standing in, which is what 'machines' already holds.
        """
        if len(self.machines) == 1:
            return next(iter(self.machines.values()))
        return None

    def machine_named(self, kind: str) -> MachineConfig | None:
        """One of this part's alternatives by name, or None where it is not one."""
        return self.machines.get(kind)

    def machine_choices(self) -> list[str]:
        """The machines this part says it could be made on, in a stable order."""
        return [kind for kind in MACHINES if kind in self.machines]

    def missing_fields(self) -> list[str]:
        """What this method needs that the declaration does not state.

        Read rather than raised on, because a declaration is judged where the
        judging is done: 'pc qual test' reports it against the one part, while
        loading a package must not fail over it - a part whose 'manufacturing:'
        section is incomplete is still a part, and everything that is not about
        making it goes on working.

        Empty for every method that needs nothing beyond its own name.
        """
        required = {
            METHOD_ADDITIVE: ADDITIVE_REQUIRED,
            METHOD_SHEET_METAL: SHEET_METAL_REQUIRED,
            METHOD_SUBTRACTIVE: SUBTRACTIVE_REQUIRED,
        }.get(self.method, ())
        return [field for field in required if not getattr(self, field, None)]

    def _method_string(self) -> str:
        if self.method in _METHOD_NAMES:
            return _METHOD_NAMES[self.method]
        if self.method == METHOD_NONE:
            return "none"
        return "unknown"

    def __str__(self) -> str:
        return f"PartConfigManufacturing(method={self._method_string()})"
