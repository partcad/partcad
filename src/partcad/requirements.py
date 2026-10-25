#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object is required to be, and whether the CAD model is it.

``simulate:`` says what an object is supposed to *do*. ``requirements:`` says
what it is supposed to *be*, and it is written before the design is, in the
terms whoever asked for the design thinks in:

    features    a name for each thing the object has to have or do, with a
                sentence saying what. Free text, because most of what a product
                is asked for is not a number: "takes an M3 screw from either
                side", "survives a drop from a desk". A ``simulate:`` entry can
                name the feature it demonstrates (``feature:``), and so can a
                scenario of an engineering analysis (``fea: <name>:``, see
                'partcad.cae') -- "carries a full shelf" is demonstrated by the
                stress analysis under one. Everything else is for a reader -- a
                person, or an LLM running ``/pc:validate`` -- to judge against
                the renders, the bill of materials and the instructions.
    ports       the ports the object has to have, by name, and as much of where
                each one is as matters. Every part of that may be null, and most
                of it should be: "a port called 'top' that faces down" is a
                requirement, "a port at exactly these coordinates" is usually a
                design decision written down too early.
    interfaces  the interfaces the object has to implement, and as much of
                where each instance is as matters, in the same terms.
    physics     what the object's physical properties have to be: any of the
                fields of a 'physics:' section, in the same terms.

The last three are what ``pc test`` checks (the ``requirements`` test, see
'test/requirements.py'), and this module is the one place that says what they
mean -- the test, the daemon's ``requirements.check`` that the IDE's
Requirements tab is drawn from, and anything else that asks, all go through
'check_async()'.

**What a requirement value is.** Wherever a value can be required, it may be
null (no requirement), a constant (a number, a string or a boolean), or a
comparison: ``>0``, ``>=1``, ``<10``, ``<=1``, ``!0`` (not 0; ``!=0`` too) and
``=5``. Several are joined with commas, and the two kinds join differently:
constants are alternatives (``"1,2,4"`` is one of the three) and comparisons are
all required at once (``">0,<=1"`` is a value in (0, 1]). A value given both
has to be one of the constants *and* meet every comparison. Numbers are compared
with a tolerance of 'TOLERANCE', because a direction worked out from a rotation
is never exactly the one written down.

**What a location requirement is.** A port and an interface instance are
coordinate frames, and a requirement on one is three things, each of which may
be null: ``position`` (where its origin is, in millimetres, in the object's own
frame), ``direction`` (where its Z axis points -- the way the port faces) and
``angle`` (in degrees, how far it is turned about that axis). Written either as
a mapping with those three keys or, the way a port's own location is written,
as a list of three: ``[position, direction, angle]``.

The middle element of a *port's* location is the axis it is rotated about, and
of a requirement it is the direction the port faces. They are deliberately not
the same thing: "faces down" is what a requirement means, and a port facing
down is written ``[[0, 0, 0], [1, 0, 0], 180]`` -- rotated about X -- which
compared as written would say it faces along X. 'facing()' is the rule: the
direction is the frame's Z axis, and the angle is how far its X axis is turned
about that direction from where the shortest turn from +Z leaves it. For a port
written as a turn about Z, that is the angle it was written with; for one
written as a tilt about an axis across Z, it is 0.

