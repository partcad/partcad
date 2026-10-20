#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a part says about the analyses that can be run on it, and in what units.

Computer-aided *engineering* is the third thing PartCAD does with a shape, beside
writing it out (`export:`) and drawing it (`render:`). It has the same shape as
those two and is configured the same way -- a `cae:` section whose subsections are
file types, each naming the package and script that implements it -- and it is run
by `pc cae <analysis>`. What it adds is a second output beside the file: the
**findings**, a JSON array of what the analysis has to say about the part.

PartCAD runs four analyses, each its own question with its own command:

* `fea` -- does the part hold up under what it carries (`pc cae fea`);
* `dynamic` -- at what frequencies does it ring, held as it is (`pc cae dynamic`);
* `thermal` -- how hot does it get, heated and cooled as it is (`pc cae thermal`);
* `cfd` -- how does a fluid flow through it (`pc cae cfd`).

The boundary conditions are not part of that configuration. They belong to the
part, because they are a property of the part rather than of whoever analyses it:
a bracket is bolted down at the same holes and carries the same load whichever
solver is asked about it. So a part declares them in a section named after the
analysis::

    parts:
      bracket:
        type: build123d
        path: bracket.py
        fea:
          fix:
            - m3-screw           # every instance of this interface is held
          load:
            mount-point: 5 kg    # every instance carries this
            hook:
              left: 30 N         # one named instance carries this
              right: 30 N
        dynamic:
          fix:
            - m3-screw           # held where it is bolted down, and left to ring
        thermal:
          temperature:
            heatsink: 40 C       # held at a temperature
          heat:
            chip: 5 W            # heat put in through the port's surface
          convection:
            fins: 10             # cooled by the air around it, in W/(m^2*K)

Every key names interfaces the part implements, in one of two shapes. A *set*
(`fix:`, `outlet:`) is a list of interface types, or a map from an interface type
to the list of its instances. A *value* (`load:`, `temperature:`, `heat:`,
`convection:`) is a map from an interface type to one value for all of its
instances, or a nested map naming the instance. `ROLES` says which analysis reads
which key and how each is read; an analysis is refused a key it does not read,
because a key taken silently would read as a boundary condition and not be one.

`fea:` takes `fix:` and `load:`, and one key that names no interface:
`gravity:`, the acceleration of free fall the part is analysed in, in m/s^2 and
in the part's own frame. An implementation weighs the part under its own idea of
gravity otherwise (CalculiX: 9.81 m/s^2 along -Z, with `self_weight`), which is
right for a part standing the way it is drawn and wrong for one a simulation
found upside down, or accelerating -- where what it carries is its weight less
its mass times its acceleration, `g - a` (see `parse_gravity`). `cfd:` takes the
same two -- the walls the fluid
is held still against, and the force driving it in -- and `outlet:`, where it
leaves. `dynamic:` takes `fix:` alone: a natural frequency is a property of the
part and how it is held, not of what it carries. `thermal:` takes
`temperature:`, `heat:` and `convection:`.

The values are stored in one unit each, whatever unit they were written in:

* `load` values are **forces**, in newtons. A value may be a bare number or a
  string ending in a unit name (see `parse_force`), and a bare number is read as
  a *mass* in kilograms -- which is what a user writing "the shelf carries 5"
  means. A mass becomes a force by weighing it: `GRAVITY` newtons per kilogram.
  A force so stated is a magnitude, and an implementation applies it the way it
  always has (CalculiX along -Z, "where a weight goes"). A value may also be a
  **vector**, three of those, in the part's own frame -- `[0 N, -146 N, 12 N]`
  -- which is a force *with a direction*: what a simulation measured acting on
  the part, which is seldom straight down (see `parse_load`).
* `temperature` values are in **degrees Celsius**; a bare number is one, and
  "300 K" or "100 F" are converted (see `parse_temperature`).
* `heat` values are a **power**, in watts, put in through the whole of the
  port's surface (see `parse_power`).
* `convection` values are a **film coefficient**, in W/(m^2*K), against the
  ambient temperature the implementation is configured with (see
  `parse_film_coefficient`).

A direction and a gravity are two things an implementation has to *read*, and
one that does not would apply the load straight down and weigh the part under
its own gravity, and answer as if it had been asked. So an implementation says
which of them it reads, as `reads:` on its file type (`READS`), and an analysis
that states either is refused by one that does not say it reads it rather than
answered wrongly (see `unread_by`).

Where a condition lands is a port, and a port is a coordinate frame -- and,
when its interface draws it with a sketch, a surface: the circle of a bore, the
outline of a mounting pad. The sketch travels with the port to the sandbox, where
it is imprinted on the part and turned into the faces the condition is applied
to (see `wrappers/cae_support.py`). A port with no sketch is applied to the face
it lies on, when it lies on one.

