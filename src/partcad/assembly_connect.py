#
# OpenVMP, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The non-geometric half of a connection declared in an ASSY file.

The 'connect' and 'connectPorts' sections say *where* an object ends up. The
two sections handled here say *how* the assembler is expected to get it there
('how') and carry free-form context that nothing in the toolchain acts upon
('comment').

'comment' is supplementary context for a human or an LLM reading the assembly.
It is never parsed and never required to assemble anything: every instruction
that the assembler needs must be codified in the other ASSY fields.

'how' says which *tools* the step is performed with, too. 'holdWith', 'holdTo'
and 'driver' each map a mechanical tool (see 'partcad.tool') to the places on
the object that tool acts on, so that "hold the screw by its head with a finger
and turn it with a hex driver" is data rather than a sentence in 'comment'. The
places are interface instances the object already declares, which is what makes
them locations as well as names: an assembly instruction book draws the tool at
the port of the instance it holds.
"""

import math
import typing

from . import logging as pc_logging

# 'how' defaults. See 'docs/source/assy.rst' for the units and the semantics.
# The units are SI, except for lengths, which are in millimetres like everywhere
# else in PartCAD. A push is a linear force (N); a turn is a torque (N*m).
DEFAULT_PUSH_FORCE_MAX = 5.0  # N
DEFAULT_TURN_DIRECTION = "cw"  # clockwise
DEFAULT_TURN_TORQUE_MAX = 0.0  # N*m
DEFAULT_THREAD_STEP = 0.0  # mm

# 'pushDistance' has no fixed default: it is derived from the object that is
# being connected, as this multiple of its own length along the Z axis of the
# interface that it is connected by.
PUSH_DISTANCE_FACTOR = 1.5

DEFAULT_HOLD_FORCE_MIN = 3.0  # N
DEFAULT_HOLD_FORCE_MAX = 7.0  # N

TURN_DIRECTION_CW = "cw"
TURN_DIRECTION_CCW = "ccw"
TURN_DIRECTIONS = (TURN_DIRECTION_CW, TURN_DIRECTION_CCW)

# The fields of 'how' that are recognized. Anything else is a typo worth reporting.
HOW_FIELDS = (
    "stage",
    "pushForceMax",
    "pushDistance",
    "turnDirection",
    "turnTorqueMax",
    "threadStep",
    "holdWith",
    "holdWithInstance",
    "holdWithForce",
    "holdWithForceMin",
    "holdWithForceMax",
    "holdTo",
    "holdToInstance",
    "holdToForce",
    "holdToForceMin",
    "holdToForceMax",
    "driver",
    "holdUntil",
    "holdUntilStage",
)

# What a connection does to the object it adds. A push is a straight insertion;
# a screw is turned in, which is the only kind of connection a 'driver' means
# anything for. Which of the two it is follows from 'turnTorqueMax': a
# connection nothing is asked to turn is not a screwed one.
METHOD_PUSH = "push"
METHOD_SCREW = "screw"

# Fields that were renamed, and the field that replaces each of them. They are
# still accepted, so that the ASSY files written against the earlier spelling
# keep working, but they are reported so that they can be fixed.
HOW_FIELDS_DEPRECATED = {
    # A push is a force, not a torque: the value is in newtons either way, but
    # the name said otherwise.
    "pushTorqueMax": "pushForceMax",
}

# The 'connect:' subsection of a part or an assembly in 'partcad.yaml': what
# that object contributes to every connection it takes part in, and what the
# 'holdWith*'/'holdTo*' fields inherit when the ASSY file does not give one.
CONFIG_CONNECT = "connect"
CONFIG_HOLD = "hold"
CONFIG_HOLD_INSTANCE = "holdInstance"
CONFIG_HOLD_FORCE = "holdForce"
CONFIG_HOLD_FORCE_MIN = "holdForceMin"
CONFIG_HOLD_FORCE_MAX = "holdForceMax"

# The fields that subsection may carry. Anything else is a typo worth reporting.
CONNECT_FIELDS = (
    CONFIG_HOLD,
    CONFIG_HOLD_INSTANCE,
    CONFIG_HOLD_FORCE,
    CONFIG_HOLD_FORCE_MIN,
    CONFIG_HOLD_FORCE_MAX,
)


def connect_config(item, where: str = None):
    """The 'connect:' subsection of a part or assembly definition, or an empty one."""
    config = getattr(item, "config", None) or {}
    if not isinstance(config, dict):
        return {}
    section = config.get(CONFIG_CONNECT, None)
    if section is None:
        return {}
    if not isinstance(section, dict):
        pc_logging.error("%s: 'connect' must be a section, ignoring: %s" % (where or "connect", section))
        return {}
    for field in section.keys():
        if field not in CONNECT_FIELDS:
            pc_logging.error("%s: unknown 'connect' field, ignoring: %s" % (where or "connect", field))
    return section


def _as_number(value, field, where):
    """The value as a non-negative float, or None with the problem reported."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        pc_logging.error("%s: '%s' must be a number, using the default: %s" % (where, field, value))
        return None
    if value < 0.0:
        pc_logging.error("%s: '%s' must not be negative, using the default: %s" % (where, field, value))
        return None
    return float(value)