What is deliberately not here: any judgement about features. PartCAD checks
what it can measure. Whether a part "survives a drop from a desk" is for a
simulation or an analysis that names the feature, or for whoever reads the
evidence.
"""

from __future__ import annotations

import math
import re
import typing

from . import logging as pc_logging
from .geom import Location

# The section of a part's, an assembly's, a scene's or a sketch's declaration.
SECTION = "requirements"

FEATURES = "features"
PORTS = "ports"
INTERFACES = "interfaces"
PHYSICS = "physics"

# The sections 'pc test' verifies against the model, in the order a report
# lists them. 'features' is not one of them: a feature is prose.
STRUCTURED = (PORTS, INTERFACES, PHYSICS)

# Where a feature reference that names nothing is reported: it is a mistake in
# a 'simulate:' entry, not in the requirements. One an analysis scenario makes
# is reported under the analysis's own section ('fea', 'cfd', ...).
SIMULATE = "simulate"

# How close two numbers have to be to be the same number: a millimetre of
# position, a component of a unit vector and a degree are all compared with it.
TOLERANCE = 1e-6

# The name a requirements section written as one paragraph of text is listed
# under, and what a list of paragraphs is numbered from. Both are the free-form
# shape 'requirements:' had before it had structure, and both are still read: a
# paragraph is a feature nobody has named yet.
LEGACY_FEATURE = "general"

# A comparison: the operator, then what is compared with.
_COMPARISON = re.compile(r"^\s*(>=|<=|!=|==|>|<|!|=)\s*(.*?)\s*$")

_AXES = ("x", "y", "z")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_number(text: str):
    """'text' as the number it spells, or None."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _fmt(value) -> str:
    """A value the way a requirement shows it: numbers short, null as null."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if _is_number(value):
        number = float(value)
        if number == 0.0:
            # Not "-0": a direction worked out from a rotation is full of them.
            return "0"
        return "%g" % number
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(_fmt(item) for item in value)
    return str(value)


def wrap_angle(degrees: float) -> float:
    """An angle in degrees, in (-180, 180]."""
    wrapped = math.fmod(float(degrees), 360.0)
    if wrapped <= -180.0:
        wrapped += 360.0
    elif wrapped > 180.0:
        wrapped -= 360.0
    return wrapped


def numbers_equal(a: float, b: float, angle: bool = False) -> bool:
    """Whether two numbers are the same, to 'TOLERANCE' -- and modulo a turn for an angle."""
    if angle:
        return abs(wrap_angle(float(a) - float(b))) <= TOLERANCE
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=TOLERANCE)


# ---------------------------------------------------------------------------
# One required value
# ---------------------------------------------------------------------------


class ValueSpec:
    """One required value: the constants it may be, and the comparisons it has to meet.

    Parsed once, from what the declaration says. A term that cannot be read is
    recorded in 'error' rather than raised: the requirement then fails, saying
    why, instead of taking the rest of the report down with it.
    """

    def __init__(self, raw):
        self.raw = raw
        self.constants: list = []
        # (operator, operand): '>', '>=', '<', '<=' with a number, '!' with
        # anything a constant can be.
        self.conditions: list = []
        self.error: typing.Optional[str] = None

        if isinstance(raw, bool) or _is_number(raw):
            self.constants.append(raw if isinstance(raw, bool) else float(raw))
        elif isinstance(raw, str):
            self._parse(raw)
        else:
            self.error = "'%s' is not a value: a requirement is a number, a string, a boolean or a comparison" % (
                _fmt(raw),
            )

    def _parse(self, text: str) -> None:
        terms = [term.strip() for term in text.split(",")]
        if any(term == "" for term in terms):
            self.error = "'%s' has an empty term between its commas" % text
            return
        for term in terms:
            match = _COMPARISON.match(term)
            if match is None:
                number = _as_number(term)
                self.constants.append(term if number is None else number)
                continue
            operator, operand = match.group(1), match.group(2)
            if operand == "":
                self.error = "'%s' compares with nothing" % term
                return
            number = _as_number(operand)
            if operator in ("=", "=="):
                # Not a comparison at all: '=5' is the constant 5, spelled out.
                self.constants.append(operand if number is None else number)
            elif operator in ("!", "!="):
                self.conditions.append(("!", operand if number is None else number))
            elif number is None:
                self.error = "'%s' compares with '%s', which is not a number" % (term, operand)
                return
            else:
                self.conditions.append((operator, number))

    @property
    def numeric_constant(self) -> typing.Optional[float]:
        """The one number this requires exactly, or None when it requires anything else."""
        if len(self.constants) == 1 and not self.conditions and _is_number(self.constants[0]):
            return float(self.constants[0])
        return None

    def matches(self, actual, angle: bool = False, equal=None) -> bool:
        """Whether 'actual' is what this requires.

        'angle' compares modulo a turn: 270 is -90, and an ordering compares
        the value in (-180, 180]. 'equal' replaces equality for a value that
        has several spellings (a sketch's name).
        """
        if self.error is not None or actual is None:
            return False
        if equal is None:

            def equal(a, b):
                if isinstance(a, bool) or isinstance(b, bool):
                    return isinstance(a, bool) and isinstance(b, bool) and a == b
                if _is_number(a) and _is_number(b):
                    return numbers_equal(a, b, angle)
                return str(a) == str(b)

        if self.constants and not any(equal(actual, constant) for constant in self.constants):
            return False
        for operator, operand in self.conditions:
            if operator == "!":
                if equal(actual, operand):
                    return False
                continue
            if not _is_number(actual):
                return False
            value = wrap_angle(actual) if angle else float(actual)
            same = numbers_equal(value, operand)
            if operator == ">" and not (value > operand and not same):
                return False
            if operator == ">=" and not (value > operand or same):
                return False
            if operator == "<" and not (value < operand and not same):
                return False
            if operator == "<=" and not (value < operand or same):
                return False
        return True

    def __str__(self) -> str:
        if isinstance(self.raw, str):
            return self.raw
        return _fmt(self.raw)


def parse_value(raw) -> typing.Optional[ValueSpec]:
    """A required value, or None for null - which requires nothing."""
    return None if raw is None else ValueSpec(raw)


def parse_vector(raw, what: str):
    """Three required values, or None when the whole vector is null.

    Returns (specs, error): 'specs' is a list of three, each a 'ValueSpec' or
    None, and 'error' says what is wrong with a vector that is not three values.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None, "the %s '%s' is not three values" % (what, _fmt(raw))
    specs = [parse_value(item) for item in raw]
    for spec in specs:
        if spec is not None and spec.error is not None:
            return None, "the %s: %s" % (what, spec.error)
    return specs, None


def _vector_text(specs) -> str:
    return "[%s]" % ", ".join("null" if spec is None else str(spec) for spec in specs)


def _vector_matches(specs, actual, unit: bool = False):
    """Whether a vector is what 'specs' requires, and which component is not.

    'unit' normalizes a requirement whose three components are all plain
    numbers: 'down' is [0, 0, -1] whether or not it was written as one.
    """
    required = list(specs)
    if unit:
        constants = [spec.numeric_constant if spec is not None else None for spec in required]
        if all(constant is not None for constant in constants):
            norm = math.sqrt(sum(constant * constant for constant in constants))
            if norm > 0.0:
                required = [ValueSpec(constant / norm) for constant in constants]
    for axis, spec, value in zip(_AXES, required, actual):
        if spec is not None and not spec.matches(value):
            return False, axis
    return True, None


# ---------------------------------------------------------------------------
# Where a frame is, as a requirement sees it
# ---------------------------------------------------------------------------


def _shortest_turn(direction) -> Location:
    """The smallest rotation that takes +Z to 'direction' (a unit vector).

    Opposite +Z every axis across it is as short as any other, and the turn
    about X is taken: it is how a port facing down is most often written.
    """
    dz = max(-1.0, min(1.0, direction[2]))
    if dz >= 1.0 - 1e-12:
        return Location()
    if dz <= -1.0 + 1e-12:
        return Location([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], 180.0])
    # +Z x direction, which is the axis of the turn.
    return Location([[0.0, 0.0, 0.0], [-direction[1], direction[0], 0.0], math.degrees(math.acos(dz))])