Nothing here imports a CAD library or touches geometry. It reads the
configuration, converts the units, and hands the result to an implementation that
runs in a sandbox like every other one.
"""

from __future__ import annotations

import platform
import re
from typing import Callable, Optional

# The analyses. Each is a file type of the `cae:` section (so an implementation
# is declared exactly as an `export:` or `render:` one is), a section a part
# declares its boundary conditions in, and a `pc cae` subcommand.
FEA = "fea"
CFD = "cfd"
DYNAMIC = "dynamic"
THERMAL = "thermal"
# In the order a reader meets them: the structural pair, then heat, then flow.
# Which is also the order the IDE lays its tabs out in.
ANALYSES = (FEA, DYNAMIC, THERMAL, CFD)

# What each analysis is called where there is room for words: in a report, a
# heading, a tab. The name above is what is typed; this is what is read.
LABELS = {
    FEA: "FEA",
    DYNAMIC: "Dynamic FEA",
    THERMAL: "Heat Transfer",
    CFD: "CFD",
}

# Newtons per kilogram. The task this was written for names 9.8 rather than
# 9.80665; a fraction of a percent means nothing to a finding, and reproducing
# the number a user was told to expect means everything.
GRAVITY = 9.8

# The instance name that stands for "every instance of this interface". It
# cannot collide with a real one: PartCAD spells the unnamed instance of an
# interface as the empty string (see WithPorts.instantiate_interfaces), and every
# named one matches '^[a-zA-Z0-9_/.-]+$'.
EVERY_INSTANCE = "*"

# Unit names, lowercased and singular, longest match first when parsing. The
# task names 'nm' for force alongside the plain 'n'; both are newtons here.
_MASS_UNITS = {
    "mg": 1e-6,
    "g": 1e-3,
    "kg": 1.0,
    "ton": 1000.0,
    "tonne": 1000.0,
    "lb": 0.45359237,
    "pound": 0.45359237,
}
_FORCE_UNITS = {
    "n": 1.0,
    "nm": 1.0,
    "mn": 1e-3,
    "kn": 1e3,
    "newton": 1.0,
}

# Longest first, so that "5mg" is milligrams rather than 5 m of "g", and "5kn"
# is kilonewtons rather than an unparseable "5k" of newtons.
_UNIT_NAMES = sorted(set(_MASS_UNITS) | set(_FORCE_UNITS), key=len, reverse=True)

# What a number may look like in front of a unit: an ordinary decimal, with an
# optional sign and an optional exponent.
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


class CaeConfigError(ValueError):
    """A `fea:`/`cfd:` section that cannot be made sense of.

    Carried rather than logged, because every caller has a different place to put
    it: `pc cae` prints it, `pc test` fails the part with it, and the IDE's FEA
    tab shows it where the results would have been. "It is malformed" is the
    answer the user asked for in each case, so it has to survive as a sentence.
    """


class CaeFailed(Exception):
    """An analysis that was asked and produced no answer.

    Carries what `dysfunction_report()` writes, and is raised by
    `Shape.analyze_async()` around every way an implementation can fail to
    deliver -- no mesher, no solver, a sandbox that will not build, a crash. It
    exists so that the sentence is written once, where the implementation's name
    is known, rather than by each caller: `pc cae` prints it, `pc test` fails
    the part with it, and the IDE's tab shows it, and a user who saw one of
    those and then ran another must not be told two different things about the
    same machine.

    Not `CaeConfigError`, and the distinction is the action it asks for: that
    one means the part's own section is wrong and is fixed by editing it, this
    one means the part is fine and the machine or the plugin is not.
    """


def parse_force(value, what: str = "value") -> float:
    """One `load:` value, in newtons.

    Accepts a number or a string ending in a unit name. The unit is matched
    case-insensitively, with or without a space in front of it and with or
    without a plural "s": "5kg", "5 KG", "5 kgs" and "5 Kilograms"... well, not
    the last one -- the names are the ones in `_MASS_UNITS`/`_FORCE_UNITS`, plus
    a trailing "s".

    A value with no unit is a **mass in kilograms**, which is the documented
    default. Mass is converted to force by weighing it, so what comes back is
    always newtons, whichever way it was written.

    Raises:
        CaeConfigError: the value is neither a number nor a number and a unit.
    """
    if isinstance(value, bool):
        # bool is an int in Python, and "load: true" is not a load.
        raise CaeConfigError("%s is not a number: %r" % (what, value))
    if isinstance(value, (int, float)):
        # A bare number is a mass in kilograms.
        return float(value) * GRAVITY
    if not isinstance(value, str):
        raise CaeConfigError("%s is not a number: %r" % (what, value))

    text = value.strip()
    if not text:
        raise CaeConfigError("%s is empty" % what)

    lowered = text.lower()
    for unit in _UNIT_NAMES:
        for spelling in (unit + "s", unit):
            if not lowered.endswith(spelling):
                continue
            number = text[: len(text) - len(spelling)].strip()
            if not _NUMBER.match(number):
                # "moons" ends in "n" without being a number of newtons. Keep
                # looking: a shorter unit name may still make sense of it.
                continue
            amount = float(number)
            if unit in _FORCE_UNITS:
                return amount * _FORCE_UNITS[unit]
            return amount * _MASS_UNITS[unit] * GRAVITY

    if _NUMBER.match(text):
        return float(text) * GRAVITY

    raise CaeConfigError(
        "%s is not a force or a mass: %r. Write a number (kilograms), or a number and a unit (%s)"
        % (what, value, ", ".join(sorted(set(_MASS_UNITS) | set(_FORCE_UNITS))))
    )


def parse_load(value, what: str = "value"):
    """One `load:` value: a force in newtons, or a force vector in newtons.

    A number or a string is a magnitude (see `parse_force`) and comes back as a
    float. A list of three is a vector in the part's own frame -- each component
    a force or a mass exactly as a magnitude is, so `[0 N, 0 N, -49 N]` and
    `[0, 0, -5]` (five kilograms, weighed) are the same downward force -- and
    comes back as a list of three floats. A vector of nought pulls on nothing,
    and is refused, as a section naming a port it then does nothing to would be
    a condition doing nothing.

    Raises:
        CaeConfigError: neither a force nor three of them.
    """
    if not isinstance(value, (list, tuple)):
        return parse_force(value, what)
    if len(value) != 3:
        raise CaeConfigError(
            "%s is a list of %d, and a force with a direction is three: [x, y, z], in the part's own frame"
            % (what, len(value))
        )
    vector = [parse_force(component, "the %s of %s" % (axis, what)) for axis, component in zip("xyz", value)]
    if not any(vector):
        raise CaeConfigError("%s is a force of nought in every direction: %r" % (what, value))
    return vector


def magnitude(load) -> float:
    """The size of a `parse_load` value, in newtons: itself for a magnitude, the length of a vector."""
    if isinstance(load, list):
        return sum(component * component for component in load) ** 0.5
    return float(load)


# The ways an acceleration's unit gets written. Accepted so that a value can say
# what it is; there is nothing to convert, since this is the only unit.
_ACCELERATION_UNITS = {
    "m/s2": 1.0,
    "m/s^2": 1.0,
    "m/s²": 1.0,
    "m/s/s": 1.0,
}


def parse_gravity(value, what: str = "'fea: gravity:'") -> list:
    """`gravity:` -- the acceleration of free fall the part is analysed in, m/s^2, in its own frame.

    Three numbers, each a number of m/s^2 or a string saying so ("9.81 m/s^2").
    What a simulation's reading gives as `g - a` at the part: the gravity of the
    scene, less the part's own acceleration, turned into the part's frame -- the
    weight a part held upside down hangs by, or a part swung round a corner is
    flung by. `[0, 0, 0]` is a part analysed weightless, which is a thing worth
    saying.

    Raises:
        CaeConfigError: not three accelerations.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CaeConfigError(
            "%s is not an acceleration: %r. Write three numbers, m/s^2, in the part's own frame" % (what, value)
        )
    return [
        _number_and_unit(component, "the %s of %s" % (axis, what), _ACCELERATION_UNITS, None, "an acceleration")[0]
        for axis, component in zip("xyz", value)
    ]


