#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object is required to be, and whether the model is it.

The subject is one package, 'data/requirements', whose objects declare
requirements they meet ('plate', and the assembly 'pair' of two of them) and
requirements they do not ('plate-wrong'). Ports and interfaces are read off the
declarations, so nothing here builds geometry: what the physics is worked out
from - what 'plate.py' measures as it is built, a 30 x 30 x 3 box about its
centre - is stood in for, and so is the tree an assembly is built as.
"""

import asyncio
import copy

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad import requirements, simulation
from partcad.assembly import Assembly
from partcad.geom import Location
from partcad.lint.all import get_partcad_schema
from partcad.shape import Shape
from partcad.test.requirements import RequirementsTest
from partcad.test.test import Test

PACKAGE = "tests/partcad/unit/data/requirements/partcad.yaml"

# What 'plate.py' measures as it is built: a 30 x 30 x 3 box about its centre,
# its centroid, and its inertia at unit density (V (b^2 + c^2) / 12 and so on).
PLATE = {
    "bbox": [-15.0, -15.0, -1.5, 15.0, 15.0, 1.5],
    "volume": 2700.0,
    "centroid": [0.0, 0.0, 0.0],
    "unitInertia": [[204525.0, 0.0, 0.0], [0.0, 204525.0, 0.0], [0.0, 0.0, 405000.0]],
    "solids": 1,
}
PLATE_VOLUME = PLATE["volume"]

# The density of the package's steel, in kg/m^3.
STEEL = 7850.0


@pytest.fixture
def ctx(monkeypatch):
    async def measured(self, ctx):
        return dict(PLATE)

    async def built(self, ctx):
        """An assembly as it is built: a node per part, each with what it measured - and no geometry."""
        await self.do_instantiate()
        return {
            "name": "%s:%s" % (self.project_name, self.name),
            "assembly": [
                {
                    "name": "%s:%s" % (child.item.project_name, child.item.name),
                    "brep": "AAAA",
                    "properties": child.item.config.get("properties") or {},
                    "metadata": {"measurements": dict(PLATE)},
                    "location": child.location.as_packed(),
                }
                for child in self.children
            ],
        }

    monkeypatch.setattr(Shape, "get_measurements_async", measured)
    monkeypatch.setattr(Assembly, "get_wrapped", built)
    # A context of its own rather than 'pc.init()': the process-wide one may be
    # another test's, already walked.
    context = pc.Context(PACKAGE)
    # Nothing weighed here is worth remembering in a cache somebody else reads.
    monkeypatch.setattr(context, "cache_shapes", None)
    return context


def _check(ctx, kind, name, verify=True):
    shape = ctx.get_assembly("//:" + name) if kind == "assembly" else ctx.get_part("//:" + name)
    return asyncio.run(requirements.check_async(ctx, shape, verify=verify))


def _verdicts(report):
    return {(check.section, check.name): check.passed for check in report.checks}


# --- one required value -------------------------------------------------------


@pytest.mark.parametrize(
    "spec, value, expected",
    [
        (0, 0.0, True),
        (0, 1e-9, True),  # to within the tolerance
        (0, 1e-3, False),
        (">0", 1e-3, True),
        (">0", 0.0, False),
        (">0", 1e-9, False),  # zero, to within the tolerance, is not more than zero
        (">=0", 0.0, True),
        ("<1", 1.0, False),
        ("<=1", 1.0, True),
        ("!0", 0.5, True),
        ("!0", 0.0, False),
        ("!=0", 0.0, False),
        ("=5", 5.0, True),
        # Constants with commas are alternatives...
        ("1,2,4", 2.0, True),
        ("1,2,4", 3.0, False),
        # ... comparisons with commas all have to hold ...
        (">0,<=1", 0.5, True),
        (">0,<=1", 1.5, False),
        (">0,<=1", 0.0, False),
        # ... and together, one of the constants and every comparison.
        ("1,2,3,!2", 2.0, False),
        ("1,2,3,!2", 3.0, True),
        # Strings and booleans are constants like any other.
        ("revolute,continuous", "continuous", True),
        ("!revolute", "revolute", False),
        (True, True, True),
        (True, 1.0, False),
        # A value that is not known never meets anything.
        (">0", None, False),
        # A comparison of something that is not a number is not met.
        (">0", "text", False),
    ],
)
def test_a_required_value(spec, value, expected):
    assert requirements.ValueSpec(spec).matches(value) is expected


@pytest.mark.parametrize("spec", ["<abc", ">", "1,,2", [1, 2], {"a": 1}])
def test_a_value_that_cannot_be_read_says_why_and_meets_nothing(spec):
    parsed = requirements.ValueSpec(spec)
    assert parsed.error
    assert parsed.matches(1.0) is False


def test_an_angle_is_compared_modulo_a_turn():
    assert requirements.ValueSpec(270).matches(-90.0, angle=True)
    assert requirements.ValueSpec("-90").matches(270.0, angle=True)
    assert requirements.ValueSpec(">0").matches(270.0, angle=True) is False  # 270 is -90


def test_a_requirement_is_shown_as_it_was_written():
    assert str(requirements.ValueSpec(">0,<=1")) == ">0,<=1"
    assert str(requirements.ValueSpec(0.5)) == "0.5"
    assert str(requirements.ValueSpec(True)) == "true"


# --- where a frame is -----------------------------------------------------------


@pytest.mark.parametrize(
    "location, direction, angle",
    [
        ([[0, 0, 0], [0, 0, 1], 0], (0, 0, 1), 0),
        # A turn about Z is the angle it was written with.
        ([[0, 0, 0], [0, 0, 1], 90], (0, 0, 1), 90),
        ([[0, 0, 0], [0, 0, 1], 270], (0, 0, 1), -90),
        # Facing down is a half turn about an axis across Z - not the axis
        # [0, 0, -1], which with any angle is a turn about Z and faces up.
        ([[0, 0, 0], [1, 0, 0], 180], (0, 0, -1), 0),
        ([[0, 0, 0], [0, 0, -1], 0], (0, 0, 1), 0),
        # A tilt about an axis across Z is turned by nothing about where it faces.
        ([[0, 0, 0], [0, 1, 0], 90], (1, 0, 0), 0),
        ([[0, 0, 0], [1, 0, 0], 90], (0, -1, 0), 0),
    ],
)
def test_where_a_frame_faces(location, direction, angle):
    _, facing, turned = requirements.facing(Location(location))
    assert facing == pytest.approx(direction, abs=1e-9)
    assert turned == pytest.approx(angle, abs=1e-9)


def test_a_location_requirement_is_written_either_way():
    as_list, _, error = requirements.LocationSpec.parse([None, [0, 0, -1], None])
    assert error is None
    as_map, _, error = requirements.LocationSpec.parse({"direction": [0, 0, -1]})
    assert error is None
    assert as_list.describe() == as_map.describe() == "direction [0, 0, -1]"
    # All of it null is no requirement at all, rather than one nothing can fail.
    assert requirements.LocationSpec.parse([None, None, None])[0] is None
    assert requirements.LocationSpec.parse([[None, None, None], None, None])[0] is None


@pytest.mark.parametrize(
    "raw",
    [
        [None, [0, 0]],  # not three things
        [None, [0, 0], None],  # a direction of two
        {"direction": [0, 0, 1], "spin": 3},  # a key a location has not got
        [None, None, [1, 2]],  # an angle of two
        "facing down",
    ],
)
def test_a_location_requirement_that_cannot_be_read_says_why(raw):
    spec, _, error = requirements.LocationSpec.parse(raw)
    assert spec is None
    assert error


def test_a_direction_of_plain_numbers_is_the_way_it_points():
    spec, _, _ = requirements.LocationSpec.parse({"direction": [0, 0, -5]})
    assert spec.mismatch(Location([[0, 0, 0], [1, 0, 0], 180])) is None


# --- the declaration ------------------------------------------------------------


def test_the_free_form_spellings_are_features():
    assert requirements.parse("Has to be flat.").features == {requirements.LEGACY_FEATURE: "Has to be flat."}
    assert requirements.parse(["a", "b"]).features == {"1": "a", "2": "b"}
    headings = requirements.parse({"mechanical": "Holds 2 kg.", "features": {"flat": "Is flat."}})
    assert headings.features == {"flat": "Is flat.", "mechanical": "Holds 2 kg."}
    assert not headings.structured


def test_a_requirement_that_cannot_be_read_is_kept_so_that_it_fails():
    declaration = requirements.parse(
        {
            "ports": {"top": [None, [0, 0], None]},
            "physics": {"mass": "<abc", "maxEffort": 1, "inertia": {"ixx": 1, "iqq": 2}, "centerOfMass": [1]},
        }
    )
    problems = {(problem.section, problem.name) for problem in declaration.problems}
    assert problems == {
        ("ports", "top"),
        ("physics", "mass"),
        # A connection's property, which an object does not state.
        ("physics", "maxEffort"),
        ("physics", "inertia.iqq"),
        ("physics", "centerOfMass"),
    }
    # What could be read still is.
    assert [requirement.path for requirement in declaration.physics] == ["inertia.ixx"]


def test_every_property_a_shape_states_can_be_required():
    """The two lists in the schema cannot drift apart: one is the other less a connection's."""
    definitions = get_partcad_schema()["definitions"]
    physics = set(definitions["physics"]["properties"])
    connection = set(definitions["shape-physics"]["allOf"][1]["propertyNames"]["not"]["enum"])
    assert set(definitions["requirement-physics"]["properties"]) == physics - connection


