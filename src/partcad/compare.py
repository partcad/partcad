#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Two objects read against each other: what 'pc compare' reports.

The 3D counterpart of the gen-sketch skill's 'measure.py compare', which reads
two drawings of one object against each other. Here the two are parts or
assemblies, and the first is the *reference* -- what the second, the *current*
object, is held to:

  volume     how much of each there is, in mm^3: a part's measured solid, an
             assembly's parts added up (see 'physics.amounts_async')
  displacement
             optionally, how much each would push aside if it were submerged,
             in mm^3: its volume and every void sealed inside it, which a hole
             right through it is not (see 'shape_measure.displacement' among
             the wrappers). Measured in a sandbox, so only when asked for -
             with 'displacement', or with a limit on it
  mass       what each weighs, in kg, stated or worked out from its material
  tolerance  how precisely each is to be made ('get_tolerance()'), and the two
             added up: how far apart two surfaces each made within its own
             tolerance can be
  surface    optionally, how far the current object's surface is from the
             reference's, measured at points a given distance apart over the
             whole of the reference, along its normals (see
             'wrappers/wrapper_compare.py' for which points, and how)

Every difference is the current object's value less the reference's, and every
percentage is of the reference's: "the current one is 4% heavier".

A comparison passes or fails only on what it was asked to hold the two to. A
volume, a displacement or a mass is judged only against a limit given with it,
in percent of the reference's; the surface is judged whenever it is measured,
against the two tolerances added up. With nothing judged, 'passed' is None: a
report, not a verdict. A value that cannot be known -- a mass of something made of nothing
with a density -- fails a limit set on it, because "not known" is not "within
5%" (the rule 'partcad.requirements' has for every requirement).

The two are compared where they are. Nothing moves one onto the other: two
objects whose geometry is the same and whose origins are not are, for the
surface, a millimetre or a metre apart, and that is reported.

The same rules answer a 'match:' requirement (see 'partcad.requirements'), so
that 'pc test' and 'pc compare' cannot disagree about what "within 5%" means.
"""

from __future__ import annotations

import math
import typing

from . import measure as pc_measure
from . import physics as pc_physics

VOLUME = "volume"
DISPLACEMENT = "displacement"
MASS = "mass"
# Every amount a limit, or a 'match:' requirement, may hold two objects to, in
# the order a report lists them. The displacement is measured only when it is
# asked for, and a report without it leaves it out.
AMOUNTS = (VOLUME, DISPLACEMENT, MASS)

UNITS = {VOLUME: "mm^3", DISPLACEMENT: "mm^3", MASS: "kg"}

# What a value that is not known because nothing in the object can hold it says.
NO_SOLID = "it holds no solid"

# What a limit in percent is allowed to be off by and still hold: the last bit
# of the arithmetic, not a tolerance anyone asked for.
PERCENT_SLACK = 1e-9

# How many of the points furthest apart a report lists.
WORST = 10

# What a tolerance that cannot be added up says instead, and why.
NO_TOLERANCE = "states none, counted as 0"
FEATURE_BY_FEATURE = "tolerated feature by feature, so there is no one allowance for the whole surface"

# The kinds of object that have a volume and a mass to compare.
KINDS = ("part", "assembly")


def percent_limit(raw) -> typing.Optional[float]:
    """A limit in percent, as written: 5, 5.0 or "5%". None for a value that is none of them.

    Negative limits are none of them either: nothing differs by less than not
    at all.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        try:
            value = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def difference(reference, current) -> dict:
    """'{"reference", "current", "difference", "percent"}' of two values, either of which may be None.

    'percent' is the difference as a percentage of the reference's value, and
    None when there is none to take: one of the two is not known, or the
    reference's is zero while the current one's is not.
    """
    result = {"reference": reference, "current": current, "difference": None, "percent": None}
    if reference is None or current is None:
        return result
    result["difference"] = current - reference
    if reference != 0:
        result["percent"] = 100.0 * (current - reference) / abs(reference)
    elif current == 0:
        result["percent"] = 0.0
    return result


