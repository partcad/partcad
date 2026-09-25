#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part a saw cuts out of its stock, and what has to be true of it.

`cut:` is the subtractive machine that cuts stock across and does nothing else,
so it is described by where it cuts:

    manufacturing:
      method: subtractive
      source: board_8ft          # the stock, in the part's own coordinates
      cut:
        cuts:
          - along: +Y            # the dimension to cut...
            length: $length in   # ...and how long a piece; '$length' is the part's own parameter
          - plane: [[0, 0, 20], [0, 0, 1]]   # or a plane: a point, and a normal facing the offcut

The measurement is exercised against real OCCT geometry here and the check with
it stubbed, the way `test_subtractive.py` splits the other machines.
"""

import asyncio
import os
import sys

import pytest
import yaml
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

import partcad as pc
from partcad import cam as pc_cam
from partcad.part_config_manufacturing import (
    MACHINE_CUT,
    ROUTED_MACHINES,
    PartConfigManufacturing,
    parse_cuts,
)
from partcad.test import manufacturability_analysis
from partcad.test.manufacturability_cut import ManufacturabilityCutTest
from partcad.test.manufacturability_laser import ManufacturabilityLaserTest

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_manufacturability  # noqa: E402

INCH = 25.4


def _manufacturing(parameters=None, **section):
    section.setdefault("method", "subtractive")
    section.setdefault("source", "stock")
    return PartConfigManufacturing({"manufacturing": section, "parameters": parameters or {}})


#
# What the declaration says
#


def test_a_cut_along_a_dimension_is_a_normal_and_a_length():
    assert parse_cuts([{"along": "+Y", "length": "48 in"}]) == [{"normal": [0.0, 1.0, 0.0], "length": 48 * INCH}]


def test_a_cut_may_be_a_plane_in_either_spelling():
    as_list = parse_cuts([{"plane": [[0, 0, "10 mm"], [0, 0, 2]]}])
    as_map = parse_cuts([{"plane": {"origin": [0, 0, 10], "normal": "+Z"}}])
    assert as_list == as_map == [{"origin": [0.0, 0.0, 10.0], "normal": [0.0, 0.0, 1.0]}]


def test_a_plane_may_lie_behind_the_origin():
    """A coordinate is not a tool size: zero and negative are ordinary places to cut."""
    assert parse_cuts([{"plane": [[0, -5, 0], [0, -1, 0]]}])[0]["origin"] == [0.0, -5.0, 0.0]


def test_a_cut_follows_the_part_s_own_parameters():
    """A leg is as long as the desk is high, so its cut is too."""
    data = _manufacturing(
        parameters={"length": {"type": "float", "default": 30}},
        cut={"cuts": [{"along": [0, 1, 0], "length": "$length in"}, {"plane": [[0, "${length}", 0], "+Y"]}]},
    )
    assert data.machine_error is None
    machine = data.machine
    assert machine.kind == MACHINE_CUT and machine.declared
    assert machine.cuts[0]["length"] == pytest.approx(30 * INCH)
    assert machine.cuts[1]["origin"] == [0.0, 30.0, 0.0]


@pytest.mark.parametrize(
    "section, says",
    [
        ({}, "names no 'cuts:'"),
        ({"cuts": [{"along": "+Y"}]}, "either 'plane:', or 'along:' and 'length:'"),
        ({"cuts": [{"along": "+Y", "length": "$height"}]}, "the parameter 'height'"),
        ({"cuts": [{"plane": [[0, 0, 0], [0, 0, 0]]}]}, "zero vector"),
        ({"cuts": [{"plane": [[0, 0, 0], [0, 0, 1]], "length": 3}]}, "takes nothing else"),
        ({"cuts": [{"along": "+W", "length": 3}]}, "is not an axis"),
        ({"cuts": [{"along": "+Y", "length": 0}]}, "not a positive length"),
        # A saw has no axis of its own, and nothing is routed for it.
        ({"toolAxis": "-Z", "cuts": [{"along": "+Y", "length": 3}]}, "does not take toolAxis"),
        ({"feed": 100, "cuts": [{"along": "+Y", "length": 3}]}, "does not take feed"),
    ],
)
def test_a_cut_that_cannot_be_read_is_recorded_rather_than_raised(section, says):
    data = _manufacturing(parameters={"length": 5}, cut=section)
    assert says in data.machine_error
    assert data.machines == {}


def test_a_drawing_is_not_cut_to_length():
    """A sketch declares machines with no method, and a saw is not one of them."""
    data = PartConfigManufacturing({"manufacturing": {"cut": {"cuts": [{"along": "+Y", "length": 3}]}}})
    assert "a drawing is not one" in data.machine_error


def test_a_saw_is_not_a_machine_a_route_is_written_for():
    assert MACHINE_CUT not in ROUTED_MACHINES


def test_the_cut_is_the_cache_key_of_the_claim():
    """Moving a cut by an inch changes nothing the part's own hash covers."""
    one = _manufacturing(cut={"cuts": [{"along": "+Y", "length": "24 in"}]}).machine.key()
    other = _manufacturing(cut={"cuts": [{"along": "+Y", "length": "25 in"}]}).machine.key()
    assert one != other


