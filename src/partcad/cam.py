#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object says about the route a machine cuts it with.

Computer-aided *manufacturing* is the fourth thing PartCAD does with a shape,
beside writing it out (`export:`), drawing it (`render:`) and analysing it
(`cae:`). It has the same shape as those three and is configured the same way --
a `cam:` section whose subsections are file types, each naming the package and
script that implements it -- and it is run by `pc cam`. What it produces is the
**route file**: the program a CNC machine runs, as a file beside the package.

Unlike `cae:`, PartCAD ships an implementation of it: `//builtin/cam` writes
G-code. A route is arithmetic on the object's own outline rather than somebody
else's program with a release cycle of its own, which is the test `export:` and
`render:` already pass and `cae:` does not -- so it ships here for the same
reason DXF does, and a package replaces it by declaring `gcode` (or a file type
of its own) in its own `cam:` section.

The job is not part of that configuration in the sense that matters. What is cut
and how deep is a property of **the object** -- a panel is 18 mm thick and has
to be cut through whoever routes it -- so the object states it, in the section
that already says how it is made::

    parts:
      panel:
        type: build123d
        path: panel.py
        manufacturing:
          method: subtractive
          source: sheet          # the stock it comes out of
          cnc:
            operation: profile   # around the outside of it
            diameter: 6 mm       # the cutter
            depth: 18 mm         # how far down from the top of the shape
            depth_per_pass: 6 mm
            feed: 1200           # mm/min
            plunge: 300          # mm/min
            speed: 18000         # rpm
            safe_z: 5 mm

**Saying something about being cut is the object's opt-in**, and it is the whole
of it: `pc cam` with no object named produces a route for every object of the
package that does, and for nothing else. An object that says nothing is not a
failure and is not reported as one -- most objects are never cut on this
machine. `declares_job` is that question, asked without judging the answer.

There are two scopes, and the difference between them is the point of having
two. What is written directly under `manufacturing:` is shared by every machine
the object names; what is written inside a machine's own subsection is that
machine's and outranks the shared value. So a part that could be cut either way
says `feed: 1800` once and lets the laser say `power: 85` for itself.

Each machine takes only the keys it actually reads, which is what a single flat
namespace could not express. A laser has no `diameter:` -- it has no cutter, and
`kerf:` is what it removes -- so writing one in `laser:` is an error naming what
a laser does take, rather than a value silently ignored. A drill has no `depth:`
and no `feed:`; a part is free to write either in the shared scope, where it
simply is not read by a machine that has no use for it.

An object may name **several** machines. They are alternatives -- ways it could
be made -- rather than stages it goes through, so `pc cam` writes for one of
them and asks which where there is a choice. A part that really is machined in
stages is a chain of parts, each naming the previous one as its `source`,
because each stage has its own geometry and its own stock.

A *sketch* has one of these sections too, and no `method:` in it: a drawing is
not made from anything, it is a path a machine follows. What it does have is a
`depth:`, and uniquely so -- a part has a thickness to be cut through and a
sketch does not, so how deep to score is the one thing it has to answer.

What an object may *not* set is the half that describes the file rather than the
cut -- `//builtin/cam`'s `units`, `precision`, `tolerance` and `comments`, and
whatever an implementation PartCAD has never seen calls its own. Those stay with
the file type, in a package's `cam:` section. The reason is `KEYS` below: a
section is checked against a list, and a list can only hold what PartCAD knows
the name of, so the closed set is what buys the error message.

That split is also why the word `cam:` now means exactly one thing. It used to
mean two -- the file types a package declares, and the job an object declared --
and the ambiguity was managed by keeping the two key sets disjoint. The job
lives in `manufacturing:` now, beside the method and the machine it belongs to,
so `cam:` is the implementation registry and nothing else.

`partcad.test.manufacturability` is the neighbouring idea and not this one: it
is the `pc test` check that asks whether an object can be made or bought at all
-- whether its geometry suits the method it declares, whether what it is made
from is reproducible, whether a supplier could be found. This says how to make
it. Both are computer-aided manufacturing, which is why that check was called
`cam` until `pc cam` existed and the one word had to answer two questions;
`partcad.test.cam` is now the check that this module backs.

