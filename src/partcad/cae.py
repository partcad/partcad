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
by `pc cae fea` / `pc cae cfd`. What it adds is a second output beside the file:
the **findings**, a JSON array of what the analysis has to say about the part.

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

`fix:` names what is held still: either a list of interface types, or a map from
an interface type to the list of its instances that are held. `load:` names what
is pulled on: a map from an interface type to one value for all of its instances,
or a nested map naming the instance. `cfd:` takes the same two keys, with the
same meaning -- what is held still, and what force the flow puts on it.

`load` values are **forces**, stored in newtons. A value may be a bare number or
a string ending in a unit name (see `parse_force`), and a bare number is read as
a *mass* in kilograms -- which is what a user writing "the shelf carries 5"
means. A mass becomes a force by weighing it: `GRAVITY` newtons per kilogram.

Nothing here imports a CAD library or touches geometry. It reads the
configuration, converts the units, and hands the result to an implementation that
runs in a sandbox like every other one.
"""

from __future__ import annotations

import platform
import re
from typing import Optional

# The two analyses. Each is a file type of the `cae:` section (so an
# implementation is declared exactly as an `export:` or `render:` one is) and a
# section a part declares its boundary conditions in.
FEA = "fea"
CFD = "cfd"
ANALYSES = (FEA, CFD)

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


class AnalysisConfig:
    """The boundary conditions one part declares for one analysis.

    Both members are keyed by the interface type as the part spelled it -- short
    or fully qualified, exactly as `implements:` and `connect:` spell it -- and
    matched against a part's resolved interfaces by `assign_ports()`.

    Attributes:
        analysis: "fea" or "cfd".
        fixtures: interface type -> the instances held still. `["*"]` for every
            instance of it.
        loads: interface type -> instance -> newtons. The instance `"*"` is every
            instance of that interface.
        outlets: interface type -> the instances the fluid leaves through, in
            the same shape as `fixtures`. `cfd:` only -- a stress analysis has
            nothing to let out.
        implementation: who runs this analysis, as `<package>:<file type>`, or
            None to leave it to the user configuration. A part that names one is
            saying "this is the solver I was written against", which is a
            property of the part rather than of the machine -- and it is what
            lets a package ship a working analysis without every user first
            pointing `caeFeaImplementation` at the right place.
    """

    def __init__(self, analysis: str, config: Optional[dict]) -> None:
        """Read one `fea:`/`cfd:` section, converting every load to newtons.

        Raises:
            CaeConfigError: the section is absent, is not a mapping, names a key
                that is neither `fix:` nor `load:`, or holds a value that is not
                a force. Every one of those is a sentence rather than a code,
                because it is what `pc cae` prints and what the IDE's tab shows
                where the results would have been.
        """
        self.analysis = analysis
        self.fixtures: dict[str, list[str]] = {}
        self.loads: dict[str, dict[str, float]] = {}
        self.outlets: dict[str, list[str]] = {}
        self.implementation: Optional[str] = None

        if config is None:
            raise CaeConfigError("'%s:' is empty" % analysis)
        if not isinstance(config, dict):
            raise CaeConfigError("'%s:' is not a section: %r" % (analysis, config))

        # 'outlet:' is CFD's and only CFD's. A stress analysis has nothing to
        # let out, and accepting the word there would let a part say something
        # that reads as a boundary condition and is not one.
        keys = ["fix", "load", "desc", "implementation"] + (["outlet"] if analysis == CFD else [])
        unknown = [key for key in config if key not in keys]
        if unknown:
            raise CaeConfigError(
                "'%s:' does not take %s; it takes %s and 'implementation:'"
                % (
                    analysis,
                    ", ".join(sorted(unknown)),
                    ", ".join("'%s:'" % key for key in keys if key not in ("desc", "implementation")),
                )
            )

        self._parse_implementation(config.get("implementation"))
        self._parse_fix(config.get("fix"))
        self._parse_load(config.get("load"))
        self._parse_outlet(config.get("outlet"))

        if not self.fixtures and not self.loads:
            raise CaeConfigError("'%s:' declares neither 'fix:' nor 'load:'" % analysis)

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

    def _parse_fix(self, fix) -> None:
        """Read `fix:`, which comes in three shapes that mean two things.

        A bare name and a list of them say "every instance of these interfaces";
        a mapping says which instances, and an entry with nothing under it means
        the whole of that interface again. All three normalize to the same
        `interface -> instances` mapping, so nothing downstream has to know
        which spelling the package used.
        """
        if fix is None:
            return
        if isinstance(fix, str):
            # One interface type, held whole. The degenerate case of the list.
            self.fixtures[fix] = [EVERY_INSTANCE]
            return
        if isinstance(fix, list):
            for entry in fix:
                if not isinstance(entry, str):
                    raise CaeConfigError("'fix:' names an interface that is not a name: %r" % (entry,))
                self.fixtures[entry] = [EVERY_INSTANCE]
            return
        if isinstance(fix, dict):
            for interface, instances in fix.items():
                self.fixtures[interface] = _instance_names(instances, "'fix: %s:'" % interface)
            return
        raise CaeConfigError("'fix:' is neither a list of interfaces nor a map of them: %r" % (fix,))

    def _parse_outlet(self, outlet) -> None:
        """Read `outlet:`, which names where the fluid leaves.

        The same three shapes as `fix:`, and for the same reason: it names
        interfaces and, where it matters, which instances of them.

        It exists because an incompressible flow is posed by *differences* in
        pressure. `load:` says what drives the flow in; with nothing saying
        where it goes, the problem has no downstream reference and a solver
        answers it with a dead field or with a divergence -- which is what it
        did, and what this key was added for. A part that names an inlet and no
        outlet is not asking a harder question, it is asking one that has no
        answer.
        """
        if outlet is None:
            return
        if isinstance(outlet, str):
            self.outlets[outlet] = [EVERY_INSTANCE]
            return
        if isinstance(outlet, list):
            for entry in outlet:
                if not isinstance(entry, str):
                    raise CaeConfigError("'outlet:' names an interface that is not a name: %r" % (entry,))
                self.outlets[entry] = [EVERY_INSTANCE]
            return
        if isinstance(outlet, dict):
            for interface, instances in outlet.items():
                self.outlets[interface] = _instance_names(instances, "'outlet: %s:'" % interface)
            return
        raise CaeConfigError("'outlet:' is neither a list of interfaces nor a map of them: %r" % (outlet,))

    def _parse_load(self, load) -> None:
        """Read `load:`, converting every value to a force in newtons.

        Flat (`hook: 5 kg`) applies to every instance of the interface; nested
        (`rail: {left: 30 N}`) names the instance. Unlike `fix:` there is no
        list form -- a list of interfaces would say what is loaded without
        saying with what, which is not a boundary condition.
        """
        if load is None:
            return
        if not isinstance(load, dict):
            raise CaeConfigError("'load:' is not a map of interfaces to forces: %r" % (load,))
        for interface, value in load.items():
            if isinstance(value, dict):
                # The nested form: one value per named instance.
                if not value:
                    raise CaeConfigError("'load: %s:' names no instance" % interface)
                self.loads[interface] = {
                    instance: parse_force(amount, "'load: %s: %s:'" % (interface, instance))
                    for instance, amount in value.items()
                }
            else:
                self.loads[interface] = {EVERY_INSTANCE: parse_force(value, "'load: %s:'" % interface)}

    @property
    def interfaces(self) -> list[str]:
        """Every interface type this analysis has something to say about."""
        names = list(self.fixtures)
        names.extend(name for name in self.loads if name not in names)
        names.extend(name for name in self.outlets if name not in names)
        return names

    def to_data(self) -> dict:
        """This configuration as the plain data an implementation is handed."""
        data = {
            "analysis": self.analysis,
            "fix": {name: list(instances) for name, instances in self.fixtures.items()},
            "load": {name: dict(values) for name, values in self.loads.items()},
        }
        if self.outlets:
            # Only when there is one: an implementation that has never heard of
            # outlets is handed the request it always was, and a part that names
            # none is not told it has an empty one.
            data["outlet"] = {name: list(instances) for name, instances in self.outlets.items()}
        if self.implementation is not None:
            # Carried so that `pc test`'s cache key changes when the part is
            # re-pointed at another solver: two solvers are two answers, and the
            # verdict on one must not be handed back for the other.
            data["implementation"] = self.implementation
        return data

    def __repr__(self) -> str:
        """The parsed conditions, with the loads as the newtons they became."""
        return "AnalysisConfig(%r, fix=%r, load=%r, outlet=%r)" % (
            self.analysis,
            self.fixtures,
            self.loads,
            self.outlets,
        )


def config_of(shape, analysis: str) -> Optional[AnalysisConfig]:
    """The boundary conditions a shape declares for an analysis, or None.

    None means the shape said nothing at all, which is the ordinary case and not
    an error: most parts are never analysed. A shape that declared the section
    but got it wrong raises `CaeConfigError`, because that is a mistake the user
    wants to hear about.
    """
    if analysis not in ANALYSES:
        raise CaeConfigError("Unknown analysis '%s'; PartCAD runs %s" % (analysis, " and ".join(ANALYSES)))
    get_final_config = getattr(shape, "get_final_config", None)
    config = get_final_config() if callable(get_final_config) else getattr(shape, "config", None)
    if not isinstance(config, dict) or analysis not in config:
        return None
    return AnalysisConfig(analysis, config[analysis])


def _matches(record_interface: Optional[str], declared_name: str) -> bool:
    """Whether a port's interface is the one a `fix:`/`load:` entry names.

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
    port of the shape, carrying the interface it belongs to, the instance, and
    where it is. Each record that a `fix:` or a `load:` names comes back with a
    `fix` flag and/or a `load` in newtons on it; the ones nothing names are left
    out, because an implementation is being told where to hold the part and where
    to pull it, not what the part's other ports are.

    A load written for every instance of an interface is applied to every
    instance of it -- **not** divided between them. "This interface carries 5 kg"
    reads as each of them carrying it, which is the conservative reading and the
    one a user checking a bracket wants.

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
        entry = None

        for name in config.interfaces:
            if _matches(interface, name):
                interfaces_seen.add(name)

        for name, instances in config.fixtures.items():
            if not _matches(interface, name):
                continue
            # Both spellings are recorded when both apply, because both are
            # declarations a user could have got wrong on their own.
            held = [one for one in (EVERY_INSTANCE, instance) if one in instances]
            if not held:
                continue
            matched.update(("fix", name, one) for one in held)
            entry = entry or dict(record)
            entry["fix"] = True

        for name, values in config.loads.items():
            if not _matches(interface, name):
                continue
            # The instance's own value wins over the interface-wide one, so it
            # is the one that counts as used.
            declared = instance if instance in values else EVERY_INSTANCE
            amount = values.get(declared)
            if amount is None:
                continue
            matched.add(("load", name, declared))
            entry = entry or dict(record)
            entry["load"] = amount

        for name, instances in config.outlets.items():
            if not _matches(interface, name):
                continue
            opened = [one for one in (EVERY_INSTANCE, instance) if one in instances]
            if not opened:
                continue
            matched.update(("outlet", name, one) for one in opened)
            entry = entry or dict(record)
            entry["outlet"] = True

        if entry is not None:
            entry.setdefault("fix", False)
            entry.setdefault("load", 0.0)
            # Only where the part has outlets at all, so that a record handed to
            # an implementation that has never heard of them looks exactly as it
            # always did.
            if config.outlets:
                entry.setdefault("outlet", False)
            assigned.append(entry)

    unmatched = []
    for key, declared in (("fix", config.fixtures), ("load", config.loads), ("outlet", config.outlets)):
        for name, wanted in declared.items():
            # `fix:` and `outlet:` hold a list of instance names and `load:` a
            # map of them to forces; iterating any of them yields the names,
            # which is all this needs.
            missing = [one for one in wanted if (key, name, one) not in matched]
            if not missing:
                continue
            if name not in interfaces_seen:
                unmatched.append((name, "this object does not implement it"))
                continue
            named = ", ".join(sorted(str(one) for one in missing if one != EVERY_INSTANCE))
            unmatched.append((name, "no instance named %s" % named if named else "it names no instance of it"))
    return assigned, unmatched


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


def dysfunction_report(name: str, analysis: str, implementation: str, error: Exception) -> str:
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
    return "\n".join(
        [
            "%s: %s could not be run by %s" % (name, analysis.upper(), implementation),
            "\t%s" % str(error).replace("\n", "\n\t"),
            "\tplatform: %s-%s, Python %s"
            % (platform.system(), platform.machine(), platform.python_version()),
        ]
    )


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
