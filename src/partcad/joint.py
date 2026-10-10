#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A connection kept as the steps it is composed of, and the joint those steps make.

**The composition.** ``connect:`` places the child at

    target placement . target port . T . target offsets . source offsets . source port^-1

where ``T`` is the half turn about (1, 1, 0) that makes two ports face each
other, and every "offset" is one freedom-of-movement parameter of one of the two
interfaces at the value the connection gives it ('toParams', 'withParams'). The
frame right after ``T`` is the **contact frame**: at zero offsets the source port
coincides with it, and both sides' parameters are read in it - which is why a
target interface's 'turnZ' turns the child about the contact frame's Z, the
target port's own Z reversed. That has been the placement since connections
existed. 'Composition' is the same product kept as an ordered list of factors
instead of multiplied out: 'fixed' steps (a port, the half turn, an adjustment)
and 'free' ones (a degree of freedom, at its starting value).

**The invariant.** 'Composition.location()' multiplies the steps in exactly the
order and grouping the placement always used, through exactly the arithmetic it
always used ('interface.movement_offset'), so it *is* the child's location, to
the last bit - 'AssemblyFactoryAssy' takes the location from it rather than
computing it a second way. Nothing that does not care about joints - the BREP
envelope, the shape cache, every exporter - sees any difference.

**The joint.** A connection is a joint when any of its steps is free. Which
parameters are free is what 'motion:' declares (see 'partcad.motion'), in three
places, most specific first - exactly the precedence a mating's 'how' already
has:

  1. the connection's own 'motion:' ('connect: {motion: fixed}' locks a joint);
  2. the mating's - what this pair does, whatever each would do with another;
  3. the two interfaces' own, combined: the union of both sides' degrees of
     freedom, with two that lie on the same axis merged into one whose range and
     value are the sums of the two (the two sides' freedoms are in series, which
     is how the placement composes them too).

A parameter that is not a degree of freedom stays what it always was: an
adjustment, fixed at its value. A degree of freedom a 'motion:' implies uses the
interface's parameter of the same kind along the same axis when there is one,
and otherwise brings its own ('turnZ' along a principal axis, 'angle'/'offset'
along any other) - which a connection can then address like a declared one.

There are no fixed joints. A connection with no free step is a rigid attachment,
and 'AssemblyChild.joint' is None for it.

Nothing here imports OCP.
"""

from . import motion as pc_motion
from .geom import Location
from .interface import PARAM_MOVE, PARAM_TURN, InterfaceParameter, movement_offset

TO = "to"
WITH = "with"
SIDES = (TO, WITH)

CONNECTION = "connection"
MATING = "mating"
INTERFACE = "interface"

# What a fixed step of a composition is, for whoever reads it.
ROLE_PORT = "port"  # the target port, in the parent's frame
ROLE_FACING = "facing"  # the half turn that makes the two ports face each other
ROLE_ADJUSTMENT = "adjustment"  # a freedom-of-movement parameter that is not a degree of freedom
ROLE_SOURCE_PORT = "sourcePort"  # the connected object's own port, undone

# The half turn about (1, 1, 0). Written as AssemblyFactoryAssy always wrote it:
# the placement composes this Location, and a joint that composed a different
# spelling of the same rotation would differ from the placement in the last bit.
FACING = Location((0, 0, 0), (0.71, 0.71, 0), 180)


def facing(direction):
    """A direction in a target port's frame, in the contact frame: what the half turn does to it.

    Exactly '(x, y, z) -> (y, x, -z)', which the rotation is (see
    'actions.assembly.convert.joint_axis_in_port_frame', the URDF converter's
    copy of the same fact); spelled out rather than rotated so that a principal
    axis stays a principal axis without rounding noise.
    """
    return (direction[1], direction[0], -direction[2])


def _kind(parameter) -> str:
    return PARAM_TURN if parameter.type == PARAM_TURN else PARAM_MOVE


def _length(vector) -> float:
    return pc_motion.dot(vector, vector) ** 0.5


def _number(value):
    """'value' as a float for reporting, or None when it is not a number."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FixedStep:
    """One rigid factor of a composition: a port, the half turn, or an adjustment."""

    free = False

    def __init__(self, location: Location, role: str, source: str = None):
        self.location = location
        self.role = role
        # For an adjustment: the parameter it is, as 'side:parameter'.
        self.source = source

    def transform(self, value=None):
        return self.location

    def to_envelope(self, steps) -> dict:
        entry = {"type": "fixed", "role": self.role, "location": self.location.as_packed()}
        if self.source is not None:
            entry["source"] = self.source
        return entry

    def __repr__(self):
        return "<fixed %s %s>" % (self.role, self.location)