Nothing here imports a CAD library or touches geometry. It reads the
configuration, converts the units, and hands the result to an implementation that
runs in a sandbox like every other one.
"""

from __future__ import annotations

import re
from typing import Optional

# The operations a route can be. Each says what the tool does with the outline
# the object's section is taken as, and the difference between them is which
# side of it the tool runs on:
#
#   'profile'  around the outside of the material, so the object survives the
#              cut at its nominal size. The tool is offset outward by its own
#              radius on the outer boundary and inward on every hole.
#   'pocket'   inside the outline, clearing what is within it: the same offset
#              as a profile's holes, then concentric rings stepping inward by
#              'stepover' until nothing is left.
#   'engrave'  along the outline itself, offset by nothing. What a V-bit or a
#              drag knife does, and what a diameter means nothing to.
PROFILE = "profile"
POCKET = "pocket"
ENGRAVE = "engrave"
OPERATIONS = (PROFILE, POCKET, ENGRAVE)

# Which way round a contour is cut. It decides which side of the tool the chip
# comes off and which of the two edges is the finished one, so it is a property
# of how this object is made rather than of the file it is written to -- which
# is why it is a job key and `units:` is not.
CLIMB = "climb"
CONVENTIONAL = "conventional"
DIRECTIONS = (CLIMB, CONVENTIONAL)

# Every key an object's `cam:` section may hold, and what kind of value each is.
# Everything in here reaches the implementation as a parameter; what is not in
# here is refused (see the module docstring for why this set is closed).
#
# The units are the ones the implementation is handed, not the ones a user
# writes: lengths arrive in millimetres and feeds in millimetres per minute,
# whatever spelling the configuration used. The file type decides what the file
# says (`units:` on `//builtin/cam`'s `gcode`), which is a separate question --
# a route written in inches is still cut to the depth the part declared.
# 'kerf' is here with the rest although it describes the machine rather than the
# cut: once the job and the machine live in one section there is one vocabulary,
# and a length is read the same way whichever of the two it belongs to. Which
# keys each machine will *accept* is a separate question, and the one
# 'part_config_manufacturing.MACHINE_JOB_KEYS' answers.
LENGTH_KEYS = ("diameter", "depth", "depth_per_pass", "safe_z", "peck", "kerf")
FEED_KEYS = ("feed", "plunge")
# 'power' is how hard a laser fires, as the fraction or the S-word its
# controller reads. Chosen per cut rather than fixed by the machine -- a thicker
# part on the same laser is cut harder -- which is why it is a job parameter and
# 'kerf' is the machine's own.
NUMBER_KEYS = ("speed", "stepover", "power")
KEYS = LENGTH_KEYS + FEED_KEYS + NUMBER_KEYS + ("operation", "direction", "implementation", "desc")


def value_parsers() -> dict:
    """Which parser reads each key, for whoever holds a section of these.

    One table rather than three loops repeated at every call site: the
    `manufacturing:` section is read in several scopes -- shared, and once per
    machine the part names -- and each of them wants "6", "6 mm" and "0.25 in"
    to mean one cutter. The keys whose values are words rather than quantities
    are absent, because there is nothing to convert about them.
    """
    parsers = {}
    for key in LENGTH_KEYS:
        parsers[key] = parse_length
    for key in FEED_KEYS:
        parsers[key] = parse_feed
    for key in NUMBER_KEYS:
        parsers[key] = parse_number
    return parsers


# Millimetres per unit, lowercased and singular, for every spelling a length may
# carry. Millimetres are the base because that is what CAD works in here and
# what the request travels in.
_LENGTH_UNITS = {
    "um": 1e-3,
    "µm": 1e-3,
    "micron": 1e-3,
    "mm": 1.0,
    "cm": 10.0,
    "dm": 100.0,
    "m": 1000.0,
    "mil": 0.0254,
    "thou": 0.0254,
    "in": 25.4,
    "inch": 25.4,
    '"': 25.4,
    "ft": 304.8,
    "foot": 304.8,
    "feet": 304.8,
}

# Longest first, so that "5mm" is millimetres rather than 5 m of "m", and "5in"
# is inches rather than an unparseable "5i" of "n". The same rule 'partcad.cae'
# parses a force with, and for the same reason.
_LENGTH_NAMES = sorted(_LENGTH_UNITS, key=len, reverse=True)

# How long a minute is in each spelling of a feed's denominator. A feed is a
# length over a time, and both halves are written the way a machinist writes
# them: "1200" is millimetres per minute, "1200 mm/min" says so, "20 mm/s" is
# the same speed said differently, and "60 in/min" is imperial.
_PER_MINUTE = {
    "min": 1.0,
    "minute": 1.0,
    "m": 1.0,
    "s": 60.0,
    "sec": 60.0,
    "second": 60.0,
}

# What a number may look like in front of a unit: an ordinary decimal, with an
# optional sign and an optional exponent.
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def _spellings(unit: str) -> tuple:
    """How one unit name may be written, longest first.

    Plurals, because "6 mms" and "0.25 inches" are what people write. The "es"
    one is only offered where English would use it -- a unit ending in a
    sibilant -- so that "mes" is not a spelling of metres and "12 items" is not
    twelve of anything.
    """
    plurals = [unit + "s"]
    if unit.endswith(("ch", "s", "sh", "x", "z")):
        plurals.insert(0, unit + "es")
    return tuple(plurals) + (unit,)


class CamConfigError(ValueError):
    """A `cam:` section that cannot be made sense of.

    Carried rather than logged, for the reason `CaeConfigError` is: every caller
    has a different place to put it. `pc cam` prints it and stops, and a
    recursive run reports it against the object it belongs to and carries on
    with the rest -- an object whose section is wrong must not cost the other
    nineteen their routes.
    """


class CamFailed(Exception):
    """A route that was asked for and did not come back.

    Carries what `dysfunction_report()` writes, and is raised by
    `Shape.route_async()` around every way an implementation can fail to deliver
    -- no implementation, a sandbox that will not build, a crash, a file that
    was never written.

    Not `CamConfigError`, and the distinction is the action it asks for: that one
    means the object's own section is wrong and is fixed by editing it, this one
    means the object is fine and the machine or the plugin is not.
    """


def parse_length(value, what: str = "value") -> float:
    """One length, in millimetres.

    Accepts a number or a string ending in a unit name, case-insensitively, with
    or without a space in front of it: "6", "6mm", "6 MM", "0.25 in", '0.25"'.
    A value with no unit is millimetres, which is what the rest of PartCAD
    measures in.

    Raises:
        CamConfigError: the value is neither a number nor a number and a unit,
            or is not positive. A tool of zero diameter and a depth of zero are
            both a route that cuts nothing, which is a mistake rather than a
            degenerate case worth supporting.
    """
    amount = _parse_scaled(value, what, _LENGTH_UNITS, _LENGTH_NAMES, "a length")
    if amount <= 0:
        raise CamConfigError("%s is not a positive length: %r" % (what, value))
    return amount


def parse_feed(value, what: str = "value") -> float:
    """One feed rate, in millimetres per minute.

    A bare number is millimetres per minute. A string may name the length unit,
    the time unit, or both: "1200", "1200 mm/min", "20 mm/s", "60 in/min".

    Raises:
        CamConfigError: the value cannot be read as a feed, or is not positive.
            A feed of zero is a move that never finishes.
    """
    if isinstance(value, bool):
        raise CamConfigError("%s is not a number: %r" % (what, value))
    if isinstance(value, (int, float)):
        rate = float(value)
    elif isinstance(value, str):
        text = value.strip()
        per_minute = 1.0
        if "/" in text:
            text, _, denominator = text.rpartition("/")
            key = denominator.strip().lower().rstrip(".")
            if key not in _PER_MINUTE:
                raise CamConfigError(
                    "%s is not a feed: %r. The time is one of %s" % (what, value, ", ".join(sorted(set(_PER_MINUTE))))
                )
            per_minute = _PER_MINUTE[key]
        rate = _parse_scaled(text, what, _LENGTH_UNITS, _LENGTH_NAMES, "a feed") * per_minute
    else:
        raise CamConfigError("%s is not a number: %r" % (what, value))
    if rate <= 0:
        raise CamConfigError("%s is not a positive feed: %r" % (what, value))
    return rate


def parse_number(value, what: str = "value") -> float:
    """One plain positive number: a spindle speed in rpm, or a stepover."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise CamConfigError("%s is not a number: %r" % (what, value))
    if isinstance(value, str):
        text = value.strip()
        # "18000 rpm" is the one spelling worth accepting, because it is how a
        # spindle speed is written everywhere else. It scales nothing.
        for suffix in ("rpm", "rev/min", "r/min"):
            if text.lower().endswith(suffix):
                text = text[: -len(suffix)].strip()
                break
        if not _NUMBER.match(text):
            raise CamConfigError("%s is not a number: %r" % (what, value))
        number = float(text)
    else:
        number = float(value)
    if number <= 0:
        raise CamConfigError("%s is not a positive number: %r" % (what, value))
    return number


