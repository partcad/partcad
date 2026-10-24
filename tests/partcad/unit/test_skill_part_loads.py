#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`part_loads.py`, the helper the `sim-assembly-fea` skill ships beside its `SKILL.md`.

It is arithmetic on poses, and an agent reading its answer has no way to tell a
wrong frame from a right one: a load turned the wrong way is still three
plausible numbers. So each case here is a pose worked out by hand.

It is loaded from the skills library rather than imported, because it is not a
module of any package -- `pc init` copies it into a user's repository beside the
skill -- and without writing bytecode, so that running the tests leaves nothing
in the library for the wheel or `pc init` to carry along.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[3] / "ai-agents" / "common" / "skills" / "sim-assembly-fea" / "part_loads.py"


@pytest.fixture(scope="module")
def part_loads():
    spec = importlib.util.spec_from_file_location("part_loads", HELPER)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def close(a, b, tolerance=1e-6):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b)) and len(a) == len(b)


# A quarter turn about Z, 'w x y z'.
QUARTER_Z = [0.7071067811865476, 0.0, 0.0, 0.7071067811865476]


def run(**overrides):
    """One run: the body 'arm' at (100, 0, 0), turned a quarter about Z, at rest under a 9.81 gravity.

    'gear' is welded into it 10 mm along the body's X and turned a further
    quarter about Z there, so in the world it sits at (100, 10, 0) and is turned
    half a turn: its X is the world's -X, its Y the world's -Y.
    """
    reading = {
        "time": 1.0,
        "bodies": {
            "arm": {
                "pos": [100.0, 0.0, 0.0],
                "quat": QUARTER_Z,
                "mass": 2.0,
                "acc": [0.0, 0.0, 0.0],
                "loads": [
                    # Held at its origin against its weight, and against the moment of
                    # the weight's lever.
                    {
                        "kind": "fixed",
                        "from": "world",
                        "at": [100.0, 0.0, 0.0],
                        "force": [0.0, 0.0, 19.62],
                        "torque": [0.0, 0.0, 0.0],
                    },
                    {
                        "kind": "gravity",
                        "from": "arm",
                        "at": [100.0, 0.0, 0.0],
                        "force": [0.0, 0.0, -19.62],
                        "torque": [0.0, 0.0, 0.0],
                    },
                    # A push along the world's X, 1 N*m about its Z, at the gear's origin.
                    {
                        "kind": "joint",
                        "from": "hand",
                        "joint": "wrist",
                        "at": [100.0, 10.0, 0.0],
                        "force": [5.0, 0.0, 0.0],
                        "torque": [0.0, 0.0, 1.0],
                    },
                ],
            },
            "hand": {"pos": [0.0, 0.0, 0.0], "quat": [1.0, 0.0, 0.0, 0.0], "loads": []},
        },
    }
    result = {
        "gravity": [0.0, 0.0, -9.81],
        "before": reading,
        "after": reading,
        "samples": [reading],
        "parts": {
            "subject/arm/gear": {
                "part": "//pub/vendor:motion/gear",
                "body": "arm",
                "placement": [[10.0, 0.0, 0.0], [0.0, 0.0, 1.0], 90.0],
            },
            "subject/arm/plate": {"part": "//pub/vendor:plate", "body": "arm", "placement": None},
            "subject/hand/plate": {"part": "//pub/vendor:plate", "body": "hand", "placement": None},
        },
    }
    result.update(overrides)
    return result


def test_a_load_is_stated_where_it_acts_and_which_way_it_points_in_the_part_s_frame(part_loads):
    answer = part_loads.loads(run(), "subject/arm/gear")
    assert close(answer["pose"]["pos"], [100.0, 10.0, 0.0])
    wrist = [load for load in answer["loads"] if load["joint"] == "wrist"][0]
    # At the part's origin; the world's +X is the part's -X; Z is Z both ways.
    assert close(wrist["at"], [0.0, 0.0, 0.0])
    assert close(wrist["force"], [-5.0, 0.0, 0.0])
    assert close(wrist["torque"], [0.0, 0.0, 1.0])
    assert wrist["kind"] == "joint" and wrist["from"] == "hand"


def test_the_part_s_gravity_is_the_scene_s_less_the_body_s_acceleration_in_its_frame(part_loads):
    result = run()
    # Accelerating at 2 m/s^2 along the world's +Y: flung 2 m/s^2 along the
    # world's -Y, which is the part's +Y.
    result["after"] = json.loads(json.dumps(result["after"]))
    result["after"]["bodies"]["arm"]["acc"] = [0.0, 2.0, 0.0]
    answer = part_loads.loads(result, "gear")
    assert close(answer["gravity"], [0.0, 0.0, -9.81])
    assert close(answer["acceleration"], [0.0, -2.0, 0.0])
    assert close(answer["apparent_gravity"], [0.0, 2.0, -9.81])