class FreeStep:
    """One degree of freedom of a joint: a turn about 'axis', or a move along it.

    'axis' is the parameter's own 'dir', in the frame the steps before this one
    leave - the contact frame, unless an adjustment before it turned that frame.
    'value' is the joint's starting position, the value the connection gives the
    parameter ('toParams'/'withParams', zero when it gives none); the parameter
    at zero is the joint's zero. 'lower'/'upper' are in the same units - degrees,
    or millimetres per unit of 'axis' - and None where the joint is unlimited.

    'source' says which parameter (or parameters, when two on one axis were
    summed into this one) the step came from, and what made it free, so that a
    report can point at the declaration. 'coupling' ties it to another free step
    of the same joint: a screw's move follows its turn, as
    'value = ratio * other + offset'.
    """

    free = True

    def __init__(self, kind, axis, lower, upper, value, source, side):
        self.kind = kind
        self.axis = [float(component) for component in axis]
        self.lower = lower
        self.upper = upper
        self.value = value
        self.source = list(source)
        self.side = side
        self.follows = None
        self.ratio = None
        self.offset = None

    def transform(self, value=None):
        return movement_offset(self.kind, self.axis, self.value if value is None else value)

    @property
    def sides(self) -> set:
        return {entry.get("side") for entry in self.source}

    def coupling(self, steps):
        if self.follows is None:
            return None
        return {"step": steps.index(self.follows), "ratio": self.ratio, "offset": self.offset}

    def to_envelope(self, steps) -> dict:
        return {
            "type": "free",
            "kind": self.kind,
            "axis": list(self.axis),
            "lower": self.lower,
            "upper": self.upper,
            "value": _number(self.value),
            "source": [dict(entry) for entry in self.source],
            "coupling": self.coupling(steps),
        }

    def __repr__(self):
        return "<free %s %s [%s, %s] = %s>" % (self.kind, self.axis, self.lower, self.upper, self.value)


class Composition:
    """The placement of one connected child, as the ordered steps it is the product of.

    'base' is the target's placement, the first factor; 'outer' is a placement
    composed on top of the whole product afterwards - an ASSY file's root
    'location:', which moves everything the file holds (see
    'AssemblyFactoryAssy.apply_root_placement'). Both stay out of 'steps', which
    are what the joint relates the child to its parent by.
    """

    def __init__(self, base: Location):
        self.base = base
        self.steps = []
        self.outer = None

    def location(self, values: dict = None) -> Location:
        """The product of the steps, at their own values or at the ones 'values' gives.

        'values' maps an index into 'steps' to a value for that free step. The
        order and the grouping are the placement's own - the target placement,
        then each step to the right of it, then the outer placement to the left
        of all of it - and a free step at zero is skipped rather than multiplied
        by the identity, the way the placement skips a parameter at zero. That is
        what makes the product the placement bit for bit and not merely to
        within rounding.
        """
        location = self.base
        for index, step in enumerate(self.steps):
            value = None if values is None else values.get(index)
            transform = step.transform(value)
            if transform is not None:
                location = location * transform
        if self.outer is not None:
            location = self.outer * location
        return location

    def free_steps(self) -> list:
        return [step for step in self.steps if step.free]

    @property
    def has_freedom(self) -> bool:
        return any(step.free for step in self.steps)

    def place_within(self, placement: Location) -> None:
        """Compose 'placement' on top of the product, as the placement of a whole file is."""
        self.outer = placement if self.outer is None else placement * self.outer

    def contact_lines(self) -> dict:
        """Where each free step's axis is in the contact frame, with every degree of freedom at zero.

        Keyed by the step; each is '(point, direction)', the direction a unit
        vector. Adjustments are taken at their values: an adjustment is part of
        the fixed geometry of the connection, and two turns about the same axis
        on either side of a slot are about two different lines once the slot
        has moved one of them.
        """
        lines = {}
        prefix = Location()
        started = False
        for step in self.steps:
            if not started:
                started = not step.free and step.role == ROLE_FACING
                continue
            if step.free:
                direction = pc_motion.unit(prefix.rotate_vector(step.axis))
                lines[step] = (prefix.translation, direction)
            else:
                prefix = prefix * step.location
        return lines