def _parse_scaled(value, what: str, units: dict, names: list, noun: str) -> float:
    """A number, optionally carrying one of `names`, in the base unit."""
    if isinstance(value, bool):
        # bool is an int in Python, and "depth: true" is not a depth.
        raise CamConfigError("%s is not a number: %r" % (what, value))
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise CamConfigError("%s is not a number: %r" % (what, value))

    text = value.strip()
    if not text:
        raise CamConfigError("%s is empty" % what)

    lowered = text.lower()
    for unit in names:
        for spelling in _spellings(unit):
            if not lowered.endswith(spelling):
                continue
            number = text[: len(text) - len(spelling)].strip()
            if not _NUMBER.match(number):
                # "12 items" ends in "m" without being 12 metres of anything.
                # Keep looking: a shorter unit name may still make sense of it.
                continue
            return float(number) * units[unit]

    if _NUMBER.match(text):
        return float(text)

    raise CamConfigError(
        "%s is not %s: %r. Write a number (millimetres), or a number and a unit (%s)"
        % (what, noun, value, ", ".join(sorted(units)))
    )


class CamConfig:
    """The route one object declares for itself.

    Attributes:
        operation: what the tool does with the outline -- one of `OPERATIONS`,
            or None where the object did not say and the file type's default
            stands.
        values: every job parameter the object declared, in millimetres,
            millimetres per minute and revolutions per minute. Only what the
            object actually said: a key it left out is a key the layer
            underneath it still answers, and writing a default in here would
            silently overrule a package that set one for all of its objects.
        implementation: who produces this route, as `<package>:<file type>`, or
            None to leave it to the user configuration. An object that names one
            is saying which post-processor its numbers were written for -- the
            same thing a part's `fea: implementation:` says about a solver, and
            outranked by `-i` for the same reason.
        desc: what the object says this route is, for whoever reads the YAML.
    """

    def __init__(self, config: Optional[dict]) -> None:
        """Read one `cam:` section, converting every value to PartCAD's units.

        Raises:
            CamConfigError: the section is absent, is not a mapping, is empty,
                names a key that is not a job parameter, or holds a value that
                cannot be read as one. Every one of those is a sentence rather
                than a code, because it is what `pc cam` prints against the
                object it belongs to.
        """
        self.operation: Optional[str] = None
        self.direction: Optional[str] = None
        self.values: dict[str, float] = {}
        self.implementation: Optional[str] = None
        self.desc: Optional[str] = None

        if config is None:
            raise CamConfigError("'manufacturing:' declares no job")
        if not isinstance(config, dict):
            raise CamConfigError("'manufacturing:' is not a section: %r" % (config,))

        unknown = [key for key in config if key not in KEYS]
        if unknown:
            raise CamConfigError(
                "'manufacturing:' does not take %s; it takes %s"
                % (", ".join(sorted(unknown)), ", ".join("'%s:'" % key for key in KEYS))
            )
        if not config:
            # An object that declares the section and says nothing in it has
            # opted in to being routed and then described no route. The file
            # type's defaults could cover it, and that is exactly the reading to
            # refuse: a depth and a tool nobody chose are a cut nobody meant.
            raise CamConfigError("'manufacturing:' declares no job; it needs at least a 'diameter:'")

        self._parse_operation(config.get("operation"))
        self._parse_direction(config.get("direction"))
        self._parse_implementation(config.get("implementation"))

        for key in LENGTH_KEYS:
            if config.get(key) is not None:
                self.values[key] = parse_length(config[key], "'manufacturing: %s:'" % key)
        for key in FEED_KEYS:
            if config.get(key) is not None:
                self.values[key] = parse_feed(config[key], "'manufacturing: %s:'" % key)
        for key in NUMBER_KEYS:
            if config.get(key) is not None:
                self.values[key] = parse_number(config[key], "'manufacturing: %s:'" % key)

        stepover = self.values.get("stepover")
        if stepover is not None and stepover > 1:
            # A stepover is a fraction of the cutter's diameter, so more than one
            # leaves a ridge of uncut material between passes. It parses, it
            # runs, and what comes off the machine is wrong in a way nobody sees
            # until then.
            raise CamConfigError(
                "'manufacturing: stepover:' is a fraction of the tool diameter, so it cannot exceed 1: %r" % stepover
            )

        desc = config.get("desc")
        if desc is not None:
            if not isinstance(desc, str):
                raise CamConfigError("'manufacturing: desc:' is not text: %r" % (desc,))
            self.desc = desc

    def _parse_operation(self, operation) -> None:
        """Read `operation:`, which says which side of the outline to run on."""
        if operation is None:
            return
        if not isinstance(operation, str) or operation.strip().lower() not in OPERATIONS:
            raise CamConfigError(
                "'cam: operation:' is not one of %s: %r" % (", ".join("'%s'" % one for one in OPERATIONS), operation)
            )
        self.operation = operation.strip().lower()

    def _parse_direction(self, direction) -> None:
        """Read `direction:`, which says which way round each contour is cut."""
        if direction is None:
            return
        if not isinstance(direction, str) or direction.strip().lower() not in DIRECTIONS:
            raise CamConfigError(
                "'cam: direction:' is not one of %s: %r" % (", ".join("'%s'" % one for one in DIRECTIONS), direction)
            )
        self.direction = direction.strip().lower()

    def _parse_implementation(self, implementation) -> None:
        """Read `implementation:`, which names who produces this route.

        Checked only for being a non-empty name here. Whether the package exists
        and declares that file type is `Shape._route_implementation()`'s
        question, asked where the packages are: this class deliberately imports
        nothing from `partcad`, which is what lets it be tested without a
        sandbox.
        """
        if implementation is None:
            return
        if not isinstance(implementation, str) or not implementation.strip():
            raise CamConfigError("'cam: implementation:' is not a '<package>:<file type>' name: %r" % (implementation,))
        self.implementation = implementation.strip()

    def to_data(self) -> dict:
        """This configuration as the parameters an implementation is handed.

        Only what the object declared, which is what makes the layering work: a
        key that is absent here is a key the file type's own configuration still
        answers (see `Shape._output_getopts`), and one that is present overrides
        it for this object.

        `implementation:` and `desc:` are left out. The first has been acted on
        by the time anything is handed over, and the second is for the reader of
        the YAML rather than for the machine.
        """
        data = dict(self.values)
        if self.operation is not None:
            data["operation"] = self.operation
        if self.direction is not None:
            data["direction"] = self.direction
        return data

    def __repr__(self) -> str:
        return "CamConfig(operation=%r, %r)" % (self.operation, self.values)


