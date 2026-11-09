#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Two objects read against each other: the rules 'pc compare' and 'match:' share.

What a volume and a mass *are* is 'partcad.physics', and how far apart two
surfaces are is 'wrappers/wrapper_compare.py', each tested beside itself; both are
stood in for here. What is pinned is the arithmetic between them -- which way a
difference goes, what it is a percentage of, when a limit holds -- the
tolerances added up into an allowance, when a comparison is a verdict and when
only a report, and the lines it is printed as.
"""

import asyncio
import math

import pytest

from partcad import compare


class _Shape:
    def __init__(self, name, kind="part", tolerance=0.0):
        self.project_name = "//pkg"
        self.name = name
        self.kind = kind
        self._tolerance = tolerance
        self.wrapped = {"name": name}

    async def get_tolerance(self):
        """The tolerance the shape was given, or the exception it was told to raise."""
        if isinstance(self._tolerance, Exception):
            raise self._tolerance
        return self._tolerance

    async def get_wrapped(self, ctx):
        return self.wrapped

    def artifacts_cacheable(self):
        return True


@pytest.fixture
def amounts(monkeypatch):
    """What each object weighs and holds, by name; and every surface and displacement measurement asked for.

    What each object displaces is under 'displaced', by name: what the sandbox
    answers, or the exception it fails with.
    """
    table = {"displaced": {}}
    measured = []
    displaced = []

    async def amounts_async(ctx, shape):
        return table.get(shape.name)

    async def surface_distance(ctx, reference, current, spacing, allowance=None, worst=10, cacheable=True):
        measured.append((reference, current, spacing, allowance, worst, cacheable))
        return dict(table.get("surface", {}), allowance=allowance)

    async def displacement(ctx, shape, cacheable=True):
        displaced.append((shape, cacheable))
        answer = table["displaced"].get(shape["name"])
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(compare.pc_physics, "amounts_async", amounts_async)
    monkeypatch.setattr(compare.pc_measure, "surface_distance", surface_distance)
    monkeypatch.setattr(compare.pc_measure, "displacement", displacement)
    table["measured"] = measured
    table["displacements measured"] = displaced
    return table


def _side(volume, mass, unknown=None):
    """What 'physics.amounts_async' answers for an object of that volume and mass."""
    return {"volume": volume, "mass": mass, "massSource": None if mass is None else "stated", "unknown": unknown}


def _compare(reference, current, **kwargs):
    return asyncio.run(compare.compare_async(None, reference, current, **kwargs))


# --- the arithmetic ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (5, 5.0),
        (0, 0.0),
        (2.5, 2.5),
        ("5%", 5.0),
        (" 5 % ", 5.0),
        ("0.5", 0.5),
        (-1, None),
        ("-1%", None),
        ("lots", None),
        (True, None),
        (None, None),
        (float("nan"), None),
        ([5], None),
    ],
)
def test_a_limit_is_a_percentage_written_either_way(raw, expected):
    """5, 5.0 and '5%' are one limit; a negative, non-numeric or infinite one is none."""
    assert compare.percent_limit(raw) == expected


def test_a_difference_is_the_current_less_the_reference_as_a_share_of_the_reference():
    """A zero or unknown reference has no share to take, and says so with None."""
    assert compare.difference(100.0, 105.0) == {"reference": 100.0, "current": 105.0, "difference": 5.0, "percent": 5.0}
    assert compare.difference(100.0, 90.0)["percent"] == pytest.approx(-10.0)
    # Nothing to take a share of.
    assert compare.difference(0.0, 1.0)["percent"] is None
    assert compare.difference(0.0, 0.0)["percent"] == 0.0
    # Not known on either side, nothing to subtract.
    assert compare.difference(None, 1.0) == {"reference": None, "current": 1.0, "difference": None, "percent": None}


def test_a_limit_holds_either_way_and_says_so():
    """A limit bounds the difference in both directions, and the detail says by how much and which way."""
    entry = dict(compare.difference(1000.0, 1050.0), unit="mm^3")
    assert compare.within(entry, 5) == (True, "1050 mm^3, 5% more than the reference's 1000 mm^3 (within 5%)")
    assert compare.within(entry, 4) == (False, "1050 mm^3, 5% more than the reference's 1000 mm^3 (more than 4%)")
    lighter = dict(compare.difference(2.0, 1.9), unit="kg")
    assert compare.within(lighter, 5)[0] is True
    assert "5% less than" in compare.within(lighter, 5)[1]


def test_a_value_not_known_never_holds():
    """Not known is not within a limit, and the detail says which side is not known and why."""
    entry = dict(compare.difference(None, 1.0), unit="kg", referenceUnknown="it states no density")
    assert compare.within(entry, 100) == (False, "the reference's is not known: it states no density")
    entry = dict(compare.difference(1.0, None), unit="kg", currentUnknown="nothing it is made of says")
    assert compare.within(entry, 100) == (False, "it is not known: nothing it is made of says")
    entry = dict(compare.difference(0.0, 1.0), unit="kg")
    assert compare.within(entry, 100) == (False, "it is 1 kg, and the reference's is 0")


def test_the_allowance_is_both_tolerances_added_up():
    """Each object may be off by its own tolerance; feature-by-feature tolerances have no one sum."""
    assert compare.allowance(0.1, None, 0.05, None) == (pytest.approx(0.15), None)
    # Nobody said: nothing.
    assert compare.allowance(None, compare.NO_TOLERANCE, 0.05, None) == (0.05, None)
    # A file that tolerances each feature its own way has no one number.
    assert compare.allowance(None, compare.FEATURE_BY_FEATURE, 0.05, None) == (None, compare.FEATURE_BY_FEATURE)


# --- the comparison -------------------------------------------------------------


def test_with_nothing_to_hold_it_to_a_comparison_is_a_report(amounts):
    """No limit and no surface: the differences are reported, 'passed' is None, and nothing is measured."""
    amounts["old"] = _side(1000.0, 0.0027)
    amounts["new"] = _side(1050.0, 0.002835)
    report = _compare(_Shape("old"), _Shape("new"))
    assert report["passed"] is None
    assert report["reference"]["object"] == "//pkg:old"
    assert report["current"]["object"] == "//pkg:new"
    assert report["volume"]["percent"] == pytest.approx(5.0)
    assert report["mass"]["difference"] == pytest.approx(0.000135)
    assert report["volume"]["passed"] is None
    assert report["surface"] is None
    assert report["displacement"] is None
    assert amounts["measured"] == []
    assert amounts["displacements measured"] == []


def test_a_limit_given_is_a_verdict(amounts):
    """A limit on the volume or the mass makes the comparison pass or fail on it."""
    amounts["old"] = _side(1000.0, 1.0)
    amounts["new"] = _side(1050.0, 1.01)
    report = _compare(_Shape("old"), _Shape("new"), limits={"volume": 4.0, "mass": 2.0})
    assert report["volume"]["passed"] is False
    assert report["mass"]["passed"] is True
    assert report["passed"] is False
    assert _compare(_Shape("old"), _Shape("new"), limits={"mass": 2.0})["passed"] is True


def test_a_mass_not_known_fails_a_limit_on_it(amounts):
    """A reference that weighs nothing known fails a mass limit, saying why."""
    amounts["old"] = _side(1000.0, None, unknown="the part states no density and names no material")
    amounts["new"] = _side(1000.0, 1.0)
    report = _compare(_Shape("old"), _Shape("new"), limits={"mass": 50})
    assert report["passed"] is False
    assert report["mass"]["detail"] == (
        "the reference's is not known: the part states no density and names no material"
    )


def test_the_surface_is_judged_against_the_allowance_whenever_it_is_measured(amounts):
    """Every point within the allowance and none missed, or it fails; the sandbox is told the allowance."""
    amounts["old"] = _side(1000.0, None)
    amounts["new"] = _side(1000.0, None)
    reference, current = _Shape("old", tolerance=0.1), _Shape("new", tolerance=0.05)

    amounts["surface"] = {"measured": 400, "missed": 0, "beyond": 0}
    report = _compare(reference, current, spacing=2.0, worst=3)
    ((asked_reference, asked_current, spacing, allowance, worst, cacheable),) = amounts["measured"]
    assert (asked_reference, asked_current) == ({"name": "old"}, {"name": "new"})
    assert (spacing, worst, cacheable) == (2.0, 3, True)
    assert allowance == pytest.approx(0.15)
    assert report["tolerance"]["allowance"] == pytest.approx(0.15)
    assert report["surface"]["passed"] is True
    assert report["passed"] is True

    amounts["surface"] = {"measured": 400, "missed": 0, "beyond": 12}
    assert _compare(reference, current, spacing=2.0)["passed"] is False
    amounts["surface"] = {"measured": 399, "missed": 1, "beyond": 0}
    assert _compare(reference, current, spacing=2.0)["passed"] is False


def test_a_surface_with_no_one_allowance_is_measured_and_not_judged(amounts):
    """A file tolerancing each feature apart has no one allowance: the surface is reported, not judged."""
    amounts["old"] = _side(1000.0, None)
    amounts["new"] = _side(1000.0, None)
    amounts["surface"] = {"measured": 400, "missed": 0, "beyond": None}
    report = _compare(_Shape("old", tolerance=math.nan), _Shape("new"), spacing=2.0)
    assert report["reference"]["tolerance"] is None
    assert report["reference"]["toleranceNote"] == compare.FEATURE_BY_FEATURE
    assert report["tolerance"]["allowance"] is None
    assert report["surface"]["passed"] is None
    assert report["passed"] is None


def test_a_tolerance_that_cannot_be_read_counts_as_nothing_and_says_why(amounts):
    """An unreadable tolerance and one nobody stated both count as 0, each with its reason."""
    amounts["old"] = _side(1.0, None)
    amounts["new"] = _side(1.0, None)
    report = _compare(_Shape("old", tolerance=RuntimeError("the file is gone")), _Shape("new", tolerance=None))
    assert report["reference"]["toleranceNote"] == "could not be read: the file is gone"
    assert report["current"]["toleranceNote"] == compare.NO_TOLERANCE
    assert report["tolerance"]["allowance"] == 0.0


def _displaced(displacement, cavities=0, solids=1):
    """What the sandbox answers for an object displacing that much, with that many voids sealed in it."""
    return {"displacement": displacement, "solids": solids, "cavities": cavities}


def test_the_displacements_are_measured_when_asked_for(amounts):
    """Each object's envelope goes to the sandbox, and the two are read against each other like the volumes."""
    amounts["old"] = _side(992.0, None)
    amounts["new"] = _side(992.0, None)
    amounts["displaced"] = {"old": _displaced(1000.0, cavities=1), "new": _displaced(992.0)}
    report = _compare(_Shape("old"), _Shape("new"), displacement=True)

    assert amounts["displacements measured"] == [({"name": "old"}, True), ({"name": "new"}, True)]
    assert report["reference"]["displacement"] == 1000.0
    assert report["reference"]["cavities"] == 1
    assert report["current"]["cavities"] == 0
    entry = report["displacement"]
    assert (entry["reference"], entry["current"], entry["difference"]) == (1000.0, 992.0, -8.0)
    assert entry["percent"] == pytest.approx(-0.8)
    assert entry["unit"] == "mm^3"
    assert (entry["limit"], entry["passed"]) == (None, None)
    # The same material, so the volumes alone would say they are the same object.
    assert report["volume"]["percent"] == 0.0
    assert report["passed"] is None