def _number_and_unit(value, what: str, units, default: Optional[str], kind: str):
    """A value as (number, unit), with `units` the spellings it may end in.

    The common half of every parser below. A bare number carries `default`; a
    string is a number followed by one of `units`, matched case-insensitively,
    longest first, with or without a space in front of it. What a string ends in
    that is not a unit is a sentence naming the field and what it takes, because
    that sentence is what `pc cae` prints and the IDE's tab shows.
    """
    if isinstance(value, bool):
        raise CaeConfigError("%s is not a number: %r" % (what, value))
    if isinstance(value, (int, float)):
        return float(value), default
    if not isinstance(value, str) or not value.strip():
        raise CaeConfigError("%s is not %s: %r" % (what, kind, value))

    text = value.strip()
    if _NUMBER.match(text):
        return float(text), default
    compact = text.lower().replace(" ", "")
    for unit in sorted(units, key=len, reverse=True):
        if compact.endswith(unit):
            number = compact[: len(compact) - len(unit)]
            if _NUMBER.match(number):
                return float(number), unit
    raise CaeConfigError(
        "%s is not %s: %r. Write a number, or a number and a unit (%s)" % (what, kind, value, ", ".join(sorted(units)))
    )


# Temperature units, as the offset and scale that make each one Celsius. Only
# these three: a Rankine or a Reaumur in a part file is far likelier to be a typo
# than a temperature.
_TEMPERATURE_UNITS = {
    "c": "c",
    "°c": "c",
    "degc": "c",
    "celsius": "c",
    "k": "k",
    "kelvin": "k",
    "f": "f",
    "°f": "f",
    "degf": "f",
    "fahrenheit": "f",
}

# The temperature below which nothing is: a held temperature under it is a typo
# (a kelvin written as Celsius), not a cryostat.
ABSOLUTE_ZERO = -273.15


def parse_temperature(value, what: str = "value") -> float:
    """One `temperature:` value, in degrees Celsius.

    A bare number is Celsius, because that is what a person writing "the
    heatsink is held at 40" means. "313 K" and "104 F" are converted. A value
    below absolute zero is refused rather than solved: it is always a kelvin
    figure written without its unit, or a sign that should not be there.
    """
    number, unit = _number_and_unit(value, what, _TEMPERATURE_UNITS, "c", "a temperature")
    kind = _TEMPERATURE_UNITS.get(unit, "c")
    if kind == "k":
        celsius = number + ABSOLUTE_ZERO
    elif kind == "f":
        celsius = (number - 32.0) * 5.0 / 9.0
    else:
        celsius = number
    if celsius < ABSOLUTE_ZERO:
        raise CaeConfigError("%s is below absolute zero: %r" % (what, value))
    return celsius


_POWER_UNITS = {
    "w": 1.0,
    "watt": 1.0,
    "watts": 1.0,
    "mw": 1e-3,
    "kw": 1e3,
}


