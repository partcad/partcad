#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The 'tools' section of a package: what a product is made *with*."""

import pytest

import partcad as pc
from partcad.tool import (
    CATEGORIES,
    AdditiveTool,
    MechanicalTool,
    SubtractiveTool,
    Tool,
)

# The fixture package that declares one tool of every category.
TOOL_PACKAGE = "tests/partcad/unit/data/connect_how/partcad.yaml"


@pytest.fixture
def project():
    ctx = pc.init(TOOL_PACKAGE)
    return ctx, ctx.get_project("//")


#
# The section
#


def test_tools_are_objects_of_the_package(project):
    """Every tool of every sub-section is an object of the package"""
    _, prj = project
    assert set(prj.tools.keys()) == {"finger", "driver", "thumb", "extruder", "end-mill"}


def test_the_subsection_becomes_the_category(project):
    """A tool does not declare its category: the sub-section it sits in is it"""
    _, prj = project
    assert prj.get_tool("finger").category == "mechanical"
    assert prj.get_tool("extruder").category == "additive"
    assert prj.get_tool("end-mill").category == "subtractive"


def test_the_category_decides_the_class(project):
    """Each category is a class of its own, not a set of fields on one class"""
    _, prj = project
    assert isinstance(prj.get_tool("finger"), MechanicalTool)
    assert isinstance(prj.get_tool("extruder"), AdditiveTool)
    assert isinstance(prj.get_tool("end-mill"), SubtractiveTool)
    assert all(isinstance(prj.get_tool(name), Tool) for name in prj.tools)


def test_every_category_has_a_class():
    """A category with no class would be a tool nothing can read"""
    from partcad.tool import TOOL_CLASSES

    assert set(TOOL_CLASSES.keys()) == set(CATEGORIES)


def test_an_unknown_category_is_reported_and_dropped(caplog):
    """A sub-section PartCAD does not know is not a tool of no class at all"""
    project = _project({"tools": {"pneumatic": {"suction-cup": {"visual": "plate"}}}})
    assert project.tools == {}
    assert "unknown tool category" in caplog.text


def test_one_name_under_two_categories_keeps_the_first(caplog):
    """One name is one object, and saying it twice is a mistake somebody made"""
    project = _project(
        {
            "tools": {
                "mechanical": {"clamp": {"visual": "plate"}},
                "subtractive": {"clamp": {"visual": "plate"}},
            }
        }
    )
    assert project.get_tool("clamp").category == "mechanical"
    assert "declared under two categories" in caplog.text


#
# What a tool says about itself
#


def test_the_visual_is_resolved_against_the_declaring_package(project):
    """A bare name means a part of the package the tool was written in"""
    ctx, prj = project
    assert prj.get_tool("finger").visual == "%s:tool-visual" % prj.name
    assert prj.get_tool("finger").get_visual(ctx) is ctx.get_part(prj.name + ":tool-visual")


def test_the_short_form_is_the_visual(project):
    """A tool with nothing else to say is written as its likeness alone"""
    _, prj = project
    thumb = prj.get_tool("thumb")
    assert isinstance(thumb, MechanicalTool)
    assert thumb.visual == "%s:tool-visual" % prj.name


def test_a_tool_without_a_visual_says_so(caplog):
    """There is nothing to draw where such a tool acts, and that is worth saying"""
    project = _project({"tools": {"mechanical": {"clamp": {"mates": "grip"}}}})
    tool = project.get_tool("clamp")
    assert tool.visual is None
    assert tool.errors
    assert "no 'visual'" in caplog.text


def test_a_visual_that_does_not_resolve_is_reported(project, caplog):
    """A likeness that is not there costs the picture its tool, not the run"""
    ctx, _ = project
    project_obj = _project({"tools": {"mechanical": {"clamp": {"visual": "nonexistent"}}}})
    assert project_obj.get_tool("clamp").get_visual(project_obj.ctx) is None
    assert "not found" in caplog.text


