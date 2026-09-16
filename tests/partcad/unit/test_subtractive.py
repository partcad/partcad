#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part that is made by cutting material away, and what has to be true of it.

`subtractive` says two things beyond naming itself, and each is checked:

    manufacturing:
      method: subtractive
      source: stock_plate   # the piece it is cut out of
      laser:                # ...and the machine that cuts it
        kerf: 0.15

The stock, because cutting only ever removes material, so the part has to be
what is left of it -- which is also why naming it is required rather than
optional: subtraction is defined by what it starts from. And the machine,
because a laser's beam does not tilt and a drill only goes in and out, so each
can produce some of what a router can and no more.

The two geometric analyses are exercised against real OCCT geometry here,
because geometry is what they are about. The checks that drive them are
exercised with those analyses stubbed, because what a check does with the
answers is arithmetic and a sentence, and building a sandbox to find that out
would cost minutes per assertion.
"""

import asyncio
import os
import sys

import pytest
import yaml
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

import partcad as pc
from partcad.part_config import PartConfiguration
from partcad.part_config_manufacturing import (
    MACHINE_CNC,
    MACHINE_DRILLING,
    MACHINE_LASER,
    METHOD_SUBTRACTIVE,
    PartConfigManufacturing,
    tool_axis_vector,
)
from partcad.test import manufacturability_analysis
from partcad.test.manufacturability_drilling import ManufacturabilityDrillingTest
from partcad.test.manufacturability_laser import ManufacturabilityLaserTest
from partcad.test.manufacturability_subtractive import ManufacturabilitySubtractiveTest

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_manufacturability  # noqa: E402


def _manufacturing(**section):
    """A 'manufacturing:' section as the config layer reads it, defaulting to subtractive."""
    section.setdefault("method", "subtractive")
    return PartConfigManufacturing({"manufacturing": section})


#
# What the declaration says
#


def test_a_part_that_names_no_machine_is_a_cnc_part():
    """The answer that is never wrong, and what every such part used to mean.

    It matters that this is not None: a CNC router can make anything the other
    two can, so a part that never heard of machines is not unclassified, it is
    a router's.
    """
    machine = _manufacturing().machine
    assert machine is not None
    assert machine.kind == MACHINE_CNC
    # ...but it did not *say* so, which is what keeps the laser and drilling
    # checks off a package that has declared 'subtractive' for a year.
    assert machine.declared is False


def test_naming_a_machine_selects_it():
    assert _manufacturing(laser={"kerf": 0.2}).machine.kind == MACHINE_LASER
    assert _manufacturing(drilling={}).machine.kind == MACHINE_DRILLING
    assert _manufacturing(cnc={}).machine.kind == MACHINE_CNC
    # Named, so the machine-specific checks apply.
    assert _manufacturing(laser={}).machine.declared is True


def test_a_part_is_made_on_one_machine():
    data = _manufacturing(laser={}, drilling={})
    assert data.machine is None
    assert "one machine" in data.machine_error


def test_a_machine_takes_only_its_own_options():
    data = _manufacturing(laser={"kerff": 0.2})
    assert data.machine is None
    assert "kerff" in data.machine_error


def test_a_tool_axis_is_one_of_the_six_axes():
    assert tool_axis_vector("-Z") == (0.0, 0.0, -1.0)
    assert tool_axis_vector("+x") == (1.0, 0.0, 0.0)
    # An axis written without a sign is the positive one, as everywhere else.
    assert tool_axis_vector("Y") == (0.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        tool_axis_vector("sideways")


def test_a_misspelt_tool_axis_is_recorded_rather_than_defaulted():
    """The one input here whose wrong value produces a check that passes.

    Defaulting it would measure the walls against an axis nobody chose and
    report the answer as though it were about the part.
    """
    data = _manufacturing(laser={"toolAxis": "up-ish"})
    assert data.machine is None
    assert "is not an axis" in data.machine_error


def test_a_kerf_is_a_length_like_every_other():
    assert _manufacturing(laser={"kerf": "0.008 in"}).machine.get("kerf") == pytest.approx(0.2032)
    assert _manufacturing(laser={"kerf": 0.2}).machine.get("kerf") == pytest.approx(0.2)
    assert _manufacturing(laser={"kerf": "wide"}).machine is None


def test_the_machine_is_only_read_for_a_subtractive_part():
    """A machine is what takes material away, and nothing else here does."""
    assert PartConfigManufacturing({"manufacturing": {"method": "additive"}}).machine is None
    assert PartConfigManufacturing({"manufacturing": {"method": "sheet_metal"}}).machine is None


def test_what_the_machine_hands_an_implementation():
    data = _manufacturing(laser={"kerf": 0.15, "toolAxis": "+Z"}).machine.to_data()
    assert data["machine"] == "laser"
    assert data["tool_axis"] == "+Z"
    assert data["tool_axis_vector"] == [0.0, 0.0, 1.0]
    assert data["kerf"] == pytest.approx(0.15)


#
# The analyses, against real geometry
#


def _box(x, y, z, at=(0.0, 0.0, 0.0)):
    """A solid box, which is the stock every measurement here starts from."""
    return BRepPrimAPI_MakeBox(gp_Pnt(*at), x, y, z).Shape()


def _cut(minuend, subtrahend):
    """The boolean the checks themselves use: what is left of one solid after another."""
    operation = BRepAlgoAPI_Cut(minuend, subtrahend)
    operation.Build()
    return operation.Shape()


def _hole(x, y, radius, at_z=-1.0, height=20.0):
    """A cylinder along Z, tall enough to go through whatever it is cut from."""
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, y, at_z), gp_Dir(0, 0, 1)), radius, height).Shape()


def test_a_part_inside_its_stock_has_nothing_outside_it():
    stock = _box(100.0, 60.0, 10.0)
    part = _cut(stock, _hole(50.0, 30.0, 8.0))
    measured = wrapper_manufacturability.enclosure({"shape": part, "source": stock})
    assert measured["outside_volume"] == pytest.approx(0.0)
    # ...and the stock is bigger, by exactly the hole.
    assert measured["removed_volume"] > 0.0
    assert measured["part_volume"] + measured["removed_volume"] == pytest.approx(measured["source_volume"])


def test_a_part_that_pokes_out_of_its_stock_is_measured_by_how_much():
    """The number is the whole point: it says which mistake this is.

    A sliver is a part modelled to the stock's own outline; a large volume is
    the wrong stock entirely, and a check that said only "does not fit" would
    leave the reader to find out which.
    """
    stock = _box(100.0, 60.0, 10.0)
    part = _box(120.0, 60.0, 10.0)
    measured = wrapper_manufacturability.enclosure({"shape": part, "source": stock})
    assert measured["outside_volume"] == pytest.approx(20.0 * 60.0 * 10.0)


def test_a_stock_that_is_the_part_removes_nothing():
    """The mistake a reader of the YAML cannot see: 'source' naming the part."""
    stock = _box(100.0, 60.0, 10.0)
    measured = wrapper_manufacturability.enclosure({"shape": stock, "source": _box(100.0, 60.0, 10.0)})
    assert measured["outside_volume"] == pytest.approx(0.0)
    assert measured["removed_volume"] == pytest.approx(0.0)


def _classify(shape, tool_axis=(0.0, 0.0, -1.0), source=None):
    """Run the real face classifier, against real geometry, in this process.

    'source' selects the other subject: given one, the wrapper classifies what
    was removed rather than the part that was left.
    """
    request = {"shape": shape, "tool_axis_vector": list(tool_axis)}
    if source is not None:
        request["source"] = source
    return wrapper_manufacturability.wall_alignment(request)


def test_a_box_is_walls_and_caps_and_nothing_else():
    measured = _classify(_box(40.0, 30.0, 10.0))
    assert (measured["walls"], measured["caps"], measured["other"]) == (4, 2, 0)


def test_a_round_hole_is_a_wall_along_the_axis_and_a_defect_across_it():
    """Why the surface *type* is not the question.

    The same cylinder is a hole a drill made when it runs along the machine's
    axis and something no beam can cut when it lies across it. Only the normal
    tells them apart.
    """
    part = _cut(_box(100.0, 60.0, 10.0), _hole(50.0, 30.0, 8.0))
    along = _classify(part, (0.0, 0.0, -1.0))
    assert along["other"] == 0 and along["round"] == 1
    across = _classify(part, (1.0, 0.0, 0.0))
    assert across["other"] == 1


def test_a_taper_is_a_face_no_beam_can_make():
    cone = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 20.0, 10.0, 15.0).Shape()
    measured = _classify(cone)
    assert measured["other"] == 1
    assert measured["offenders"][0]["tilt"] > 1.0


def test_what_a_drill_cut_is_asked_of_the_material_it_removed():
    """A drilled plate's straight sides came with the stock.

    Asked of the part, the plate has four walls a drill did not make and would
    fail for them. Asked of what was taken away, it is exactly what it should
    be: two round holes.
    """
    stock = _box(100.0, 60.0, 10.0)
    part = _cut(_cut(stock, _hole(25.0, 30.0, 4.0)), _hole(75.0, 30.0, 4.0))

    as_part = _classify(part)
    assert as_part["round"] != as_part["walls"]

    as_removed = _classify(part, source=stock)
    assert as_removed["round"] == as_removed["walls"] == 2


#
# The checks, with the analyses stubbed
#


PACKAGE = {
    "name": "//test",
    "parts": {
        "stock": {"type": "stl"},
        "plain": {"type": "stl"},
        "sourceless": {"type": "stl", "manufacturing": {"method": "subtractive"}},
        "from_stock": {"type": "stl", "manufacturing": {"method": "subtractive", "source": "stock"}},
        "from_other_stock": {"type": "stl", "manufacturing": {"method": "subtractive", "source": "plain"}},
        "additive": {"type": "stl", "manufacturing": {"method": "additive"}},
        "formed": {"type": "stl", "manufacturing": {"method": "forming"}},
        "routed": {"type": "stl", "manufacturing": {"method": "subtractive", "source": "stock", "cnc": {}}},
        "burned": {
            "type": "stl",
            "manufacturing": {"method": "subtractive", "source": "stock", "laser": {"kerf": 0.2}},
        },
        "burned_upward": {
            "type": "stl",
            "manufacturing": {"method": "subtractive", "source": "stock", "laser": {"toolAxis": "+Z"}},
        },
        "drilled": {"type": "stl", "manufacturing": {"method": "subtractive", "source": "stock", "drilling": {}}},
        "drilled_from_other": {
            "type": "stl",
            "manufacturing": {"method": "subtractive", "source": "plain", "drilling": {}},
        },
        "confused": {
            "type": "stl",
            "manufacturing": {"method": "subtractive", "source": "stock", "laser": {}, "drilling": {}},
        },
    },
}


@pytest.fixture
def ctx(tmp_path):
    """The fixture package, with an empty file behind every part it declares.

    Empty because nothing here builds geometry from them: the checks are driven
    with the analyses stubbed, and what a part's file holds never comes up.
    """
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    for name in PACKAGE["parts"]:
        (tmp_path / (name + ".stl")).write_text("")
    return pc.Context(str(tmp_path))


def _arrange(monkeypatch, enclosure=None, cut=None, free_bounds=0):
    """Answer what the checks ask, without a sandbox and without geometry."""

    async def wrapped(self, ctx):
        """A shape envelope that is never decoded, because nothing here builds geometry."""
        return {"name": self.name, "label": self.name, "brep": b"CASCADE Topology V3"}

    async def fake_free_bounds(ctx, envelope):
        """How many open edges the solidity question found: 0 is a closed solid."""
        return free_bounds

    async def fake_enclosure(ctx, envelope, source_envelope):
        """What the stock-fit measurement came to, as the caller arranged it."""
        return enclosure or {"part_volume": 1000.0, "outside_volume": 0.0, "removed_volume": 100.0}

    async def fake_cut(ctx, envelope, tool_axis, source_envelope=None):
        """What the face classification came to, as the caller arranged it."""
        return cut or {"walls": 4, "caps": 2, "other": 0, "round": 4, "offenders": []}

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    monkeypatch.setattr(manufacturability_analysis, "free_bounds_count", fake_free_bounds)
    monkeypatch.setattr(manufacturability_analysis, "enclosure", fake_enclosure)
    monkeypatch.setattr(manufacturability_analysis, "wall_alignment", fake_cut)


def _verdict(check, ctx, name):
    """Drive one check over one part of the fixture package and return its verdict."""
    return asyncio.run(check.test([], ctx, ctx.get_part("//test:" + name)))


def test_the_subtractive_check_passes_over_a_part_made_some_other_way(ctx, monkeypatch):
    _arrange(monkeypatch, free_bounds=99)
    check = ManufacturabilitySubtractiveTest()
    assert _verdict(check, ctx, "additive") is check.TEST_PASSED


def test_a_subtractive_part_naming_no_stock_is_refused(ctx, monkeypatch, caplog):
    """Subtraction is defined by what it starts from.

    A shape somebody arrived at is not a subtractive part -- what makes it one
    is being what is left of a piece that existed first -- so a declaration
    naming no stock has not said what the method means.
    """
    _arrange(monkeypatch)
    check = ManufacturabilitySubtractiveTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "sourceless") is check.TEST_FAILED
    assert "states no 'source'" in caplog.text


def test_what_is_missing_is_read_rather_than_raised_on(ctx):
    """A part whose section is incomplete is still a part.

    Loading the package must not fail over it -- everything that is not about
    making the part goes on working -- so the omission is reported by the check,
    against the one part it belongs to.
    """
    part = ctx.get_part("//test:sourceless")
    assert part is not None
    assert PartConfiguration.get_manufacturing_data(part).missing_fields() == ["source"]


def test_a_part_outside_its_stock_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, enclosure={"part_volume": 1000.0, "outside_volume": 50.0, "removed_volume": 10.0})
    check = ManufacturabilitySubtractiveTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "from_stock") is check.TEST_FAILED
    assert "outside" in caplog.text


def test_a_part_that_fills_its_stock_exactly_fails(ctx, monkeypatch, caplog):
    """'source' naming the part itself: the mistake a reader cannot see."""
    _arrange(monkeypatch, enclosure={"part_volume": 1000.0, "outside_volume": 0.0, "removed_volume": 0.0})
    check = ManufacturabilitySubtractiveTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "from_stock") is check.TEST_FAILED
    assert "nothing is cut" in caplog.text


def test_a_sliver_outside_the_stock_is_within_tolerance(ctx, monkeypatch):
    """Two independently built solids meeting face to face.

    The boolean leaves something of the order of the modelling tolerance, while
    a part that genuinely does not fit misses by a whole feature.
    """
    _arrange(monkeypatch, enclosure={"part_volume": 1000.0, "outside_volume": 1e-9, "removed_volume": 10.0})
    check = ManufacturabilitySubtractiveTest()
    assert _verdict(check, ctx, "from_stock") is check.TEST_PASSED


def test_a_declaration_naming_two_machines_is_reported(ctx, monkeypatch, caplog):
    _arrange(monkeypatch)
    check = ManufacturabilitySubtractiveTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "confused") is check.TEST_FAILED
    assert "one machine" in caplog.text


def test_the_laser_check_only_applies_to_a_part_that_named_a_laser(ctx, monkeypatch):
    """A CNC part and one that named nothing are neither of them a laser's."""
    _arrange(monkeypatch, cut={"walls": 0, "caps": 0, "other": 99, "round": 0, "offenders": []})
    check = ManufacturabilityLaserTest()
    assert _verdict(check, ctx, "routed") is check.TEST_PASSED
    assert _verdict(check, ctx, "plain") is check.TEST_PASSED
    assert _verdict(check, ctx, "drilled") is check.TEST_PASSED