# --- the schema -----------------------------------------------------------------


def _package():
    with open(PACKAGE) as f:
        return yaml.safe_load(f)


def test_the_test_package_is_a_valid_configuration():
    jsonschema.validate(instance=_package(), schema=get_partcad_schema())


@pytest.mark.parametrize(
    "kind, name",
    [("parts", "plate"), ("assemblies", "pair")],
)
def test_requirements_are_refused_where_they_say_nothing(kind, name):
    for broken in (
        {"ports": {"top": [None, [0, 0], None]}},  # a direction of two
        {"physics": {"maxEffort": 1}},  # a connection's property
        {"physics": {"mass": [1, 2]}},  # one value, not two
        {"interfaces": {"m3": {"TL": {"spin": 1}}}},  # not a location
    ):
        config = _package()
        config[kind][name]["requirements"] = broken
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance=config, schema=get_partcad_schema())


def test_every_kind_of_object_may_declare_requirements():
    config = {
        "sketches": {"s": {"type": "basic", "circle": 1, "requirements": {"features": {"round": "Is round"}}}},
        "scenes": {"w": {"type": "assy", "requirements": {"physics": {"mass": "<10"}}}},
        "assemblies": {"a": {"type": "assy", "requirements": "Holds together."}},
        "parts": {"p": {"type": "step", "requirements": ["One.", "Two."]}},
    }
    jsonschema.validate(instance=config, schema=get_partcad_schema())