def facing(location: Location):
    """(position, direction, angle) of a frame: what a location requirement reads.

    'direction' is the frame's Z axis, the way a port faces. 'angle' is how far
    its X axis is turned about that direction, in degrees in (-180, 180], from
    where the shortest turn from +Z to the direction leaves it.
    """
    position = tuple(location.translation)
    direction = location.rotate_vector((0.0, 0.0, 1.0))
    x_axis = location.rotate_vector((1.0, 0.0, 0.0))
    reference = _shortest_turn(direction).rotate_vector((1.0, 0.0, 0.0))
    cross = (
        reference[1] * x_axis[2] - reference[2] * x_axis[1],
        reference[2] * x_axis[0] - reference[0] * x_axis[2],
        reference[0] * x_axis[1] - reference[1] * x_axis[0],
    )
    sine = sum(c * d for c, d in zip(cross, direction))
    cosine = sum(r * x for r, x in zip(reference, x_axis))
    angle = wrap_angle(math.degrees(math.atan2(sine, cosine)))
    return position, tuple(direction), angle


class LocationSpec:
    """What a frame's position, direction and angle are required to be; any of them None."""

    KEYS = ("position", "direction", "angle")

    def __init__(self, position=None, direction=None, angle=None):
        self.position = position
        self.direction = direction
        self.angle = angle

    @classmethod
    def parse(cls, raw, extra_keys=()):
        """(LocationSpec or None, the other keys of a mapping, error).

        A list of three is ``[position, direction, angle]``; a mapping says the
        same by key, and may carry the 'extra_keys' a port has beside them.
        """
        if raw is None:
            return None, {}, None
        extra = {}
        if isinstance(raw, (list, tuple)):
            if len(raw) != 3:
                return None, {}, "'%s' is not [position, direction, angle]" % _fmt(raw)
            position, direction, angle = raw
        elif isinstance(raw, dict):
            unknown = sorted(set(raw) - set(cls.KEYS) - set(extra_keys))
            if unknown:
                return (
                    None,
                    {},
                    "%s: not a part of a location requirement, which is %s"
                    % (", ".join("'%s'" % key for key in unknown), ", ".join(cls.KEYS + tuple(extra_keys))),
                )
            position, direction, angle = (raw.get(key) for key in cls.KEYS)
            extra = {key: raw[key] for key in extra_keys if key in raw}
        else:
            return None, {}, "'%s' is not a location requirement" % _fmt(raw)

        position, error = parse_vector(position, "position")
        if error is not None:
            return None, {}, error
        direction, error = parse_vector(direction, "direction")
        if error is not None:
            return None, {}, error
        if isinstance(angle, (list, tuple, dict)):
            return None, {}, "the angle '%s' is not one value" % _fmt(angle)
        angle = parse_value(angle)
        if angle is not None and angle.error is not None:
            return None, {}, "the angle: %s" % angle.error
        spec = cls(position, direction, angle)
        return (None if spec.empty else spec), extra, None

    @property
    def empty(self) -> bool:
        def none(vector):
            return vector is None or all(spec is None for spec in vector)

        return none(self.position) and none(self.direction) and self.angle is None

    def describe(self) -> str:
        parts = []
        if self.position is not None and any(spec is not None for spec in self.position):
            parts.append("position %s" % _vector_text(self.position))
        if self.direction is not None and any(spec is not None for spec in self.direction):
            parts.append("direction %s" % _vector_text(self.direction))
        if self.angle is not None:
            parts.append("angle %s" % self.angle)
        return ", ".join(parts)

    def mismatch(self, location: Location) -> typing.Optional[str]:
        """What about 'location' this does not allow, or None when it allows all of it."""
        position, direction, angle = facing(location)
        if self.position is not None:
            ok, axis = _vector_matches(self.position, position)
            if not ok:
                return "the position is %s, and %s has to be %s" % (
                    _fmt(_rounded(position)),
                    axis,
                    self.position[_AXES.index(axis)],
                )
        if self.direction is not None:
            ok, axis = _vector_matches(self.direction, direction, unit=True)
            if not ok:
                return "it faces %s, and has to face %s" % (_fmt(_rounded(direction)), _vector_text(self.direction))
        if self.angle is not None and not self.angle.matches(angle, angle=True):
            return "it is turned %s degrees about its direction, and has to be %s" % (_fmt(round(angle, 6)), self.angle)
        return None


def _rounded(vector) -> list:
    """A measured vector for a message: six decimals say all there is to say."""
    return [round(value, 6) + 0.0 for value in vector]


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


class PortRequirement:
    """A port the object has to have, and what is required of it."""

    def __init__(self, name: str, location: typing.Optional[LocationSpec], sketch: typing.Optional[ValueSpec]):
        self.name = name
        self.location = location
        self.sketch = sketch

    def describe(self) -> str:
        parts = []
        if self.location is not None:
            parts.append(self.location.describe())
        if self.sketch is not None:
            parts.append("sketch %s" % self.sketch)
        return ", ".join(parts) if parts else "present"


