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
"""

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
    "holdTo",
    "holdToInstance",
)

# Fields that were renamed, and the field that replaces each of them. They are
# still accepted, so that the ASSY files written against the earlier spelling
# keep working, but they are reported so that they can be fixed.
HOW_FIELDS_DEPRECATED = {
    # A push is a force, not a torque: the value is in newtons either way, but
    # the name said otherwise.
    "pushTorqueMax": "pushForceMax",
}

# The object-level ('parts' and 'assemblies' in 'partcad.yaml') defaults for
# 'holdWith'/'holdTo' and 'holdWithInstance'/'holdToInstance'.
CONFIG_HOLD = "hold"
CONFIG_HOLD_INSTANCE = "holdInstance"


def _as_list(value):
    """Normalize a scalar-or-list configuration value into a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    return [value]


class ConnectHold:
    """One interface (and the instance of it) to hold an object by while connecting."""

    def __init__(self, interface: str, instance=None):
        self.interface = interface
        self.instance = instance

    def info(self):
        return {"interface": self.interface, "instance": self.instance}

    def __eq__(self, other):
        if not isinstance(other, ConnectHold):
            return NotImplemented
        return self.interface == other.interface and self.instance == other.instance

    def __repr__(self):
        if self.instance:
            return "%s[%s]" % (self.interface, self.instance)
        return str(self.interface)


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
        self.thread_step = self._number(config, "threadStep", DEFAULT_THREAD_STEP)

        # 'pushDistance' is derived from the object's own geometry when the ASSY
        # file does not give it. That needs a CAD runtime, which instantiating an
        # assembly otherwise does not, so it is left for 'resolve_push_distance()'
        # to fill in on demand rather than computed here.
        self.push_distance = self._number(config, "pushDistance", None)
        self.push_distance_specified = self.push_distance is not None
        self._push_item = None
        self._push_frame = None

        # The requested holds, before they are matched against the objects being
        # connected. 'resolve()' turns these into 'ConnectHold' lists.
        self._hold_with_spec = _as_list(config.get("holdWith", None))
        self._hold_with_instance_spec = _as_list(config.get("holdWithInstance", None))
        self._hold_to_spec = _as_list(config.get("holdTo", None))
        self._hold_to_instance_spec = _as_list(config.get("holdToInstance", None))

        self.hold_with: list[ConnectHold] = []
        self.hold_to: list[ConnectHold] = []

    def _number(self, config, field, default):
        value = config.get(field, None)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            pc_logging.error("%s: 'how.%s' must be a number, using the default: %s" % (self.where, field, value))
            return default
        if value < 0.0:
            pc_logging.error("%s: 'how.%s' must not be negative, using the default: %s" % (self.where, field, value))
            return default
        return float(value)

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

    def resolve(self, source_item=None, target_item=None, source_frame=None):
        """Match the requested holds against the objects that are being connected.

        'source_item' is the object that is being added to the assembly (the
        'with' end), 'target_item' is the object it is connected to (the 'to'
        end). Either may be missing, in which case that end is resolved as far
        as the ASSY file alone allows.

        'source_frame' is the placement of the interface that the source object
        is connected by, in that object's own coordinates. It is what a derived
        'pushDistance' is measured along, and is remembered rather than used
        here: see 'resolve_push_distance()'.
        """
        self._push_item = source_item
        self._push_frame = source_frame

        self.hold_with = _resolve_holds(
            self._hold_with_spec,
            self._hold_with_instance_spec,
            source_item,
            self.where,
            "holdWith",
        )
        self.hold_to = _resolve_holds(
            self._hold_to_spec,
            self._hold_to_instance_spec,
            target_item,
            self.where,
            "holdTo",
        )
        return self

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
        return not self.specified and not self.hold_with and not self.hold_to

    def info(self):
        info = {
            "pushForceMax": self.push_force_max,
            # None means "not derived yet": see 'resolve_push_distance()'.
            "pushDistance": self.push_distance,
            "turnDirection": self.turn_direction,
            "turnTorqueMax": self.turn_torque_max,
            "threadStep": self.thread_step,
        }
        if self.stage is not None:
            info["stage"] = self.stage
        if self.hold_with:
            info["holdWith"] = [hold.info() for hold in self.hold_with]
        if self.hold_to:
            info["holdTo"] = [hold.info() for hold in self.hold_to]
        return info


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
        holds.append(ConnectHold(resolved, instance))

    return holds


class _HoldDefaults:
    """The 'hold' and 'holdInstance' fields of a part or assembly definition."""

    def __init__(self, item):
        config = getattr(item, "config", None) or {}
        if not isinstance(config, dict):
            config = {}

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