class Joint:
    """A connection that keeps a degree of freedom.

    'parent' and 'child' are the two links it joins, by the names they have in
    the 'links:' list they share - a connection is always between two siblings.
    'Assembly.joints()' prefixes them with the containers above them, which is
    the path the rest of PartCAD names a link by.
    """

    def __init__(self, name, parent, child, composition, physics=None, physics_source=None, record=None):
        self.name = name
        self.parent = parent
        self.child = child
        self.composition = composition
        self.physics = dict(physics or {})
        self.physics_source = physics_source
        record = record or {}
        self.soft_limits = record.get("softLimits")
        self.mimic = record.get("mimic")
        self.problems = []

    @property
    def steps(self) -> list:
        return self.composition.steps

    def free_steps(self) -> list:
        return self.composition.free_steps()

    def to_envelope(self) -> dict:
        """The joint as plain data, for the node of the child it moves.

        This is what an exporter that walks the tree ('decode: false') reads
        beside the node's properties. The steps relate the parent's placement to
        the child's: the child node sits at the parent node's placement times
        their product at their values.
        """
        steps = self.steps
        entry = {
            "name": self.name,
            "parent": self.parent,
            "child": self.child,
            "steps": [step.to_envelope(steps) for step in steps],
        }
        if self.physics:
            entry["physics"] = dict(self.physics)
        if self.soft_limits:
            entry["softLimits"] = dict(self.soft_limits)
        if self.mimic:
            entry["mimic"] = dict(self.mimic)
        return entry

    def info(self, prefix: str = "") -> dict:
        """What 'pc info' shows of this joint: what it joins, how it moves, and where each came from."""
        info = {
            "parent": prefix + str(self.parent),
            "child": prefix + str(self.child),
            "free": [_free_step_info(step, self.steps) for step in self.free_steps()],
        }
        if self.physics:
            info["physics"] = dict(self.physics)
            info["physicsFrom"] = self.physics_source
        if self.soft_limits:
            info["softLimits"] = dict(self.soft_limits)
        if self.mimic:
            info["mimic"] = dict(self.mimic)
        if self.problems:
            info["problems"] = list(self.problems)
        return info

    def __repr__(self):
        return "<Joint %s: %s -> %s, %s>" % (self.name, self.parent, self.child, self.free_steps())


def _shown(value):
    value = float(value)
    return 0.0 if value == 0 else round(value, 9)


def _range_text(step) -> str:
    unit = "deg" if step.kind == PARAM_TURN else "mm"
    if step.lower is None and step.upper is None:
        return "unlimited"
    if step.lower is None:
        return "up to %g %s" % (step.upper, unit)
    if step.upper is None:
        return "from %g %s" % (step.lower, unit)
    return "%g to %g %s" % (step.lower, step.upper, unit)


def describe_source(source: dict) -> str:
    """One entry of a free step's 'source', in words."""
    side = {TO: "the target's", WITH: "the connected object's"}.get(source.get("side"), "a")
    interface = source.get("interface")
    owner = ("%s interface %s" % (side, interface)) if interface else ("%s side" % side)
    what = "'%s'" % source.get("parameter")
    if source.get("synthesized"):
        what += " (no such parameter is declared; implied)"
    reason = source.get("by")
    level = source.get("level")
    where = {CONNECTION: "the connection's", MATING: "the mating's", INTERFACE: "its"}.get(level, "its")
    return "%s of %s, free by %s %s" % (what, owner, where, reason)


def _free_step_info(step, steps) -> dict:
    info = {
        "kind": step.kind,
        "axis": [_shown(component) for component in step.axis],
        "range": _range_text(step),
        "value": _number(step.value),
        "from": [describe_source(entry) for entry in step.source],
    }
    coupling = step.coupling(steps)
    if coupling is not None:
        info["coupling"] = "follows step %d: value = %g * that + %g" % (
            coupling["step"],
            coupling["ratio"],
            coupling["offset"],
        )
    return info


#
# Resolution: which parameters of a connection are free
#