class InterfaceRequirement:
    """An interface the object has to implement, and its instances.

    'instances' is None when any instance anywhere will do; otherwise each named
    instance has to exist, at a location its spec allows. 'anywhere' is a
    location some instance - any of them - has to be at.
    """

    def __init__(self, name: str, instances=None, anywhere: typing.Optional[LocationSpec] = None):
        self.name = name
        self.instances = instances
        self.anywhere = anywhere


class PhysicsRequirement:
    """One physical property, by its path in a 'physics:' section ('mass', 'inertia.ixx')."""

    def __init__(self, path: str, spec=None, vector=None):
        self.path = path
        self.spec = spec
        self.vector = vector

    def describe(self) -> str:
        return _vector_text(self.vector) if self.vector is not None else str(self.spec)


class Problem:
    """A requirement that cannot be read, kept so that it fails rather than vanishes."""

    def __init__(self, section: str, name: str, detail: str):
        self.section = section
        self.name = name
        self.detail = detail


class Declaration:
    """An object's requirements, normalized."""

    def __init__(self):
        self.features: dict = {}
        self.ports: list = []
        self.interfaces: list = []
        self.physics: list = []
        self.problems: list = []

    @property
    def structured(self) -> bool:
        """Whether anything here is for 'pc test' to check."""
        return bool(self.ports or self.interfaces or self.physics or self.problems)

    @property
    def empty(self) -> bool:
        return not self.features and not self.structured


def _physics_fields() -> dict:
    """{field: 'value' | 'vector' | [the fields of a mapping]} that a requirement may name.

    Read off PartCAD's own configuration schema rather than listed here again:
    'requirement-physics' is what may be required, and it is 'physics' less the
    properties of a connection, which a shape does not state (see
    'shape-physics'). A field added to the schema is a field that can be
    required without anyone remembering this module.
    """
    from partcad_utils.assy_lint import PARTCAD_SCHEMA, get_schema

    properties = get_schema(PARTCAD_SCHEMA)["definitions"]["requirement-physics"]["properties"]
    fields = {}
    for name, definition in properties.items():
        if definition.get("$ref", "").endswith("/requirement-vector"):
            fields[name] = "vector"
        elif "properties" in definition:
            fields[name] = list(definition["properties"].keys())
        else:
            fields[name] = "value"
    return fields


def _parse_physics(raw, declaration: Declaration) -> None:
    if not isinstance(raw, dict):
        declaration.problems.append(Problem(PHYSICS, PHYSICS, "'%s' is not a mapping of properties" % _fmt(raw)))
        return
    fields = _physics_fields()
    for name, value in raw.items():
        if value is None:
            continue
        kind = fields.get(name)
        if kind is None:
            declaration.problems.append(
                Problem(
                    PHYSICS,
                    name,
                    "'%s' is not a physical property an object states; it may be one of %s"
                    % (name, ", ".join(sorted(fields))),
                )
            )
        elif kind == "vector":
            specs, error = parse_vector(value, name)
            if error is not None:
                declaration.problems.append(Problem(PHYSICS, name, error))
            elif specs is not None and any(spec is not None for spec in specs):
                declaration.physics.append(PhysicsRequirement(name, vector=specs))
        elif isinstance(kind, list):
            if not isinstance(value, dict):
                declaration.problems.append(Problem(PHYSICS, name, "'%s' is a mapping of %s" % (name, ", ".join(kind))))
                continue
            for member, member_value in value.items():
                path = "%s.%s" % (name, member)
                if member not in kind:
                    declaration.problems.append(
                        Problem(PHYSICS, path, "'%s' is not one of %s" % (member, ", ".join(kind)))
                    )
                    continue
                spec = parse_value(member_value)
                if spec is not None and spec.error is not None:
                    declaration.problems.append(Problem(PHYSICS, path, spec.error))
                elif spec is not None:
                    declaration.physics.append(PhysicsRequirement(path, spec=spec))
        elif isinstance(value, (list, dict)):
            declaration.problems.append(Problem(PHYSICS, name, "'%s' is one value" % name))
        else:
            spec = parse_value(value)
            if spec.error is not None:
                declaration.problems.append(Problem(PHYSICS, name, spec.error))
            else:
                declaration.physics.append(PhysicsRequirement(name, spec=spec))


def _parse_ports(raw, declaration: Declaration) -> None:
    if isinstance(raw, str):
        raw = {raw: None}
    elif isinstance(raw, list):
        raw = {name: None for name in raw if isinstance(name, str)}
    if not isinstance(raw, dict):
        declaration.problems.append(Problem(PORTS, PORTS, "'%s' is not a mapping of port names" % _fmt(raw)))
        return
    for name, value in raw.items():
        location, extra, error = LocationSpec.parse(value, extra_keys=("sketch",))
        if error is not None:
            declaration.problems.append(Problem(PORTS, str(name), error))
            continue
        sketch = parse_value(extra.get("sketch"))
        if sketch is not None and sketch.error is not None:
            declaration.problems.append(Problem(PORTS, str(name), "the sketch: %s" % sketch.error))
            continue
        declaration.ports.append(PortRequirement(str(name), location, sketch))


def _looks_like_location(value) -> bool:
    """Whether a list in an 'interfaces:' requirement is a location rather than instance names."""
    return isinstance(value, (list, tuple)) and len(value) == 3 and not all(isinstance(item, str) for item in value)