def _push_direction(mated_frame):
    """The direction an object travels while it is pushed into place.

    'mated_frame' is the interface the object is connected by, once the object
    is in place, in the assembly's coordinates. The connection puts that frame
    face to face with the target's - 'assembly_factory_assy' turns the object
    around to mate the two - so the object arrives travelling along the frame's
    **negative** Z axis, which is the target interface's positive Z.

    That the positive Z of an interface points into the object it belongs to is
    what the examples encode: 'examples/feature_interface' places both faces of
    the same 3mm bracket as instances of one interface, the 'outer' one at z=0
    unrotated and the 'inner' one at z=3 turned around, so the two axes point at
    each other through the material. A screw connected to either face therefore
    travels along that face's positive Z to get in.
    """
    if mated_frame is None:
        return None
    axis = mated_frame.rotate_vector((0.0, 0.0, -1.0))
    length = math.sqrt(sum(value * value for value in axis))
    if length == 0.0:
        return None
    # Rounded because the quaternion math leaves 1e-17 dust on the components
    # that are meant to be zero, and this ends up in the assembly's documents.
    unit = [round(value / length, 12) for value in axis]
    return tuple(0.0 if value == 0.0 else value for value in unit)


def _as_list(value):
    """Normalize a scalar-or-list configuration value into a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    return [value]


class ConnectHold:
    """One place on an object a tool acts on while the connection is made.

    'interface' and 'instance' say where - an instance of an interface the
    object implements - and 'ports' are the ports of that instance, which is
    what turns the name into a location: a document drawing the tool puts it at
    one of them.

    'tool' is the tool that acts there, when the ASSY file named one. It is None
    for a hold that only says which interface to hold by and leaves the choice
    of tool to whoever performs the assembly, which is what every 'holdWith' and
    'holdTo' meant before tools existed and what an object's own 'hold' still
    means.
    """

    def __init__(self, interface: str, instance=None, tool: str = None, ports=None):
        self.interface = interface
        self.instance = instance
        self.tool = tool
        self.ports = list(ports) if ports else []

    def info(self):
        info = {"interface": self.interface, "instance": self.instance}
        if self.tool is not None:
            info["tool"] = self.tool
        if self.ports:
            info["ports"] = list(self.ports)
        return info

    def __eq__(self, other):
        if not isinstance(other, ConnectHold):
            return NotImplemented
        return self.interface == other.interface and self.instance == other.instance and self.tool == other.tool

    def __repr__(self):
        where = self.interface if not self.instance else "%s[%s]" % (self.interface, self.instance)
        if self.tool is None:
            return str(where)
        return "%s with %s" % (where, self.tool)


class ConnectHow:
    """The 'how' section of a 'connect' or 'connectPorts' node.

    Everything here is optional in the ASSY file: an omitted field, and an
    omitted 'how' section altogether, mean the documented default.

    Units: 'pushForceMax' is a linear force in newtons (N), 'turnTorqueMax' is a
    torque in newton-metres (N*m), and 'threadStep' is a length in millimetres
    (mm), matching the length unit used everywhere else in PartCAD.
    """

    def __init__(self, config=None, where: str = "connect"):
        self.where = where
        self.specified = config is not None

        if config is None:
            config = {}
        elif not isinstance(config, dict):
            pc_logging.error("%s: 'how' must be a section, ignoring: %s" % (where, config))
            config = {}

        config = dict(config)
        for old_field, new_field in HOW_FIELDS_DEPRECATED.items():
            if old_field not in config:
                continue
            pc_logging.warning("%s: 'how.%s' is deprecated, use 'how.%s'" % (where, old_field, new_field))
            # The new spelling wins if the file happens to carry both.
            config.setdefault(new_field, config.pop(old_field))

        for field in config.keys():
            if field not in HOW_FIELDS:
                pc_logging.error("%s: unknown 'how' field, ignoring: %s" % (where, field))

        self.stage = self._stage(config)
        self.push_force_max = self._number(config, "pushForceMax", DEFAULT_PUSH_FORCE_MAX)
        self.turn_direction = self._turn_direction(config)
        self.turn_torque_max = self._number(config, "turnTorqueMax", DEFAULT_TURN_TORQUE_MAX)
        # 'threadStep' is inherited from the interfaces being connected when the
        # ASSY file does not give one: see 'resolve()'.
        declared_thread_step = self._number(config, "threadStep", None)
        self.thread_step_specified = declared_thread_step is not None
        self.thread_step = DEFAULT_THREAD_STEP if declared_thread_step is None else declared_thread_step

        # 'pushDistance' is derived from the object's own geometry when the ASSY
        # file does not give it. That needs a CAD runtime, which instantiating an
        # assembly otherwise does not, so it is left for 'resolve_push_distance()'
        # to fill in on demand rather than computed here.
        self.push_distance = self._number(config, "pushDistance", None)
        self.push_distance_specified = self.push_distance is not None
        self._push_item = None
        self._push_frame = None

        # The direction the object travels while it is pushed into place, in the
        # assembly's coordinates. Deduced from the connection: see 'resolve()'.
        self.push_direction = None

        # What the connection does to the object it adds. Not a field of its
        # own: a connection nothing is asked to turn is a straight push, and one
        # that is turned is screwed in. It is what decides whether a 'driver'
        # means anything here.
        self.method = METHOD_SCREW if self.turn_torque_max > 0.0 else METHOD_PUSH

        # The requested holds, before they are matched against the objects being
        # connected. 'resolve()' turns these into 'ConnectHold' lists.
        #
        # Two spellings, and they are told apart by shape rather than by a flag.
        # A mapping is the tool form - '{<tool>: [<where it acts>, ...]}' - and
        # a string or a list of them is the older one, naming interfaces and
        # leaving the tool to whoever performs the assembly. 'driver' has no
        # older spelling, so a bare string there is a tool with nothing said
        # about where it acts.
        self._hold_with_tools = self._tool_spec(config, "holdWith")
        self._hold_to_tools = self._tool_spec(config, "holdTo")
        self._driver_tools = self._tool_spec(config, "driver", tools_only=True)

        self._hold_with_spec = [] if self._hold_with_tools is not None else _as_list(config.get("holdWith", None))
        self._hold_with_instance_spec = _as_list(config.get("holdWithInstance", None))
        self._hold_to_spec = [] if self._hold_to_tools is not None else _as_list(config.get("holdTo", None))
        self._hold_to_instance_spec = _as_list(config.get("holdToInstance", None))

        for field, tools, instances in (
            ("holdWith", self._hold_with_tools, self._hold_with_instance_spec),
            ("holdTo", self._hold_to_tools, self._hold_to_instance_spec),
        ):
            if tools is not None and instances:
                pc_logging.error(
                    "%s: 'how.%sInstance' says nothing next to the tool form of 'how.%s', ignoring"
                    % (self.where, field, field)
                )

        self.hold_with: list[ConnectHold] = []
        self.hold_to: list[ConnectHold] = []
        # Where the tool that turns the object acts, once resolved. Empty for a
        # connection that names none, and for one that is pushed rather than
        # screwed in - see 'method' above.
        self.driver: list[ConnectHold] = []

        # The holding forces, before the object-level defaults are folded in.
        self._hold_force_spec = {
            "holdWith": (
                config.get("holdWithForceMin", None),
                config.get("holdWithForceMax", None),
                config.get("holdWithForce", None),
            ),
            "holdTo": (
                config.get("holdToForceMin", None),
                config.get("holdToForceMax", None),
                config.get("holdToForce", None),
            ),
        }
        self.hold_with_force_min = DEFAULT_HOLD_FORCE_MIN
        self.hold_with_force_max = DEFAULT_HOLD_FORCE_MAX
        self.hold_to_force_min = DEFAULT_HOLD_FORCE_MIN
        self.hold_to_force_max = DEFAULT_HOLD_FORCE_MAX
        self.hold_force_specified = False

        # What makes these instructions invalid, for 'pc test' to report. Every
        # one of them is also repaired in place, so that an assembly still
        # builds; the list is what says the repair happened.
        #
        # Seeded from the problems the declaration itself has, which are found
        # here rather than in 'resolve()' - that method starts the list over
        # every time it runs, and a contradiction between two fields is a fact
        # about the file that no amount of resolving changes.
        self._declared_problems: list[str] = []
        self.problems: list[str] = []

        # How long the hold declared on this step lasts. Without either field it
        # lasts for this step alone, which is what a hold meant before these
        # existed. 'holdUntil' names a later step by its 'name:'; 'holdUntilStage'
        # names a stage, and the hold lasts to the last step of it. Both are
        # inclusive: the step that ends the hold is the last one performed with
        # it still on.
        self.hold_until = self._name(config, "holdUntil")
        self.hold_until_stage = self._name(config, "holdUntilStage")
        if self.hold_until is not None and self.hold_until_stage is not None:
            self._declare_problem(
                "'holdUntil' and 'holdUntilStage' are two ways of saying the same thing;"
                " using 'holdUntil' (%s) and ignoring 'holdUntilStage' (%s)" % (self.hold_until, self.hold_until_stage)
            )
            self.hold_until_stage = None

        # The steps this hold carries through, resolved against the rest of the
        # assembly once every one of them is known: see 'resolve_hold_until()'.
        # Empty for a hold that ends with its own step.
        self.hold_until_steps: list[str] = []
        # The last step the hold covers, as an index into the assembly's own
        # children. None until it is resolved, and for a hold that ends with its
        # own step - which an instruction book reads as "not carried".
        self.hold_until_last: typing.Optional[int] = None

    def _number(self, config, field, default):
        value = config.get(field, None)
        if value is None:
            return default
        number = _as_number(value, "how." + field, self.where)
        return default if number is None else number

    def _stage(self, config):
        value = config.get("stage", None)
        if value is None:
            return None
        if isinstance(value, str) and value != "":
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # A stage is a label, not a quantity, but a bare number in YAML is a
            # natural thing to write and unambiguous to name.
            return str(value)
        pc_logging.error("%s: 'how.stage' must be a non-empty string, ignoring: %s" % (self.where, value))
        return None

    def _name(self, config, field):
        """A field naming something else in the assembly, or None.

        A step's name and a stage's are both labels, so a bare number in YAML is
        as good a name as a word and is read as one - the same rule 'how.stage'
        itself follows.
        """
        value = config.get(field, None)
        if value is None:
            return None
        if isinstance(value, str) and value != "":
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        pc_logging.error("%s: 'how.%s' must be a non-empty string, ignoring: %s" % (self.where, field, value))
        return None

    def _declare_problem(self, message):
        """Record what is wrong with the declaration itself, and report it.

        Kept apart from 'problems' because 'resolve()' clears that list every
        time it runs and these findings do not depend on what is being connected.
        They are copied back in at the start of each resolution, unlogged: this
        is where they were reported.
        """
        self._declared_problems.append(message)
        pc_logging.error("%s: %s" % (self.where, message))

    def _tool_spec(self, config, field, tools_only=False):
        """The '{tool: [where it acts]}' mapping of one field, or None.

        None means the field is not in the tool form at all: absent, or written
        the older way as an interface name or a list of them. That distinction
        is the whole point of the method - a caller that gets None falls through
        to the interface form, and one that gets a mapping (empty included)
        does not.

        'tools_only' is for 'driver', which has no older spelling: a bare string
        there names the tool, with nothing said about where it acts, and a list
        of strings names several.
        """
        value = config.get(field, None)
        if value is None:
            return None

        if isinstance(value, dict):
            spec = {}
            for tool, where in value.items():
                if not isinstance(tool, str) or not tool.strip():
                    pc_logging.error("%s: 'how.%s' must be keyed by tool, ignoring: %s" % (self.where, field, tool))
                    continue
                spec[tool.strip()] = _as_list(where)
            return spec

        if tools_only:
            spec = {}
            for tool in _as_list(value):
                if not isinstance(tool, str) or not tool.strip():
                    pc_logging.error("%s: 'how.%s' must name a tool, ignoring: %s" % (self.where, field, tool))
                    continue
                # No list of places: every place the tool mates to, which is what
                # an empty list means in the mapping form as well.
                spec[tool.strip()] = []
            return spec

        return None

    def _turn_direction(self, config):
        value = config.get("turnDirection", None)
        if value is None:
            return DEFAULT_TURN_DIRECTION
        if isinstance(value, str) and value.lower() in TURN_DIRECTIONS:
            return value.lower()
        pc_logging.error(
            "%s: 'how.turnDirection' must be one of %s, using the default: %s"
            % (self.where, str(list(TURN_DIRECTIONS)), value)
        )
        return DEFAULT_TURN_DIRECTION

    def resolve(
        self,
        source_item=None,
        target_item=None,
        source_frame=None,
        mated_frame=None,
        source_interface=None,
        target_interface=None,
        ctx=None,
    ):
        """Match the requested holds against the objects that are being connected.

        'source_item' is the object that is being added to the assembly (the
        'with' end), 'target_item' is the object it is connected to (the 'to'
        end). Either may be missing, in which case that end is resolved as far
        as the ASSY file alone allows.

        'source_frame' is the placement of the interface that the source object
        is connected by, in that object's own coordinates. It is what a derived
        'pushDistance' is measured along, and is remembered rather than used
        here: see 'resolve_push_distance()'.

        'mated_frame' is that same interface once the object is in place, in the
        assembly's coordinates. It is what the push direction is deduced from.

        'source_interface' and 'target_interface' are the two interface objects
        being mated. They are what an unspecified 'threadStep' is inherited from.

        'ctx' is what the tools named by 'holdWith'/'holdTo'/'driver' are looked
        up in. Without it the tool form still resolves to the places it names,
        but nothing is known about the tools themselves - so a tool that only
        said which object it acts on ('holdWith: {//builtin:finger: []}') has
        nothing to enumerate, and neither a missing tool nor one that cannot
        turn anything is reported. Every caller that has a context passes it;
        the parameter is optional so that the field can be read from a
        configuration alone.
        """
        self.problems = list(self._declared_problems)
        self._push_item = source_item
        self._push_frame = source_frame
        self.push_direction = _push_direction(mated_frame)
        self._resolve_thread_step(source_interface, target_interface)

        if self._hold_with_tools is not None:
            self.hold_with = self._resolve_tool_holds(self._hold_with_tools, source_item, "holdWith", ctx)
        else:
            self.hold_with = _resolve_holds(
                self._hold_with_spec,
                self._hold_with_instance_spec,
                source_item,
                self.where,
                "holdWith",
            )
        if self._hold_to_tools is not None:
            self.hold_to = self._resolve_tool_holds(self._hold_to_tools, target_item, "holdTo", ctx)
        else:
            self.hold_to = _resolve_holds(
                self._hold_to_spec,
                self._hold_to_instance_spec,
                target_item,
                self.where,
                "holdTo",
            )
        self.driver = self._resolve_driver(source_item, ctx)

        specified = False
        for side, item in (("holdWith", source_item), ("holdTo", target_item)):
            minimum, maximum, was_specified = self._hold_force(side, item)
            specified = specified or was_specified
            if side == "holdWith":
                self.hold_with_force_min, self.hold_with_force_max = minimum, maximum
            else:
                self.hold_to_force_min, self.hold_to_force_max = minimum, maximum
        self.hold_force_specified = specified
        return self

    def _resolve_tool_holds(self, spec, item, field, ctx, must_drive=False):
        """Turn '{tool: [where it acts]}' into the places on 'item' it acts on.

        Each place is either an instance name on its own, or the pair
        '[<interface>, <instance>]' for an object that names one instance in two
        interfaces. An empty list is not "nowhere": it asks for **every** place
        the tool mates to, which is what makes the common case - hold this by
        whatever a finger fits - a line with nothing in it to keep up to date as
        the object grows another grip.

        'must_drive' holds the tools to being able to turn what they hold, which
        is what a 'driver' is. Checked here rather than by the caller so that
        each tool is looked up once and a tool that does not resolve is reported
        once.
        """
        available = _item_interfaces(item)
        where = _item_name(item) or "the object"

        holds = []
        for tool_ref, places in spec.items():
            tool = self._tool(tool_ref, field, ctx)
            if must_drive and tool is not None and not tool.can_drive():
                self._problem("'%s': %s cannot turn anything ('torqueMax' is zero)" % (field, tool_ref))

            # What the tool says it meets an object through, matched against
            # what this object implements. A tool that said nothing - and one
            # PartCAD could not find - constrains nothing, and every interface
            # the object has is a candidate.
            candidates = _tool_interfaces(tool, available, item)
            constrained = bool(getattr(tool, "mates", None))

            if not places:
                enumerated = _enumerate_instances(
                    tool_ref, candidates if constrained else list(available.keys()), available
                )
                if not enumerated:
                    self._problem("'%s': %s does not meet %s anywhere" % (field, tool_ref, where))
                holds += enumerated
                continue

            for place in places:
                hold = self._resolve_place(place, tool_ref, candidates, constrained, available, where, field)
                if hold is not None:
                    holds.append(hold)
        return holds

    def _resolve_place(self, place, tool_ref, candidates, constrained, available, where, field):
        """One entry of a tool's list of places, as a 'ConnectHold'."""
        interface = None
        if isinstance(place, (list, tuple)):
            if len(place) != 2 or not all(isinstance(part, str) for part in place):
                self._problem("'%s': a place is an instance name or [interface, instance], not %r" % (field, place))
                return None
            interface, instance = place[0], place[1]
        elif isinstance(place, str):
            instance = place
        else:
            self._problem("'%s': a place is an instance name or [interface, instance], not %r" % (field, place))
            return None

        if interface is not None:
            matched = _match_interface(interface, available)
            if matched is None:
                if available:
                    self._problem("'%s': the object does not implement the interface: %s" % (field, interface))
                matched = interface
        else:
            # Only the instance was named. It has to belong to one of the
            # interfaces the tool meets the object through, and to exactly one
            # of them: the same name under two of them is a place this cannot
            # pick between, and guessing would put the tool somewhere the author
            # did not mean.
            search = candidates if constrained else list(available.keys())
            owners = [name for name in search if instance in (available.get(name) or {})]
            if not owners:
                if available:
                    self._problem(
                        "'%s': %s has no such instance for %s to act on: %s" % (field, where, tool_ref, instance)
                    )
                return ConnectHold(None, instance, tool=tool_ref)
            if len(owners) > 1:
                self._problem(
                    "'%s': the instance '%s' belongs to more than one interface (%s); name the interface as well"
                    % (field, instance, ", ".join(sorted(owners)))
                )
            matched = owners[0]

        return ConnectHold(matched, instance, tool=tool_ref, ports=_instance_ports(available, matched, instance))

    def _resolve_driver(self, source_item, ctx):
        """Where the tool that turns the object acts, or nothing.

        'driver' belongs to a connection that is screwed in. On one that is
        pushed there is nothing to turn, so a 'driver' there is a contradiction
        rather than an unused field: it is reported, and dropped.
        """
        if self._driver_tools is None:
            return []
        if self.method != METHOD_SCREW:
            self._problem(
                "'driver' applies to a connection that is turned in, and this one is pushed"
                " ('turnTorqueMax' is zero)"
            )
            return []

        return self._resolve_tool_holds(self._driver_tools, source_item, "driver", ctx, must_drive=True)

    def _tool(self, tool_ref, field, ctx):
        """The tool a reference names, with what is wrong with it reported.

        None whenever the tool cannot be had - there is no context to look it up
        in, the reference resolves to nothing, or what it resolves to is not a
        mechanical tool. The places the ASSY file named are still honoured in
        that case: what the author wrote about this step is not made worthless
        by a tool PartCAD could not find.
        """
        if ctx is None:
            return None
        from .tool import MechanicalTool

        tool = ctx.get_tool(tool_ref, quiet=True)
        if tool is None:
            self._problem("'%s': the tool is not found: %s" % (field, tool_ref))
            return None
        if not isinstance(tool, MechanicalTool):
            self._problem(
                "'%s': %s is a '%s' tool; only a mechanical one holds or turns anything"
                % (field, tool_ref, tool.category)
            )
            return None
        return tool

    def _resolve_thread_step(self, source_interface, target_interface):
        """Inherit 'threadStep' from the interfaces, and check that they agree.

        Two interfaces that are screwed together have to share a thread, unless
        one of them cuts its own - a self-tapping screw, or the plain hole it
        goes into. When they disagree and neither does, the connection cannot be
        made as described, so it is reported and the thread is left unset.
        """
        ends = []
        for side, interface in (("with", source_interface), ("to", target_interface)):
            if interface is None:
                continue
            step = interface.get_thread_step() if hasattr(interface, "get_thread_step") else None
            self_screw = bool(interface.get_self_screw()) if hasattr(interface, "get_self_screw") else False
            ends.append((side, None if step is None else float(step), self_screw))

        declared = {side: step for side, step, _ in ends if step is not None}
        cuts_its_own = any(self_screw for _, _, self_screw in ends)
        if len(set(declared.values())) > 1 and not cuts_its_own:
            self._problem(
                "the interfaces disagree about 'threadStep' (%s) and neither declares 'selfScrew'"
                % ", ".join("%s: %s" % (side, step) for side, step in sorted(declared.items()))
            )
            return

        if self.thread_step_specified:
            # What the ASSY file says about this one connection wins.
            return

        # The thread of the end that has to match one is the thread that gets
        # cut; failing that, the one the self-tapping end brings with it. The
        # object being added comes first, so a screw defines the thread of the
        # plain hole it goes into rather than the other way round.
        matched = [step for _, step, self_screw in ends if step is not None and not self_screw]
        brought = [step for _, step, _ in ends if step is not None]
        candidates = matched or brought
        if candidates:
            self.thread_step = candidates[0]

    def _problem(self, message):
        """Record what makes these instructions invalid, and report it."""
        self.problems.append(message)
        pc_logging.error("%s: %s" % (self.where, message))

    def _hold_force(self, side, item):
        """The force range to hold one end of the connection with, in newtons.

        The ASSY file wins over the object's own definition, and the bound
        specific field ('...Min'/'...Max') wins over the one that sets both at
        once. Failing all four, the documented defaults apply.
        """
        how_min, how_max, how_both = self._hold_force_spec[side]
        config = connect_config(item, self.where)
        object_both = (config.get(CONFIG_HOLD_FORCE, None), CONFIG_HOLD_FORCE)
        how_both = (how_both, "how.%sForce" % side)

        minimum, min_specified = self._first_number(
            [
                (how_min, "how.%sForceMin" % side),
                how_both,
                (config.get(CONFIG_HOLD_FORCE_MIN, None), CONFIG_HOLD_FORCE_MIN),
                object_both,
            ],
            DEFAULT_HOLD_FORCE_MIN,
        )
        maximum, max_specified = self._first_number(
            [
                (how_max, "how.%sForceMax" % side),
                how_both,
                (config.get(CONFIG_HOLD_FORCE_MAX, None), CONFIG_HOLD_FORCE_MAX),
                object_both,
            ],
            DEFAULT_HOLD_FORCE_MAX,
        )

        if minimum > maximum:
            self._problem(
                "'%sForceMin' is above '%sForceMax' (%s > %s), using the defaults" % (side, side, minimum, maximum)
            )
            return DEFAULT_HOLD_FORCE_MIN, DEFAULT_HOLD_FORCE_MAX, False
        return minimum, maximum, min_specified or max_specified

    def _first_number(self, candidates, default):
        """The first of '(value, field)' that is a usable number, and whether there was one."""
        for value, field in candidates:
            if value is None:
                continue
            number = _as_number(value, field, self.where)
            if number is not None:
                return number, True
        return default, False

    async def resolve_push_distance(self, ctx):
        """Fill in 'push_distance' from the object's geometry, if it was not given.

        The default is 'PUSH_DISTANCE_FACTOR' times the object's own length
        along the Z axis of the interface it is connected by. Measuring that
        needs the object's geometry, and therefore a CAD runtime, so this is
        never done while the assembly is merely being instantiated. Failure to
        measure leaves the distance unresolved rather than failing the assembly:
        'how' is guidance for the assembler, not geometry.
        """
        if self.push_distance is not None:
            return self.push_distance
        if ctx is None or self._push_item is None:
            return None

        try:
            shape = await self._push_item.get_wrapped(ctx)
            if shape is None:
                return None
            length = await _measure_extent_z(ctx, self._push_item, shape, self._push_frame)
            if length is None:
                return None
            self.push_distance = PUSH_DISTANCE_FACTOR * length
        except Exception as e:
            pc_logging.debug("%s: failed to derive 'how.pushDistance': %s" % (self.where, e))
            return None
        return self.push_distance

    def is_default(self):
        """Whether the ASSY file said nothing at all about how to connect."""
        return (
            not self.specified
            and not self.hold_with
            and not self.hold_to
            and not self.driver
            and not self.hold_force_specified
            and self.hold_until is None
            and self.hold_until_stage is None
        )

    def info(self):
        info = {
            "method": self.method,
            "pushForceMax": self.push_force_max,
            # None means "not derived yet": see 'resolve_push_distance()'.
            "pushDistance": self.push_distance,
            "pushDirection": None if self.push_direction is None else list(self.push_direction),
            "turnDirection": self.turn_direction,
            "turnTorqueMax": self.turn_torque_max,
            "threadStep": self.thread_step,
            "holdWithForceMin": self.hold_with_force_min,
            "holdWithForceMax": self.hold_with_force_max,
            "holdToForceMin": self.hold_to_force_min,
            "holdToForceMax": self.hold_to_force_max,
        }
        if self.stage is not None:
            info["stage"] = self.stage
        if self.hold_with:
            info["holdWith"] = [hold.info() for hold in self.hold_with]
        if self.hold_to:
            info["holdTo"] = [hold.info() for hold in self.hold_to]
        if self.driver:
            info["driver"] = [hold.info() for hold in self.driver]
        if self.hold_until is not None:
            info["holdUntil"] = self.hold_until
        if self.hold_until_stage is not None:
            info["holdUntilStage"] = self.hold_until_stage
        if self.hold_until_steps:
            info["holdUntilSteps"] = list(self.hold_until_steps)
        return info