def within(entry: dict, limit: float) -> typing.Tuple[bool, str]:
    """(whether a difference is within 'limit' percent of the reference, and why it is or is not).

    'entry' is what 'difference()' answers, with the 'unit' and the 'unknown'
    reason of each side where there is one.
    """
    unit = entry.get("unit")
    if entry.get("reference") is None:
        return False, "the reference's is not known: %s" % (entry.get("referenceUnknown") or "nothing says what it is")
    if entry.get("current") is None:
        return False, "it is not known: %s" % (entry.get("currentUnknown") or "nothing says what it is")
    percent = entry.get("percent")
    if percent is None:
        return False, "it is %s, and the reference's is 0" % quantity(entry["current"], unit)
    ok = abs(percent) <= limit + PERCENT_SLACK
    return ok, "%s, %s the reference's %s (%s)" % (
        quantity(entry["current"], unit),
        _how_far(percent),
        quantity(entry["reference"], unit),
        "within %s%%" % number(limit) if ok else "more than %s%%" % number(limit),
    )


def _how_far(percent: float) -> str:
    """How a percentage reads between two quantities: 'the same as', or '5% more than'."""
    if percent == 0:
        return "the same as"
    return "%s%% %s than" % (number(abs(percent)), "more" if percent > 0 else "less")


def number(value) -> str:
    """A number the way a report shows it: nine significant digits and no noise."""
    if value is None:
        return "?"
    value = float(value)
    if value == 0:
        return "0"
    return "%.9g" % value


def quantity(value, unit) -> str:
    """A value with its unit, the way the report writes one: '1050 mm^3'."""
    return "%s %s" % (number(value), unit) if unit else number(value)


async def _tolerance(shape) -> typing.Tuple[typing.Optional[float], typing.Optional[str]]:
    """(how precisely 'shape' is to be made, or None; why it is None or NaN)."""
    try:
        value = await shape.get_tolerance()
    except Exception as e:  # pylint: disable=broad-except
        return None, "could not be read: %s" % e
    if value is None:
        return None, NO_TOLERANCE
    if isinstance(value, float) and math.isnan(value):
        return None, FEATURE_BY_FEATURE
    return float(value), None


def allowance(reference_tolerance, reference_note, current_tolerance, current_note):
    """(how far apart the two surfaces may be anywhere, or None; why it is None).

    The two tolerances added up: each object may be made off its nominal by its
    own, in either direction, so two made within theirs can be that far apart.
    A tolerance nobody stated counts as nothing. A file that tolerances each
    feature differently states no one number, and there is then no allowance.
    """
    for note in (reference_note, current_note):
        if note == FEATURE_BY_FEATURE:
            return None, note
    return (reference_tolerance or 0.0) + (current_tolerance or 0.0), None


def name_of(shape) -> str:
    return "%s:%s" % (shape.project_name, shape.name)


async def _displacement(ctx, shape) -> dict:
    """'{"displacement", "cavities", "displacementUnknown"}' of one object, measured in a sandbox.

    A measurement that fails leaves the displacement not known and says why,
    the way a mass nothing states is not known: one object the sandbox could
    not measure fails a limit on it, and takes nothing else down with it.
    """
    try:
        measured = await pc_measure.displacement(
            ctx, await shape.get_wrapped(ctx), cacheable=shape.artifacts_cacheable()
        )
    except Exception as e:  # pylint: disable=broad-except
        return {DISPLACEMENT: None, "cavities": None, "displacementUnknown": "could not be measured: %s" % e}
    measured = measured or {}
    value = measured.get(DISPLACEMENT)
    return {
        DISPLACEMENT: value,
        "cavities": measured.get("cavities"),
        "displacementUnknown": None if value is not None else NO_SOLID,
    }


async def side_async(ctx, shape, displacement: bool = False) -> dict:
    """What one of the two objects is: its name, kind, volume, mass and tolerance.

    With 'displacement', its displacement as well, and how many voids are
    sealed inside its solids ('cavities'): what makes the two volumes differ.
    """
    amounts = await pc_physics.amounts_async(ctx, shape) or {}
    tolerance, note = await _tolerance(shape)
    side = {
        "object": name_of(shape),
        "kind": getattr(shape, "kind", None),
        VOLUME: amounts.get(VOLUME),
        MASS: amounts.get(MASS),
        "massSource": amounts.get("massSource"),
        "massUnknown": amounts.get("unknown"),
        "tolerance": tolerance,
        "toleranceNote": note,
    }
    if displacement:
        side.update(await _displacement(ctx, shape))
    return side


