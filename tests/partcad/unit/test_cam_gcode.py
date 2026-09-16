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


# --------------------------------------------------------------------------- #
# The machines other than a router                                            #
# --------------------------------------------------------------------------- #


def _drilled_panel():
    """A panel with two round holes through it: something a drill can make."""
    panel = _panel()
    for x in (10, 30):
        panel -= b3d.Solid.make_cylinder(3, 12).locate(b3d.Location((x, 15, -3)))
    return panel


def test_a_part_that_names_no_machine_is_routed_exactly_as_before(gcode, tmp_path):
    """The guarantee the whole machine split rests on.

    `_orient` is the identity for the default `-Z` and the CNC emitter is the
    old body verbatim, so a part that never heard of machines produces the same
    bytes it always produced. Asserted here as "declaring the default changes
    nothing", which is the same claim from the other side.
    """
    _, without = _route(gcode, tmp_path, _panel_with_hole())
    _, with_default = _route(gcode, tmp_path, _panel_with_hole(), machine="cnc", tool_axis_vector=[0.0, 0.0, -1.0])
    assert without == with_default


def test_a_machine_it_does_not_know_is_refused_with_the_set(gcode, tmp_path):
    """The refusal names what it does know, so the sentence is actionable."""
    assert "cnc" in _refusal(gcode, tmp_path, machine="waterjet")


def test_a_laser_cuts_through_in_one_pass_and_never_moves_in_z(gcode, tmp_path):
    """Three things at once, because they are one fact about the machine.

    A beam has no depth of cut, so there is no stepping; it has no spindle, so
    there is no `M3 S<rpm>` at the top and no `M5` at the bottom; and it never
    plunges, so no `G1 Z` appears anywhere.
    """
    result, text = _route(gcode, tmp_path, _panel_with_hole(), machine="laser", kerf=0.2, power=60)
    assert result["stats"]["machine"] == "laser"
    assert result["stats"]["passes"] == 1
    assert "G1 Z" not in text
    # The beam is gated around each contour instead.
    assert "M3 S60" in text
    assert text.count("M3 S60") == text.count("M5")


def test_a_laser_offsets_by_half_the_kerf(gcode, tmp_path):
    """What makes the part come out at its nominal size.

    The beam removes a kerf-wide stripe centred on the path, so the path runs
    half a kerf outside the part -- the same geometry a profile uses, with the
    beam's half-width in place of the cutter's radius.
    """
    _, text = _route(gcode, tmp_path, machine="laser", kerf=0.4)
    xs = [x for x, _ in _cuts(text)]
    # The panel is 40 wide from x=0, so the path runs from -0.2 to 40.2.
    assert min(xs) == pytest.approx(-0.2, abs=1e-6)
    assert max(xs) == pytest.approx(40.2, abs=1e-6)


def test_a_laser_needs_no_cutter_diameter(gcode, tmp_path):
    """The one parameter a router cannot run without, and a laser does not have."""
    request = dict(JOB)
    del request["tool"]
    request.update({"machine": "laser", "kerf": 0.1, "wrapped": _panel().wrapped})
    result = gcode.process(str(tmp_path / "route.nc"), request)
    assert result["success"] is True, result.get("exception")


def test_a_drill_goes_to_each_hole_and_makes_no_cutting_moves(gcode, tmp_path):
    """A drill does not follow a path, so there is nothing to cut along."""
    result, text = _route(gcode, tmp_path, _drilled_panel(), machine="drilling", tool=6.0)
    assert result["stats"]["machine"] == "drilling"
    assert result["stats"]["holes"] == 2
    assert result["stats"]["cut_length"] == pytest.approx(0.0)
    # Two centres, each rapid'ed to.
    assert "G0 X10.000 Y15.000" in text
    assert "G0 X30.000 Y15.000" in text


def test_a_drill_with_nothing_round_to_make_is_refused(gcode, tmp_path):
    """A refusal rather than an empty program: a drill with no hole is a mistake."""
    assert "no round hole" in _refusal(gcode, tmp_path, _panel(), machine="drilling")


def test_a_round_plate_is_not_one_enormous_hole(gcode, tmp_path):
    """The outer wall of a round part is a cylinder about Z, and not a hole.

    Nothing about the surface distinguishes it from a bore of the same radius --
    only which side the material is on does. Read as a hole it would put a
    plunge at the centre of a plate that needed no drilling at all, which is a
    program that breaks the drill.
    """
    plate = b3d.Solid.make_cylinder(20, 6)
    assert "no round hole" in _refusal(gcode, tmp_path, plate, machine="drilling")


def test_a_boss_standing_on_a_panel_is_not_drilled(gcode, tmp_path):
    """The same mistake where there is also a real hole to get right.

    The panel has one bore and one boss, both cylinders about Z. A drill makes
    the first and must not be sent at the second -- and the count is what says
    so, because a route that plunged into the boss would still be a route.
    """
    panel = _panel()
    panel -= b3d.Solid.make_cylinder(3, 12).locate(b3d.Location((10, 15, -3)))
    panel += b3d.Solid.make_cylinder(4, 5).locate(b3d.Location((30, 15, 6)))

    result, text = _route(gcode, tmp_path, panel, machine="drilling", tool=6.0)
    assert result["stats"]["holes"] == 1
    assert "G0 X10.000 Y15.000" in text
    assert "X30.000" not in text


def test_pecking_breaks_the_plunge_into_steps(gcode, tmp_path):
    """Each step comes back out to the top of the hole, which clears the swarf."""
    _, once = _route(gcode, tmp_path, _drilled_panel(), machine="drilling", tool=6.0)
    _, pecked = _route(gcode, tmp_path, _drilled_panel(), machine="drilling", tool=6.0, peck=2.0)
    assert pecked.count("G1 Z") > once.count("G1 Z")


def test_a_drill_that_is_not_the_size_of_the_hole_is_said_out_loud(gcode, tmp_path):
    """A 5 mm drill does not make a 6 mm hole, and the file cannot say so."""
    result, _ = _route(gcode, tmp_path, _drilled_panel(), machine="drilling", tool=5.0)
    assert any("not the diameter of the drill" in warning for warning in result["warnings"])


def test_the_tool_axis_turns_the_part_into_the_machines_frame(gcode, tmp_path):
    """A part cut from the side is the same solid fixtured differently.

    Its holes run along X, so a drill working down the Z axis has nothing to
    make and one working along X has two.
    """
    panel = _panel()
    for y in (10, 20):
        panel -= b3d.Solid.make_cylinder(3, 60).locate(b3d.Location((-10, y, 3), (0, 90, 0)))

    assert "no round hole" in _refusal(gcode, tmp_path, panel, machine="drilling", tool=6.0)
    result, _ = _route(gcode, tmp_path, panel, machine="drilling", tool=6.0, tool_axis_vector=[1.0, 0.0, 0.0])
    assert result["stats"]["holes"] == 2


def test_a_route_is_the_same_bytes_whichever_machine_wrote_it_twice(gcode, tmp_path):
    """Byte stability is what makes a route something a repository can hold."""
    for machine, extra in (("laser", {"kerf": 0.2}), ("drilling", {"tool": 6.0})):
        shape = _panel_with_hole() if machine == "laser" else _drilled_panel()
        _, first = _route(gcode, tmp_path, shape, machine=machine, **extra)
        _, second = _route(gcode, tmp_path, shape, machine=machine, **extra)
        assert first == second, machine