def test_a_laser_refuses_a_face_that_is_neither_along_the_beam_nor_across_it(ctx, monkeypatch, caplog):
    _arrange(
        monkeypatch,
        cut={"walls": 4, "caps": 2, "other": 1, "round": 0, "offenders": [{"surface": "Plane", "tilt": 45.0}]},
    )
    check = ManufacturabilityLaserTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "burned") is check.TEST_FAILED
    # The failure names the feature rather than only counting it.
    assert "Plane tilted 45.0" in caplog.text


def test_a_laser_takes_a_part_whose_every_wall_is_along_the_beam(ctx, monkeypatch):
    _arrange(monkeypatch, cut={"walls": 6, "caps": 2, "other": 0, "round": 2, "offenders": []})
    check = ManufacturabilityLaserTest()
    assert _verdict(check, ctx, "burned") is check.TEST_PASSED


def test_a_drill_refuses_a_wall_that_is_not_round(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, cut={"walls": 6, "caps": 2, "other": 0, "round": 2, "offenders": []})
    check = ManufacturabilityDrillingTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "drilled") is check.TEST_FAILED
    assert "round holes" in caplog.text


def test_a_drill_takes_a_part_whose_every_wall_is_round(ctx, monkeypatch):
    _arrange(monkeypatch, cut={"walls": 2, "caps": 4, "other": 0, "round": 2, "offenders": []})
    check = ManufacturabilityDrillingTest()
    assert _verdict(check, ctx, "drilled") is check.TEST_PASSED


