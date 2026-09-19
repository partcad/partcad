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
MACHINE_DRILL = "drill"
MACHINE_LASER = "laser"
MACHINES = (MACHINE_CNC, MACHINE_DRILL, MACHINE_LASER)

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
# 'toolAxis' is common to all three, because it is the one thing every
# subtractive machine has: the axis the tool, the beam or the drill approaches
# along. It is what "all cut walls are vertical" is measured against -- vertical
# meaning parallel to it -- and it is why a part that is cut from the other side
# is a different part to the machine even though it is the same solid.
#
# Not 'direction', which is the one word this configuration cannot afford to
# reuse: it already means climb or conventional, which way round a contour is
# cut, and both would reach one implementation in one request.
MACHINE_OWN_KEYS: dict[str, tuple] = {
    MACHINE_CNC: ("toolAxis",),
    MACHINE_DRILL: ("toolAxis",),
    # 'kerf' is the width the beam itself removes. It belongs to the machine
    # rather than to the cut because it is a property of that machine and its
    # material, and because the check that the part fits its stock has to know
    # it: a part cut to its nominal outline comes off a laser half a kerf small
    # all round.
    MACHINE_LASER: ("toolAxis", "kerf"),
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
}

# Two keys every machine takes, because they are about the route rather than
# about the cut: who writes it, and what it is.
MACHINE_ROUTE_KEYS = ("implementation", "desc")


def machine_keys(kind: str) -> tuple:
    """Every key one machine's subsection may hold."""
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
        """Read one machine subsection.

        Raises:
            ValueError: the axis is not one of the six, or a length is not a
                length. Raised rather than recorded because the caller --
                '_read_machine' -- is what turns either into the 'machine_error'
                a check reports, and it adds the machine's name on the way.
        """
        self.kind = kind
        self.declared = declared
        self.options = dict(config or {})
        self.tool_axis = str(self.options.pop("toolAxis", None) or DEFAULT_TOOL_AXIS)
        try:
            self.vector = tool_axis_vector(self.tool_axis)
        except ValueError as e:
            # Named here rather than by the caller, so that every message out of
            # this class says which machine and which key without the caller
            # having to guess which of them already did.
            raise ValueError("'%s: toolAxis:' %s" % (kind, e)) from e
        # Every value read the way PartCAD reads that kind of value, so "6",
        # "6 mm" and "0.25 in" are one cutter. 'CamConfigError' is a
        # 'ValueError', which is what the caller already catches to turn a bad
        # number into a recorded message rather than a package that will not
        # load.
        for key, parse in pc_cam.value_parsers().items():
            if self.options.get(key) is not None:
                self.options[key] = parse(self.options[key], "'%s: %s:'" % (kind, key))

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
        data = {"machine": self.kind, "tool_axis": self.tool_axis, "tool_axis_vector": list(self.vector)}
        own = MACHINE_OWN_KEYS[self.kind]
        data.update({key: value for key, value in self.options.items() if key in own and value is not None})
        return data

    def __str__(self) -> str:
        """The machine and its axis, which are what distinguish two of these."""
        return "MachineConfig(kind=%s, toolAxis=%s)" % (self.kind, self.tool_axis)


class PartConfigManufacturing:
    method: int | None

    # The part that is worked on, and the sketch that says how, for the methods
    # that are defined in terms of another object. None for every other method,
    # which describes a part made from stock and has nothing to point at.
    source: str | None
    instructions: str | None

    def __init__(self, final_config: dict) -> None:
        """Read a part's 'manufacturing:' section, without refusing any of it.

        Nothing here raises. An unknown method is logged and read as none, and a
        machine subsection that cannot be made sense of is recorded in
        'machine_error' -- because loading a package must not fail over one
        part's declaration, and a part whose manufacturing section is wrong is
        still a part that can be listed, rendered and exported. What is wrong
        with it is 'pc test's to report, against the part it belongs to.
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
        self.machine_error: str | None = None
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
        self._read_machines(manufacturing_config)

    def _read_machines(self, manufacturing_config: dict) -> None:
        """Which machines this part could be made on, and the job they share.

        Nothing for a method that is not 'subtractive': a machine is what takes
        material away, and nothing else here does.

        A bad declaration is *recorded* rather than raised, the same way
        'missing_fields()' is read rather than raised on. Loading a package must
        not fail over it -- a part whose machine subsection is wrong is still a
        part, and everything that is not about making it goes on working. The
        check is what reports it, against the one part it belongs to.
        """
        if self.method != METHOD_SUBTRACTIVE and not (self.declared_section and self.method == METHOD_NONE):
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
            return MachineConfig(kind, config, declared=declared)
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