class Side:
    """One end of a connection, as the joint sees it.

    'to' is the target (the object connected *to*) and 'with' the object being
    connected; 'values' is what the connection says about that side's
    parameters ('toParams'/'withParams'); 'active' whether the placement
    composes that side's parameters at all - it does not when the side's port
    could not be found, which is how it has always been.
    """

    def __init__(self, name, interface, values, active):
        self.name = name
        self.interface = interface
        self.values = dict(values or {})
        self.active = active
        # Parameters this connection brought in because a 'motion:' implied a
        # degree of freedom no declared parameter is along. Addressable from
        # 'values' like a declared one, which is the point of having them.
        self.synthesized = {}
        # The degrees of freedom of this side, by parameter name, in the order
        # they were declared: name -> (lower, upper, source).
        self.dof = {}

    @property
    def interface_name(self):
        return getattr(self.interface, "full_name", None)

    def to_contact(self, direction):
        """A direction in this side's port frame, in the contact frame."""
        return facing(direction) if self.name == TO else tuple(direction)

    def declared(self) -> dict:
        params = getattr(self.interface, "params", None)
        return dict(params) if isinstance(params, dict) else {}

    def parameter(self, name):
        declared = self.declared().get(name)
        return declared if declared is not None else self.synthesized.get(name)

    def unique_name(self, base: str) -> str:
        name, suffix = base, 2
        while self.parameter(name) is not None:
            name = "%s-%d" % (base, suffix)
            suffix += 1
        return name

    def synthesize(self, kind, direction) -> tuple:
        """A parameter for a degree of freedom nothing declared, and its sign against 'direction'.

        'direction' is in the contact frame, where the parameters of both sides
        are read. Named as the predefined parameter would be along a principal
        axis - 'turnZ' turns about +Z, so a freedom about -Z is 'turnZ' with its
        range read the other way round - and 'angle'/'offset' along any other,
        which are the names the URDF converter writes.
        """
        name, sign = pc_motion.principal_name(kind, direction)
        if name is not None and self.parameter(name) is None:
            axis = pc_motion.PREDEFINED[name][1]
        else:
            name = self.unique_name("angle" if kind == PARAM_TURN else "offset")
            axis, sign = direction, 1
        parameter = InterfaceParameter(
            {"name": name, "type": kind, "dir": list(axis), "min": None, "max": None, "default": 0.0}
        )
        parameter.unbounded = True
        self.synthesized[name] = parameter
        return name, parameter, sign

    def add_dof(self, name, lower, upper, source) -> None:
        if name in self.dof:
            return
        self.dof[name] = (lower, upper, source)

    def steps(self) -> list:
        """This side's factors of the composition, in the order the placement composes them.

        The parameters the connection names come first, in the order it names
        them, exactly as the placement always composed them: a degree of
        freedom as a free step at the value given, anything else as an
        adjustment fixed at it. The degrees of freedom it does not name follow,
        free at zero - which composes nothing, so they change no placement.
        """
        steps = []
        named = set()
        for name, value in self.values.items():
            parameter = self.parameter(name)
            if parameter is None:
                continue
            named.add(name)
            # Called for every named parameter, free or not: it is what reports
            # a value outside the parameter's range, as it always has.
            offsets = parameter.get_offsets(value)
            if name in self.dof:
                steps.append(self._free(name, parameter, value))
            else:
                steps.extend(FixedStep(offset, ROLE_ADJUSTMENT, "%s:%s" % (self.name, name)) for offset in offsets)
        for name in self.dof:
            if name not in named:
                steps.append(self._free(name, self.parameter(name), 0.0))
        return steps

    def _free(self, name, parameter, value):
        lower, upper, source = self.dof[name]
        value = _number(value)
        return FreeStep(_kind(parameter), parameter.dir, lower, upper, value, [source], self.name)


def _parameter_range(parameter) -> tuple:
    if parameter.unbounded:
        return None, None
    return _number(parameter.min), _number(parameter.max)


def _scaled_range(lower, upper, factor) -> tuple:
    """'[lower, upper]' in a parameter whose unit is 'factor' of the freedom's: flipped when negative."""
    low = None if lower is None else lower * factor
    high = None if upper is None else upper * factor
    return (low, high) if factor > 0 else (high, low)