def resolve_hold_until(children, where: str) -> None:
    """Work out how far each step's hold reaches, once every step is known.

    A 'holdUntil'/'holdUntilStage' is a statement about the steps that come
    *after* the one that declares it, so it cannot be resolved while that step is
    being built. This runs once the whole list is: it is handed the children of
    one assembly, in the order they are assembled, and fills in how far each hold
    carries. After every child's own 'resolve()', and once - what it finds wrong
    is appended to the same 'problems' list that method starts over.

    A declaration that names nothing later is reported and left unresolved. The
    step still holds what it said it holds - for its own step, as it would
    without the field - because the hold is the useful half and the span is the
    half that was written wrong.
    """
    names = [getattr(child, "name", None) for child in children]
    stages = [getattr(child.how, "stage", None) if child.how is not None else None for child in children]

    def display(index):
        name = names[index]
        if name:
            return name
        return getattr(getattr(children[index], "item", None), "name", None) or "<unnamed>"

    for index, child in enumerate(children):
        how = child.how
        if how is None:
            continue
        how.hold_until_last = None
        how.hold_until_steps = []
        if how.hold_until is None and how.hold_until_stage is None:
            continue

        last = None
        if how.hold_until is not None:
            # The first later step of that name: a name repeated further down
            # would extend the hold past the step the author pointed at.
            for later in range(index + 1, len(children)):
                if names[later] == how.hold_until:
                    last = later
                    break
            if last is None:
                how._problem("'holdUntil' names no step that comes after this one: %s" % how.hold_until)
        else:
            # The *last* step of that stage: a stage is a group, and holding
            # until it ends means holding through all of it.
            for later in range(index + 1, len(children)):
                if stages[later] == how.hold_until_stage:
                    last = later
            if last is None:
                how._problem("'holdUntilStage' names no stage that comes after this step: %s" % how.hold_until_stage)

        if last is None:
            continue
        if not how.hold_with and not how.hold_to:
            how._problem(
                "there is nothing to keep holding: the step holds neither end,"
                " and 'holdUntil%s' says to keep doing it" % ("" if how.hold_until else "Stage")
            )
            continue
        how.hold_until_last = last
        how.hold_until_steps = [display(covered) for covered in range(index + 1, last + 1)]