def _parse_interfaces(raw, declaration: Declaration) -> None:
    if isinstance(raw, str):
        raw = {raw: None}
    elif isinstance(raw, list):
        raw = {name: None for name in raw if isinstance(name, str)}
    if not isinstance(raw, dict):
        declaration.problems.append(
            Problem(INTERFACES, INTERFACES, "'%s' is not a mapping of interface names" % _fmt(raw))
        )
        return
    for name, value in raw.items():
        name = str(name)
        if value is None:
            declaration.interfaces.append(InterfaceRequirement(name))
        elif isinstance(value, str):
            declaration.interfaces.append(InterfaceRequirement(name, instances={value: None}))
        elif _looks_like_location(value):
            location, _, error = LocationSpec.parse(value)
            if error is not None:
                declaration.problems.append(Problem(INTERFACES, name, error))
            else:
                declaration.interfaces.append(InterfaceRequirement(name, anywhere=location))
        elif isinstance(value, list):
            declaration.interfaces.append(InterfaceRequirement(name, instances={item: None for item in value}))
        elif isinstance(value, dict):
            instances = {}
            for instance, instance_value in value.items():
                location, _, error = LocationSpec.parse(instance_value)
                if error is not None:
                    declaration.problems.append(Problem(INTERFACES, _instance_label(name, instance), error))
                    continue
                instances["" if instance is None else str(instance)] = location
            declaration.interfaces.append(InterfaceRequirement(name, instances=instances))
        else:
            declaration.problems.append(Problem(INTERFACES, name, "'%s' is not an interface requirement" % _fmt(value)))


def _parse_features(raw, declaration: Declaration) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        declaration.problems.append(
            Problem(FEATURES, FEATURES, "'%s' is not a mapping of feature names to descriptions" % _fmt(raw))
        )
        return
    for name, desc in raw.items():
        declaration.features[str(name)] = "" if desc is None else str(desc).strip()


def parse(raw) -> typing.Optional[Declaration]:
    """The requirements a 'requirements:' section declares, or None when there is none.

    The free-form shapes the section had before it had structure are still
    read, as features: a paragraph is one feature ('LEGACY_FEATURE'), a list
    is one per item, and a key of the mapping that is not one of the four
    sections is a feature named by it.
    """
    if raw is None:
        return None
    declaration = Declaration()
    if isinstance(raw, str):
        if raw.strip():
            declaration.features[LEGACY_FEATURE] = raw.strip()
        return declaration
    if isinstance(raw, list):
        for index, item in enumerate(raw, start=1):
            declaration.features[str(index)] = _fmt(item).strip()
        return declaration
    if not isinstance(raw, dict):
        declaration.problems.append(Problem(SECTION, SECTION, "'%s' is not a requirements section" % _fmt(raw)))
        return declaration

    _parse_features(raw.get(FEATURES), declaration)
    for key, value in raw.items():
        if key in (FEATURES, PORTS, INTERFACES, PHYSICS) or value is None:
            continue
        # A free-form paragraph under a heading of its own: the mapping form of
        # the section before it had structure. A feature by another name, and
        # one the structured section has not already named.
        declaration.features.setdefault(str(key), _fmt(value).strip())
    if raw.get(PORTS) is not None:
        _parse_ports(raw[PORTS], declaration)
    if raw.get(INTERFACES) is not None:
        _parse_interfaces(raw[INTERFACES], declaration)
    if raw.get(PHYSICS) is not None:
        _parse_physics(raw[PHYSICS], declaration)
    return declaration


def of_shape(shape) -> typing.Optional[Declaration]:
    """The requirements an object declares, through whatever it resolves to.

    'final_config()' rather than 'config', for the reason 'simulation.of_shape'
    reads it: an alias and an enrich answer for what they point at, and an
    enrich that states requirements of its own states them on top.
    """
    from .shape_config import final_config

    config = final_config(shape)
    return parse(config.get(SECTION) if isinstance(config, dict) else None)


def _instance_label(interface: str, instance) -> str:
    """How one instance of an interface is named in a report."""
    return "%s (%s)" % (interface, "unnamed" if instance in (None, "") else instance)


# ---------------------------------------------------------------------------
# What the model is
# ---------------------------------------------------------------------------


def _instance_full_name(state: str, instance: str) -> str:
    """An inherited instance's name, the way 'WithPorts.instantiate_interfaces' composes it."""
    if instance and state:
        return state + "-" + instance
    return instance or state


def implemented_interfaces(shape) -> dict:
    """{interface full name: {instance name: [Location]}} of everything 'shape' implements.

    Every level of the inheritance, abstract interfaces included, each instance
    placed where it is in the object's own frame: implementing 'm3-thru' is
    implementing 'm3' as well, which is what "has an M3 hole" means to
    'pc search --interface' too (see 'shape_ports.interface_closure').

    A list per instance, because one inherited interface can be reached under
    the same instance name by more than one path - two interfaces that both
    inherit it - and each path places it where its own instance is. Keeping only
    the first would fail a location the second meets.
    """
    from .shape_ports import port_carrier

    carrier = port_carrier(shape)
    found: dict = {}
    if carrier is None or not hasattr(carrier, "get_parents"):
        return found

    def walk(parents, state: str, placement: Location, seen: frozenset) -> None:
        for inherit in (parents or {}).values():
            interface = getattr(inherit, "interface", None)
            if interface is None:
                continue
            names = {inherit.name, getattr(interface, "full_name", inherit.name)}
            for instance, location in (inherit.instances or {}).items():
                full = _instance_full_name(state, instance)
                placed = placement * (location if location is not None else Location())
                for name in names:
                    found.setdefault(name, {}).setdefault(full, []).append(placed)
                key = (interface.full_name, full)
                if key not in seen:
                    walk(interface.get_parents(), full, placed, seen | {key})

    walk(carrier.get_parents(), "", Location(), frozenset())
    return found