class Resolution:
    """Which parameters of one connection are degrees of freedom, and why.

    Built once per connection by 'AssemblyFactoryAssy', before the placement is
    composed: a degree of freedom a 'motion:' implies may bring a parameter of
    its own, and the placement has to be able to read 'toParams' against it.
    """

    def __init__(self, to_side: Side, with_side: Side, connect: dict, mating=None, thread_step=None):
        self.to_side = to_side
        self.with_side = with_side
        self.connect = connect if isinstance(connect, dict) else {}
        self.mating = mating
        self.thread_step = thread_step
        self.problems = []
        self.record = {}
        # The freedoms that follow another one (a screw's move), as
        # '(side, follower name, side, leader name, ratio)'.
        self.couplings = []

        self.levels = self._levels()
        self._resolve()
        # Every declaration that has a say is reported on, governing or not: a
        # 'motion:' that contradicts itself is a mistake in the package that
        # wrote it, whichever level decided this one connection. Collected after
        # resolving, since implying a declaration's freedoms is one more place a
        # contradiction shows.
        self.problems = [problem for _, motion, _ in self.levels for problem in motion.problems] + self.problems

    def _levels(self) -> list:
        """Every 'motion:' that has a say here, most specific first, as '(level, motion, side)'.

        'side' is the side an interface's declaration is its own side's; None for
        the connection and the mating, which state what the pair does and are
        resolved against both.
        """
        levels = []
        if self.connect.get("motion") is not None:
            levels.append((CONNECTION, pc_motion.Motion(self.connect.get("motion"), where="connect: motion"), None))
        mating_motion = getattr(self.mating, "motion", None)
        if mating_motion is not None:
            where = "the mating of %s and %s: motion" % (
                getattr(self.mating.source, "full_name", "?"),
                getattr(self.mating.target, "full_name", "?"),
            )
            levels.append((MATING, pc_motion.Motion(mating_motion, where=where), None))
        for side in (self.to_side, self.with_side):
            get_motion = getattr(side.interface, "get_motion", None)
            declared = get_motion() if get_motion is not None else None
            if declared is not None:
                where = "%s: motion" % side.interface_name
                levels.append((INTERFACE, pc_motion.Motion(declared, where=where), side))
        return levels

    def _declarer_side(self) -> Side:
        """The side whose interface declared the mating; its port's frame is the mating's.

        A mating is registered both ways round, and 'reverse' is set on the copy
        whose source is the interface the 'mates:' was written *against* - so
        when it is clear, the connected object's interface is the one that
        wrote it.
        """
        return self.to_side if getattr(self.mating, "reverse", False) else self.with_side

    def _resolve(self) -> None:
        governing = [entry for entry in self.levels if entry[1].declared]
        if governing and governing[0][0] in (CONNECTION, MATING):
            level, motion, _ = governing[0]
            if level == CONNECTION:
                # A connection's axis is in the contact frame - the frame its own
                # 'toParams' are read in - and what it brings, it brings to the
                # target, whose parameters 'toParams' sets.
                frame, default = (lambda direction: tuple(direction)), self.to_side
            else:
                declarer = self._declarer_side()
                frame, default = declarer.to_contact, declarer
            self._apply(level, motion, [self.to_side, self.with_side], frame, default)
        else:
            for level, motion, side in governing:
                self._apply(level, motion, [side], side.to_contact, side)

        # What the declarations say about the joint as a whole - its soft limits
        # and what it mimics - comes from the most specific one that says it.
        # The two interfaces are one level, so between those two it is the
        # target's, and saying two different things is reported.
        stated_at = {}
        for level, motion, _ in self.levels:
            for field, value in motion.joint_record().items():
                if field not in self.record:
                    self.record[field] = value
                    stated_at[field] = level
                elif level == INTERFACE and stated_at[field] == INTERFACE and self.record[field] != value:
                    self.problems.append(
                        "the two interfaces state different '%s' for one joint; the target's is used" % field
                    )

    def _apply(self, level, motion, sides, frame, default) -> None:
        """Mark what one 'motion:' declares free, on the sides it is resolved against."""
        named = []
        if motion.dof is not None:
            named = self._explicit(level, motion, sides, default)
        implied = motion.implied()

        if motion.dof is not None and motion.type is not None:
            self._check_agreement(motion, implied, named, frame)
            return
        if motion.dof is not None:
            return

        claimed = set()
        followers = {}
        for index, freedom in enumerate(implied):
            direction = pc_motion.unit(frame(freedom.axis))
            match = None
            for side in sides:
                for name, parameter in side.declared().items():
                    if (side.name, name) in claimed or _kind(parameter) != freedom.kind:
                        continue
                    axis = pc_motion.unit(parameter.dir)
                    sign = 0 if axis is None else pc_motion.parallel(axis, direction)
                    if sign:
                        match = (side, name, parameter, sign, False)
                        break
                if match is not None:
                    break
            if match is None:
                name, parameter, sign = default.synthesize(freedom.kind, direction)
                match = (default, name, parameter, sign, True)
            side, name, parameter, sign, synthesized = match
            claimed.add((side.name, name))

            # A parameter's value is this factor times the freedom's: the sign
            # their directions have against each other, and for a move the
            # length of the parameter's 'dir' as well.
            factor = float(sign)
            if freedom.kind == PARAM_MOVE:
                factor /= _length(parameter.dir)
            if freedom.unlimited:
                lower, upper = None, None
            elif freedom.limited:
                lower, upper = _scaled_range(freedom.lower, freedom.upper, factor)
            else:
                lower, upper = _parameter_range(parameter)
            source = {
                "side": side.name,
                "interface": side.interface_name,
                "parameter": name,
                "level": level,
                "by": "motion '%s'" % motion.type,
                "synthesized": synthesized,
            }
            side.add_dof(name, lower, upper, source)
            followers[index] = (side, name, factor)
            if freedom.follows is not None:
                self._couple(motion, followers, index, freedom.follows)

    def _explicit(self, level, motion, sides, default) -> list:
        """The parameters 'dof:' names, marked free; '(side, name, parameter)' for each."""
        named = []
        for name in motion.dof:
            found = False
            for side in sides:
                parameter = side.declared().get(name)
                if parameter is None:
                    continue
                found = True
                lower, upper = _parameter_range(parameter)
                source = {
                    "side": side.name,
                    "interface": side.interface_name,
                    "parameter": name,
                    "level": level,
                    "by": "'dof'",
                    "synthesized": False,
                }
                side.add_dof(name, lower, upper, source)
                named.append((side, name, parameter))
            if found:
                continue
            if name in pc_motion.PREDEFINED:
                # The name says the kind and the axis, which is all a parameter
                # declared by name alone says too: free along it, unbounded.
                kind, axis = pc_motion.PREDEFINED[name]
                parameter = InterfaceParameter(
                    {"name": name, "type": kind, "dir": list(axis), "min": None, "max": None, "default": 0.0}
                )
                parameter.unbounded = True
                default.synthesized[name] = parameter
                source = {
                    "side": default.name,
                    "interface": default.interface_name,
                    "parameter": name,
                    "level": level,
                    "by": "'dof'",
                    "synthesized": True,
                }
                default.add_dof(name, None, None, source)
                named.append((default, name, parameter))
                continue
            where = motion.where
            if len(sides) == 1:
                self.problems.append(
                    "%s: 'dof' names '%s', which is not a freedom-of-movement parameter of %s"
                    % (where, name, sides[0].interface_name or "the interface")
                )
            else:
                self.problems.append(
                    "%s: 'dof' names '%s', which neither interface declares as a freedom-of-movement parameter"
                    % (where, name)
                )
        return named

    def _check_agreement(self, motion, implied, named, frame) -> None:
        """A 'type' and a 'dof' list stated together have to describe the same freedoms.

        Paired up by kind and by axis - the same line, either way round - with
        the parameters' directions read in the contact frame and the type's axis
        mapped there from the frame it is stated in. Where they agree, the type
        still says what the range is ('continuous' has none, 'limits:' gives
        one); the parameters 'dof' names are what the freedoms *are*.
        """
        remaining = list(named)
        unmatched = []
        for freedom in implied:
            direction = pc_motion.unit(frame(freedom.axis))
            for entry in remaining:
                side, name, parameter = entry
                axis = pc_motion.unit(parameter.dir)
                sign = 0 if axis is None else pc_motion.parallel(axis, direction)
                if _kind(parameter) == freedom.kind and sign:
                    remaining.remove(entry)
                    factor = float(sign)
                    if freedom.kind == PARAM_MOVE:
                        factor /= _length(parameter.dir)
                    lower, upper, source = side.dof[name]
                    if freedom.unlimited:
                        lower, upper = None, None
                    elif freedom.limited:
                        lower, upper = _scaled_range(freedom.lower, freedom.upper, factor)
                    side.dof[name] = (lower, upper, dict(source, by="'dof' and motion '%s'" % motion.type))
                    break
            else:
                unmatched.append(freedom)
        if unmatched or remaining:
            said = ", ".join(name for _, name, _ in named) or "nothing"
            self.problems.append(
                "%s: 'type: %s' and 'dof: [%s]' do not describe the same degrees of freedom; 'dof' is used"
                % (motion.where, motion.type, said)
            )

    def _couple(self, motion, followers, index, leader_index) -> None:
        """A screw's move follows its turn, by the thread the connection advances along."""
        if not self.thread_step:
            self.problems.append(
                "%s: a screw motion advances along a thread, and nothing here states its 'threadStep'; "
                "the move is left free on its own" % motion.where
            )
            return
        leader_side, leader, leader_factor = followers[leader_index]
        follower_side, follower, follower_factor = followers[index]
        # Along the axis, in the axis's own sense: mm = threadStep / 360 * deg
        # (a right-handed helix, which is a right-hand thread). Each parameter
        # is that freedom times its factor, so the ratio between the two
        # parameters is the pitch over the two factors.
        ratio = self.thread_step / 360.0 * follower_factor / leader_factor
        self.couplings.append((follower_side.name, follower, leader_side.name, leader, ratio))

    def apply_couplings(self, composition) -> None:
        by_source = {}
        for step in composition.free_steps():
            for entry in step.source:
                by_source[(entry.get("side"), entry.get("parameter"))] = step
        for follower_side, follower, leader_side, leader, ratio in self.couplings:
            step = by_source.get((follower_side, follower))
            leader_step = by_source.get((leader_side, leader))
            if step is None or leader_step is None or step is leader_step:
                continue
            step.follows = leader_step
            step.ratio = ratio
            # The connection may start the two anywhere, and the placement is
            # where it starts them; the offset is what keeps the relation true
            # there rather than moving the part to make it so.
            step.offset = (step.value or 0.0) - ratio * (leader_step.value or 0.0)