def parse_power(value, what: str = "value") -> float:
    """One `heat:` value, in watts: the power put in through the port's surface.

    A power rather than a flux, for the reason `load:` is a force rather than a
    pressure: it is what a datasheet says about the thing at the port -- a chip
    dissipates 5 W, whatever the size of the pad it sits on. The implementation
    divides it by the area it lands on. A negative value is heat taken out,
    which is a thing a Peltier element does, so it is allowed.
    """
    number, unit = _number_and_unit(value, what, _POWER_UNITS, "w", "a power")
    return number * _POWER_UNITS.get(unit, 1.0)


# The ways a film coefficient's unit gets written. Accepted so that a value can
# say what it is; there is nothing to convert, since this is the only unit.
_FILM_UNITS = {
    "w/m2k": 1.0,
    "w/m^2k": 1.0,
    "w/m²k": 1.0,
    "w/(m2k)": 1.0,
    "w/(m2*k)": 1.0,
    "w/(m^2*k)": 1.0,
    "w/(m²·k)": 1.0,
    "w/m2/k": 1.0,
}


def parse_film_coefficient(value, what: str = "value") -> float:
    """One `convection:` value: a film coefficient, in W/(m^2*K).

    Roughly 5-25 for still air, 25-250 for moving air, hundreds to thousands
    for a liquid. A negative one would be a surface that heats up by being
    cooled, so it is refused.
    """
    number, _unit = _number_and_unit(value, what, _FILM_UNITS, None, "a film coefficient")
    if number < 0:
        raise CaeConfigError("%s is a negative film coefficient: %r" % (what, value))
    return number


def _instance_names(value, what: str) -> list[str]:
    """The instances a `fix:` entry names: a name, a list of them, or all."""
    if value is None:
        return [EVERY_INSTANCE]
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise CaeConfigError("%s names an instance that is not a name: %r" % (what, item))
        if not value:
            # Not the same as `None`. Writing nothing under an interface says
            # "all of it"; writing an empty list is naming the instances and
            # then naming none, which is what `load: {}` is already refused for.
            raise CaeConfigError("%s names no instance" % what)
        return list(value)
    raise CaeConfigError("%s is neither an interface instance nor a list of them: %r" % (what, value))


# The two shapes a boundary condition comes in. A *set* names where something is
# true -- held still, open to the outside -- and is a list or a map of instances.
# A *value* says how much of something lands there -- a force, a temperature --
# and is a map to a number or to a map of numbers per instance. Nothing else:
# every key any analysis takes is one of the two, which is what lets one parser,
# one matcher and one schema shape serve them all.
SET = None


class Role:
    """One key of an analysis section: its name, its shape, how it is read.

    Attributes:
        key: the key as a part writes it, `fix` or `temperature`.
        parse: None for a set; for a value, the function turning what was
            written into the stored unit (`parse_force`, `parse_temperature`).
        attribute: where `AnalysisConfig` keeps it, for the three keys that
            predate this table and are read by name -- `fixtures`, `loads`,
            `outlets`.
    """

    def __init__(self, key: str, parse: Optional[Callable] = SET, attribute: Optional[str] = None) -> None:
        """Describe one key; see the class docstring for the fields."""
        self.key = key
        self.parse = parse
        self.attribute = attribute or key

    @property
    def is_set(self) -> bool:
        """Whether the key names where (a set) rather than how much (a value)."""
        return self.parse is SET


_FIX = Role("fix", attribute="fixtures")
_LOAD = Role("load", parse_load, attribute="loads")
_OUTLET = Role("outlet", attribute="outlets")

# Which keys each analysis reads, in the order a reader of an error meets them.
#
# `dynamic:` reads `fix:` and nothing else on purpose: a natural frequency is a
# property of the part and of how it is held. What it carries changes it too --
# a mass bolted on rings lower -- but `load:` is a force, and a force is not a
# mass to vibrate; a key for carried masses is a change of its own.
#
# `thermal:` shares no key with the others, because nothing in a heat problem is
# "held" or "pulled": a surface is held at a temperature, heated, or cooled.
ROLES = {
    FEA: (_FIX, _LOAD),
    CFD: (_FIX, _LOAD, _OUTLET),
    DYNAMIC: (_FIX,),
    THERMAL: (
        Role("temperature", parse_temperature),
        Role("heat", parse_power),
        Role("convection", parse_film_coefficient),
    ),
}


# The keys of an analysis section that name no interface, by analysis: what the
# whole part is analysed under rather than where something lands on it. Each is
# read by the function beside it. 'gravity:' is a stress analysis's: the weight
# a part carries of itself, which a natural frequency and a flow do not ask for
# and a temperature has nothing to do with.
SECTION_KEYS = {
    FEA: {"gravity": parse_gravity},
}

# What an implementation may say it reads, as 'reads:' on its file type, beyond
# where each condition lands and how big it is -- which every implementation
# reads. Each is the request key it is handed under:
#
# * 'force' -- a load's direction: the boundary record of a port a vector
#   `load:` names carries the vector as 'force', in newtons and the part's frame,
#   beside the magnitude under 'load' an implementation has always read;
# * 'gravity' -- the request carries the section's `gravity:`.
#
# An implementation that does not list one is handed it all the same and would
# not know it was there, so an analysis that states it is refused by it rather
# than answered as if it had not (see 'unread_by').
READS = ("force", "gravity")