#
# The measurement, against real geometry
#


def _box(x, y, z, at=(0.0, 0.0, 0.0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*at), x, y, z).Shape()


def _measure(part, stock, cuts):
    return wrapper_manufacturability.cut({"shape": part, "source": stock, "cuts": cuts})


def test_a_board_cut_to_length_is_what_the_cut_leaves():
    board = _box(89.0, 2438.4, 38.0)
    stud = _box(89.0, 1219.2, 38.0)
    measured = _measure(stud, board, parse_cuts([{"along": "+Y", "length": "48 in"}]))
    assert measured["extra_volume"] == pytest.approx(0.0, abs=1e-3)
    assert measured["missing_volume"] == pytest.approx(0.0, abs=1e-3)
    assert measured["removed"][0] == pytest.approx(89.0 * 1219.2 * 38.0, rel=1e-6)
    assert measured["planes"][0]["origin"][1] == pytest.approx(1219.2)


def test_a_length_is_measured_from_where_the_stock_starts():
    """Not from the origin: a board lying at y=100 is cut 100 further along."""
    board = _box(10.0, 1000.0, 10.0, at=(0.0, 100.0, 0.0))
    piece = _box(10.0, 300.0, 10.0, at=(0.0, 100.0, 0.0))
    measured = _measure(piece, board, parse_cuts([{"along": "+Y", "length": 300}]))
    assert measured["planes"][0]["origin"][1] == pytest.approx(400.0)
    assert measured["extra_volume"] + measured["missing_volume"] == pytest.approx(0.0, abs=1e-3)


def test_cutting_the_other_end_counts_from_the_other_end():
    board = _box(10.0, 1000.0, 10.0)
    piece = _box(10.0, 300.0, 10.0, at=(0.0, 700.0, 0.0))
    measured = _measure(piece, board, parse_cuts([{"along": "-Y", "length": 300}]))
    assert measured["extra_volume"] + measured["missing_volume"] == pytest.approx(0.0, abs=1e-3)


def test_a_sheet_cut_to_size_takes_two_cuts():
    sheet = _box(1219.2, 2438.4, 18.0)
    top = _box(914.4, 1828.8, 18.0)
    cuts = parse_cuts(
        [
            {"along": "+X", "length": "36 in"},
            {"plane": [[0, "72 in", 0], [0, 1, 0]]},
        ]
    )
    measured = _measure(top, sheet, cuts)
    assert all(removed > 0 for removed in measured["removed"])
    assert measured["extra_volume"] + measured["missing_volume"] == pytest.approx(0.0, abs=1e-2)