def normalize_job(parameters: dict) -> dict:
    """The merged job parameters, every one of them in PartCAD's units.

    `CamConfig` converts what the *object* declared, and that is only the top
    layer: a package sets the feed for all of its parts under the file type in
    its own `cam:` section, and `//builtin/cam` sets a clearance for everybody,
    and both of those reach the implementation through
    `Shape._output_getopts()` without passing through anything here. So a
    '2400 mm/min' written one layer down used to arrive at the implementation as
    the string it was written as, and be refused by it -- which is the right
    answer to the wrong question: the spelling is PartCAD's to understand, at
    every layer, and the implementation's business is numbers.

    This is where that happens, once, over the request as it finally stands.
    Only the keys `KEYS` names are touched; everything else in the request --
    the shape, the file type's own settings, whatever a package added that
    PartCAD has never heard of -- travels untouched, which is what keeps a
    parameter an implementation invented from having to be known here.

    What it deliberately does *not* do is require anything. `diameter:` is
    needed by the router and the drill `//builtin/cam` ships and refused by it
    where it is missing, but "a route needs a cutter diameter" is a statement
    about that implementation rather than about the concept -- the laser beside
    them cuts with a beam, which has a `kerf:` and no diameter at all. PartCAD
    does not know what the next one cuts with, and a requirement here would be
    PartCAD answering on its behalf.

    Raises:
        CamConfigError: a value that cannot be read as the kind of number its
            key is. Named by key, and with the layer left unsaid on purpose --
            the reader does not have to know which of the three said it to fix
            it.
    """
    normalized = dict(parameters)
    for key in LENGTH_KEYS:
        if normalized.get(key) is not None:
            normalized[key] = parse_length(normalized[key], "'manufacturing: %s:'" % key)
    for key in FEED_KEYS:
        if normalized.get(key) is not None:
            normalized[key] = parse_feed(normalized[key], "'manufacturing: %s:'" % key)
    for key in NUMBER_KEYS:
        if normalized.get(key) is not None:
            normalized[key] = parse_number(normalized[key], "'manufacturing: %s:'" % key)

    # The same bound `CamConfig` puts on the object's own layer. It belongs at
    # both: a stepover above 1 leaves a ridge of uncut material between passes,
    # and the mistake is as easy to write one layer down -- under the package's
    # own `cam: <file type>:` -- where it would otherwise reach the
    # implementation unchecked and produce the very route the object-level
    # check exists to prevent.
    stepover = normalized.get("stepover")
    if stepover is not None and stepover > 1:
        raise CamConfigError(
            "'manufacturing: stepover:' is a fraction of the tool diameter, so it cannot exceed 1: %r" % stepover
        )

    direction = normalized.get("direction")
    if direction is not None:
        if not isinstance(direction, str) or direction.strip().lower() not in DIRECTIONS:
            raise CamConfigError(
                "'cam: direction:' is not one of %s: %r" % (", ".join("'%s'" % one for one in DIRECTIONS), direction)
            )
        normalized["direction"] = direction.strip().lower()

    operation = normalized.get("operation")
    if operation is not None:
        if not isinstance(operation, str) or operation.strip().lower() not in OPERATIONS:
            raise CamConfigError(
                "'cam: operation:' is not one of %s: %r" % (", ".join("'%s'" % one for one in OPERATIONS), operation)
            )
        normalized["operation"] = operation.strip().lower()
    return normalized