class AnalysisConfig:
    """The boundary conditions one part declares for one analysis.

    Every member is keyed by the interface type as the part spelled it -- short
    or fully qualified, exactly as `implements:` and `connect:` spell it -- and
    matched against a part's resolved interfaces by `assign_ports()`.

    Attributes:
        analysis: one of `ANALYSES`.
        conditions: key -> interface type -> the instances (a set) or
            instance -> value (a value), for every key `ROLES` gives this
            analysis, whether or not the part used it. The instance `"*"` is
            every instance of that interface.
        fixtures: `conditions["fix"]`: interface type -> the instances held
            still. Empty for an analysis that takes no `fix:`.
        loads: `conditions["load"]`: interface type -> instance -> newtons.
        outlets: `conditions["outlet"]`: the instances the fluid leaves through.
            `cfd:` only -- a stress analysis has nothing to let out.
        implementation: who runs this analysis, as `<package>:<file type>`, or
            None to leave it to the user configuration. A part that names one is
            saying "this is the solver I was written against", which is a
            property of the part rather than of the machine -- and it is what
            lets a package ship a working analysis without every user first
            pointing `caeFeaImplementation` at the right place.
    """

    def __init__(self, analysis: str, config: Optional[dict]) -> None:
        """Read one analysis section, converting every value to its stored unit.

        Raises:
            CaeConfigError: the section is absent, is not a mapping, names a key
                this analysis does not read, declares none it does, or holds a
                value that is not what its key takes. Every one of those is a
                sentence rather than a code, because it is what `pc cae` prints
                and what the IDE's tab shows where the results would have been.
        """
        if analysis not in ROLES:
            raise CaeConfigError("Unknown analysis '%s'; PartCAD runs %s" % (analysis, ", ".join(ANALYSES)))
        self.analysis = analysis
        self.roles = ROLES[analysis]
        self.conditions: dict[str, dict] = {role.key: {} for role in self.roles}
        self.implementation: Optional[str] = None
        # The keys naming no interface this analysis takes, and what the part
        # said under each: 'gravity' -> [gx, gy, gz] for a stress analysis
        # that states one. Absent when it states none.
        self.section_keys = SECTION_KEYS.get(analysis, {})
        self.settings: dict = {}

        if config is None:
            raise CaeConfigError("'%s:' is empty" % analysis)
        if not isinstance(config, dict):
            raise CaeConfigError("'%s:' is not a section: %r" % (analysis, config))

        # A key another analysis reads is refused here as firmly as a misspelt
        # one. `outlet:` on a stress analysis, or `fix:` on a heat one, would
        # read as a boundary condition and not be one.
        keys = [role.key for role in self.roles] + list(self.section_keys) + ["desc", "implementation"]
        unknown = [key for key in config if key not in keys]
        if unknown:
            raise CaeConfigError(
                "'%s:' does not take %s; it takes %s and 'implementation:'"
                % (
                    analysis,
                    ", ".join(sorted(unknown)),
                    ", ".join("'%s:'" % key for key in [role.key for role in self.roles] + list(self.section_keys)),
                )
            )

        self._parse_implementation(config.get("implementation"))
        for role in self.roles:
            if role.is_set:
                self._parse_set(role, config.get(role.key))
            else:
                self._parse_values(role, config.get(role.key))
        for key, parse in self.section_keys.items():
            if config.get(key) is not None:
                self.settings[key] = parse(config[key], "'%s: %s:'" % (analysis, key))

        if not any(self.conditions.values()):
            if analysis in (FEA, CFD):
                # The sentence these two always said, and that their tests and
                # the IDE's tab still look for.
                raise CaeConfigError("'%s:' declares neither 'fix:' nor 'load:'" % analysis)
            raise CaeConfigError(
                "'%s:' declares none of %s" % (analysis, ", ".join("'%s:'" % role.key for role in self.roles))
            )

    @property
    def gravity(self) -> Optional[list]:
        """The acceleration of free fall the part is analysed in, m/s^2 in its frame, or None for the implementation's."""
        return self.settings.get("gravity")

    @property
    def directed(self) -> bool:
        """Whether any load is stated with a direction (a vector) rather than as a magnitude."""
        return any(isinstance(load, list) for values in self.loads.values() for load in values.values())

    def reads(self) -> set:
        """What of 'READS' an implementation has to read to answer this section as it was written."""
        needed = set()
        if self.directed:
            needed.add("force")
        if self.gravity is not None:
            needed.add("gravity")
        return needed

    @property
    def fixtures(self) -> dict[str, list[str]]:
        """What is held still: interface type -> the instances held."""
        return self.conditions.get("fix", {})

    @property
    def loads(self) -> dict[str, dict[str, float]]:
        """What is pulled on: interface type -> instance -> newtons."""
        return self.conditions.get("load", {})

    @property
    def outlets(self) -> dict[str, list[str]]:
        """Where a fluid leaves: interface type -> the instances it leaves by."""
        return self.conditions.get("outlet", {})

    def _parse_implementation(self, implementation) -> None:
        """Read `implementation:`, which names who runs this analysis.

        Checked only for being a non-empty name here. Whether the package exists
        and declares that file type is `Shape._analysis_implementation()`'s
        question, asked where the packages are: this class deliberately imports
        nothing from `partcad`, which is what lets it be tested without a
        sandbox.
        """
        if implementation is None:
            return
        if not isinstance(implementation, str) or not implementation.strip():
            raise CaeConfigError(
                "'%s: implementation:' is not a '<package>:<file type>' name: %r" % (self.analysis, implementation)
            )
        self.implementation = implementation.strip()

    def _parse_set(self, role: Role, value) -> None:
        """Read a set -- `fix:`, `outlet:` -- which comes in three shapes that mean two things.

        A bare name and a list of them say "every instance of these interfaces";
        a mapping says which instances, and an entry with nothing under it means
        the whole of that interface again. All three normalize to the same
        `interface -> instances` mapping, so nothing downstream has to know
        which spelling the package used.

        `outlet:` is a set because an incompressible flow is posed by
        *differences* in pressure. `load:` says what drives the flow in; with
        nothing saying where it goes, the problem has no downstream reference
        and a solver answers it with a dead field or with a divergence -- which
        is what it did, and what that key was added for.
        """
        if value is None:
            return
        found = self.conditions[role.key]
        if isinstance(value, str):
            # One interface type, held whole. The degenerate case of the list.
            found[value] = [EVERY_INSTANCE]
            return
        if isinstance(value, list):
            for entry in value:
                if not isinstance(entry, str):
                    raise CaeConfigError("'%s:' names an interface that is not a name: %r" % (role.key, entry))
                found[entry] = [EVERY_INSTANCE]
            return
        if isinstance(value, dict):
            for interface, instances in value.items():
                found[interface] = _instance_names(instances, "'%s: %s:'" % (role.key, interface))
            return
        raise CaeConfigError("'%s:' is neither a list of interfaces nor a map of them: %r" % (role.key, value))

    def _parse_values(self, role: Role, value) -> None:
        """Read a value -- `load:`, `temperature:` -- converting each to its stored unit.

        Flat (`hook: 5 kg`) applies to every instance of the interface; nested
        (`rail: {left: 30 N}`) names the instance. Unlike a set there is no list
        form -- a list of interfaces would say where without saying how much,
        which is not a boundary condition.
        """
        if value is None:
            return
        if not isinstance(value, dict):
            raise CaeConfigError("'%s:' is not a map of interfaces to values: %r" % (role.key, value))
        found = self.conditions[role.key]
        for interface, amount in value.items():
            if isinstance(amount, dict):
                # The nested form: one value per named instance.
                if not amount:
                    raise CaeConfigError("'%s: %s:' names no instance" % (role.key, interface))
                found[interface] = {
                    instance: role.parse(each, "'%s: %s: %s:'" % (role.key, interface, instance))
                    for instance, each in amount.items()
                }
            else:
                found[interface] = {EVERY_INSTANCE: role.parse(amount, "'%s: %s:'" % (role.key, interface))}

    @property
    def interfaces(self) -> list[str]:
        """Every interface type this analysis has something to say about."""
        names = []
        for role in self.roles:
            names.extend(name for name in self.conditions[role.key] if name not in names)
        return names

    def to_data(self) -> dict:
        """This configuration as the plain data an implementation is handed.

        `fix` and `load` are always there for the two analyses that have always
        sent them, empty or not, so an implementation written against them
        reads exactly what it always read. Every other key is there only when
        the part used it: an implementation that has never heard of outlets is
        handed the request it always was, and a part that names none is not told
        it has an empty one.
        """
        data = {"analysis": self.analysis}
        for role in self.roles:
            found = self.conditions[role.key]
            if not found and not (self.analysis in (FEA, CFD) and role.key in ("fix", "load")):
                continue
            if role.is_set:
                data[role.key] = {name: list(instances) for name, instances in found.items()}
            elif role is _LOAD:
                # Magnitudes under 'load', which is what an implementation has
                # always read there; the directions, where the part states
                # them, under 'force' beside it ('READS').
                data[role.key] = {
                    name: {instance: magnitude(load) for instance, load in values.items()}
                    for name, values in found.items()
                }
                directed = {
                    name: {instance: list(load) for instance, load in values.items() if isinstance(load, list)}
                    for name, values in found.items()
                }
                directed = {name: values for name, values in directed.items() if values}
                if directed:
                    data["force"] = directed
            else:
                data[role.key] = {name: dict(values) for name, values in found.items()}
        for key, value in self.settings.items():
            data[key] = list(value) if isinstance(value, list) else value
        if self.implementation is not None:
            # Carried so that `pc test`'s cache key changes when the part is
            # re-pointed at another solver: two solvers are two answers, and the
            # verdict on one must not be handed back for the other.
            data["implementation"] = self.implementation
        return data

    def __repr__(self) -> str:
        """The parsed conditions, with every value in the unit it became."""
        return "AnalysisConfig(%r, %s)" % (
            self.analysis,
            ", ".join("%s=%r" % (role.key, self.conditions[role.key]) for role in self.roles),
        )


