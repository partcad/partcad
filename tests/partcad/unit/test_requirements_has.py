#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The yes-or-no requirements: 'has_color', 'has_material', 'has_finish' and 'has_weight'."""

import asyncio
import textwrap

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad import requirements
from partcad.lint.all import get_partcad_schema

PACKAGE = """
colors:
  natural: "#A8A9AD"
  red: "#C91A09"
  picture:
    display: "#00FF00"
    manufacturable: false
materials:
  alu:
    density: 2700
    color: ":natural"
  mystery:
    desc: A substance nobody has weighed
finishes:
  satin:
    display: {roughness: 0.6}
parts:
  # Bought, as a vendor's part is, and specified all the same.
  specified:
    type: basic
    cuboid: 10
    vendor: acme
    sku: "1"
    parameters:
      material: {type: string, default: ":alu"}
      finish: {type: string, default: ":satin"}
    requirements:
      has_color: true
      has_material: true
      has_finish: true
      has_weight: true
  bare:
    type: basic
    cuboid: 10
    requirements:
      has_color: false
      has_material: false
      has_finish: false
      has_mass: false
  bare-but-required:
    type: basic
    cuboid: 10
    requirements:
      has_color: true
      has_material: true
      has_finish: true
      has_weight: true
  a-picture:
    type: basic
    cuboid: 10
    parameters:
      color: {type: string, default: ":picture"}
      material: {type: string, default: ":mystery"}
    requirements:
      has_color: true
      has_material: true
      has_weight: true
  misspelt:
    type: basic
    cuboid: 10
    parameters:
      material: {type: string, default: ":aluminium"}
    requirements:
      has_material: true
  # Another name for 'specified', under which it is bought again.
  specified-again:
    type: alias
    source: specified
    vendor: acme
    sku: "2"
  with-a-stated-weight:
    type: basic
    cuboid: 10
    properties:
      physics:
        mass: 0.002
    requirements:
      has_weight: true
assemblies:
  kit:
    type: assy
    requirements:
      has_material: true
      has_weight: true
"""

KIT = """
links:
  - part: specified
    name: one
  - part: bare
    name: two
    location: [[20, 0, 0], [0, 0, 1], 0]
"""


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    path = tmp_path_factory.mktemp("has")
    (path / "partcad.yaml").write_text(textwrap.dedent(PACKAGE))
    (path / "kit.assy").write_text(textwrap.dedent(KIT))
    return pc.Context(str(path))


def _report(ctx, name, kind="part"):
    shape = ctx.get_assembly(":" + name) if kind == "assembly" else ctx.get_part(":" + name)
    assert shape is not None, name
    return asyncio.run(requirements.check_async(ctx, shape))


def _verdicts(report) -> dict:
    return {check.name: check.passed for check in report.checks if check.section == requirements.HAS}


def _details(report) -> dict:
    return {check.name: check.detail for check in report.checks if check.section == requirements.HAS}


# --- reading them ------------------------------------------------------------


def test_each_is_read_as_a_requirement_and_not_as_a_feature():
    declaration = requirements.parse({"has_material": True, "has_mass": False, "general": "Holds together."})
    assert [(has.name, has.required) for has in declaration.has] == [("has_material", True), ("has_weight", False)]
    assert declaration.features == {"general": "Holds together."}
    assert declaration.structured


@pytest.mark.parametrize(
    "raw, problem",
    [
        ({"has_color": "yes"}, "has_color"),
        ({"has_finish": 1}, "has_finish"),
        ({"has_weight": True, "has_mass": True}, "has_mass"),
    ],
)
def test_one_that_cannot_be_read_says_why_and_meets_nothing(raw, problem):
    declaration = requirements.parse(raw)
    assert [(p.section, p.name) for p in declaration.problems] == [(requirements.HAS, problem)]


def test_the_schema_takes_them_and_only_as_true_or_false():
    schema = get_partcad_schema()
    package = yaml.safe_load(textwrap.dedent(PACKAGE))
    jsonschema.validate(package, schema)
    package["parts"]["bare"]["requirements"]["has_color"] = "no"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(package, schema)


# --- checking them -----------------------------------------------------------


def test_a_bought_part_that_says_what_it_is_has_all_of_it(ctx):
    report = _report(ctx, "specified")
    assert _verdicts(report) == {"has_color": True, "has_material": True, "has_finish": True, "has_weight": True}
    # The colour is the one its material claims.
    assert "colour" in _details(report)["has_color"]
    assert "0.0027 kg" in _details(report)["has_weight"]


def test_an_alias_has_what_its_source_has(ctx):
    """The requirements are its source's, and so is what it is made of: read as 'pc info' reads it."""
    verdicts = _verdicts(_report(ctx, "specified-again"))
    assert {name: verdicts[name] for name in ("has_color", "has_material", "has_finish")} == {
        "has_color": True,
        "has_material": True,
        "has_finish": True,
    }


def test_one_required_not_to_have_any_meets_that(ctx):
    assert set(_verdicts(_report(ctx, "bare")).values()) == {True}


def test_one_required_to_have_what_it_has_not_says_what_is_missing(ctx):
    report = _report(ctx, "bare-but-required")
    assert _verdicts(report) == {"has_color": False, "has_material": False, "has_finish": False, "has_weight": False}
    details = _details(report)
    assert details["has_material"] == "no material on any of its solids"
    assert details["has_finish"] == "no finish on any of its faces"
    assert details["has_weight"].startswith("not known")


def test_a_picture_is_no_colour_and_a_substance_nobody_weighed_is_no_weight(ctx):
    report = _report(ctx, "a-picture")
    assert _verdicts(report) == {"has_color": False, "has_material": True, "has_weight": False}
    assert "display-only" in _details(report)["has_color"]


def test_a_material_that_does_not_resolve_is_none(ctx):
    report = _report(ctx, "misspelt")
    assert _verdicts(report) == {"has_material": False}
    assert "does not resolve" in _details(report)["has_material"]


def test_a_stated_weight_is_a_weight(ctx):
    assert _verdicts(_report(ctx, "with-a-stated-weight")) == {"has_weight": True}


def test_of_an_assembly_every_part_in_it_is_held_to_it(ctx):
    report = _report(ctx, "kit", kind="assembly")
    assert _verdicts(report) == {"has_material": False, "has_weight": False}
    # The part that lacks it is named; the one that has it is not.
    assert ":bare" in _details(report)["has_material"]
    assert ":specified" not in _details(report)["has_material"]


def test_pc_qual_test_holds_a_bought_part_to_them(ctx):
    from partcad.qual.basic.requirements import RequirementsTest

    shape = ctx.get_part(":bare-but-required")
    assert RequirementsTest().inapplicable(shape) is None
    assert not asyncio.run(RequirementsTest().test([], ctx, shape, {}))