def check_stage_sequence(node_list, where: str):
    """Report a 'how.stage' that is not one uninterrupted run of nodes.

    Consecutive nodes sharing a stage are the ones expected to be connected at
    the same time, so a stage that starts, is interrupted by another one, and
    then resumes does not mean what its author is likely to think it means.
    """
    seen = set()
    previous = None
    for node in node_list:
        if not isinstance(node, dict):
            continue
        connect = node.get("connect", None) or node.get("connectPorts", None)
        how = connect.get("how", None) if isinstance(connect, dict) else None
        stage = how.get("stage", None) if isinstance(how, dict) else None

        if stage != previous:
            if stage is not None and stage in seen:
                pc_logging.warning(
                    "%s: 'how.stage' is not contiguous, so its steps are not sequential: %s" % (where, stage)
                )
            if stage is not None:
                seen.add(stage)
            previous = stage


# Derived push distances, keyed by the object measured and the frame it was
# measured in. One assembly typically connects the very same part through the
# very same interface many times over (every screw in a bolt pattern), and each
# measurement is a round trip to a sandboxed CAD runtime.
_extent_cache = {}


def _measure_key(item, shape, frame):
    shape_hash = getattr(item, "hash", None)
    identity = None
    if shape_hash is not None:
        try:
            identity = shape_hash.get()
        except Exception:
            identity = None
    if identity is None:
        identity = "%s:%s" % (getattr(item, "project_name", None), getattr(item, "name", None))
    return (identity, None if frame is None else tuple(map(tuple, frame.as_packed()[:2])) + (frame.as_packed()[2],))