def config_of(shape, analysis: str) -> Optional[AnalysisConfig]:
    """The boundary conditions a shape declares for an analysis, or None.

    None means the shape said nothing at all, which is the ordinary case and not
    an error: most parts are never analysed. A shape that declared the section
    but got it wrong raises `CaeConfigError`, because that is a mistake the user
    wants to hear about.
    """
    if analysis not in ANALYSES:
        raise CaeConfigError("Unknown analysis '%s'; PartCAD runs %s" % (analysis, ", ".join(ANALYSES)))
    get_final_config = getattr(shape, "get_final_config", None)
    config = get_final_config() if callable(get_final_config) else getattr(shape, "config", None)
    if not isinstance(config, dict) or analysis not in config:
        return None
    return AnalysisConfig(analysis, config[analysis])


def _matches(record_interface: Optional[str], declared_name: str) -> bool:
    """Whether a port's interface is the one a boundary condition names.

    A part names an interface the way it names one everywhere else: short for one
    of its own package's, qualified for anyone else's. The resolved records carry
    the qualified name and the short one beside it, so both spellings are
    accepted -- and a qualified declaration is never satisfied by a same-named
    interface of another package.
    """
    if record_interface is None:
        return False
    if record_interface == declared_name:
        return True
    if ":" in declared_name:
        return False
    return record_interface.rsplit(":", 1)[-1] == declared_name