def amount_entry(reference: dict, current: dict, key: str) -> dict:
    """How one amount ('volume', 'displacement' or 'mass') of two sides 'side_async()' answered differs.

    'difference()', with the unit, and why each side's value is not known where
    it is not - which is what 'within()' says when it fails for that reason.
    """
    entry = difference(reference.get(key), current.get(key))
    entry["unit"] = UNITS[key]
    if key == VOLUME:
        entry["referenceUnknown"] = None if reference.get(key) is not None else NO_SOLID
        entry["currentUnknown"] = None if current.get(key) is not None else NO_SOLID
    elif key == DISPLACEMENT:
        entry["referenceUnknown"] = reference.get("displacementUnknown")
        entry["currentUnknown"] = current.get("displacementUnknown")
    else:
        entry["referenceUnknown"] = reference.get("massUnknown")
        entry["currentUnknown"] = current.get("massUnknown")
    return entry


async def compare_async(
    ctx, reference, current, spacing=None, limits=None, worst: int = WORST, displacement: bool = False
) -> dict:
    """Read 'current' against 'reference', both parts or assemblies; see the module's docstring.

    'spacing', when given, measures the surface with points that far apart, in
    millimetres. 'limits' is '{"volume": percent, "displacement": percent,
    "mass": percent}', any of them absent: how far each may differ, in percent
    of the reference's, for the comparison to pass. 'displacement' measures the
    displacements as well, which a limit on them also does; without either the
    report's 'displacement' is None.
    """
    limits = dict(limits or {})
    displacement = bool(displacement) or limits.get(DISPLACEMENT) is not None
    reference_side = await side_async(ctx, reference, displacement=displacement)
    current_side = await side_async(ctx, current, displacement=displacement)
    report = {
        "reference": reference_side,
        "current": current_side,
        "passed": None,
    }
    verdicts = []
    for key in AMOUNTS:
        if key == DISPLACEMENT and not displacement:
            report[key] = None
            continue
        entry = amount_entry(reference_side, current_side, key)
        limit = limits.get(key)
        entry["limit"] = limit
        entry["passed"] = None
        entry["detail"] = None
        if limit is not None:
            entry["passed"], entry["detail"] = within(entry, limit)
            verdicts.append(entry["passed"])
        report[key] = entry

    total, why = allowance(
        reference_side["tolerance"],
        reference_side["toleranceNote"],
        current_side["tolerance"],
        current_side["toleranceNote"],
    )
    report["tolerance"] = {
        "reference": reference_side["tolerance"],
        "current": current_side["tolerance"],
        "allowance": total,
        "note": why,
    }

    report["surface"] = None
    if spacing is not None:
        surface = await pc_measure.surface_distance(
            ctx,
            await reference.get_wrapped(ctx),
            await current.get_wrapped(ctx),
            spacing,
            allowance=total,
            worst=worst,
            cacheable=reference.artifacts_cacheable() and current.artifacts_cacheable(),
        )
        surface["passed"] = None
        if total is not None:
            surface["passed"] = not surface.get("missed") and not surface.get("beyond")
            verdicts.append(surface["passed"])
        report["surface"] = surface

    if verdicts:
        report["passed"] = all(verdicts)
    return report


# ---------------------------------------------------------------------------
# The report, as text.


def _point(entry) -> str:
    """Where a measured point is, the way the report writes it: '(4, 4, -5)'."""
    at = entry.get("at") or []
    return "(%s)" % ", ".join(number(round(value, 6)) for value in at)