def _sketch_spellings(port) -> set:
    """Every name a port's boundary sketch answers to: qualified or not, with its parameters or without."""
    spellings = set()
    for attribute in ("source_sketch_spec", "source_sketch_name"):
        value = getattr(port, attribute, None)
        if value:
            spellings.add(value)
    sketch = getattr(port, "sketch", None)
    if sketch is not None:
        spellings.add(sketch.name)
        spellings.add("%s:%s" % (sketch.project_name, sketch.name))
    spellings |= {spelling.split(";", 1)[0] for spelling in spellings}
    return spellings


def _stated_physics(shape) -> dict:
    """What an object's 'properties: physics:' states about itself."""
    from .shape_config import final_config

    config = final_config(shape) or {}
    properties = config.get("properties") if isinstance(config, dict) else None
    physics = properties.get("physics") if isinstance(properties, dict) else None
    return physics if isinstance(physics, dict) else {}


# What the solid a part or an assembly is made of works out when it does not
# state them (see 'partcad.physics'). For an assembly some of whose parts weigh
# nothing known, these are what the others add up to - not the assembly's.
_FROM_THE_SOLID = ("mass", "centerOfMass", "inertia")


async def resolve_physics_async(ctx, shape, paths) -> dict:
    """{path: (value or None, source or reason)} for each property asked about.

    What 'pc info' says the object's physics is, by the code that says it
    ('physics.resolved_async()'): what it states, what its material lends - a
    density, a friction - and what its solid works out to - a mass, a centre of
    mass, an inertia, or for an assembly what its parts add up to. A scene and a
    sketch have what they state and nothing else. A value none of that gives is
    reported as unknown, which fails a requirement on it: PartCAD cannot say it
    is met.
    """
    from . import physics as pc_physics

    resolved = await pc_physics.resolved_async(ctx, shape)
    if resolved is None:
        stated = _stated_physics(shape)
        physics, sources, unknown = dict(stated), {key: pc_physics.STATED for key in stated}, None
    else:
        physics, sources, unknown = resolved
        # Said the way 'pc info' prints it, which starts with what the
        # report around it already says.
        unknown = unknown.removeprefix("not known: ") if unknown else unknown

    # An assembly's total over the parts that could be weighed is not what it
    # weighs; a part's centre of mass is its solid's whether or not anything
    # says what the solid is made of.
    partial = unknown is not None and getattr(shape, "kind", None) == "assembly"

    answers = {}
    for path in paths:
        head, _, member = path.partition(".")
        value = physics.get(head)
        source = sources.get(head, pc_physics.STATED)
        if member:
            value = value.get(member) if isinstance(value, dict) else None
        from_the_solid = head in _FROM_THE_SOLID and unknown is not None
        if value is None:
            # A part's reason is why it has no mass, which is also why it has
            # no inertia; its centre of mass is its solid's, and has another.
            weighs = partial or head in ("mass", "inertia")
            reason = (
                unknown if from_the_solid and weighs else "it states no '%s', and nothing it is made of says" % path
            )
            answers[path] = (None, reason)
        elif partial and from_the_solid and source != pc_physics.STATED:
            answers[path] = (None, unknown)
        else:
            answers[path] = (value, source)
    return answers


# ---------------------------------------------------------------------------
# The verdicts
# ---------------------------------------------------------------------------


class Check:
    """One requirement and what the model made of it.

    'passed' is None until the model has been asked - a report that only lists
    the requirements, which is what the IDE shows while a check is running.
    """

    def __init__(self, section: str, name: str, requirement: str, passed=None, detail=None):
        self.section = section
        self.name = name
        self.requirement = requirement
        self.passed: typing.Optional[bool] = passed
        self.detail: typing.Optional[str] = detail

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "name": self.name,
            "requirement": self.requirement,
            "passed": self.passed,
            "detail": self.detail,
        }

    def __repr__(self) -> str:
        return "<requirement %s:%s %s: %s>" % (self.section, self.name, self.requirement, self.passed)


class Report:
    """Everything about one object's requirements: the features, and a check per requirement."""

    def __init__(self, object_name: str, kind: str, declaration: typing.Optional[Declaration]):
        self.object_name = object_name
        self.kind = kind
        self.declaration = declaration
        self.verified = False
        self.checks: list = []
        # feature name -> the 'simulate:' entries that name it, in declaration order.
        self.simulations: dict = {}
        # feature name -> the analysis scenarios that name it, as
        # {"analysis": "fea", "name": "<scenario>"}, in the order 'cae.ANALYSES'
        # and then each section lists them.
        self.analyses: dict = {}

    @property
    def defined(self) -> bool:
        return self.declaration is not None and not self.declaration.empty

    @property
    def failed(self) -> list:
        return [check for check in self.checks if check.passed is False]

    def to_dict(self) -> dict:
        features = []
        for name, desc in (self.declaration.features if self.declaration is not None else {}).items():
            features.append(
                {
                    "name": name,
                    "desc": desc,
                    "simulations": list(self.simulations.get(name, [])),
                    "analyses": [dict(entry) for entry in self.analyses.get(name, [])],
                }
            )
        return {
            "object": self.object_name,
            "kind": self.kind,
            "defined": self.defined,
            "verified": self.verified,
            "features": features,
            "requirements": [check.to_dict() for check in self.checks],
        }