async def _measure_extent_z(ctx, item, shape, frame):
    """The object's length along the Z axis of 'frame', measured at most once."""
    from . import measure

    key = _measure_key(item, shape, frame)
    if key in _extent_cache:
        return _extent_cache[key]
    length = await measure.extent_z(ctx, shape, frame)
    _extent_cache[key] = length
    return length


def _resolve_holds(interfaces_spec, instances_spec, item, where, field):
    """Turn the requested (or defaulted) hold interfaces into 'ConnectHold' objects."""

    defaults = _HoldDefaults(item)

    explicit = len(interfaces_spec) > 0
    if not explicit:
        # The object's own 'hold' is the default for this connection.
        interfaces_spec = defaults.interfaces
    if not interfaces_spec:
        # Neither the ASSY file nor the object itself says how to hold it.
        return []

    if len(instances_spec) > len(interfaces_spec):
        pc_logging.error(
            "%s: 'how.%sInstance' lists more instances than there are interfaces to hold by" % (where, field)
        )

    available = _item_interfaces(item)

    holds = []
    for index, interface in enumerate(interfaces_spec):
        resolved = _match_interface(interface, available, item)
        if resolved is None:
            if available and explicit:
                pc_logging.error(
                    "%s: 'how.%s': the object does not implement the interface: %s" % (where, field, interface)
                )
            resolved = interface

        requested = instances_spec[index] if index < len(instances_spec) else None
        instance = _resolve_instance(resolved, requested, defaults, available, where, field)
        holds.append(ConnectHold(resolved, instance, ports=_instance_ports(available, resolved, instance)))

    return holds