def test_the_tool_axis_is_in_the_machine_checks_cache_key(ctx):
    """Turning the part over is the same solid and a different answer.

    The walls that were along the axis are across it, so a corrected axis
    has to re-run rather than be handed the verdict on the one it replaced --
    and 'manufacturing:' is one of the keys a shape's own hash leaves out.
    """
    check = ManufacturabilityLaserTest()
    down = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:burned")))
    up = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:burned_upward")))
    assert down and up and down != up
    # A part this check does not apply to contributes nothing.
    assert asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:routed"))) == ""


def test_the_drilling_cache_key_follows_the_stock_it_judges(ctx):
    """A check that measures what was *removed* has read the stock.

    'judges_removed' makes the measurement stock-minus-part, so the drilling
    verdict moves when the stock does -- and the part's own hash does not,
    because 'manufacturing:' is one of the keys it leaves out. Without the
    stock in the key a re-dimensioned blank leaves the old verdict standing.
    """
    check = ManufacturabilityDrillingTest()
    assert check.judges_removed is True
    one = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:drilled")))
    other = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:drilled_from_other")))
    assert one and other and one != other


def test_the_laser_cache_key_does_not_follow_a_stock_it_never_reads(ctx):
    """The other half of the same rule, which is why it is conditional.

    A laser is judged on the part it was handed, so the stock is not an input
    to its verdict -- and keying on it anyway would re-run every laser check in
    a package each time an unrelated blank was re-dimensioned.
    """
    check = ManufacturabilityLaserTest()
    assert check.judges_removed is False
    burned = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:burned")))
    assert burned == asyncio.run(
        check.cache_key_suffix(
            ctx,
            ctx.get_part("//test:burned"),
        )
    )
    # The machine and the axis are still what it keys on.
    assert burned and burned != asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:burned_upward")))


def test_the_subtractive_cache_key_follows_the_stock(ctx):
    """The stock's own hash is what says whether the verdict still holds."""
    check = ManufacturabilitySubtractiveTest()
    one = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:from_stock")))
    other = asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:from_other_stock")))
    assert one and other and one != other


def test_a_part_made_some_other_way_contributes_no_subtractive_key(ctx):
    check = ManufacturabilitySubtractiveTest()
    formed = ctx.get_part("//test:formed")
    assert asyncio.run(check.cache_key_suffix(ctx, formed)) == ""
    assert PartConfiguration.get_manufacturing_data(formed).method != METHOD_SUBTRACTIVE