def _feature_references(shape, declaration: typing.Optional[Declaration], report: Report) -> None:
    """Which 'simulate:' entries and analysis scenarios demonstrate which feature, and which name one nobody declared."""
    from . import cae, simulation

    features = declaration.features if declaration is not None else {}
    declared = (": they declare %s" % ", ".join(sorted(features))) if features else ""
    for entry in simulation.of_shape(shape):
        for feature in entry.features:
            if feature in features:
                report.simulations.setdefault(feature, []).append(entry.name)
            else:
                report.checks.append(
                    Check(
                        SIMULATE,
                        entry.name,
                        "feature %s" % feature,
                        passed=False,
                        detail="the simulation names the feature '%s', which the requirements do not declare%s"
                        % (feature, declared),
                    )
                )

    for analysis in cae.ANALYSES:
        try:
            scenarios = cae.of_shape(shape, analysis)
        except cae.CaeConfigError:
            # A section that cannot be read is its analysis's own check to
            # fail, with the sentence saying why; nothing in it names anything.
            continue
        for scenario in scenarios:
            for feature in scenario.features:
                if feature in features:
                    report.analyses.setdefault(feature, []).append({"analysis": analysis, "name": scenario.name})
                    continue
                report.checks.append(
                    Check(
                        analysis,
                        scenario.name,
                        "feature %s" % feature,
                        passed=False,
                        detail="the %s scenario '%s' names the feature '%s', which the requirements do not declare%s"
                        % (cae.LABELS[analysis], scenario.name, feature, declared),
                    )
                )


def _declared_checks(declaration: Declaration) -> dict:
    """{section: [(requirement, Check)]} with nothing verified yet."""
    checks = {PORTS: [], INTERFACES: [], PHYSICS: []}
    for port in declaration.ports:
        checks[PORTS].append((port, Check(PORTS, port.name, port.describe())))
    for interface in declaration.interfaces:
        if interface.instances is None:
            text = interface.anywhere.describe() if interface.anywhere is not None else "implemented"
            checks[INTERFACES].append((interface, Check(INTERFACES, interface.name, text)))
            continue
        for instance, location in interface.instances.items():
            text = location.describe() if location is not None else "present"
            check = Check(INTERFACES, _instance_label(interface.name, instance), text)
            checks[INTERFACES].append(((interface, instance, location), check))
    for physics in declaration.physics:
        checks[PHYSICS].append((physics, Check(PHYSICS, physics.path, physics.describe())))
    return checks


async def _verify_ports(ctx, shape, entries) -> None:
    from . import shape_ports

    await shape_ports.prepare_async(shape, ctx)
    ports = {record.name: record for record in shape_ports.own_ports(shape)}
    for requirement, check in entries:
        record = ports.get(requirement.name)
        if record is None:
            check.passed = False
            check.detail = "there is no port '%s'; %s" % (
                requirement.name,
                ("the ports are %s" % ", ".join(sorted(ports))) if ports else "it has no ports",
            )
            continue
        problem = requirement.location.mismatch(record.location) if requirement.location is not None else None
        if problem is None and requirement.sketch is not None:
            spellings = _sketch_spellings(record.port)
            if not requirement.sketch.matches(
                spellings, equal=lambda actual, required: _sketch_matches(shape, actual, required)
            ):
                drawn = sorted(spellings)
                problem = "its sketch is %s, and has to be %s" % (drawn[0] if drawn else "none", requirement.sketch)
        check.passed = problem is None
        check.detail = problem if problem is not None else _where(record.location)


def _sketch_matches(shape, spellings: set, required) -> bool:
    """Whether a required sketch name is one of the names a port's sketch answers to."""
    from .utils import resolve_resource_path

    if not spellings:
        return False
    required = str(required)
    candidates = {required, required.split(";", 1)[0]}
    try:
        package, name = resolve_resource_path(shape.project_name, required)
        candidates |= {"%s:%s" % (package, name), "%s:%s" % (package, name.split(";", 1)[0])}
    except Exception:  # pylint: disable=broad-except
        pass
    return bool(candidates & spellings)


def _where(location: Location) -> str:
    position, direction, angle = facing(location)
    return "at %s, facing %s, turned %s" % (
        _fmt(_rounded(position)),
        _fmt(_rounded(direction)),
        _fmt(round(angle, 6)),
    )


def _matching_interfaces(shape, name: str, implemented: dict) -> list:
    """The implemented interfaces a required name stands for.

    Resolved the way an 'implements:' key is, against the object's own package;
    a bare name nothing there declares is matched by its short name, the way
    'pc search --interface' matches one (see 'shape_ports.implementers').
    """
    from .shape_ports import qualified_interface_name, short_interface_name

    project = getattr(getattr(shape, "with_ports", None), "project", None)
    qualified = None
    if project is not None:
        try:
            qualified = qualified_interface_name(project, name)
        except Exception:  # pylint: disable=broad-except
            qualified = None
    if qualified is not None and qualified in implemented:
        return [qualified]
    if ":" in name:
        return []
    return [full for full in implemented if short_interface_name(full) == name]