class _HoldDefaults:
    """The 'hold' and 'holdInstance' fields of a part or assembly definition."""

    def __init__(self, item):
        config = connect_config(item)

        self.interfaces = _as_list(config.get(CONFIG_HOLD, None))
        instances = _as_list(config.get(CONFIG_HOLD_INSTANCE, None))

        # 'holdInstance' is positional against 'hold'.
        self.by_interface = {}
        for index, interface in enumerate(self.interfaces):
            if index < len(instances):
                self.by_interface[interface] = instances[index]

        # 'holdInstance' without 'hold' applies to whichever interface is used.
        self.fallback = instances[0] if instances and not self.interfaces else None

    def instance_for(self, interface: str):
        for candidate, instance in self.by_interface.items():
            if _same_interface(candidate, interface):
                return instance
        return self.fallback


def _item_interfaces(item):
    """The interfaces implemented by a part or an assembly, or an empty dict."""
    with_ports = getattr(item, "with_ports", None)
    if with_ports is None:
        return {}
    try:
        return with_ports.get_interfaces() or {}
    except Exception as e:
        # An object with no usable interface metadata is not a reason to fail
        # the assembly: 'how' is documentation for the assembler, not geometry.
        pc_logging.debug("Failed to enumerate the interfaces to hold by: %s" % e)
        return {}