def test_a_simulation_names_the_feature_it_demonstrates():
    config = copy.deepcopy(_package())
    config["parts"]["plate"]["simulate"]["on-the-table"]["feature"] = ["flat", "holes"]
    jsonschema.validate(instance=config, schema=get_partcad_schema())
    assert simulation.declared(config["parts"]["plate"])[0].features == ["flat", "holes"]
    assert simulation.declared({"simulate": {"x": {"simulation": "//a:b"}}})[0].features == []


# --- verdicts -------------------------------------------------------------------


def test_without_verifying_nothing_is_judged(ctx):
    report = _check(ctx, "part", "plate", verify=False)
    assert report.defined
    assert not report.verified
    assert all(check.passed is None for check in report.checks)
    assert [feature["name"] for feature in report.to_dict()["features"]] == ["holes", "flat"]


def test_what_is_required_and_met_passes(ctx):
    report = _check(ctx, "part", "plate")
    assert report.verified
    assert _verdicts(report) == {
        ("ports", "top"): True,
        ("ports", "side"): True,
        ("interfaces", "m3-thru (TL)"): True,
        ("interfaces", "m3-thru (TR)"): True,
        # Implementing 'm3-thru' implements the interface it inherits, and one
        # of its instances is turned to face down.
        ("interfaces", "m3"): True,
        ("physics", "mass"): True,
        # From the material's 'mu'.
        ("physics", "friction"): True,
        ("physics", "density"): True,
        # Both worked out from the solid.
        ("physics", "centerOfMass"): True,
        ("physics", "inertia.izz"): True,
    }, [(check.name, check.detail) for check in report.failed]


def test_an_instance_anywhere_says_which_one_it_was(ctx):
    report = _check(ctx, "part", "plate")
    details = {check.name: check.detail for check in report.checks}
    # 'TR' is turned to face down; the 'm3' it inherits is its 'thru' instance.
    assert details["m3"] == "'TR-thru' is there"