def config_of(shape, machine: Optional[str] = None) -> Optional[CamConfig]:
    """The route a shape declares, or None where it declares none.

    None means the shape said nothing about being cut, which is the ordinary
    case and not an error: most objects never go on a machine. A shape that said
    something and got it wrong raises `CamConfigError`, because that is a
    mistake the user wants to hear about -- and the difference is exactly what
    lets `pc cam` over a whole package be quiet about the objects it skips and
    loud about the one that is broken.

    Args:
        shape: the object whose `manufacturing:` section is read.
        machine: which of the machines it names to write for. None takes the
            one it names, and refuses where it names several -- see
            `declared_config`.
    """
    config = declared_config(shape, machine)
    if config is None:
        return None
    return CamConfig(config)


def declared_config(shape, machine: Optional[str] = None) -> Optional[dict]:
    """A shape's job as written, merged for the machine that will cut it.

    Two scopes are merged, and the order between them is the whole point of
    having two: what is written directly under `manufacturing:` is shared by
    every machine the part names, and what is written inside a machine's own
    subsection is that machine's and outranks it. So a part cut either way can
    say `feed: 1200` once and let the laser say `feed: 2400` for itself.

    Split out from `config_of` because two callers want different things from
    it: one is about to run a route and needs the job parsed, the other is
    deciding which objects of a package to route at all and only needs to know
    whether there is one. The second must not raise on a neighbour's broken
    section while it is still deciding what to visit.

    Raises:
        CamConfigError: the section could not be read, the part names several
            machines and none was chosen, or the one chosen is not among them.
            None of the three is answerable here: a default nobody picked is a
            program for the wrong machine.
    """
    from .part_config import PartConfiguration
    from .part_config_manufacturing import ROUTED_MACHINES

    data = PartConfiguration.get_manufacturing_data(shape)
    if data is None:
        return None

    if data.machine_error:
        # Before anything else, because a section that could not be read leaves
        # no machine behind and no job -- which is indistinguishable from the
        # part that declared neither, and that one is skipped in silence. So a
        # `cnc:` with a typo in it would be passed over rather than reported,
        # and the user would be told their part says nothing about being cut
        # while looking straight at the subsection saying how it is.
        raise CamConfigError(data.machine_error)

    # Only the machines a program is written for. A saw cutting stock to length
    # runs none, so a part that is only cut has no route, and a part that could
    # be cut or routed has one choice fewer to make.
    routed = [kind for kind in data.machine_choices() if kind in ROUTED_MACHINES]
    chosen = None
    if machine is not None:
        chosen = data.machine_named(machine)
        if chosen is None:
            raise CamConfigError(
                "it is not made on a '%s'; it names %s"
                % (machine, ", ".join("'%s'" % kind for kind in data.machine_choices()) or "no machine")
            )
        if machine not in ROUTED_MACHINES:
            raise CamConfigError(
                "a '%s' runs no program: where it cuts is the whole of what it is told, and the part's own"
                " declaration already says so" % machine
            )
    elif len(routed) > 1:
        raise CamConfigError(
            "it could be made on %s, so one of them has to be chosen" % " or ".join("'%s'" % kind for kind in routed)
        )
    elif routed:
        chosen = data.machine_named(routed[0])
    elif data.machines:
        # Made on machines none of which runs a program.
        return None

    # The opt-in: an object is routed when it has said something about being
    # cut, either by naming a machine or by declaring a job parameter. A
    # `subtractive` part that names neither has described what it is made from
    # and nothing about the making, so there is no route to write.
    declared_machine = chosen is not None and chosen.declared
    if not declared_machine and not data.job:
        return None

    merged = dict(data.job)
    if chosen is not None:
        merged.update(chosen.job_options())
    return merged or None