def test_a_feature_no_saw_makes_is_what_the_part_is_missing():
    """A hole in the piece is material the cut stock still has."""
    board = _box(89.0, 1000.0, 38.0)
    piece = _box(89.0, 500.0, 38.0)
    hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(44.5, 250.0, -1.0), gp_Dir(0, 0, 1)), 5.0, 40.0).Shape()
    operation = BRepAlgoAPI_Cut(piece, hole)
    operation.Build()
    measured = _measure(operation.Shape(), board, parse_cuts([{"along": "+Y", "length": 500}]))
    assert measured["missing_volume"] > 1000.0
    assert measured["extra_volume"] == pytest.approx(0.0, abs=1e-3)


def test_a_cut_past_the_end_of_the_board_takes_nothing():
    board = _box(10.0, 100.0, 10.0)
    measured = _measure(board, board, parse_cuts([{"along": "+Y", "length": 150}]))
    assert measured["removed"] == [pytest.approx(0.0)]


#
# The check, with the measurement stubbed
#


PACKAGE = {
    "name": "//test",
    "parts": {
        "board": {"type": "stl"},
        "sawn": {
            "type": "stl",
            "manufacturing": {
                "method": "subtractive",
                "source": "board",
                "cut": {"cuts": [{"along": "+Y", "length": 300}]},
            },
        },
        "sawn_or_burned": {
            "type": "stl",
            "manufacturing": {
                "method": "subtractive",
                "source": "board",
                "cut": {"cuts": [{"along": "+Y", "length": 300}]},
                "laser": {},
            },
        },
        "burned": {"type": "stl", "manufacturing": {"method": "subtractive", "source": "board", "laser": {}}},
    },
}


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    for name in PACKAGE["parts"]:
        (tmp_path / (name + ".stl")).write_text("")
    return pc.Context(str(tmp_path))


def _arrange(monkeypatch, measured):
    async def wrapped(self, ctx):
        return {"name": self.name, "label": self.name, "brep": b"CASCADE Topology V3"}

    async def fake_cut(ctx, envelope, source_envelope, cuts):
        return measured

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    monkeypatch.setattr(manufacturability_analysis, "cut", fake_cut)


PLANE = {"origin": [0.0, 300.0, 0.0], "normal": [0.0, 1.0, 0.0]}


def _verdict(check, ctx, name):
    return asyncio.run(check.test([], ctx, ctx.get_part("//test:" + name)))


def test_a_part_that_is_what_the_cut_leaves_passes(ctx, monkeypatch):
    _arrange(
        monkeypatch,
        {"part_volume": 3000.0, "extra_volume": 0.0, "missing_volume": 1e-9, "removed": [7000.0], "planes": [PLANE]},
    )
    check = ManufacturabilityCutTest()
    assert _verdict(check, ctx, "sawn") is check.TEST_PASSED


def test_a_part_a_saw_did_not_make_fails_and_says_where_it_cut(ctx, monkeypatch, caplog):
    _arrange(
        monkeypatch,
        {"part_volume": 3000.0, "extra_volume": 0.0, "missing_volume": 250.0, "removed": [7000.0], "planes": [PLANE]},
    )
    check = ManufacturabilityCutTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "sawn") is check.TEST_FAILED
    assert "the plane through [0, 300, 0] facing [0, 1, 0]" in caplog.text
    assert "250.000 mm3 of what the cuts leave is not in the part" in caplog.text


def test_a_cut_that_takes_nothing_off_fails(ctx, monkeypatch, caplog):
    _arrange(
        monkeypatch,
        {"part_volume": 3000.0, "extra_volume": 0.0, "missing_volume": 0.0, "removed": [0.0], "planes": [PLANE]},
    )
    check = ManufacturabilityCutTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "sawn") is check.TEST_FAILED
    assert "Cut #1" in caplog.text and "takes nothing off" in caplog.text


