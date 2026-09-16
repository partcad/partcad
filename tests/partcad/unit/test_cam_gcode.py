#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in G-code route implementation, run in this process.

`//builtin/cam`'s `cam_gcode.py` is a script the sandbox executes, so everything
that reaches it end to end -- `pc cam`, `pc test -f cam`, `features/cam.feature`
-- runs it in an interpreter this one cannot see into. That is the right way to
*use* it and a poor way to test it: a failure arrives as a sentence from another
process, and the arithmetic that produces the route is never examined on its own.

So this loads the module directly, the way `test_output.py` loads
`wrapper_export`, and asks it the questions worth asking about a machine program:
what it refuses, which way round it cuts, how deep, and whether the same object
twice produces the same bytes. `wrapper_common` is stubbed because the module
imports it for its two exception helpers and nothing else; the module under test
is the real one, and so is the geometry -- these are real build123d solids being
really sectioned and offset.

Reading the assertions: G-code words are a letter and a number, so a cut is
`G1 X.. Y..`, a rapid is `G0`, `G21`/`G20` select millimeters or inches, and
`M3`/`M5` start and stop the spindle.
"""

import importlib.util
import math
import os
import sys

import build123d as b3d
import pytest

import partcad as pc

CAM_DIR = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "builtin", "cam")

# Executed under a name *inside* the `partcad` namespace, and that is not
# cosmetic: CI measures coverage through pytest-cov, which passes `--cov=partcad`
# and so sets coverage's `source` to the **module name** rather than to a path.
# Coverage then decides what to trace from the name the frame is running under,
# so a module executed as `partcad_test_cam_gcode` is "outside the --source
# spec" however squarely its file sits inside `src/partcad/`. Under that name
# this file measured 0% in CI while measuring 90% locally, where `coverage run`
# uses the `include` path list instead.
#
# The name is never registered in `sys.modules`, so nothing can import it or be
# confused by a package path that has no `__init__.py` behind it.
MODULE_NAME = "partcad.builtin.cam.cam_gcode"


class _WrapperCommonStub:
    """The two helpers `cam_gcode` imports from `wrapper_common`.

    The real one pulls in `ocp_serialize` and with it a CAD stack that the
    sandbox has and this process need not, and neither helper is what is under
    test -- they turn an exception into a string on its way back to PartCAD.
    """

    @staticmethod
    def exception_to_str(exc):
        return None if exc is None else str(exc)

    @staticmethod
    def handle_exception(exc, script=None):
        pass


@pytest.fixture(scope="module")
def gcode():
    """`builtin/cam/cam_gcode.py` as an importable module."""
    saved = sys.modules.get("wrapper_common")
    sys.modules["wrapper_common"] = _WrapperCommonStub
    saved_path = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location(MODULE_NAME, os.path.join(CAM_DIR, "cam_gcode.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = saved_path
        if saved is None:
            del sys.modules["wrapper_common"]
        else:
            sys.modules["wrapper_common"] = saved


# A job that is complete: every parameter the implementation refuses to guess.
# Individual tests override one key at a time, so what a test is about is the
# key it names rather than the eight it repeats.
JOB = {
    "tool": 3.0,
    "feed": 600.0,
    "plunge": 200.0,
    "safe_z": 5.0,
    "depth_per_pass": 2.0,
}


def _panel():
    """A prismatic part: 40 x 30 x 6, the shape this implementation is for."""
    return b3d.Solid.make_box(40, 30, 6)


def _panel_with_hole():
    """The same panel with a hole through it, so there is an inside to cut."""
    hole = b3d.Solid.make_cylinder(5, 6).locate(b3d.Location((20, 15, 0)))
    return _panel() - hole


def _route(gcode, tmp_path, shape=None, **overrides):
    """Produce a route and return (result, text), failing loudly if it did not."""
    request = dict(JOB)
    request.update(overrides)
    request["wrapped"] = (shape if shape is not None else _panel()).wrapped
    path = str(tmp_path / "route.nc")
    result = gcode.process(path, request)
    assert result["success"] is True, result.get("exception")
    return result, open(path).read()


def _refusal(gcode, tmp_path, shape=None, **overrides):
    """The sentence the implementation refused with."""
    request = dict(JOB)
    request.update(overrides)
    request["wrapped"] = (shape if shape is not None else _panel()).wrapped
    result = gcode.process(str(tmp_path / "route.nc"), request)
    assert result["success"] is False, "expected a refusal, got a route"
    return result["exception"]


def _cuts(text):
    """The (x, y) of every G1 cutting move, in order."""
    points = []
    for line in text.splitlines():
        if line.startswith("G1 X"):
            words = line.split()
            points.append((float(words[1][1:]), float(words[2][1:])))
    return points


# --------------------------------------------------------------------------- #
# Program: the words themselves                                               #
# --------------------------------------------------------------------------- #


def test_a_feed_that_is_a_whole_number_is_written_without_a_fraction(gcode):
    """`F600`, not `F600.000`.

    Feed is the one word where the trailing zeros are not merely noise: senders
    and controllers display it back to the operator, and a rate is read at a
    glance or not at all.
    """
    program = gcode.Program("mm", 3, True)
    assert program.feed(600.0) == "600"
    assert program.feed(600) == "600"
    # ...and a rate that genuinely is fractional keeps what it needs.
    assert program.feed(62.5) == "62.5"


def test_coordinates_carry_the_configured_precision(gcode):
    program = gcode.Program("mm", 3, True)
    assert program.number(1.23456) == "1.235"
    assert gcode.Program("mm", 1, True).number(1.23456) == "1.2"


def test_comments_can_be_turned_off(gcode):
    """A controller with a small screen, or a diff that should carry no prose."""
    on = gcode.Program("mm", 3, True)
    on.comment("hello")
    assert "(hello)" in on.text()

    off = gcode.Program("mm", 3, False)
    off.comment("hello")
    assert "hello" not in off.text()


def test_a_move_to_where_the_tool_already_is_is_dropped(gcode):
    """And says so, because the caller owes the pass a feed word.

    An offset contour carries points a micron apart where edges meet at a
    tangent. Emitting those is a line in the file and a dwell on the machine;
    dropping one silently would be worse, because the first move of a pass
    carries the feed and a dropped first move would leave the contour cutting at
    the plunge rate.
    """
    program = gcode.Program("mm", 3, True)
    assert program.cut_to((0.0, 0.0)) is True
    assert program.cut_to((0.0, 0.0)) is False
    assert program.cut_to((10.0, 0.0)) is True
    assert program.cut_length == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# What it refuses                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key,word", [("tool", "tool"), ("feed", "feed"), ("safe_z", "safe_z")])
def test_a_parameter_it_cannot_guess_is_refused_by_name(gcode, tmp_path, key, word):
    """And the refusal says where to set it, which is the whole of the remedy."""
    message = _refusal(gcode, tmp_path, **{key: None})
    assert word in message
    assert "'cam:' section" in message


def test_the_cutter_diameter_has_no_default(gcode, tmp_path):
    """The one parameter where a default would be a wrong answer rather than a
    conservative one: a route cut against a diameter nobody chose is wrong by
    exactly the amount nobody noticed."""
    assert "tool" in _refusal(gcode, tmp_path, tool=None)


@pytest.mark.parametrize(
    "key,value",
    [("units", "furlongs"), ("operation", "sculpt"), ("direction", "sideways")],
)
def test_a_parameter_outside_its_set_is_refused_with_the_set(gcode, tmp_path, key, value):
    message = _refusal(gcode, tmp_path, **{key: value})
    assert key in message and value in message


def test_a_flat_object_with_no_depth_is_refused_rather_than_guessed(gcode, tmp_path):
    """A sketch has no thickness, so "cut through it" names no number."""
    flat = b3d.Face.make_rect(40, 30)
    message = _refusal(gcode, tmp_path, shape=flat)
    assert "flat" in message and "depth" in message


# --------------------------------------------------------------------------- #
# The route                                                                   #
# --------------------------------------------------------------------------- #


def test_a_profile_runs_outside_the_part_by_the_tool_radius(gcode, tmp_path):
    """The part survives the cut at its nominal size.

    A 40 x 30 panel cut with a 3 mm cutter is walked at 41.5 x 31.5 -- half the
    diameter beyond each face.
    """
    _result, text = _route(gcode, tmp_path, operation="profile")
    xs = [x for x, _y in _cuts(text)]
    ys = [y for _x, y in _cuts(text)]
    assert max(xs) == pytest.approx(41.5, abs=0.01)
    assert min(xs) == pytest.approx(-1.5, abs=0.01)
    assert max(ys) == pytest.approx(31.5, abs=0.01)
    assert min(ys) == pytest.approx(-1.5, abs=0.01)


def test_an_engrave_follows_the_outline_itself(gcode, tmp_path):
    """Offset by nothing: what a V-bit or a drag knife does."""
    _result, text = _route(gcode, tmp_path, operation="engrave")
    xs = [x for x, _y in _cuts(text)]
    assert max(xs) == pytest.approx(40.0, abs=0.01)
    assert min(xs) == pytest.approx(0.0, abs=0.01)


def test_a_pocket_stays_inside_the_outline(gcode, tmp_path):
    """Clearing what is inside, so nothing may cross the boundary."""
    result, text = _route(gcode, tmp_path, operation="pocket")
    xs = [x for x, _y in _cuts(text)]
    assert min(xs) >= 1.5 - 0.01
    assert max(xs) <= 38.5 + 0.01
    # More than one ring, or it cleared nothing.
    assert result["stats"]["paths"] > 1


def test_the_depth_is_divided_into_passes_of_at_most_depth_per_pass(gcode, tmp_path):
    """6 mm at 2 mm a pass is three passes, and the last one reaches the bottom."""
    result, text = _route(gcode, tmp_path, depth_per_pass=2.0)
    assert result["stats"]["passes"] == 3

    plunges = [float(line.split()[1][1:]) for line in text.splitlines() if line.startswith("G1 Z")]
    assert plunges == pytest.approx([4.0, 2.0, 0.0])


def test_a_depth_that_does_not_divide_evenly_gets_a_whole_extra_pass(gcode, tmp_path):
    """5 mm at 2 mm a pass is three passes, not two and a half."""
    result, _text = _route(gcode, tmp_path, depth=5.0, depth_per_pass=2.0)
    assert result["stats"]["passes"] == 3


def test_rapids_clear_the_top_of_the_object_rather_than_the_origin(gcode, tmp_path):
    """`safe_z` is a clearance, not a coordinate.

    The panel's top is at Z6, so a 5 mm clearance is Z11. Read as an absolute
    height it would be Z5 -- a rapid straight through the work, which is the
    failure this parameter exists to avoid.
    """
    _result, text = _route(gcode, tmp_path, safe_z=5.0)
    rapids = {float(line.split()[1][1:]) for line in text.splitlines() if line.startswith("G0 Z")}
    assert rapids == {11.0}


def test_climb_and_conventional_are_opposite_ways_round(gcode, tmp_path):
    """Which way round a contour is cut decides which edge it leaves."""
    _climb, climb_text = _route(gcode, tmp_path, direction="climb")
    _conv, conv_text = _route(gcode, tmp_path, direction="conventional")

    def signed_area(points):
        total = 0.0
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
            total += x1 * y2 - x2 * y1
        return total / 2.0

    assert signed_area(_cuts(climb_text)) * signed_area(_cuts(conv_text)) < 0


def test_a_hole_is_cut_before_the_outside_of_the_part(gcode, tmp_path):
    """A profile ends by separating the part from its stock.

    Anything still to be cut after that is cut in a part held by nothing, so the
    holes go first.
    """
    result, text = _route(gcode, tmp_path, shape=_panel_with_hole(), operation="profile")
    assert result["stats"]["paths"] == 2

    points = _cuts(text)
    hole_centre = (20.0, 15.0)
    # The first contour walked is the one near the middle of the panel.
    first = points[0]
    assert math.dist(first, hole_centre) < 10.0


def test_a_spindle_speed_starts_and_stops_the_spindle(gcode, tmp_path):
    _result, text = _route(gcode, tmp_path, speed=12000)
    assert "M3 S12000" in text
    assert "M5" in text


def test_no_spindle_speed_commands_no_spindle(gcode, tmp_path):
    """A spindle nobody commanded is one the operator set.

    Matched line by line rather than as a substring: every program ends `M30`,
    which contains `M3`.
    """
    _result, text = _route(gcode, tmp_path)
    lines = text.splitlines()
    assert not [line for line in lines if line.startswith("M3 ")]
    assert "M5" not in lines


def test_inches_select_the_inch_mode_word(gcode, tmp_path):
    _result, mm_text = _route(gcode, tmp_path, units="mm")
    _result, in_text = _route(gcode, tmp_path, units="in")
    assert "G21" in mm_text and "G20" not in mm_text
    assert "G20" in in_text and "G21" not in in_text


def test_every_route_ends_the_program(gcode, tmp_path):
    _result, text = _route(gcode, tmp_path)
    assert text.rstrip().endswith("M30")


# --------------------------------------------------------------------------- #
# What it warns about                                                         #
# --------------------------------------------------------------------------- #


def test_an_outline_that_changes_over_the_cut_is_warned_about(gcode, tmp_path):
    """The one failure that looks like a success all the way to the machine.

    The outline is a section taken at the bottom of the cut, which is the whole
    truth for a prismatic part and a guess for anything else. A cone is the
    clearest case: follow the bottom and the route is far wider than the top.
    """
    cone = b3d.Solid.make_cone(20, 5, 10)
    result, _text = _route(gcode, tmp_path, shape=cone, depth=10.0)
    assert any("the outline changes over the depth of the cut" in w for w in result["warnings"])


def test_a_prismatic_object_is_not_warned_about(gcode, tmp_path):
    """Nothing changes over the cut, so there is nothing to say."""
    result, _text = _route(gcode, tmp_path)
    assert result["warnings"] == []


def test_cutting_past_the_bottom_of_the_object_is_warned_about(gcode, tmp_path):
    """Which is ordinary -- it is how a part is cut free of a spoilboard -- so
    it is said rather than refused."""
    result, _text = _route(gcode, tmp_path, depth=8.0)
    assert any("past the bottom" in w for w in result["warnings"])


# --------------------------------------------------------------------------- #
# What makes it reviewable                                                    #
# --------------------------------------------------------------------------- #


def test_the_same_object_and_parameters_produce_the_same_bytes(gcode, tmp_path):
    """Nothing in the file is a timestamp, a host name or a version.

    It is what lets a route be checked in, and a change to one be a diff
    somebody reads rather than noise they learn to skip.
    """
    _first, first_text = _route(gcode, tmp_path, operation="profile")
    _second, second_text = _route(gcode, tmp_path, operation="profile")
    assert first_text == second_text


def test_the_object_is_named_in_the_file_it_was_cut_from(gcode, tmp_path):
    _result, text = _route(gcode, tmp_path, shape_name="panel", package_name="//shop")
    assert "(object: //shop:panel)" in text


def test_the_stats_report_the_size_of_the_job(gcode, tmp_path):
    """Reported rather than interpreted -- what is worth knowing about a route
    differs between a router and a wire EDM."""
    result, _text = _route(gcode, tmp_path)
    stats = result["stats"]
    assert stats["operation"] == "profile"
    assert stats["passes"] == 3
    assert stats["depth"] == pytest.approx(6.0)
    # Three passes around a 41.5 x 31.5 rectangle is on the order of 440 mm.
    assert stats["cut_length"] > 400.0
