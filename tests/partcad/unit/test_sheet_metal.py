#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part that is made by bending a flat piece, and what has to be true of it.

'sheet_metal' is not described the way the other manufacturing methods are. It
is not a part made from stock: it is a *flat piece* - made by somebody else, and
already carrying the outline and the holes - put through a brake. So the
declaration names two things rather than describing one:

    manufacturing:
      method: sheet_metal
      source: blank                         # the part that is bent
      instructions: bends;include=BEND_UP   # the sketch that says where

and 'pc test' asks one question of each of them: the blank has to be flat on top
and bottom, and every bend line has to say what kind of bend it is.

The flatness analysis is exercised against real OCCT geometry here, because it
is geometry that it is about; the check that drives it is exercised with that
analysis and the sketch's annotations stubbed, because what it does with the
answers is not.
"""

import asyncio
import os
import sys

import pytest
import yaml
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeSphere

import partcad as pc
from partcad.part_config import PartConfiguration
from partcad.part_config_manufacturing import (
    METHOD_SHEET_METAL,
    METHOD_SUBTRACTIVE,
    PartConfigManufacturing,
)
from partcad.test import manufacturability_analysis
from partcad.test.manufacturability_sheet_metal import ManufacturabilitySheetMetalTest, bend_failure

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_manufacturability  # noqa: E402

GOOD_BEND = {"type": "LINE", "layer": "BEND_UP", "handle": "2F", "metadata": {}}


def _bend(**metadata):
    annotation = dict(GOOD_BEND)
    annotation["metadata"] = {"angle": 90.0, "radius": 1.5, "direction": "up"}
    annotation["metadata"].update(metadata)
    return annotation


#
# What the declaration says
#


def _manufacturing(**section):
    return PartConfigManufacturing({"manufacturing": section})


def test_the_method_is_read_with_what_it_is_made_from():
    data = _manufacturing(method="sheet_metal", source="blank", instructions="bends;include=BEND_UP")
    assert data.method == METHOD_SHEET_METAL
    assert data.source == "blank"
    assert data.instructions == "bends;include=BEND_UP"
    assert data.missing_fields() == []
    assert "sheet_metal" in str(data)


def test_both_halves_are_required():
    """Neither answers the other: one is what is bent, the other is how."""
    assert _manufacturing(method="sheet_metal").missing_fields() == ["source", "instructions"]
    assert _manufacturing(method="sheet_metal", source="blank").missing_fields() == ["instructions"]
    assert _manufacturing(method="sheet_metal", instructions="bends").missing_fields() == ["source"]


def test_another_method_needs_neither():
    """A part made from stock has nothing to point at, and is not asked to."""
    data = _manufacturing(method="subtractive")
    assert data.method == METHOD_SUBTRACTIVE
    assert data.missing_fields() == []


def test_an_unknown_method_is_still_an_unknown_method(caplog):
    with caplog.at_level("ERROR"):
        assert _manufacturing(method="sheet-metal").method is None
    assert "sheet_metal" in caplog.text  # it is listed among the supported ones


#
# What a bend line has to say
#


def test_a_bend_that_says_everything_is_a_bend_that_can_be_made():
    assert bend_failure(_bend()) is None
    # However the drawing spells the direction, and however it states a number.
    assert bend_failure(_bend(direction="DOWN")) is None
    assert bend_failure(_bend(angle="90", radius="1.5")) is None


def test_a_line_with_no_metadata_at_all_is_reported_as_such():
    """Which is what every sketch type but 'dxf' produces today."""
    assert bend_failure(GOOD_BEND) == "it carries no metadata"


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"angle": 0.0}, "not a bend"),
        ({"angle": -90.0}, "not a bend"),
        ({"angle": 720.0}, "whole turn"),
        ({"angle": "ninety"}, "non-numeric 'angle'"),
        ({"radius": 0.0}, "fold rather than a bend"),
        ({"radius": -1.0}, "fold rather than a bend"),
        ({"direction": "sideways"}, "neither 'up' nor 'down'"),
        ({"direction": 1.0}, "neither 'up' nor 'down'"),
    ],
)
def test_a_value_that_is_not_one_is_refused(metadata, expected):
    failure = bend_failure(_bend(**metadata))
    assert failure and expected in failure


def test_a_key_that_is_absent_is_reported_as_absent():
    """Said differently from a key that is there and wrong, because it is."""
    annotation = _bend()
    del annotation["metadata"]["radius"]
    del annotation["metadata"]["direction"]
    failure = bend_failure(annotation)
    assert "no 'radius'" in failure
    assert "no 'direction'" in failure


def test_every_fault_in_one_line_is_reported_at_once():
    """A drawing that got two of the three wrong should learn both in one run."""
    failure = bend_failure(_bend(angle=-1.0, radius=0.0))
    assert "'angle'" in failure and "'radius'" in failure


def test_true_is_not_a_number():
    """YAML and XDATA can both produce it, and it reads as one millimetre."""
    assert "non-numeric 'radius'" in bend_failure(_bend(radius=True))


#
# Whether the blank is flat
#


def _flatness(shape):
    return wrapper_manufacturability.flatness({"shape": shape})


def test_a_plate_is_flat_on_both_sides():
    """The shape a brake takes: sheet, so both extremes are faces."""
    measured = _flatness(BRepPrimAPI_MakeBox(40.0, 20.0, 2.0).Shape())
    assert measured["z_min"] == pytest.approx(0.0)
    assert measured["z_max"] == pytest.approx(2.0)
    assert measured["area_min"] == pytest.approx(800.0)
    assert measured["area_max"] == pytest.approx(800.0)


def test_a_sphere_is_flat_on_neither():
    """It meets each of the two planes at a point, which has no area."""
    measured = _flatness(BRepPrimAPI_MakeSphere(5.0).Shape())
    assert measured["area_min"] == 0.0
    assert measured["area_max"] == 0.0


def test_a_cone_is_flat_on_one_side_only():
    """The half-answer, which is the one a plain bounding box cannot give."""
    measured = _flatness(BRepPrimAPI_MakeCone(5.0, 0.0, 4.0).Shape())
    assert measured["area_min"] > 0.0
    assert measured["area_max"] == 0.0


def test_the_analysis_is_asked_for_by_name():
    """'wrapper_manufacturability' answers more than one question; each says which it is."""
    assert set(wrapper_manufacturability.OPERATIONS) == {"free_bounds", "flatness"}
    assert wrapper_manufacturability.OPERATIONS["free_bounds"](
        {"shape": BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()}
    ) == {"free_bounds": 0}


#
# The check itself
#

PACKAGE = {
    "name": "//test",
    "manufacturable": True,
    "parts": {
        "blank": {
            "type": "stl",
            "desc": "The flat piece that is bent, cut to shape by somebody else",
            "manufacturing": {"method": "subtractive"},
            "parameters": {"tolerance": 0.1},
        },
        "bracket": {
            "type": "stl",
            "manufacturing": {
                "method": "sheet_metal",
                "source": "blank",
                "instructions": "bends;include=BEND_UP",
            },
            "parameters": {"tolerance": 0.1},
        },
        "incomplete": {
            "type": "stl",
            "manufacturing": {"method": "sheet_metal", "source": "blank"},
            "parameters": {"tolerance": 0.1},
        },
        "nowhere": {
            "type": "stl",
            "manufacturing": {
                "method": "sheet_metal",
                "source": "missing",
                "instructions": "bends",
            },
            "parameters": {"tolerance": 0.1},
        },
        "elsewhere": {
            "type": "stl",
            "manufacturing": {
                "method": "sheet_metal",
                "source": "blank",
                # Parameterized, and pointing at nothing: the resolver reaches
                # this through its "base object" branch rather than its plain
                # lookup, and those were two different answers to 'quiet'.
                "instructions": "gone;include=BEND_UP",
            },
            "parameters": {"tolerance": 0.1},
        },
        "faraway": {
            "type": "stl",
            "manufacturing": {
                "method": "sheet_metal",
                # A package this context has never heard of, as opposed to an
                # object this package does not declare: a different branch of
                # the resolver, and a different thing to tell the user.
                "source": "//nosuch:blank",
                "instructions": "bends",
            },
            "parameters": {"tolerance": 0.1},
        },
        "machined": {
            "type": "stl",
            "manufacturing": {"method": "subtractive"},
            "parameters": {"tolerance": 0.1},
        },
    },
    "sketches": {"bends": {"type": "dxf"}},
    # An assembly, because 'pc test' runs over those too and they carry a
    # 'manufacturing:' of their own in the same spelling: AssemblyConfiguration
    # gives every 'type: assy' assembly 'method: assy'.
    "assemblies": {"rig": {"type": "assy"}},
}


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    for name in PACKAGE["parts"]:
        (tmp_path / (name + ".stl")).write_text("")
    (tmp_path / "bends.dxf").write_text("")
    (tmp_path / "rig.assy").write_text("links:\n  - part: blank\n")
    return pc.Context(str(tmp_path))


def _arrange(monkeypatch, area_min=800.0, area_max=800.0, annotations=None):
    """Answer the two questions the check asks, without a sandbox or a drawing."""

    async def wrapped(self, ctx):
        return {"name": self.name, "label": self.name, "brep": b"CASCADE Topology V3"}

    async def flatness(ctx, envelope):
        return {"z_min": 0.0, "z_max": 2.0, "area_min": area_min, "area_max": area_max}

    async def get_annotations(self, ctx):
        return [_bend()] if annotations is None else annotations

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    monkeypatch.setattr(manufacturability_analysis, "flatness", flatness)
    monkeypatch.setattr(pc.sketch.Sketch, "get_annotations", get_annotations)


def _verdict(ctx, part_name):
    return asyncio.run(ManufacturabilitySheetMetalTest().test([], ctx, ctx.get_part("//test:" + part_name)))


def test_a_sheet_metal_part_with_a_flat_blank_and_stated_bends_passes(ctx, monkeypatch):
    _arrange(monkeypatch)
    assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_PASSED


def test_a_part_made_some_other_way_is_not_asked(ctx, monkeypatch):
    """The check applies to one method, like its three siblings."""
    _arrange(monkeypatch, area_min=0.0, area_max=0.0, annotations=[])
    assert _verdict(ctx, "machined") is ManufacturabilitySheetMetalTest.TEST_PASSED


def test_a_blank_that_is_not_flat_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, area_max=0.0)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "not flat on the top" in caplog.text


def test_a_blank_that_is_flat_on_neither_side_says_so(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, area_min=0.0, area_max=0.0)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "not flat on the bottom or the top" in caplog.text


def test_a_bend_that_says_nothing_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, annotations=[GOOD_BEND])
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "carries no metadata" in caplog.text
    assert "BEND_UP" in caplog.text


def test_instructions_that_draw_no_bend_lines_fail(ctx, monkeypatch, caplog):
    """A sketch type that states nothing about its elements leaves nothing to bend along."""
    _arrange(monkeypatch, annotations=[{"type": "CIRCLE", "layer": "HOLES", "metadata": {}}])
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "no bend lines" in caplog.text


def test_a_declaration_that_states_only_half_of_it_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "incomplete") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "states no 'instructions'" in caplog.text


def test_a_reference_that_resolves_to_nothing_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "nowhere") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "source part 'missing' is not found" in caplog.text


def test_a_missing_reference_is_reported_by_the_check_and_not_by_the_resolver(ctx, monkeypatch, caplog):
    """Once, and in the words of the thing that asked.

    The check resolves its references twice - once to key the verdict, once to
    reach the annotations - so a resolver that reported a miss of its own would
    say it twice over, ahead of the one message that names the part and what is
    wrong with its declaration. Worse, it was the resolver's wording that 'pc'
    then gave as its reason for exiting.

    The parameterized spelling is the one under test because it is the one the
    filters produce, and because 'quiet' used to stop at the plain lookup: the
    branch that resolves a base name logged regardless, so 'gone' was silent
    and 'gone;include=BEND_UP' was not.
    """
    _arrange(monkeypatch)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "elsewhere") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "instructions sketch 'gone;include=BEND_UP' is not found" in caplog.text
    assert "Base object" not in caplog.text
    assert "not found in" not in caplog.text


def test_a_blank_whose_shape_cannot_be_had_fails(ctx, monkeypatch, caplog):
    """Not the same as a blank that is not flat, and not to be reported as one.

    A part that is declared but whose geometry cannot be produced answers with
    nothing, and "is it flat?" has no answer at all then - measuring the
    envelope that is not there would be the check deciding for itself.
    """
    _arrange(monkeypatch)

    async def nothing(self, ctx):
        return None

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", nothing)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "Failed to get the shape of the sheet metal source part 'blank'" in caplog.text


def test_a_reference_into_a_package_that_is_not_there_fails(ctx, monkeypatch, caplog):
    """A package nobody imported, rather than an object nobody declared."""
    _arrange(monkeypatch)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "faraway") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "source part '//nosuch:blank' is not found" in caplog.text


def test_an_angle_that_is_not_a_finite_number_is_refused():
    """'nan' and 'inf' parse as floats and are not angles anything was bent to."""
    for value in (float("nan"), float("inf"), float("-inf"), "nan", "inf"):
        failure = bend_failure(_bend(angle=value))
        assert failure and "non-numeric 'angle'" in failure


def test_a_reference_that_cannot_be_keyed_still_produces_a_key(ctx, monkeypatch):
    """The key is the point, not the keying.

    An object that refuses to say what its cache key is - because the files it
    is built from are not there, say - must not take the verdict's key with it:
    the test is about to fail that part anyway, and a key that raised would
    fail the run instead of the part.
    """
    _arrange(monkeypatch)

    async def refuse(self):
        raise RuntimeError("no key for you")

    monkeypatch.setattr(pc.shape.Shape, "get_cache_key_async", refuse)
    part = ctx.get_part("//test:bracket")
    suffix = asyncio.run(ManufacturabilitySheetMetalTest().cache_key_suffix(ctx, part))
    assert suffix.startswith(".sheet-metal=")


def test_a_declaration_missing_a_reference_still_keys(ctx, monkeypatch):
    """There is nothing to resolve, and a key is still owed.

    The part fails the check either way, but it has to fail it *every* run: a
    suffix that came out empty here would be the same suffix a complete
    declaration gets, so filling the missing reference in would be answered
    from the cache with the verdict of the declaration that lacked it.
    """
    _arrange(monkeypatch)
    incomplete = asyncio.run(ManufacturabilitySheetMetalTest().cache_key_suffix(ctx, ctx.get_part("//test:incomplete")))
    complete = asyncio.run(ManufacturabilitySheetMetalTest().cache_key_suffix(ctx, ctx.get_part("//test:bracket")))
    assert incomplete.startswith(".sheet-metal=")
    assert incomplete != complete


def test_the_check_itself_passes_over_an_assembly(ctx):
    """The other half of the question the key already asks.

    'pc test' offers every shape to every check, and this one is about a part:
    an assembly is not made by bending a blank, so it is not this check's to
    fail.
    """
    assert (
        asyncio.run(ManufacturabilitySheetMetalTest().test([], ctx, ctx.get_assembly("//test:rig")))
        is ManufacturabilitySheetMetalTest.TEST_PASSED
    )


def test_the_blank_is_resolved_with_the_accessor_a_coroutine_may_use(ctx, monkeypatch):
    """A blank an assembly produces, rather than one the package declares.

    'Project.get_part()' says it in as many words: a coroutine must use
    'get_part_async()'. Materializing a *derived* part - a STEP component or a
    URDF link, which the assembly's own source file declares rather than
    'partcad.yaml' - instantiates that assembly, and the synchronous accessor
    drives that with 'asyncio.run()', which raises on a thread that already has
    a loop. Every caller of '_resolve' here is a coroutine, so a sheet metal
    part whose blank was derived would have failed with a RuntimeError about
    the event loop rather than being measured.

    The synchronous accessor is made to raise the way it would for a derived
    part, so that reaching for it at all is what the test catches.
    """
    _arrange(monkeypatch)
    # Resolved before the accessor is made to refuse: it is the check's own
    # lookup of the blank that is under test, not this one.
    part = ctx.get_part("//test:bracket")

    def refuse(self, part_name, func_params=None, quiet=False):
        raise RuntimeError("asyncio.run() cannot be called from a running event loop")

    monkeypatch.setattr(pc.project.Project, "get_part", refuse)
    assert (
        asyncio.run(ManufacturabilitySheetMetalTest().test([], ctx, part))
        is ManufacturabilitySheetMetalTest.TEST_PASSED
    )


def test_an_assembly_is_not_read_as_though_it_were_a_part(ctx, caplog):
    """'manufacturing:' means something else on an assembly, and this may not read it.

    'pc test' runs every check over assemblies as well as parts, and an
    assembly's method vocabulary is its own: AssemblyConfiguration gives every
    'type: assy' assembly 'method: assy', which is not a way of making a *part*
    and is not in the part method map. Reading it with
    'PartConfiguration.get_manufacturing_data' therefore reports an unknown
    method - and reports it as an error, so it does not merely read oddly. It
    fails 'pc test' outright for every package that contains an assembly, which
    is most of them.

    'test()' has always asked this question first. The key had to ask it too.
    """
    assembly = ctx.get_assembly("//test:rig")
    with caplog.at_level("ERROR"):
        assert asyncio.run(ManufacturabilitySheetMetalTest().cache_key_suffix(ctx, assembly)) == ""
    assert "Unknown manufacturing method" not in caplog.text


def test_both_questions_are_asked_even_when_the_first_one_fails(ctx, monkeypatch, caplog):
    """A package that got both wrong should learn both in one run."""
    _arrange(monkeypatch, area_max=0.0, annotations=[GOOD_BEND])
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "bracket") is ManufacturabilitySheetMetalTest.TEST_FAILED
    assert "not flat" in caplog.text
    assert "carries no metadata" in caplog.text


#
# What the verdict is remembered against
#


def test_the_cached_verdict_follows_what_the_check_actually_read(ctx, monkeypatch):
    """'manufacturing:' is not in the part's hash, and neither is the drawing.

    A shape's key covers what the shape is built from, and naming a blank does
    not change the geometry of the part that names it. So without a suffix of
    its own, re-pointing the part - or editing the drawing it points at - would
    be answered with the verdict of the declaration that was replaced.
    """
    _arrange(monkeypatch)
    test = ManufacturabilitySheetMetalTest()
    bracket = ctx.get_part("//test:bracket")

    before = asyncio.run(test.cache_key_suffix(ctx, bracket))
    assert before

    bracket.config["manufacturing"]["source"] = "machined"
    assert asyncio.run(test.cache_key_suffix(ctx, bracket)) != before


def test_the_key_of_a_part_made_some_other_way_does_not_move(ctx, monkeypatch):
    """It reads nothing, so it adds nothing, and its cached verdicts stay valid."""
    _arrange(monkeypatch)
    machined = ctx.get_part("//test:machined")
    assert asyncio.run(ManufacturabilitySheetMetalTest().cache_key_suffix(ctx, machined)) == ""


def test_the_key_follows_the_drawing_the_instructions_are_read_from(ctx, monkeypatch, tmp_path):
    """Editing the bend angles has to re-run the check, not re-read its answer."""
    _arrange(monkeypatch)
    test = ManufacturabilitySheetMetalTest()
    bracket = ctx.get_part("//test:bracket")
    before = asyncio.run(test.cache_key_suffix(ctx, bracket))

    (tmp_path / "bends.dxf").write_text("edited")
    reloaded = pc.Context(str(tmp_path))
    after = asyncio.run(test.cache_key_suffix(reloaded, reloaded.get_part("//test:bracket")))

    assert before != after


def test_a_sheet_metal_part_is_manufacturable(ctx):
    """The method counts as a way of making the part, like every other one.

    Without this the CAM check would report a part that can be neither bought
    nor made, which is a different complaint entirely.
    """
    data = PartConfiguration.get_manufacturing_data(ctx.get_part("//test:bracket"))
    assert data.method == METHOD_SHEET_METAL