def merge(composition) -> list:
    """Make one degree of freedom out of two free steps on the same axis; what was merged.

    Two free steps are one degree of freedom when they are the same kind and on
    the same axis in the contact frame - the same line for two turns, parallel
    directions for two moves, either way round - with every degree of freedom at
    zero and every adjustment at its value. The merged step's range is the sum
    of the two ranges and its value the sum of the two values, read in one
    step's sense; it is unlimited if either was.

    One condition beyond that, which keeps the merge exact: nothing that *moves*
    may lie between the two unless it commutes with them - a turn about the same
    line, or a move along it. A slide between two parallel turns turns them
    about two lines as soon as it moves, and summing them would lose a freedom.
    A step that follows another (a screw's move) is never merged: it is not a
    freedom of its own.

    The merged step stays where the one that has a value was (the earlier one
    when both or neither have), so that a connection that gives only one of the
    two a value composes exactly the factors it always composed.
    """
    merged = []
    changed = True
    while changed:
        changed = False
        lines = composition.contact_lines()
        free = composition.free_steps()
        followed = {step.follows for step in free if step.follows is not None}
        for i, first in enumerate(free):
            if first.follows is not None or first in followed:
                continue
            for second in free[i + 1 :]:
                if second.follows is not None or second in followed or second.kind != first.kind:
                    continue
                sign = _same_axis(first, second, lines)
                if not sign or not _commutes_between(composition, first, second, lines):
                    continue
                _merge_pair(composition, first, second, sign)
                merged.append((first, second))
                changed = True
                break
            if changed:
                break
    return merged


