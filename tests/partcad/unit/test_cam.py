#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The 'cam:' section: the instructions that make a part, and pictures of them."""

import json
import os

import pytest

import partcad as pc
from partcad import output
from partcad.actions import cam as cam_action
from partcad.exception import NotManufacturableError

PACKAGE = "tests/partcad/unit/data/cam/partcad.yaml"


@pytest.fixture
def ctx():
    return pc.init(PACKAGE)


#
# The section itself
#


def test_cam_is_a_section_of_its_own():
    assert output.CAM in output.SECTIONS
    assert output.BUILTIN_PACKAGES[output.CAM] == "//builtin/cam"


def test_cam_falls_back_to_nothing_and_nothing_falls_back_to_it():
    """Instructions are neither a part nor a picture of one"""
    assert output.config_sections(output.CAM) == (output.CAM,)
    assert output.CAM not in output.config_sections(output.EXPORT)
    assert output.CAM not in output.config_sections(output.RENDER)


def test_partcad_ships_the_section_and_no_implementation(ctx):
    """Which machine, and what it wants said to it, lives outside PartCAD"""
    builtin = ctx.get_project("//builtin/cam")
    assert builtin is not None
    assert output.builtin_formats(ctx, output.CAM) == {}


def test_cam_is_not_produced_by_pc_render(ctx):
    """'pc render' writes every output file an object has; G-code is not one"""
    assert "gcode" not in output.all_formats(ctx)


#
# What an object declares
#


def test_the_declared_kinds_are_found(ctx):
    part = ctx.get_part(":block")
    assert cam_action.cam_formats(ctx, part) == ["gcode", "plain"]


def test_a_package_with_several_kinds_has_to_be_asked_which(ctx):
    part = ctx.get_part(":block")
    with pytest.raises(ValueError, match="more than one kind"):
        cam_action.resolve_format(ctx, part)
    assert cam_action.resolve_format(ctx, part, "plain") == "plain"


def test_a_kind_the_package_does_not_declare_is_refused(ctx):
    part = ctx.get_part(":block")
    with pytest.raises(ValueError, match="is not one of"):
        cam_action.resolve_format(ctx, part, "nonexistent")


def test_cam_info_reports_the_kind_that_can_draw_itself(ctx):
    """What an editor asks before offering a CAM view: configuration, no work"""
    info = cam_action.cam_info(ctx, ctx.get_part(":block"))
    assert info["formats"] == ["gcode", "plain"]
    assert info["format"] == "gcode"
    assert info["visual"] == "stl"


def test_cam_info_says_so_when_nothing_declares_a_cam_type():
    context = pc.init("tests/partcad/unit/data/connect_how/partcad.yaml")
    info = cam_action.cam_info(context, context.get_part(":plate"))
    assert info == {"formats": [], "visual": None, "format": None}


def test_the_implementation_knows_whether_it_draws(ctx):
    part = ctx.get_part(":block")
    drawing, _ = part.output_getopts(ctx, "gcode", ctx.get_project("//"))
    assert drawing.supports_visual
    assert drawing.visual_extension == "stl"
    assert drawing.entry == output.DEFAULT_ENTRY

    plain, _ = part.output_getopts(ctx, "plain", ctx.get_project("//"))
    assert not plain.supports_visual


def test_a_visual_implementation_writes_its_own_file_type(ctx):
    part = ctx.get_part(":block")
    _, instructions = part.output_getopts(ctx, "gcode", ctx.get_project("//"))
    impl, picture = part.output_getopts(ctx, "gcode", ctx.get_project("//"), visual=True)
    assert instructions.endswith(".gcode")
    assert picture.endswith(".stl")
    assert impl.entry == output.VISUAL_ENTRY


#
# Where the files go
#