def format_report(report: dict) -> typing.List[str]:
    """The lines 'pc compare' prints for a report 'compare_async()' answered."""
    reference, current = report["reference"], report["current"]
    lines = [
        "reference: %s (%s)" % (reference["object"], reference["kind"]),
        "current:   %s (%s)" % (current["object"], current["kind"]),
    ]
    for key in AMOUNTS:
        entry = report.get(key)
        if entry is None:
            continue
        unit = entry["unit"]
        line = "%s: %s -> %s" % (
            key,
            quantity(entry["reference"], unit) if entry["reference"] is not None else "not known",
            quantity(entry["current"], unit) if entry["current"] is not None else "not known",
        )
        if entry["difference"] is not None:
            line += ", difference %s%s" % (
                ("+" if entry["difference"] > 0 else "") + quantity(entry["difference"], unit),
                (
                    ""
                    if entry["percent"] is None
                    else " (%s%s%%)" % ("+" if entry["percent"] > 0 else "", number(entry["percent"]))
                ),
            )
        else:
            unknown = [
                "%s: %s" % (side, entry.get(side + "Unknown"))
                for side in ("reference", "current")
                if entry.get(side) is None and entry.get(side + "Unknown")
            ]
            if unknown:
                line += " (%s)" % "; ".join(unknown)
        if entry.get("limit") is not None:
            line += "  [%s: within %s%%]" % ("PASS" if entry["passed"] else "FAIL", number(entry["limit"]))
        lines.append(line)

    tolerance = report["tolerance"]
    parts = []
    for side, label in (("reference", "reference"), ("current", "current")):
        side_report = report[side]
        if side_report["tolerance"] is not None:
            parts.append("%s %s mm" % (label, number(side_report["tolerance"])))
        else:
            parts.append("%s %s" % (label, side_report["toleranceNote"]))
    line = "tolerance: %s" % ", ".join(parts)
    if tolerance["allowance"] is not None:
        line += "; allowance %s mm" % number(tolerance["allowance"])
    elif tolerance.get("note"):
        line += "; no allowance: %s" % tolerance["note"]
    lines.append(line)

    surface = report.get("surface")
    if surface is not None:
        points = surface.get("points") or {}
        total = sum(points.values())
        lines.append(
            "surface: %d points %s mm apart on %s mm^2 of the reference (%d vertices, %d on edges, %d on faces)"
            % (
                total,
                number(surface["spacing"]),
                number(round(surface["area"], 3)),
                points.get("vertex", 0),
                points.get("edge", 0),
                points.get("face", 0),
            )
        )
        if surface.get("nearest"):
            lines.append(
                "  %d measured to the nearest point of the current one: nothing of it lies along their normals"
                % surface["nearest"]
            )
        if surface.get("missed"):
            lines.append("  %d with nothing of the current one to measure to" % surface["missed"])
        distance = surface.get("distance")
        if distance:
            lines.append(
                "  distance: %s .. %s mm, mean %s, mean |d| %s, rms %s; |d| median %s, 95%% %s, 99%% %s, max %s"
                % tuple(
                    number(distance[key])
                    for key in ("min", "max", "mean", "meanAbs", "rms", "p50", "p95", "p99", "maxAbs")
                )
            )
        if surface.get("allowance") is not None and surface.get("beyond") is not None:
            lines.append(
                "  %d of %d points further apart than the allowance of %s mm  [%s]"
                % (
                    surface["beyond"],
                    surface.get("measured", 0),
                    number(surface["allowance"]),
                    "PASS" if surface.get("passed") else "FAIL",
                )
            )
        for entry in surface.get("worst") or []:
            if not entry.get("distance"):
                continue
            lines.append(
                "  %s mm at %s, on a%s %s%s"
                % (
                    ("+" if entry["distance"] > 0 else "") + number(entry["distance"]),
                    _point(entry),
                    "n" if entry.get("on") == "edge" else "",
                    entry.get("on"),
                    ", to the nearest point" if entry.get("how") == "nearest" else "",
                )
            )
        for entry in surface.get("missedAt") or []:
            lines.append(
                "  nothing to measure to from %s, on a%s %s"
                % (_point(entry), "n" if entry.get("on") == "edge" else "", entry.get("on"))
            )

    if report.get("passed") is None:
        lines.append("nothing was held to a limit: this is a report, not a verdict")
    else:
        lines.append("the current object %s" % ("passes" if report["passed"] else "FAILS"))
    return lines
