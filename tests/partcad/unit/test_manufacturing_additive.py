#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What an additive part says about how it is made, and what checks it."""

import pytest

import partcad as pc
from partcad.part_config import PartConfiguration
from partcad.part_config_manufacturing import (
    METHOD_ADDITIVE,
    METHOD_SUBTRACTIVE,
    PartConfigManufacturing,
)

# The package that declares an additive tool and a part made on it.
PACKAGE = "tests/partcad/unit/data/connect_how/partcad.yaml"


@pytest.fixture
def ctx():
    return pc.init(PACKAGE)


def _manufacturing(ctx, name="printed-plate"):
    return PartConfiguration.get_manufacturing_data(ctx.get_part(":" + name))


def test_the_part_names_the_machine_that_makes_it(ctx):
    """A bare name is a tool of the part's own package, like every reference"""
    manufacturing = _manufacturing(ctx)
    assert manufacturing.method == METHOD_ADDITIVE
    assert manufacturing.tool == "//:extruder"
    assert manufacturing.resolve_tool(ctx) is ctx.get_tool("//:extruder")


def test_the_settings_are_typed_and_reported(ctx):
    manufacturing = _manufacturing(ctx)
    assert manufacturing.settings["layerHeight"] == 0.2
    assert manufacturing.settings["perimeters"] == 3
    assert manufacturing.settings["supports"] is False
    assert manufacturing.info()["tool"] == "//:extruder"


def test_material_and_colour_come_from_the_properties(ctx):
    """What the machine is loaded with is normally what the part is made of"""
    manufacturing = _manufacturing(ctx)
    assert manufacturing.settings["material"] == "PLA"
    assert manufacturing.settings["color"] == "#1c8f3a"


def test_the_manufacturing_section_may_say_otherwise():
    """Printed in whatever is on the spool and painted afterwards"""
    manufacturing = PartConfigManufacturing(
        {
            "properties": {"material": "PLA", "color": "#1c8f3a"},
            "manufacturing": {"method": "additive", "material": "PETG"},
        },
        project_name="//pkg",
    )
    assert manufacturing.settings["material"] == "PETG"
    assert manufacturing.settings["color"] == "#1c8f3a"


def test_a_setting_outside_the_machines_range_is_a_problem(ctx):
    manufacturing = PartConfigManufacturing(
        {"manufacturing": {"method": "additive", "tool": "//:extruder", "layerHeight": 0.9}},
        project_name="//",
    )
    problems = manufacturing.problems(ctx)
    assert len(problems) == 1
    assert "layerHeight is 0.9" in problems[0]


def test_a_material_the_machine_does_not_take_is_a_problem(ctx):
    manufacturing = PartConfigManufacturing(
        {"manufacturing": {"method": "additive", "tool": "//:extruder", "material": "titanium"}},
        project_name="//",
    )
    assert any("does not take titanium" in problem for problem in manufacturing.problems(ctx))


def test_a_part_that_does_not_fit_the_build_volume_is_a_problem(ctx):
    manufacturing = _manufacturing(ctx)
    assert manufacturing.problems(ctx, extent=[100.0, 100.0, 100.0]) == []
    problems = manufacturing.problems(ctx, extent=[300.0, 100.0, 100.0])
    assert any("does not fit the build volume" in problem for problem in problems)


def test_a_tool_of_the_wrong_category_is_a_problem(ctx):
    """A finger does not print anything"""
    manufacturing = PartConfigManufacturing(
        {"manufacturing": {"method": "additive", "tool": "//:finger"}},
        project_name="//",
    )
    assert manufacturing.resolve_tool(ctx) is None
    assert manufacturing.problems(ctx)


def test_a_tool_that_does_not_resolve_is_a_problem(ctx):
    manufacturing = PartConfigManufacturing(
        {"manufacturing": {"method": "additive", "tool": "//:nonexistent"}},
        project_name="//",
    )
    assert any("not found" in problem for problem in manufacturing.problems(ctx))


def test_additive_settings_under_another_method_are_reported(caplog):
    """A field nothing reads is a mistake, not a decoration"""
    manufacturing = PartConfigManufacturing(
        {"manufacturing": {"method": "subtractive", "layerHeight": 0.2}},
        project_name="//pkg",
    )
    assert manufacturing.method == METHOD_SUBTRACTIVE
    assert manufacturing.settings == {}
    assert "is an additive setting" in caplog.text


def test_an_infill_outside_zero_to_one_is_reported(caplog):
    manufacturing = PartConfigManufacturing(
        {"manufacturing": {"method": "additive", "infill": 20}},
        project_name="//pkg",
    )
    assert "infill" not in manufacturing.settings
    assert "fraction between 0 and 1" in caplog.text


def test_a_part_with_no_method_has_nothing_to_check(ctx):
    manufacturing = PartConfigManufacturing({}, project_name="//pkg")
    assert manufacturing.method is None
    assert manufacturing.problems(ctx) == []
