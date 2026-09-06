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
        return list(value) if value else [EVERY_INSTANCE]
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
    """

    def __init__(self, analysis: str, config: Optional[dict]) -> None:
        self.analysis = analysis
        self.fixtures: dict[str, list[str]] = {}
        self.loads: dict[str, dict[str, float]] = {}

        if config is None:
            raise CaeConfigError("'%s:' is empty" % analysis)
        if not isinstance(config, dict):
            raise CaeConfigError("'%s:' is not a section: %r" % (analysis, config))

        unknown = [key for key in config if key not in ("fix", "load", "desc")]
        if unknown:
            raise CaeConfigError(
                "'%s:' does not take %s; it takes 'fix:' and 'load:'" % (analysis, ", ".join(sorted(unknown)))
            )

        self._parse_fix(config.get("fix"))
        self._parse_load(config.get("load"))

        if not self.fixtures and not self.loads:
            raise CaeConfigError("'%s:' declares neither 'fix:' nor 'load:'" % analysis)

    def _parse_fix(self, fix) -> None:
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

    def _parse_load(self, load) -> None:
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
        names.extend(name for name in self.loads if name not in self.fixtures)
        return names

    def to_data(self) -> dict:
        """This configuration as the plain data an implementation is handed."""
        return {
            "analysis": self.analysis,
            "fix": {name: list(instances) for name, instances in self.fixtures.items()},
            "load": {name: dict(values) for name, values in self.loads.items()},
        }

    def __repr__(self) -> str:
        return "AnalysisConfig(%r, fix=%r, load=%r)" % (self.analysis, self.fixtures, self.loads)


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

    Returns the assigned records and the declarations nothing matched, which the
    caller reports: an interface named in `fix:` that the part does not implement
    is a boundary condition silently doing nothing, and that is worth a warning
    every time.
    """
    assigned = []
    matched: set[str] = set()

    for record in records:
        interface = record.get("interface")
        instance = record.get("instance") or ""
        entry = None

        for name, instances in config.fixtures.items():
            if not _matches(interface, name):
                continue
            if EVERY_INSTANCE in instances or instance in instances:
                entry = entry or dict(record)
                entry["fix"] = True
                matched.add("fix:" + name)

        for name, values in config.loads.items():
            if not _matches(interface, name):
                continue
            amount = values.get(instance)
            if amount is None:
                amount = values.get(EVERY_INSTANCE)
            if amount is None:
                continue
            entry = entry or dict(record)
            entry["load"] = amount
            matched.add("load:" + name)

        if entry is not None:
            entry.setdefault("fix", False)
            entry.setdefault("load", 0.0)
            assigned.append(entry)

    unmatched = [name for name in config.fixtures if "fix:" + name not in matched]
    unmatched += [name for name in config.loads if "load:" + name not in matched]
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