def _item_name(item):
    """What to call an object in a message about it."""
    if item is None:
        return None
    name = getattr(item, "name", None)
    project = getattr(item, "project_name", None)
    if name and project:
        return "%s:%s" % (project, name)
    return name


def _tool_interfaces(tool, available, item=None):
    """The object's interfaces this tool meets it through.

    A tool says what it mates to; this is that list matched against what the
    object actually implements. Empty when the tool is unknown or declares no
    'mates' at all, which is not the same as "none of them": the caller falls
    back to every interface the object has, because a tool that never said what
    it fits cannot rule anything out.
    """
    mates = list(getattr(tool, "mates", None) or [])
    matched = []
    for mate in mates:
        candidate = _match_interface(mate, available, item)
        if candidate is not None and candidate not in matched:
            matched.append(candidate)
    return matched


def _instance_ports(available, interface, instance):
    """The ports of one instance of one interface, in declaration order.

    They are what turns a hold into a location: a document drawing the tool puts
    it at the first of them (see 'assembly_guide'), and an instance of the
    interfaces a tool mates to has exactly one.
    """
    return list((((available.get(interface) or {}).get(instance)) or {}).values())


def _enumerate_instances(tool_ref, interfaces, available):
    """Every instance of 'interfaces' the object has, as holds by 'tool_ref'.

    This is what an empty list of places asks for. Order is the object's own,
    which is the order its interfaces were declared in: a picture drawn from it
    is the same picture every time.
    """
    holds = []
    for interface in interfaces:
        for instance in (available.get(interface) or {}).keys():
            holds.append(
                ConnectHold(
                    interface,
                    instance,
                    tool=tool_ref,
                    ports=_instance_ports(available, interface, instance),
                )
            )
    return holds