def assign_ports(config: AnalysisConfig, records: list) -> tuple[list, list[str]]:
    """Attach the boundary conditions to the ports they name.

    `records` is what `render_overlay.collect_async()` produces: one entry per
    port of the shape, carrying the interface it belongs to, the instance, where
    it is, and the sketch it is drawn with if it has one. Each record that a
    condition names comes back with that condition on it, under the condition's
    own key: `True` for a set (`fix`, `outlet`), the value in its stored unit
    for a value (`load` in newtons, `temperature` in Celsius, ...). The ones
    nothing names are left out, because an implementation is being told where
    to hold the part and where to pull it, not what the part's other ports are.

    A name under an interface is an instance of it, or one of its *ports*: the
    one a connection names with
    `withPort:`/`toPort:`. That is how one tooth of a gear is named, whose
    twenty-eight teeth are the ports of one instance of one interface, and one
    hole of a four-hole pattern. An instance's own value wins over the
    interface-wide one, and a port's over its instance's.

    A value written for every instance of an interface is applied to every
    instance of it -- **not** divided between them. "This interface carries 5 kg"
    reads as each of them carrying it, which is the conservative reading and the
    one a user checking a bracket wants; "this pad dissipates 2 W" likewise.

    Returns the assigned records and the declarations nothing matched, as
    `(name, reason)` pairs. The reason matters: an interface the part does not
    implement at all and an interface whose *named instance* does not exist are
    both silent no-ops, and reporting the first for the second hides a misspelt
    instance name behind a sentence saying the interface is missing. Either way
    it is a boundary condition doing nothing, which is worth a warning every
    time -- a solver told to hold nothing still answers with nonsense rather
    than with an error.
    """
    assigned = []
    # What actually landed somewhere, as (key, interface, the *instance the
    # declaration named*). Per instance and not merely per interface: a `fix:`
    # naming two bolts of which the object has one would otherwise count as
    # satisfied by the one, and the other would go unheld with nothing said --
    # which a solver answers with a plausible number rather than an error.
    matched: set[tuple[str, str, str]] = set()
    # Which declared interfaces exist on the object at all, whatever instance
    # they carry. What tells "not implemented" from "no such instance".
    interfaces_seen: set[str] = set()

    for record in records:
        interface = record.get("interface")
        instance = record.get("instance") or ""
        # A name under the interface may also be one of its ports.
        port = record.get("port")
        entry = None

        for name in config.interfaces:
            if _matches(interface, name):
                interfaces_seen.add(name)

        for role in config.roles:
            for name, declared in config.conditions[role.key].items():
                if not _matches(interface, name):
                    continue
                if role.is_set:
                    # Both spellings are recorded when both apply, because both
                    # are declarations a user could have got wrong on their own.
                    named = [one for one in (EVERY_INSTANCE, instance, port) if one is not None and one in declared]
                    if not named:
                        continue
                    matched.update((role.key, name, one) for one in named)
                    entry = entry or dict(record)
                    entry[role.key] = True
                else:
                    # The instance's own value wins over the interface-wide one,
                    # so it is the one that counts as used.
                    one = port if port is not None and port in declared else instance
                    one = one if one in declared else EVERY_INSTANCE
                    amount = declared.get(one)
                    if amount is None:
                        continue
                    matched.add((role.key, name, one))
                    entry = entry or dict(record)
                    if role is _LOAD and isinstance(amount, list):
                        # The magnitude where an implementation has always
                        # read it, and the direction beside it ('READS').
                        entry[role.key] = magnitude(amount)
                        entry["force"] = list(amount)
                    else:
                        entry[role.key] = amount

        if entry is not None:
            if config.analysis in (FEA, CFD):
                # What a record handed to a stress or a flow implementation has
                # always carried, so one written before the others existed reads
                # it exactly as it did.
                entry.setdefault("fix", False)
                entry.setdefault("load", 0.0)
                # Only where the part has outlets at all, so that a record
                # handed to an implementation that has never heard of them
                # looks exactly as it always did.
                if config.outlets:
                    entry.setdefault("outlet", False)
            else:
                # The newer analyses are told about every key they read, set or
                # not, so an implementation reads `record["heat"]` rather than
                # guessing whether an absent key means zero.
                for role in config.roles:
                    entry.setdefault(role.key, False if role.is_set else None)
            assigned.append(entry)

    unmatched = []
    for role in config.roles:
        for name, wanted in config.conditions[role.key].items():
            # A set holds a list of instance names and a value a map of them to
            # amounts; iterating either yields the names, which is all this
            # needs.
            missing = [one for one in wanted if (role.key, name, one) not in matched]
            if not missing:
                continue
            if name not in interfaces_seen:
                unmatched.append((name, "this object does not implement it"))
                continue
            named = ", ".join(sorted(str(one) for one in missing if one != EVERY_INSTANCE))
            unmatched.append((name, "no instance or port named %s" % named if named else "it names no instance of it"))
    return assigned, unmatched