def test_a_limit_on_the_displacement_measures_it_and_is_a_verdict(amounts):
    """Asked for by the limit alone, and judged like any other amount."""
    amounts["old"] = _side(992.0, None)
    amounts["new"] = _side(992.0, None)
    amounts["displaced"] = {"old": _displaced(1000.0, cavities=1), "new": _displaced(992.0)}

    report = _compare(_Shape("old"), _Shape("new"), limits={"displacement": 0.5})
    assert report["displacement"]["passed"] is False
    assert report["displacement"]["detail"] == "992 mm^3, 0.8% less than the reference's 1000 mm^3 (more than 0.5%)"
    assert report["passed"] is False
    assert _compare(_Shape("old"), _Shape("new"), limits={"displacement": 1})["passed"] is True


def test_a_displacement_not_measured_fails_a_limit_and_says_why(amounts):
    """A sandbox that fails, and an object holding no solid, leave it not known -- which no limit holds."""
    amounts["old"] = _side(1000.0, None)
    amounts["new"] = _side(None, None)
    amounts["displaced"] = {"old": RuntimeError("the sandbox did not start"), "new": _displaced(None, solids=0)}
    report = _compare(_Shape("old"), _Shape("new"), limits={"displacement": 5})

    assert report["reference"]["displacementUnknown"] == "could not be measured: the sandbox did not start"
    assert report["current"]["displacementUnknown"] == compare.NO_SOLID
    assert report["displacement"]["passed"] is False
    assert report["displacement"]["detail"] == (
        "the reference's is not known: could not be measured: the sandbox did not start"
    )

    amounts["displaced"]["old"] = _displaced(1000.0)
    report = _compare(_Shape("old"), _Shape("new"), limits={"displacement": 5})
    assert report["displacement"]["detail"] == "it is not known: it holds no solid"