def test_the_physics_is_what_pc_info_says_it_is(ctx):
    """Stated, else lent by the material, else worked out from the solid - by 'partcad.physics'."""
    resolved = asyncio.run(
        requirements.resolve_physics_async(
            ctx, ctx.get_part("//:plate"), ["mass", "density", "friction", "centerOfMass", "inertia.izz"]
        )
    )
    mass = PLATE_VOLUME * 1e-9 * STEEL
    assert resolved["mass"][0] == pytest.approx(mass)
    assert resolved["mass"][1] == "derived: 2700 mm^3 at 7850 kg/m^3"
    assert resolved["density"] == (STEEL, "the material //:steel")
    assert resolved["friction"] == (0.6, "the material //:steel")
    assert resolved["centerOfMass"][0] == pytest.approx([0.0, 0.0, 0.0])
    assert resolved["inertia.izz"][0] > 0

    report = _check(ctx, "part", "plate")
    mass_check = next(check for check in report.checks if check.name == "mass")
    assert mass_check.detail == "%g kg (derived: 2700 mm^3 at 7850 kg/m^3)" % mass


def test_what_is_required_and_not_met_fails_saying_what_was_found(ctx):
    report = _check(ctx, "part", "plate-wrong")
    verdicts = _verdicts(report)
    assert verdicts == {
        # A simulation naming a feature nobody declared.
        ("simulate", "wobbles"): False,
        ("ports", "top"): False,
        ("ports", "bottom"): False,
        ("ports", "turned"): False,
        ("interfaces", "m3-thru (TL)"): False,
        ("interfaces", "m3-thru (BR)"): False,
        ("interfaces", "rail"): False,
        # Its material states no density, so there is no mass to compare.
        ("physics", "mass"): False,
        # Worked out from the solid whatever it is made of, and not where required.
        ("physics", "centerOfMass"): False,
        # Neither stated nor lent by anything.
        ("physics", "restitution"): False,
    }
    details = {check.name: check.detail for check in report.checks}
    assert "faces [0, 0, 1]" in details["top"]
    assert "there is no port 'bottom'" in details["bottom"]
    assert "the position is [-10, 10, 0]" in details["m3-thru (TL)"]
    assert "there is no instance 'BR'" in details["m3-thru (BR)"]
    assert "does not implement 'rail'" in details["rail"]
    assert details["mass"] == "not known: the material //:air states no density"
    assert "x does not match" in details["centerOfMass"]
    assert "states no 'restitution'" in details["restitution"]
    assert "'stable'" in details["wobbles"]


def test_an_assembly_is_held_to_what_it_externalizes_and_what_it_holds(ctx):
    report = _check(ctx, "assembly", "pair")
    assert _verdicts(report) == {("ports", "bottom-face"): True, ("physics", "mass"): True}
    mass = next(check for check in report.checks if check.name == "mass")
    assert mass.detail == "%g kg (the sum of 2 parts)" % (2 * PLATE_VOLUME * 1e-9 * STEEL)


def test_an_assembly_part_of_which_weighs_nothing_known_has_no_mass_to_compare(ctx, monkeypatch):
    """What the others add up to is not what the assembly weighs."""
    from partcad import material

    monkeypatch.setattr(material.Material, "density", property(lambda self: None))
    report = _check(ctx, "assembly", "pair")
    mass = next(check for check in report.checks if check.name == "mass")
    assert mass.passed is False
    assert mass.detail.startswith("not known: ")


def test_an_object_that_requires_nothing_has_no_report(ctx):
    report = _check(ctx, "part", "plain")
    assert not report.defined
    assert report.checks == []
    assert report.to_dict()["features"] == []


# --- 'pc test' ------------------------------------------------------------------


def _run_test(ctx, name):
    shape = ctx.get_part("//:" + name)
    return asyncio.run(RequirementsTest().test([], ctx, shape, {}))


def test_pc_test_passes_an_object_that_meets_its_requirements(ctx):
    assert _run_test(ctx, "plate") is Test.TEST_PASSED


def test_pc_test_fails_an_object_that_does_not(ctx):
    assert _run_test(ctx, "plate-wrong") is Test.TEST_FAILED


def test_pc_test_has_nothing_to_say_about_features_alone(ctx):
    assert _run_test(ctx, "legacy-headings") is Test.TEST_PASSED
    assert _run_test(ctx, "plain") is Test.TEST_PASSED


def test_pc_test_never_remembers_the_verdict(ctx):
    """What it reads is mostly not what the cache key is made of."""
    test_ctx = {}
    shape = ctx.get_part("//:plate")
    asyncio.run(RequirementsTest().test([], ctx, shape, test_ctx))
    assert test_ctx[Test.NOT_CACHEABLE] is True