def test_a_cut_that_removes_only_a_rounding_error_takes_nothing_off(ctx, monkeypatch, caplog):
    """A plane that misses the stock leaves a floating-point sliver, not an exact zero."""
    _arrange(
        monkeypatch,
        {"part_volume": 3000.0, "extra_volume": 0.0, "missing_volume": 0.0, "removed": [1e-9], "planes": [PLANE]},
    )
    check = ManufacturabilityCutTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "sawn") is check.TEST_FAILED
    assert "takes nothing off" in caplog.text


def test_the_cut_check_only_applies_to_a_part_that_named_a_saw(ctx, monkeypatch):
    _arrange(monkeypatch, {"part_volume": 1.0, "extra_volume": 99.0, "removed": [0.0], "planes": [PLANE]})
    check = ManufacturabilityCutTest()
    assert _verdict(check, ctx, "burned") is check.TEST_PASSED
    assert asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:burned"))) == ""
    assert asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:sawn")))


def test_a_saw_is_passed_over_by_pc_cam(ctx):
    """A part that is only cut has no route, and naming the saw is refused."""
    sawn = ctx.get_part("//test:sawn")
    assert pc_cam.declares_job(sawn) is False
    assert pc_cam.declared_config(sawn) is None
    with pytest.raises(pc_cam.CamConfigError, match="runs no program"):
        pc_cam.declared_config(sawn, "cut")


def test_a_saw_beside_a_laser_leaves_the_laser_as_the_only_route(ctx):
    """The saw is an alternative with no program, so it makes nothing ambiguous."""
    part = ctx.get_part("//test:sawn_or_burned")
    assert pc_cam.declares_job(part) is True
    pc_cam.declared_config(part)
    assert part._route_machine_data()["machine"] == "laser"
    # ...and the laser check still answers for its own claim.
    assert ManufacturabilityLaserTest()._machine_of(part) is not None


#
# A reference that says how its object is made
#


REFERENCE_PACKAGE = {
    "name": "//test",
    "parts": {
        "board": {"type": "step", "tolerance": 0.4, "parameters": {"length": {"type": "float", "default": 600}}},
        "piece": {
            "type": "enrich",
            "source": "board",
            "with": {"length": 250},
            "manufacturing": {
                "method": "subtractive",
                "source": "board",
                "cut": {"cuts": [{"along": "+Y", "length": "$length"}]},
            },
        },
        "same_board": {"type": "alias", "source": "board"},
    },
}


@pytest.fixture
def reference_ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(REFERENCE_PACKAGE))
    (tmp_path / "board.step").write_text("")
    return pc.Context(str(tmp_path))


def test_an_enrich_says_how_its_instance_is_made(reference_ctx):
    """The enrich's own 'manufacturing:' is what is read, with the instance's parameters.

    A board is bought; a piece of it is cut. Before this, a reference reported
    its source's declaration whole, so the piece's cut was invisible to every
    check and the piece read as something nobody makes.
    """
    from partcad.part_config import PartConfiguration

    piece = reference_ctx.get_part("//test:piece")
    asyncio.run(piece.prepare_async())
    data = PartConfiguration.get_manufacturing_data(piece)
    assert data.machine.kind == MACHINE_CUT
    assert data.machine.cuts == [{"normal": [0.0, 1.0, 0.0], "length": 250.0}]
    # ...and a reference that says nothing about it still reports its source's.
    assert PartConfiguration.get_manufacturing_data(reference_ctx.get_part("//test:same_board")).method is None


def test_a_reference_is_made_as_precisely_as_what_it_points_at(reference_ctx):
    """A reference has no tolerance of its own to state, so it answers with its source's.

    Without this every enrich of a made part answered None, which the
    manufacturability test reads as a type that cannot say.
    """
    for name in ("piece", "same_board"):
        part = reference_ctx.get_part("//test:" + name)
        assert asyncio.run(part.get_tolerance()) == pytest.approx(0.4)
