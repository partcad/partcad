#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The checks a route passes before anything is swept (issue #975, design D9).

Each refusal says why ('reason'), where on the path ('point'), what was
measured ('values') and what to change ('remedy'). The profile here is a 6 mm
tube: radius 3 mm.
"""

import math
import time

import pytest

from partcad.route_path import EndFrame, check_route

RADIUS = 3.0


def _reasons(refusals):
    return [refusal.reason for refusal in refusals]


def test_a_via_point_at_an_end_is_refused():
    path, refusals = check_route(
        [EndFrame((0, 0, 0), (0, 0, 1)), (0, 0, 0.0004), EndFrame((50, 0, 0), (0, 0, 1))], RADIUS
    )
    assert path is None
    (refusal,) = refusals
    assert refusal.reason == "knots-coincide"
    assert refusal.point == pytest.approx((0, 0, 0))
    assert "end 1 and via point 1 of end 2" in refusal.message
    assert refusal.remedy == "remove or move via point 1 of end 2"


def test_two_ends_at_one_point_are_refused():
    path, refusals = check_route([EndFrame((5, 5, 5), (0, 0, 1)), EndFrame((5, 5, 5), (1, 0, 0))], RADIUS)
    assert path is None
    (refusal,) = refusals
    assert refusal.reason == "ends-coincide"
    assert refusal.point == pytest.approx((5, 5, 5))
    assert "end 1 and end 2 are at the same point" in refusal.message


def test_a_through_entry_on_an_end_is_refused_by_name():
    stops = [EndFrame((0, 0, 0), (0, 0, 1)), EndFrame((0, 0, 0), (1, 0, 0)), EndFrame((50, 0, 0), (0, 0, 1))]
    path, refusals = check_route(stops, RADIUS)
    assert path is None
    (refusal,) = refusals
    assert refusal.reason == "ends-coincide"
    assert "end 1 and through 1 are at the same point" in refusal.message


def test_a_via_point_one_millimetre_from_an_end_bends_tighter_than_the_tube():
    path, refusals = check_route(
        [EndFrame((0, 0, 0), (0, 0, 1)), (0.6, 0, 0.8), EndFrame((60, 0, 30), (-1, 0, 0))], RADIUS
    )
    (refusal,) = refusals
    assert refusal.reason == "bend-tighter-than-profile"
    assert refusal.values["radius"] < RADIUS
    assert refusal.values["profileRadius"] == RADIUS
    # Where the bend is: next to the end and the via point.
    assert math.dist(refusal.point, (0, 0, 0)) < 2
    assert refusal.remedy == "move via point 1 of end 2 further from its neighbours"
    assert "%.3f mm" % refusal.values["radius"] in refusal.message


def test_the_same_via_point_further_away_passes():
    path, refusals = check_route(
        [EndFrame((0, 0, 0), (0, 0, 1)), (12, 0, 16), EndFrame((60, 0, 30), (-1, 0, 0))], RADIUS
    )
    assert refusals == []
    assert path.min_radius >= RADIUS


def test_a_figure_eight_crosses_itself():
    stops = [
        EndFrame((0, 0, 0), (1, 0, 0)),
        (50, 30, 0),
        (100, 0, 0),
        (50, -30, 0),
        (0, 0, 1),
        (-50, 30, 0),
        (-100, 0, 0),
        EndFrame((-150, -30, 0), (1, 1, 0)),
    ]
    path, refusals = check_route(stops, RADIUS)
    (refusal,) = refusals
    assert refusal.reason == "path-crosses-itself"
    # Where it crosses: at the start, which the path comes back over 1 mm above.
    assert refusal.point == pytest.approx((0, 0, 0), abs=1e-9)
    assert refusal.values["distance"] == pytest.approx(1.0, abs=1e-6)


def test_a_hairpin_narrower_than_the_tube_is_refused():
    path, refusals = check_route(
        [EndFrame((0, 0, 0), (1, 0, 0), lead=100), EndFrame((0, 4, 0), (1, 0, 0), lead=100)], RADIUS
    )
    assert "path-crosses-itself" in _reasons(refusals)
    crossing = next(r for r in refusals if r.reason == "path-crosses-itself")
    assert crossing.values["distance"] == pytest.approx(4.0, abs=1e-9)
    assert crossing.point[1] == pytest.approx(0, abs=1e-9) and 0 <= crossing.point[0] <= 100


def test_a_hairpin_wider_than_the_tube_passes():
    path, refusals = check_route(
        [EndFrame((0, 0, 0), (1, 0, 0), lead=100), EndFrame((0, 10, 0), (1, 0, 0), lead=100)], RADIUS
    )
    assert refusals == []


def test_a_two_metre_route_is_checked_in_under_a_second():
    stops = [EndFrame((0, 0, 0), (1, 0, 0)), (700, 100, 0), (1300, -100, 50), EndFrame((1950, 0, 0), (-1, 0, 0))]
    start = time.perf_counter()
    path, refusals = check_route(stops, RADIUS, step=0.4)
    elapsed = time.perf_counter() - start
    assert refusals == []
    assert len(path.points) >= 5000
    assert path.length > 2000
    assert elapsed < 1.0