def test_a_displacement_is_one_trip_to_the_measure_wrapper(monkeypatch):
    """'measure.displacement' asks the measure wrapper's 'displacement', remembered like any measurement."""
    asked = []

    async def run(ctx, request, cacheable=True, script="measure.py"):
        asked.append((request, cacheable, script))
        return _displaced(1000.0, cavities=1)

    monkeypatch.setattr(compare.pc_measure, "_run", run)
    envelope = {"name": "old"}
    assert asyncio.run(compare.pc_measure.displacement("ctx", envelope, cacheable=False)) == _displaced(1000.0, 1)
    assert asked == [({"operation": "displacement", "shape": envelope}, False, "measure.py")]


# --- the report -----------------------------------------------------------------


def test_the_report_says_each_difference_and_the_verdict(amounts):
    """The lines 'pc compare' prints: each amount and its verdict, the tolerances, the surface and its worst points."""
    amounts["old"] = _side(1000.0, 0.0027)
    amounts["new"] = _side(1050.0, None, unknown="it states no density and names no material")
    amounts["surface"] = {
        "spacing": 1.0,
        "area": 600.0,
        "points": {"vertex": 8, "edge": 108, "face": 384},
        "measured": 500,
        "nearest": 4,
        "missed": 0,
        "beyond": 128,
        "distance": {
            "min": 0.0,
            "max": 0.25,
            "mean": 0.064,
            "meanAbs": 0.064,
            "rms": 0.1265,
            "maxAbs": 0.25,
            "p50": 0.0,
            "p95": 0.25,
            "p99": 0.25,
        },
        "worst": [
            {"at": [4.0, 4.0, -5.0], "normal": [0, 0, -1], "distance": 0.25, "on": "face", "how": "normal"},
            {"at": [-5.0, -5.0, -5.0], "normal": None, "distance": -0.5, "on": "edge", "how": "nearest"},
        ],
        "missedAt": [],
    }
    report = _compare(_Shape("old"), _Shape("new"), spacing=1.0, limits={"volume": 4})
    lines = compare.format_report(report)
    assert lines[0] == "reference: //pkg:old (part)"
    assert lines[1] == "current:   //pkg:new (part)"
    assert lines[2] == "volume: 1000 mm^3 -> 1050 mm^3, difference +50 mm^3 (+5%)  [FAIL: within 4%]"
    assert lines[3] == "mass: 0.0027 kg -> not known (current: it states no density and names no material)"
    assert lines[4] == "tolerance: reference 0 mm, current 0 mm; allowance 0 mm"
    assert "500 points 1 mm apart on 600 mm^2" in lines[5]
    assert any("4 measured to the nearest point" in line for line in lines)
    assert any("128 of 500 points further apart than the allowance of 0 mm  [FAIL]" in line for line in lines)
    assert "  +0.25 mm at (4, 4, -5), on a face" in lines
    assert "  -0.5 mm at (-5, -5, -5), on an edge, to the nearest point" in lines
    assert lines[-1] == "the current object FAILS"


