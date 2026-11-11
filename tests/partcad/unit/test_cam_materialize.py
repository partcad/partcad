#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `//builtin/cam` makes by following a route, run in this process.

`cam_gcode.process` with `materialize` returns, beside the route it writes, the
product the machine makes by following it: a printer's deposit (`cam_fff`),
what a router, a laser or a drill leaves of the stock, a saw's cuts and a mold's
shrunk cavity (`cam_product`). Loaded the way `test_cam_gcode.py` loads the
module, with `wrapper_common` stubbed, on real build123d solids.

The volumes asserted are the ones the design record measured
(docs/design/additive.md, section 8): a print is stroked at the line spacing,
so its deposit is within a few percent of what its extruder feeds.
"""

import importlib.util
import math
import os
import sys

import build123d as b3d
import pytest
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

import partcad as pc

CAM_DIR = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "builtin", "cam")

BOTTOM = (b3d.Align.CENTER, b3d.Align.CENTER, b3d.Align.MIN)


class _WrapperCommonStub:
    @staticmethod
    def exception_to_str(exc):
        return None if exc is None else str(exc)

    @staticmethod
    def handle_exception(exc, script=None):
        pass


@pytest.fixture(scope="module")
def gcode():
    """`builtin/cam/cam_gcode.py` as an importable module, its siblings importable beside it."""
    saved = sys.modules.get("wrapper_common")
    sys.modules["wrapper_common"] = _WrapperCommonStub
    saved_path = list(sys.path)
    sys.path.insert(0, CAM_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "partcad.builtin.cam.cam_gcode_m", os.path.join(CAM_DIR, "cam_gcode.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = saved_path
        if saved is None:
            del sys.modules["wrapper_common"]
        else:
            sys.modules["wrapper_common"] = saved


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _bbox(shape):
    return b3d.Compound(shape).bounding_box() if not hasattr(shape, "bounding_box") else shape.bounding_box()


def _make(gcode, tmp_path, machine, obj, **job):
    request = {"wrapped": obj.wrapped, "machine": machine, "materialize": True, "tolerance": 0.01}
    request.update(job)
    result = gcode.process(str(tmp_path / ("%s.nc" % machine)), request)
    assert result["success"], result.get("exception")
    return result


def _plate():
    plate = b3d.Box(40, 30, 6, align=BOTTOM)
    for x in (-10, 10):
        plate -= b3d.Pos(x, 0, 0) * b3d.Cylinder(4, 6, align=BOTTOM)
    return plate


STOCK = b3d.Box(50, 40, 6, align=BOTTOM)

#
# A printer
#


def test_a_printer_writes_a_route_with_extrusion(gcode, tmp_path):
    result = _make(gcode, tmp_path, "fff", b3d.Box(10, 10, 4, align=BOTTOM), infill=0.2)
    text = (tmp_path / "fff.nc").read_text()
    assert "M83" in text  # relative extrusion
    assert " E" in text
    stats = result["stats"]
    assert stats["machine"] == "fff"
    assert stats["layers"] == 20
    # What the extruder feeds is the stadium's area along every path.
    assert stats["volume"] > 0 and stats["volume"] < 400
    assert stats["solid_volume"] == pytest.approx(400, rel=0.01)


def test_what_a_printer_deposits_is_mostly_empty_inside(gcode, tmp_path):
    result = _make(gcode, tmp_path, "fff", _plate(), infill=0.2)
    deposited = _volume(result["product"])
    # The design is 6597 mm3; the route feeds about 3164 of it, and the deposit
    # stroked at the line spacing is within a few percent of that.
    assert deposited == pytest.approx(3212, rel=0.03)
    assert deposited == pytest.approx(result["stats"]["volume"], rel=0.05)


def test_more_infill_deposits_more(gcode, tmp_path):
    cube = b3d.Box(12, 12, 6, align=BOTTOM)
    sparse = _volume(_make(gcode, tmp_path, "fff", cube, infill=0.1)["product"])
    dense = _volume(_make(gcode, tmp_path, "fff", cube, infill=0.6)["product"])
    solid = _volume(_make(gcode, tmp_path, "fff", cube, infill=1.0)["product"])
    assert sparse < dense < solid <= 12 * 12 * 6 * 1.01


def test_a_hole_is_gone_round_not_filled(gcode, tmp_path):
    """A printer's walls go round every hole: an island OCCT's face offset loses at tangency."""
    result = _make(gcode, tmp_path, "fff", _plate(), infill=1.0, walls=3)
    product = b3d.Compound(result["product"])
    # Nothing is deposited where the holes are.
    for x in (-10, 10):
        probe = b3d.Pos(x, 0, 3) * b3d.Cylinder(3.5, 1)
        assert (product & probe).volume == pytest.approx(0, abs=1e-6)


def test_a_concentric_infill_is_a_pockets_rings(gcode, tmp_path):
    result = _make(gcode, tmp_path, "fff", b3d.Box(10, 10, 2, align=BOTTOM), infill=0.3, infillPattern="concentric")
    assert result["stats"]["paths"] > 0
    assert _volume(result["product"]) > 0


def test_a_print_on_its_side_comes_back_in_the_parts_frame(gcode, tmp_path):
    part = b3d.Box(4, 6, 10, align=BOTTOM)
    result = _make(gcode, tmp_path, "fff", part, infill=0.2, tool_axis_vector=[0, -1, 0])
    box = b3d.Compound(result["product"]).bounding_box()
    assert box.size.X == pytest.approx(4, abs=0.3)
    assert box.size.Y == pytest.approx(6, abs=0.3)
    assert box.size.Z == pytest.approx(10, abs=0.3)


def test_a_pattern_the_route_does_not_draw_is_refused(gcode, tmp_path):
    result = gcode.process(
        str(tmp_path / "x.nc"),
        {"wrapped": b3d.Box(5, 5, 2).wrapped, "machine": "fff", "infillPattern": "gyroid"},
    )
    assert not result["success"]
    assert "gyroid" in result["exception"]


def test_a_print_kept_as_an_sdf_is_a_script_with_its_route_in_it(gcode, tmp_path):
    result = _make(
        gcode, tmp_path, "fff", b3d.Box(6, 6, 2, align=BOTTOM), infill=0.2, representation="sdf", shape_name="cube"
    )
    script = result["sdf_script"]
    assert "product" not in result
    assert "show_object(print_)" in script
    compile(script, "cube.py", "exec")


def test_a_product_kept_as_step_is_step(gcode, tmp_path):
    result = _make(gcode, tmp_path, "fff", b3d.Box(4, 4, 1, align=BOTTOM), infill=0.2, representation="step")
    assert result["product_step"].startswith("ISO-10303-21")


#
# What a cut leaves of its stock
#

ROUTER = {"diameter": 3.0, "feed": 1000.0, "safe_z": 5.0, "depth_per_pass": 3.0}


def test_a_profile_leaves_the_part_and_drops_the_offcut_and_the_slugs(gcode, tmp_path):
    plate = _plate()
    result = _make(gcode, tmp_path, "cnc", plate, stock=STOCK.wrapped, **ROUTER)
    assert _volume(result["product"]) == pytest.approx(plate.volume, rel=0.002)


def test_a_laser_cuts_the_same_part_out(gcode, tmp_path):
    plate = _plate()
    result = _make(gcode, tmp_path, "laser", plate, stock=STOCK.wrapped, kerf=0.2, feed=1000.0)
    assert _volume(result["product"]) == pytest.approx(plate.volume, rel=0.002)


def test_a_drill_takes_its_own_cylinder_out(gcode, tmp_path):
    result = _make(gcode, tmp_path, "drill", _plate(), stock=STOCK.wrapped, diameter=8.0, plunge=300.0, safe_z=5.0)
    assert _volume(result["product"]) == pytest.approx(50 * 40 * 6 - 2 * math.pi * 16 * 6, rel=0.001)


def test_a_drawing_is_cut_through_the_stock_it_is_on(gcode, tmp_path):
    """A flat drawing has no depth of its own: the cut starts at the top of the stock and goes through it."""
    outline = b3d.Rectangle(30, 20)
    result = _make(gcode, tmp_path, "cnc", outline, stock=STOCK.wrapped, **ROUTER)
    assert _volume(result["product"]) == pytest.approx(30 * 20 * 6, rel=0.002)


def test_a_cut_part_needs_its_stock(gcode, tmp_path):
    result = gcode.process(
        str(tmp_path / "cnc.nc"), {"wrapped": _plate().wrapped, "machine": "cnc", "materialize": True, **ROUTER}
    )
    assert not result["success"]
    assert "stock" in result["exception"]


def test_a_saw_takes_off_everything_beyond_its_cut(gcode, tmp_path):
    board = b3d.Box(100, 20, 20, align=(b3d.Align.MIN, b3d.Align.CENTER, b3d.Align.MIN))
    result = _make(gcode, tmp_path, "cut", board, stock=board.wrapped, cuts=[{"normal": [1, 0, 0], "length": 60.0}])
    assert _volume(result["product"]) == pytest.approx(60 * 20 * 20, rel=1e-6)


def test_a_mold_gives_back_its_cavity_shrunk(gcode, tmp_path):
    cavity = b3d.Cylinder(10, 5)
    result = _make(gcode, tmp_path, "mold", cavity, shrinkage=0.01)
    assert _volume(result["product"]) == pytest.approx(cavity.volume * 0.99**3, rel=1e-6)


def test_a_machine_that_runs_no_program_writes_none(gcode, tmp_path):
    result = gcode.process(str(tmp_path / "mold.nc"), {"wrapped": b3d.Box(1, 1, 1).wrapped, "machine": "mold"})
    assert not result["success"]
    assert "runs no program" in result["exception"]