def _short_name(interface: str):
    return interface.rsplit(":", 1)[-1] if isinstance(interface, str) else interface


def _same_interface(one: str, other: str):
    if one == other:
        return True
    return _short_name(one) == _short_name(other)


def _match_interface(interface, available, item=None):
    """Find 'interface' among the ones the object implements, qualified or not."""
    if not available:
        return None
    if interface in available:
        return interface

    project_name = getattr(item, "project_name", None)
    if project_name is not None:
        qualified = project_name + ":" + str(interface)
        if qualified in available:
            return qualified

    matched = [candidate for candidate in available.keys() if _same_interface(candidate, interface)]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        pc_logging.debug("Multiple interfaces match the name '%s': %s" % (interface, matched))
    return None


def _resolve_instance(interface, requested, defaults, available, where, field):
    """Pick the instance of 'interface' to hold the object by."""
    instances = list((available.get(interface, None) or {}).keys())

    if requested is not None:
        if not instances or requested in instances:
            return requested
        pc_logging.error(
            "%s: 'how.%sInstance': the interface '%s' has no such instance: %s" % (where, field, interface, requested)
        )

    default = defaults.instance_for(interface)
    if default is not None and (not instances or default in instances):
        return default

    # Fall back to the first instance of the interface, if it is known.
    if instances:
        return instances[0]
    return None