def declares_job(shape) -> bool:
    """Whether this object says anything about being cut, without judging it.

    The question `pc cam` over a package asks of every object before it routes
    any of them, and it has to be answerable for an object whose declaration is
    wrong -- a part that names two machines, or a `laser:` with a typo in it,
    is still one this run should visit and report on rather than one it should
    silently pass over. `declared_config` raises for both, on purpose, because
    by then a route is actually being written; here there is only a list being
    drawn up.
    """
    from .part_config import PartConfiguration

    try:
        data = PartConfiguration.get_manufacturing_data(shape)
    except Exception:  # pylint: disable=broad-except
        return False
    if data is None:
        return False
    if data.machine_error:
        # Broken, and therefore visited: the sentence belongs to whoever tries
        # to route it, against the object it is about.
        return True
    from .part_config_manufacturing import ROUTED_MACHINES

    routed = [machine for machine in data.machines.values() if machine.kind in ROUTED_MACHINES]
    if data.job and (routed or not data.machines):
        return True
    return any(machine.declared for machine in routed)


def dysfunction_report(name: str, implementation: str, error: Exception, remedy: Optional[str] = None) -> str:
    """Why a route was not produced, as the failure a user has to act on.

    The same report `partcad.cae.dysfunction_report()` writes, and for the same
    reason: what the implementation said is reported verbatim, because only it
    knows what went wrong, and what PartCAD adds is the two things the sentence
    always omits and the reader always needs -- which implementation was asked,
    and which machine it did not work on.
    """
    import platform

    lines = [
        "%s: no route was produced by %s" % (name, implementation),
        "\t%s" % str(error).replace("\n", "\n\t"),
        "\tplatform: %s-%s, Python %s" % (platform.system(), platform.machine(), platform.python_version()),
    ]
    if remedy:
        lines.append("\t%s" % remedy)
    return "\n".join(lines)