def _same_axis(first, second, lines) -> int:
    point_a, direction_a = lines[first]
    point_b, direction_b = lines[second]
    if direction_a is None or direction_b is None:
        return 0
    sign = pc_motion.parallel(direction_a, direction_b)
    if not sign or first.kind == PARAM_MOVE:
        return sign
    offset = tuple(b - a for a, b in zip(point_a, point_b))
    across = pc_motion.cross(offset, direction_a)
    return sign if _length(across) <= pc_motion.TOLERANCE else 0


def _commutes(step, other, lines) -> bool:
    """Whether 'other' moves the same way whatever 'step' is at, and the other way round."""
    point, direction = lines[step]
    other_point, other_direction = lines[other]
    if direction is None or other_direction is None:
        return False
    if step.kind == PARAM_MOVE and other.kind == PARAM_MOVE:
        return True
    if step.kind == PARAM_MOVE or other.kind == PARAM_MOVE:
        return bool(pc_motion.parallel(direction, other_direction))
    return bool(_same_axis(step, other, lines))


def _commutes_between(composition, first, second, lines) -> bool:
    steps = composition.steps
    between = steps[steps.index(first) + 1 : steps.index(second)]
    return all(_commutes(first, step, lines) for step in between if step.free)


def _summed(bound, other):
    """One end of a summed range: unlimited when either end is."""
    return None if bound is None or other is None else bound + other