def test_the_copy_lands_where_the_command_was_run(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    source = package / "block.gcode"
    source.write_text("; instructions\n")
    here = tmp_path / "here"
    here.mkdir()

    copy = cam_action._copy_out(str(source), str(here), None)
    assert copy == str(here / "block.gcode")
    assert open(copy).read() == "; instructions\n"


def test_the_copy_can_be_named(tmp_path):
    source = tmp_path / "block.gcode"
    source.write_text("x")
    here = tmp_path / "here"
    here.mkdir()

    assert cam_action._copy_out(str(source), str(here), "job1.gcode") == str(here / "job1.gcode")
    # A name with a directory in it means what it says, and the directory is made.
    nested = cam_action._copy_out(str(source), str(here), os.path.join("build", "job2.gcode"))
    assert nested == str(here / "build" / "job2.gcode")
    assert os.path.exists(nested)


def test_a_copy_onto_itself_is_not_one(tmp_path):
    """'pc cam' run in the package directory has nothing to copy to"""
    source = tmp_path / "block.gcode"
    source.write_text("x")
    assert cam_action._copy_out(str(source), str(tmp_path), None) == str(source)


#
# What it refuses
#


def test_an_assembly_has_no_instructions_of_its_own(ctx):
    """It is put together out of parts that each have their own"""
    import asyncio

    context = pc.init("tests/partcad/unit/data/connect_how/partcad.yaml")
    assembly = context._get_assembly(":connect_how")
    with pytest.raises(ValueError, match="not a part"):
        asyncio.run(cam_action.cam_async(context, assembly))


def test_a_part_that_is_not_made_is_refused(ctx):
    import asyncio

    with pytest.raises(NotManufacturableError, match="ignore-manufacturability"):
        asyncio.run(cam_action.cam_async(ctx, ctx.get_part(":bought"), format_name="gcode"))


def test_asking_a_plain_implementation_to_draw_is_refused(ctx):
    import asyncio

    with pytest.raises(ValueError, match="draws nothing"):
        asyncio.run(cam_action.cam_async(ctx, ctx.get_part(":block"), format_name="plain", visual=True))


#
# End to end, which builds the part and runs the implementation in a sandbox
#


@pytest.mark.slow
def test_the_instructions_are_written_once_and_copied(ctx, tmp_path):
    import asyncio

    part = ctx.get_part(":block")
    package_copy = os.path.join(ctx.get_project("//").config_dir, "block.gcode")
    try:
        copy = asyncio.run(
            cam_action.cam_async(ctx, part, format_name="gcode", output_dir=str(tmp_path), greeting="hello")
        )
        assert os.path.exists(package_copy), "the package keeps its own copy"
        assert copy == str(tmp_path / "block.gcode")

        # What the implementation was told: the part's own settings, and the
        # machine that makes it.
        described = json.loads(open(copy).read().splitlines()[1])
        assert described["shape_name"] == "block"
        assert described["manufacturing"]["tool"] == "//:printer"
        assert described["manufacturing"]["settings"]["layerHeight"] == 0.2
        assert described["manufacturing"]["settings"]["material"] == "PLA"
        assert described["tool"]["buildVolume"] == [200.0, 200.0, 200.0]
        assert described["tool"]["positioning"]["home"] == ["z", "x", "y"]
        assert described["tool"]["layerHeight"] == {"min": 0.1, "max": 0.3, "default": 0.2, "unit": "mm"}
        # And what the file type itself passed through.
        assert described["greeting"] == "hello"

        # A second run reuses what the package has rather than making it again.
        stamp = os.path.getmtime(package_copy)
        asyncio.run(cam_action.cam_async(ctx, part, format_name="gcode", output_dir=str(tmp_path)))
        assert os.path.getmtime(package_copy) == stamp
    finally:
        for path in (package_copy, os.path.join(ctx.get_project("//").config_dir, "block.stl")):
            if os.path.exists(path):
                os.remove(path)


@pytest.mark.slow
def test_the_second_entry_point_draws_the_instructions(ctx, tmp_path):
    """'--visual' reaches 'process_visual', and its file is the visual type"""
    import asyncio

    part = ctx.get_part(":block")
    package_copy = os.path.join(ctx.get_project("//").config_dir, "block.stl")
    try:
        copy = asyncio.run(cam_action.cam_async(ctx, part, format_name="gcode", visual=True, output_dir=str(tmp_path)))
        assert copy == str(tmp_path / "block.stl")
        assert open(copy).read().startswith("solid visual")
    finally:
        if os.path.exists(package_copy):
            os.remove(package_copy)