# What to do about a route that could not be produced because this machine has
# no container runtime. Said by PartCAD rather than by the implementation,
# because the implementation never ran. The same sentence `partcad.cae` says,
# because it is the same machine and the same two remedies.
NO_RUNTIME_REMEDY = (
    "Either start a container runtime, or install what this implementation needs on this machine: "
    "an implementation that names a 'dockerImage' also declares the requirements to run without one."
)


def route_report(name: str, result: dict) -> str:
    """One produced route, as `pc cam` reports it.

    The numbers are the ones a user checks before sending the file to a machine:
    how far the tool travels with the spindle in the cut, how deep it goes, and
    how many passes that took. An implementation that reports none of them is
    still reported -- the file and where it went is the answer to the command.
    """
    lines = ["%s: %s" % (name, result.get("filepath", ""))]
    stats = result.get("stats") or {}
    described = (
        ("operation", "%s"),
        ("passes", "%s pass(es)"),
        ("depth", "%.3f mm deep"),
        ("cut_length", "%.1f mm of cutting moves"),
    )
    details = []
    for key, template in described:
        value = stats.get(key)
        if value is None:
            continue
        try:
            details.append(template % value)
        except (TypeError, ValueError):
            details.append("%s: %s" % (key, value))
    if details:
        lines.append("\t" + ", ".join(details))
    return "\n".join(lines)