def _merge_pair(composition, first, second, sign) -> None:
    keep, other = (second, first) if (not first.value and second.value) else (first, second)
    # How much of 'keep' one unit of 'other' is: the sign their directions have
    # against each other, and for a move the ratio of their lengths, since a
    # move's offset is its value times its 'dir'.
    factor = float(sign)
    if keep.kind == PARAM_MOVE:
        factor *= _length(other.axis) / _length(keep.axis)
    other_low, other_high = _scaled_range(other.lower, other.upper, factor)
    keep.lower = _summed(keep.lower, other_low)
    keep.upper = _summed(keep.upper, other_high)
    keep.value = (keep.value or 0.0) + factor * (other.value or 0.0)
    keep.source = keep.source + other.source
    composition.steps.remove(other)


#
# Physics
#


def resolve_physics(connect: dict, mating, to_side: Side, with_side: Side, composition, problems: list):
    """What moving the joint costs, and where that was said: '(physics, source)'.

    The precedence of 'motion:': the connection's 'physics:', else the mating's,
    else the interfaces'. Where both interfaces state physics they are taken
    together, and a value they both state has to agree: two dampers in series do
    not add, so there is no sum to take, and only the mating knows what the pair
    really does. A disagreement is reported - as one about the degree of freedom
    they share when they share one - and the target's value is used.
    """
    stated = (connect or {}).get("physics")
    if stated is not None:
        if isinstance(stated, dict):
            return dict(stated), CONNECTION
        problems.append("connect: 'physics' must be a section, ignoring it")
    mating_physics = getattr(mating, "physics", None)
    if isinstance(mating_physics, dict):
        return dict(mating_physics), MATING

    sides = []
    for side in (to_side, with_side):
        get_physics = getattr(side.interface, "get_physics", None)
        physics = get_physics() if get_physics is not None else None
        if isinstance(physics, dict) and physics:
            sides.append((side, physics))
    if not sides:
        return {}, None
    if len(sides) == 1:
        side, physics = sides[0]
        return dict(physics), side.interface_name

    (to, to_physics), (_, with_physics) = sides
    shared = [step for step in composition.free_steps() if step.sides == {TO, WITH}]
    combined = dict(with_physics)
    combined.update(to_physics)
    for key in sorted(set(to_physics) & set(with_physics)):
        if to_physics[key] == with_physics[key]:
            continue
        about = "the degree of freedom they share" if shared else "one joint"
        problems.append(
            "the two interfaces state different '%s' for %s (%s and %s); a mating of the two has to say "
            "which, and the target's is used" % (key, about, to_physics[key], with_physics[key])
        )
    return combined, "%s and %s" % (to.interface_name, sides[1][0].interface_name)


#
# Putting it together
#


def compose(
    target_location,
    target_port_location,
    source_port_location,
    to_side: Side,
    with_side: Side,
):
    """The composition of one connection: the steps the placement is the product of.

    'target_port_location' and 'source_port_location' are None when that port
    could not be found, and then neither that port nor that side's parameters
    are composed - the four cases the placement has always distinguished.
    """
    composition = Composition(target_location)
    if target_port_location is not None:
        composition.steps.append(FixedStep(target_port_location, ROLE_PORT))
    composition.steps.append(FixedStep(FACING, ROLE_FACING))
    # Worked out source first, as the placement always did, so that what the
    # parameters report about out-of-range values comes out in the same order;
    # composed target first, which is the product.
    with_steps = with_side.steps()
    to_steps = to_side.steps()
    for side, steps in ((to_side, to_steps), (with_side, with_steps)):
        if side.active:
            composition.steps.extend(steps)
    if source_port_location is not None:
        composition.steps.append(FixedStep(source_port_location.inverse(), ROLE_SOURCE_PORT))
    return composition