def unread_by(config: AnalysisConfig, reads, implementation: str) -> Optional[str]:
    """Why 'implementation' cannot answer 'config' as written, or None when it can.

    'reads' is what the implementation's file type says it reads ('reads:',
    see 'READS'). A load stated with a direction, or a gravity, handed to one
    that does not read it is applied straight down, or under the
    implementation's own gravity, and answered as if nothing had been said --
    so it is refused, saying what to do about it, rather than answered.
    """
    missing = sorted(config.reads() - set(reads or ()))
    if not missing:
        return None
    # What each one is, what an implementation that does not read it does
    # instead, and what to write instead of it.
    said = {
        "force": ("a load with a direction", "every load pulled straight down", "the loads as magnitudes"),
        "gravity": ("'gravity:'", "the part stood as it is drawn", "no 'gravity:'"),
    }
    return (
        "'%s:' states %s, and %s does not read %s (its 'reads:' lists %s): it would answer as if %s. "
        "Name an implementation that reads %s, or state %s"
        % (
            config.analysis,
            " and ".join(said[key][0] for key in missing),
            implementation,
            "it" if len(missing) == 1 else "them",
            ", ".join("'%s'" % key for key in sorted(reads or ())) or "nothing",
            " and ".join(said[key][1] for key in missing),
            " and ".join("'%s'" % key for key in missing),
            " and ".join(said[key][2] for key in missing),
        )
    )


def normalize_findings(findings) -> list[dict]:
    """What an implementation reported, as the JSON array the protocol promises.

    An implementation may report a list of strings, a list of objects, or
    nothing. Everything becomes a list of objects carrying at least a `message`,
    because that is what `pc cae` prints, what `pc test` fails on and what the
    IDE lists under the model -- and a reader of any of the three should not have
    to know which shape the implementation happened to choose.
    """
    if not findings:
        return []
    if isinstance(findings, dict):
        findings = [findings]
    if not isinstance(findings, list):
        return [{"message": str(findings)}]

    normalized = []
    for finding in findings:
        if isinstance(finding, dict):
            entry = dict(finding)
            if "message" not in entry:
                # Whatever it called the text, so that a finding is never a row
                # of blanks with the detail hidden in a key nobody prints.
                for key in ("text", "description", "desc", "title", "summary"):
                    if key in entry:
                        entry["message"] = str(entry[key])
                        break
                else:
                    entry["message"] = str(finding)
            normalized.append(entry)
        else:
            normalized.append({"message": str(finding)})
    return normalized


# What to do about an analysis that could not run because this machine has no
# container runtime. Said by PartCAD rather than by the implementation, because
# the implementation never ran and so cannot say anything at all -- and said as
# two remedies rather than one, because either fixes it and only the reader
# knows which is easier where they are.
NO_RUNTIME_REMEDY = (
    "Either start a container runtime, or install what this implementation needs on this machine: "
    "an implementation that names a 'dockerImage' also declares the requirements to run without one."
)


def dysfunction_report(
    name: str, analysis: str, implementation: str, error: Exception, remedy: Optional[str] = None
) -> str:
    """Why an analysis produced no answer, as the failure a user has to act on.

    The reasons need different actions -- install a solver, use another machine,
    fix the package -- and only the implementation knows which one this is. So
    what it said is reported verbatim rather than classified here: PartCAD does
    not know what `ccx` is, and a rule here that recognised it would be wrong for
    the next implementation.

    What this adds is the two things the sentence usually omits and the reader
    always needs: which implementation was asked, and which machine it did not
    work on. "gmsh is not installed" is a puzzle; the same sentence under
    `//pub/feature/cae/calculix:fea on Linux-aarch64` is an answer.
    """
    lines = [
        "%s: %s could not be run by %s" % (name, analysis.upper(), implementation),
        "\t%s" % str(error).replace("\n", "\n\t"),
        "\tplatform: %s-%s, Python %s" % (platform.system(), platform.machine(), platform.python_version()),
    ]
    if remedy:
        lines.append("\t%s" % remedy)
    return "\n".join(lines)


def findings_report(name: str, analysis: str, findings: list) -> str:
    """The findings as `pc cae` prints them: one line each, worst first."""
    if not findings:
        return "%s: %s found nothing to report" % (name, analysis.upper())

    order = {"error": 0, "critical": 0, "warning": 1, "info": 2}
    ranked = sorted(findings, key=lambda f: order.get(str(f.get("severity", "")).lower(), 1))

    lines = ["%s: %s findings:" % (name, analysis.upper())]
    for finding in ranked:
        severity = str(finding.get("severity") or "warning").upper()
        where = finding.get("where") or finding.get("location") or ""
        line = "\t%s\t%s" % (severity, finding.get("message", ""))
        if where:
            line += "\t(%s)" % where
        lines.append(line)
    lines.append("Total: %d finding(s)" % len(findings))
    return "\n".join(lines)