def test_mates_are_resolved_against_the_declaring_package(project):
    """So does an interface the tool meets an object through"""
    _, prj = project
    assert prj.get_tool("finger").mates == ["%s:grip" % prj.name]
    assert prj.get_tool("driver").mates == ["%s:drive" % prj.name]


def test_only_a_tool_with_torque_can_drive(project):
    """A finger is not a screwdriver, and 'torqueMax' is what says so"""
    _, prj = project
    assert prj.get_tool("finger").torque_max == 0.0
    assert not prj.get_tool("finger").can_drive()
    assert prj.get_tool("driver").can_drive()


def test_a_force_range_that_contradicts_itself_is_dropped(caplog):
    """A minimum above a maximum is not a range"""
    project = _project({"tools": {"mechanical": {"clamp": {"visual": "plate", "forceMin": 9.0, "forceMax": 2.0}}}})
    tool = project.get_tool("clamp")
    assert tool.force_min is None and tool.force_max is None
    assert "'forceMin' is above 'forceMax'" in caplog.text


def test_each_category_reports_its_own_properties(project):
    """'pc info' shows what that kind of tool has to say, and not more"""
    _, prj = project
    mechanical = prj.get_tool("finger").info()
    assert mechanical["Category"] == "mechanical"
    assert mechanical["ForceMax"] == 20.0
    assert "Process" not in mechanical

    additive = prj.get_tool("extruder").info()
    assert additive["Process"] == "fdm"
    assert additive["Materials"] == ["PLA", "PETG"]
    assert additive["BuildVolume"] == [220.0, 220.0, 250.0]
    assert additive["StepSize"] == [0.0125, 0.0125, 0.0025]
    assert additive["LayerHeight"] == {"min": 0.08, "max": 0.32, "default": 0.2, "unit": "mm"}
    assert additive["Positioning"]["home"] == ["z", "x", "y"]
    assert "TorqueMax" not in additive

    subtractive = prj.get_tool("end-mill").info()
    assert subtractive["Diameter"] == 3.0
    assert subtractive["Flutes"] == 2
    assert "Material" not in subtractive


#
# The tools PartCAD ships
#


def test_builtin_declares_the_tools_nobody_wants_to_declare_twice():
    """'//builtin' carries a finger and the drivers, reachable from any context"""
    ctx = pc.init(TOOL_PACKAGE)
    builtin = ctx.get_project("//builtin")
    assert {"finger", "screwdriver-hex", "screwdriver-philips", "screwdriver-slotted"} <= set(builtin.tools)

    finger = ctx.get_tool("//builtin:finger")
    assert isinstance(finger, MechanicalTool)
    assert finger.mates == ["//builtin:grip"]
    assert not finger.can_drive()

    for name in ("screwdriver-hex", "screwdriver-philips", "screwdriver-slotted"):
        driver = ctx.get_tool("//builtin:" + name)
        assert driver.can_drive()
        assert driver.mates and driver.mates[0].startswith("//builtin:drive-")


def test_builtin_tool_interfaces_are_not_abstract():
    """An abstract interface is dropped from what an object implements"""
    ctx = pc.init(TOOL_PACKAGE)
    for name in ("grip", "drive-hex", "drive-philips", "drive-slotted"):
        assert not ctx.get_interface("//builtin:" + name).abstract


def test_every_builtin_tool_visual_resolves():
    """A tool whose likeness is missing draws nothing, so none of them may be"""
    ctx = pc.init(TOOL_PACKAGE)
    builtin = ctx.get_project("//builtin")
    for name, tool in builtin.tools.items():
        assert tool.get_visual(ctx) is not None, name
        assert not tool.errors, (name, tool.errors)


#
# Helpers
#


def _project(config):
    """A package built from a configuration written here rather than on disk."""
    ctx = pc.init(TOOL_PACKAGE)
    return pc.Project(ctx, "//in-memory", ctx.get_project("//").config_dir, config_obj=dict(config))


#
# What an additive tool says a machine can do
#