def test_on_a_turning_body_the_part_s_gravity_is_where_the_part_is(part_loads):
    """A turn a second about Z, the centre of mass 10 mm from the gear: the gear is flung outward."""
    result = run()
    result["after"] = json.loads(json.dumps(result["after"]))
    arm = result["after"]["bodies"]["arm"]
    arm.update({"com": [100.0, 0.0, 0.0], "angvel": [0.0, 0.0, 360.0], "angacc": [0.0, 0.0, 0.0]})
    answer = part_loads.loads(result, "gear")
    # Centripetal: omega^2 r toward the centre of mass, the world's -Y here;
    # the part is turned half a turn, so that is its +Y.
    inward = (2.0 * math.pi) ** 2 * 0.010
    assert close(answer["acceleration"], [0.0, inward, 0.0])
    assert close(answer["apparent_gravity"], [0.0, -inward, -9.81])

    # And turning faster: alpha x r, along the world's -X at the part, its +X.
    arm.update({"angvel": [0.0, 0.0, 0.0], "angacc": [0.0, 0.0, 360.0]})
    answer = part_loads.loads(result, "gear")
    assert close(answer["acceleration"], [2.0 * math.pi * 0.010, 0.0, 0.0])


def test_the_loads_add_up_about_the_part_s_origin(part_loads):
    answer = part_loads.loads(run(), "gear")
    # The weight and the weld cancel. The push, 5 N along the part's -X at its
    # origin, has no lever; the weld and the weight do, but cancel each other.
    assert close(answer["total"]["force"], [-5.0, 0.0, 0.0])
    assert close(answer["total"]["torque"], [0.0, 0.0, 1.0])


def test_a_part_is_found_by_its_path_by_the_end_of_one_or_by_the_part_it_is(part_loads):
    result = run()
    assert part_loads.find_part(result, "subject/arm/gear")[0] == "subject/arm/gear"
    assert part_loads.find_part(result, "arm/gear")[0] == "subject/arm/gear"
    assert part_loads.find_part(result, "motion/gear")[0] == "subject/arm/gear"
    assert part_loads.find_part(result, "//pub/vendor:motion/gear")[0] == "subject/arm/gear"


def test_a_part_placed_twice_has_to_be_named_by_its_path(part_loads):
    with pytest.raises(SystemExit, match="2 placements.*subject/arm/plate, subject/hand/plate"):
        part_loads.find_part(run(), "plate")


def test_a_run_that_says_nothing_about_its_parts_says_why(part_loads):
    with pytest.raises(SystemExit, match="does not report loads"):
        part_loads.loads(run(parts=None), "gear")


def test_a_point_of_one_part_is_put_in_another_s_frame(part_loads):
    # The hand's plate is at the world's origin, unturned: its (100, 10, 5) is
    # the gear's origin, 5 mm up.
    assert close(part_loads.point(run(), "hand/plate", "gear", [100.0, 10.0, 5.0]), [0.0, 0.0, 5.0])
    # And its +Y, the world's, is the gear's -Y.
    assert close(part_loads.point(run(), "hand/plate", "gear", [0.0, 1.0, 0.0], direction=True), [0.0, -1.0, 0.0])


def test_a_reading_is_before_after_or_a_sample_by_its_index(part_loads):
    assert part_loads.loads(run(), "gear", which="0")["reading"] == "0"
    with pytest.raises(SystemExit, match="No reading '7'"):
        part_loads.loads(run(), "gear", which="7")


def test_the_run_is_found_in_what_pc_sim_json_prints(part_loads):
    document = {
        "simulations": [
            {"simulation": "dropped", "result": run(), "error": None},
            {"simulation": "held", "result": None, "error": "the engine was not found"},
        ]
    }
    with pytest.raises(SystemExit, match="2 simulations here"):
        part_loads.run_of(document)
    assert part_loads.run_of(document, "dropped")["parts"]
    with pytest.raises(SystemExit, match="'held' did not run: the engine was not found"):
        part_loads.run_of(document, "held")


def test_the_command_line_reads_past_a_log_on_the_same_stream(part_loads, tmp_path, capsys):
    captured = tmp_path / "sim.json"
    captured.write_text(
        "2026-10-19T06:00:00.000Z INFO:partcad:a line of the log\n"
        + json.dumps({"simulations": [{"simulation": "dropped", "result": run()}]}, indent=2),
        encoding="utf-8",
    )
    part_loads.main(["loads", str(captured), "arm/gear"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["part"]["body"] == "arm"
    assert close(printed["apparent_gravity"], [0.0, 0.0, -9.81])


def test_the_loads_say_what_the_scenario_they_become_is_called(part_loads):
    """After the simulation, and the reading for any reading but the one the skill reads."""
    document = {"simulations": [{"simulation": "dropped", "result": run(), "error": None}]}
    assert part_loads.loads(document, "gear")["scenario"] == "dropped"
    assert part_loads.loads(document, "gear", which="before")["scenario"] == "dropped-before"
    # One run's result names no simulation of its own.
    assert part_loads.loads(run(), "gear")["scenario"] == "simulated"


def test_a_sample_s_scenario_is_named_after_when_it_was(part_loads):
    assert part_loads.scenario_name("dropped", "3", 0.02) == "dropped-t0.02"
    assert part_loads.scenario_name("dropped", "3", None) == "dropped-3"
    assert part_loads.scenario_name("held in place", "after") == "held-in-place"