async def _verify_interfaces(ctx, shape, entries) -> None:
    from . import shape_ports

    await shape_ports.prepare_async(shape, ctx)
    implemented = implemented_interfaces(shape)
    for entry, check in entries:
        if isinstance(entry, tuple):
            requirement, instance, location = entry
        else:
            requirement, instance, location = entry, None, None
        names = _matching_interfaces(shape, requirement.name, implemented)
        instances = {}
        for name in names:
            for instance_name, placements in implemented[name].items():
                instances.setdefault(instance_name, []).extend(placements)
        if not instances:
            check.passed = False
            check.detail = "it does not implement '%s'" % requirement.name
            continue

        if not isinstance(entry, tuple):
            if requirement.anywhere is None:
                check.passed = True
                check.detail = "implemented: %s" % _instance_list(instances)
                continue
            fitting = [
                name
                for name, placements in instances.items()
                if any(requirement.anywhere.mismatch(placed) is None for placed in placements)
            ]
            check.passed = bool(fitting)
            if fitting:
                check.detail = "%s %s there" % (
                    ", ".join(_instance_name(name) for name in fitting),
                    "is" if len(fitting) == 1 else "are",
                )
            else:
                check.detail = "no instance is at %s: %s" % (
                    requirement.anywhere.describe(),
                    "; ".join(
                        "%s %s" % (_instance_name(name), _where_any(placements))
                        for name, placements in instances.items()
                    ),
                )
            continue

        placements = instances.get(instance)
        if not placements:
            check.passed = False
            check.detail = "there is no %s: %s" % (
                "instance '%s'" % instance if instance else "unnamed instance",
                _instance_list(instances),
            )
            continue
        if location is None:
            check.passed = True
            check.detail = _where(placements[0])
            continue
        problems = [location.mismatch(placed) for placed in placements]
        fitting = [placed for placed, problem in zip(placements, problems) if problem is None]
        check.passed = bool(fitting)
        check.detail = _where(fitting[0]) if fitting else "; ".join(dict.fromkeys(problems))


def _where_any(placements: list) -> str:
    """Where an instance is, by every path that places it: once, if they all agree."""
    return " and ".join(dict.fromkeys(_where(placed) for placed in placements))


def _instance_name(name: str) -> str:
    return "'%s'" % name if name else "the unnamed one"


def _instance_list(instances: dict) -> str:
    names = [_instance_name(name) for name in instances]
    return ("the instances are %s" % ", ".join(names)) if len(names) > 1 else "the instance is %s" % names[0]


# The unit each physical property is stated in, for a report to say beside the
# number: the units 'physics' states its fields in (see the schema). A property
# that is dimensionless, a count or a flag has none.
_PHYSICS_UNITS = {
    "mass": "kg",
    "density": "kg/m^3",
    "centerOfMass": "mm",
    "inertiaOrientation": "degrees",
    "inertia": "kg*m^2",
    "contactStiffness": "N/m",
    "contactDamping": "N*s/m",
    "minContactDepth": "mm",
    "maxContactVelocity": "mm/s",
}


def _quantity(path: str, value) -> str:
    unit = _PHYSICS_UNITS.get(path.partition(".")[0])
    return "%s %s" % (_fmt(value), unit) if unit else _fmt(value)


async def _verify_physics(ctx, shape, entries) -> None:
    resolved = await resolve_physics_async(ctx, shape, [requirement.path for requirement, _ in entries])
    for requirement, check in entries:
        value, source = resolved.get(requirement.path, (None, "unknown"))
        if value is None:
            check.passed = False
            check.detail = "not known: %s" % source
            continue
        if requirement.vector is not None:
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                check.passed = False
                check.detail = "it is %s (%s), which is not three values" % (_fmt(value), source)
                continue
            ok, axis = _vector_matches(requirement.vector, value)
            check.passed = ok
            check.detail = "%s (%s)%s" % (
                _quantity(requirement.path, value),
                source,
                "" if ok else ", and %s does not match" % axis,
            )
            continue
        check.passed = requirement.spec.matches(value)
        check.detail = "%s (%s)" % (_quantity(requirement.path, value), source)


def _declared(shape):
    """The report on 'shape' with nothing verified, and its checks by section.

    Every check a verified report will hold is already in it - the
    declarations that cannot be read, a 'simulate:' entry or an analysis
    scenario naming a feature nobody declares, and a line per port, interface
    and physical property -
    so whether there is anything to check is known before anything is built.
    """
    object_name = "%s:%s" % (shape.project_name, shape.name)
    declaration = of_shape(shape)
    report = Report(object_name, getattr(shape, "kind", "part"), declaration)

    if declaration is not None:
        for problem in declaration.problems:
            report.checks.append(
                Check(problem.section, problem.name, "unreadable", passed=False, detail=problem.detail)
            )
    _feature_references(shape, declaration, report)
    if declaration is None:
        return report, None
    sections = _declared_checks(declaration)
    for section in STRUCTURED:
        report.checks.extend(check for _, check in sections[section])
    return report, sections


def anything_to_check(shape) -> bool:
    """Whether 'pc test' has anything to check 'shape' against: what its 'requirements' test applies to."""
    return bool(_declared(shape)[0].checks)


async def check_async(ctx, shape, verify: bool = True) -> Report:
    """The requirements of one object, and - when 'verify' - whether the model meets each.

    Without 'verify' nothing is asked of the model: the report lists what is
    required and leaves every verdict None. That costs a declaration read, which
    is what lets the IDE decide on every show whether there is a Requirements
    tab to offer at all.

    A section the model cannot be asked about - its ports would not resolve, it
    would not build - fails every requirement in it, saying why, rather than
    failing the report: the other sections still have something to say.
    """
    report, sections = _declared(shape)
    object_name = report.object_name
    if report.declaration is None:
        report.verified = verify
        return report
    if not verify:
        return report

    verifiers = {PORTS: _verify_ports, INTERFACES: _verify_interfaces, PHYSICS: _verify_physics}
    for section in STRUCTURED:
        entries = sections[section]
        if not entries:
            continue
        try:
            await verifiers[section](ctx, shape, entries)
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("%s: the %s requirements could not be checked: %s" % (object_name, section, e))
            for _, check in entries:
                if check.passed is None:
                    check.passed = False
                    check.detail = "could not be checked: %s" % e
    report.verified = True
    return report