def test_a_range_is_written_four_ways(project):
    """A fixed value, a pair, a triple and a mapping are one thing"""
    from partcad.tool import ToolRange

    fixed = ToolRange.parse(0.2, "test", "layerHeight")
    assert (fixed.minimum, fixed.maximum, fixed.default) == (0.2, 0.2, 0.2)
    assert ToolRange.parse([0.05, 0.3], "test", "layerHeight").default is None
    assert ToolRange.parse([0.05, 0.3, 0.2], "test", "layerHeight").default == 0.2
    mapped = ToolRange.parse({"min": 0.05, "max": 0.3, "default": 0.2}, "test", "layerHeight")
    assert (mapped.minimum, mapped.maximum, mapped.default) == (0.05, 0.3, 0.2)


@pytest.mark.parametrize(
    "config",
    [
        "wide",
        [0.3],
        [0.3, 0.05],
        {"min": 0.05},
        {"min": 0.05, "max": 0.3, "default": 9.9},
        {"min": 0.05, "max": 0.3, "nominal": 0.2},
    ],
)
def test_a_range_that_is_not_one_is_reported_and_dropped(config, caplog):
    from partcad.tool import ToolRange

    assert ToolRange.parse(config, "test", "layerHeight") is None
    assert "layerHeight" in caplog.text


def test_a_range_says_what_is_inside_it():
    from partcad.tool import ToolRange

    allowed = ToolRange.parse([0.05, 0.3], "test", "layerHeight")
    assert allowed.contains(0.05) and allowed.contains(0.3) and allowed.contains(0.2)
    assert not allowed.contains(0.04) and not allowed.contains(0.31)


def test_an_additive_tool_states_ranges_rather_than_values(project):
    """A machine prints layers from 0.08 to 0.32mm; a part picks one"""
    _, prj = project
    printer = prj.get_tool("extruder")
    assert printer.range_of("layerHeight").minimum == 0.08
    assert printer.range_of("layerHeight").default == 0.2
    assert printer.range_of("spotSize").maximum == 0.8
    assert printer.range_of("nonexistent") is None
    assert printer.materials == ["PLA", "PETG"]
    assert printer.step_size == [0.0125, 0.0125, 0.0025]


def test_an_additive_tool_carries_the_initial_positioning_sequence(project):
    """What the machine has to be told before it can put anything down"""
    _, prj = project
    positioning = prj.get_tool("extruder").positioning
    assert positioning["units"] == "mm"
    assert positioning["absolute"] is True
    assert positioning["home"] == ["z", "x", "y"]
    assert positioning["homeFeedRate"] == 3000.0
    assert positioning["safeZ"] == 5.0
    assert positioning["origin"] == [0.0, 0.0, 0.0]
    assert positioning["bedLeveling"] == "auto"
    assert positioning["prime"] == {"length": 100.0, "extrude": 8.0, "feedRate": 1200.0}


def test_a_positioning_field_partcad_cannot_read_is_dropped(caplog):
    """It is about to be handed to a machine, so carrying it would be worse"""
    project = _project(
        {
            "tools": {
                "additive": {
                    "printer": {
                        "visual": "plate",
                        "positioning": {"units": "furlongs", "home": ["w"], "warmUp": True},
                    }
                }
            }
        }
    )
    assert project.get_tool("printer").positioning == {}
    assert "positioning.units" in caplog.text
    assert "positioning.home" in caplog.text
    assert "unknown 'positioning' field" in caplog.text


def test_the_build_volume_says_what_does_not_fit(project):
    """And says it per axis, because that is what has to be changed"""
    _, prj = project
    printer = prj.get_tool("extruder")
    assert printer.fits([100.0, 100.0, 100.0]) is None
    assert printer.fits([100.0, 100.0, 250.0]) is None
    over = printer.fits([300.0, 100.0, 400.0])
    assert "X: 300.0mm > 220.0mm" in over and "Z: 400.0mm > 250.0mm" in over
    # Nothing to compare against is not a failure to fit.
    assert printer.fits(None) is None
