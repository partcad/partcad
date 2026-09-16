#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

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

# The machines a `subtractive` part may be made on, and which one a declaration
# means.
#
# Subtraction is one idea -- material is taken away from a piece of stock until
# what is left is the part -- but the machines that do it are not
# interchangeable, and what they *cannot* do is the useful thing to know. A
# router will cut any 2.5D shape; a laser cuts a sheet with a beam that does not
# tilt; a drill makes round holes and nothing else. So the machine decides which
# `pc test` check applies and what `pc cam` writes.
#
# It is named by adding that machine's own subsection rather than by a `machine:`
# key, because the machines do not take the same options and a key would leave
# them all in one namespace with nothing to say which belongs to which. A
# declaration with none of them is a CNC one: that is the machine that can make
# anything the other two can, so it is the answer that is never wrong, and it is
# what every `subtractive` part written before this existed meant.
MACHINE_CNC = "cnc"
MACHINE_DRILLING = "drilling"
MACHINE_LASER = "laser"
MACHINES = (MACHINE_CNC, MACHINE_DRILLING, MACHINE_LASER)

# What each machine's subsection may hold. A closed set for the reason
# 'partcad.cam.KEYS' is one: a key that is not in it is a typo, and a typo that
# is passed through is an option nobody set being silently defaulted.
#
# 'toolAxis' is common to all three, because it is the one thing every
# subtractive machine has: the axis the tool, the beam or the drill approaches
# along. It is what "all cut walls are vertical" is measured against -- vertical
# meaning parallel to it -- and it is why a part that is cut from the other side
# is a different part to the machine even though it is the same solid.
#
# Not 'direction', which is the one word this configuration cannot afford to
# reuse: an object's 'cam:' section already has a 'direction' and it means
# something else entirely (climb or conventional, which way round a contour is
# cut). Both would reach one implementation in one request.
MACHINE_KEYS: dict[str, tuple] = {
    MACHINE_CNC: ("toolAxis",),
    MACHINE_DRILLING: ("toolAxis",),
    # 'kerf' is the width the beam itself removes. It belongs to the machine
    # rather than to the route because it is a property of that machine and its
    # material, and because the check that the part fits its stock has to know
    # it: a part cut to its nominal outline comes off a laser half a kerf small
    # all round.
    MACHINE_LASER: ("toolAxis", "kerf"),
}

# The machine options that are lengths, and so are read the way every other
# length in PartCAD is: a bare number is millimetres, and "0.008 in" is the same
# kerf said differently. Parsed here rather than left to the implementation for
# the reason 'partcad.cam.normalize_job' exists -- the spelling is PartCAD's to
# understand at every layer, and the implementation's business is numbers.
MACHINE_LENGTH_KEYS = ("kerf",)

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

    def __init__(self, kind: str, config: dict | None, declared: bool = True) -> None:
        self.kind = kind
        self.declared = declared
        self.options = dict(config or {})
        self.tool_axis = str(self.options.pop("toolAxis", None) or DEFAULT_TOOL_AXIS)
        self.vector = tool_axis_vector(self.tool_axis)
        for key in MACHINE_LENGTH_KEYS:
            if self.options.get(key) is not None:
                # 'CamConfigError' is a 'ValueError', which is what the caller
                # already catches to turn a bad axis into a recorded
                # message rather than a package that will not load.
                self.options[key] = pc_cam.parse_length(self.options[key], "'%s:'" % key)

    def get(self, key: str, default=None):
        """One machine option, or 'default' where the subsection did not say."""
        value = self.options.get(key)
        return default if value is None else value

    def to_data(self) -> dict:
        """This machine as the parameters an implementation is handed.

        The kind and the axis always, because every implementation needs to
        know what it is writing for and which way is down; the rest as the part
        wrote it.
        """
        data = {"machine": self.kind, "tool_axis": self.tool_axis, "tool_axis_vector": list(self.vector)}
        data.update({key: value for key, value in self.options.items() if value is not None})
        return data

    def __str__(self) -> str:
        return "MachineConfig(kind=%s, toolAxis=%s)" % (self.kind, self.tool_axis)


class PartConfigManufacturing:
    method: int | None

    # The part that is worked on, and the sketch that says how, for the methods
    # that are defined in terms of another object. None for every other method,
    # which describes a part made from stock and has nothing to point at.
    source: str | None
    instructions: str | None

    def __init__(self, final_config: dict) -> None:
        manufacturing_config = final_config.get("manufacturing", {}) or {}
        method_string = manufacturing_config.get("method", None)
        self.method = _METHOD_MAP.get(method_string, METHOD_NONE)
        if self.method == METHOD_NONE and method_string is not None:
            pc_logging.error(
                f"Unknown manufacturing method '{method_string}'. Supported methods: {list(_METHOD_MAP.keys())}."
            )
        self.source = manufacturing_config.get("source", None)
        self.instructions = manufacturing_config.get("instructions", None)
        self.machine_error: str | None = None
        self.machine = self._read_machine(manufacturing_config)

    def _read_machine(self, manufacturing_config: dict) -> MachineConfig | None:
        """Which machine this part is subtracted on, from the subsection naming it.

        None for every method that is not 'subtractive': a machine is what takes
        material away, and nothing else here does.

        A bad declaration is *recorded* rather than raised, the same way
        'missing_fields()' is read rather than raised on. Loading a package must
        not fail over it -- a part whose machine subsection is wrong is still a
        part, and everything that is not about making it goes on working. The
        check is what reports it, against the one part it belongs to.
        """
        if self.method != METHOD_SUBTRACTIVE:
            return None

        named = [kind for kind in MACHINES if kind in manufacturing_config]
        if len(named) > 1:
            self.machine_error = "it is made on one machine, but names %s" % " and ".join(
                "'%s:'" % kind for kind in named
            )
            return None
        if not named:
            # The answer that is never wrong, and what every 'subtractive' part
            # written before machines existed meant.
            return MachineConfig(MACHINE_CNC, None, declared=False)

        kind = named[0]
        config = manufacturing_config.get(kind)
        if config is not None and not isinstance(config, dict):
            self.machine_error = "'%s:' is not a section: %r" % (kind, config)
            return None
        unknown = [key for key in (config or {}) if key not in MACHINE_KEYS[kind]]
        if unknown:
            self.machine_error = "'%s:' does not take %s; it takes %s" % (
                kind,
                ", ".join(sorted(unknown)),
                ", ".join("'%s:'" % key for key in MACHINE_KEYS[kind]),
            )
            return None
        try:
            return MachineConfig(kind, config)
        except ValueError as e:
            # Both the axis and the lengths raise ValueError, and each already
            # names the key it is about, so this adds the machine and nothing
            # else. Naming a key here as well is how "'laser: toolAxis:'
            # 'laser: kerf:' is not a length" gets written.
            self.machine_error = "'%s:' %s" % (kind, e)
            return None

    def missing_fields(self) -> list[str]:
        """What this method needs that the declaration does not state.

        Read rather than raised on, because a declaration is judged where the
        judging is done: 'pc test' reports it against the one part, while
        loading a package must not fail over it - a part whose 'manufacturing:'
        section is incomplete is still a part, and everything that is not about
        making it goes on working.

        Empty for every method that needs nothing beyond its own name.
        """
        required = {
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