def test_the_displacement_is_reported_between_the_volume_and_the_mass(amounts):
    """Only when it was measured: a report without it is the report it always was."""
    amounts["old"] = _side(992.0, 0.0078)
    amounts["new"] = _side(992.0, 0.0078)
    amounts["displaced"] = {"old": _displaced(1000.0, cavities=1), "new": _displaced(992.0)}
    lines = compare.format_report(_compare(_Shape("old"), _Shape("new"), limits={"displacement": 1}))

    assert lines[2] == "volume: 992 mm^3 -> 992 mm^3, difference 0 mm^3 (0%)"
    assert lines[3] == "displacement: 1000 mm^3 -> 992 mm^3, difference -8 mm^3 (-0.8%)  [PASS: within 1%]"
    assert lines[4].startswith("mass: 0.0078 kg -> 0.0078 kg")
    assert lines[-1] == "the current object passes"


def test_a_report_with_nothing_judged_says_it_is_not_a_verdict(amounts):
    """Unknown amounts say why, and a report held to nothing says it is not a verdict."""
    amounts["old"] = _side(None, None, unknown="x")
    amounts["new"] = _side(None, None, unknown="y")
    lines = compare.format_report(_compare(_Shape("old", kind="assembly"), _Shape("new")))
    assert lines[2].startswith("volume: not known -> not known (reference: it holds no solid")
    assert lines[-1] == "nothing was held to a limit: this is a report, not a verdict"
