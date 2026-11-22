#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The centreline of a routed part (issue #975, design D4 and D5).

'route_path' is pure Python: what it measures is what the feasibility checks and
'pc qual test' go by, so it is tested here against shapes whose answer is known.
"""

import json
import math

import pytest

from partcad.geom import Location
from partcad.route_path import EndFrame, RoutePath, build_knots, canonical_json


def _quarter_circle(radius, vias):
    """From (R, 0, 0) heading +Y to (0, R, 0) heading -X, through 'vias' points on the circle."""
    angles = [math.pi / 2 * (k + 1) / (vias + 1) for k in range(vias)]
    points = [(radius * math.cos(a), radius * math.sin(a), 0.0) for a in angles]
    # The last end's Z points into the part it is connected to, back up the route.
    return [EndFrame((radius, 0, 0), (0, 1, 0), (0, 0, 1))] + points + [EndFrame((0, radius, 0), (1, 0, 0), (0, 0, 1))]


def _on_axis(point, origin, axis):
    offset = [point[i] - origin[i] for i in range(3)]
    along = sum(offset[i] * axis[i] for i in range(3))
    return math.sqrt(sum((offset[i] - along * axis[i]) ** 2 for i in range(3))), along


def test_a_straight_route_is_as_long_as_its_ends_are_apart():
    # Facing each other along X, 3-4-5 apart in the XY plane.
    direction = (0.6, 0.8, 0.0)
    path = RoutePath([EndFrame((0, 0, 0), direction), EndFrame((30, 40, 0), (-0.6, -0.8, 0.0))])
    assert path.length == pytest.approx(50.0, abs=1e-9)
    assert path.min_radius == math.inf
    for point in path.points:
        assert _on_axis(point, (0, 0, 0), direction)[0] < 1e-9


def test_a_lead_runs_along_the_end_axis():
    axis = (0.0, 0.0, 1.0)
    path = RoutePath([EndFrame((0, 0, 0), axis, lead=10), (40, 0, 30), EndFrame((80, 0, 0), (0, 0, 1))])
    lead_end = path.knot_samples[1]
    assert path.arc[lead_end] == pytest.approx(10.0, abs=1e-9)
    for point in path.points[: lead_end + 1]:
        off, along = _on_axis(point, (0, 0, 0), axis)
        assert off < 1e-9
        assert -1e-9 <= along <= 10 + 1e-9
    # And it bends after the lead, not on it.
    assert path.points[lead_end + 5][0] > 1e-6


def test_every_via_point_and_intermediate_end_is_a_sample():
    grommet = EndFrame((50, 0, 50), (1, 0, 0))
    stops = [
        EndFrame((0, 0, 0), (0, 0, 1)),
        (10, 5, 30),
        grommet,
        (70, -5, 40),
        (90, 0, 20),
        EndFrame((100, 0, 0), (0, 0, 1)),
    ]
    path = RoutePath(stops)
    for knot, sample in zip(path.knots, path.knot_samples):
        assert path.points[sample] == knot.point
    sampled = set(path.points)
    for stop in stops:
        assert (stop.origin if isinstance(stop, EndFrame) else tuple(float(v) for v in stop)) in sampled


def test_an_intermediate_end_is_passed_along_its_axis_in_the_direction_of_travel():
    # The grommet's Z points back the way the route comes from: it is passed along -Z.
    grommet = EndFrame((50, 0, 50), (-1, 0, 0))
    path = RoutePath([EndFrame((0, 0, 0), (0, 0, 1)), grommet, EndFrame((100, 0, 0), (0, 0, 1))])
    sample = path.knot_samples[1]
    assert path.tangents[sample] == pytest.approx((1, 0, 0), abs=1e-9)
    # The last end is arrived at along -Z, into the part.
    assert path.tangents[-1] == pytest.approx((0, 0, -1), abs=1e-9)


@pytest.mark.parametrize("vias", [0, 2])
def test_a_quarter_circle_measures_as_one(vias):
    radius = 50.0
    path = RoutePath(_quarter_circle(radius, vias))
    assert path.length == pytest.approx(math.pi * radius / 2, rel=0.02)
    assert path.min_radius == pytest.approx(radius, rel=0.02)


def test_frames_stay_orthonormal_and_start_at_the_first_end_x():
    first = EndFrame((0, 0, 0), (0, 0, 1), (1, 0, 0))
    path = RoutePath([first, (30, 20, 40), (-10, 50, 60), EndFrame((20, 80, 0), (0, 1, 1))])
    x0, _, z0 = path.frames[0]
    assert x0 == pytest.approx(first.x, abs=1e-12)
    assert z0 == pytest.approx(first.z, abs=1e-12)
    for (x, y, z), tangent in zip(path.frames, path.tangents):
        for a, b in ((x, y), (y, z), (z, x)):
            assert abs(sum(a[i] * b[i] for i in range(3))) < 1e-9
        for a in (x, y, z):
            assert abs(math.sqrt(sum(v * v for v in a)) - 1) < 1e-9
        assert z == pytest.approx(tangent, abs=1e-12)


def test_a_straight_route_never_approaches_itself():
    path = RoutePath([EndFrame((0, 0, 0), (1, 0, 0)), EndFrame((500, 0, 0), (-1, 0, 0))])
    assert path.closest_approach(50.0) == (math.inf, None, None)


def test_a_hairpin_approaches_itself_by_its_gap():
    # Two 100 mm leads, 10 mm apart, joined by a U-turn.
    path = RoutePath([EndFrame((0, 0, 0), (1, 0, 0), lead=100), EndFrame((0, 10, 0), (1, 0, 0), lead=100)])
    distance, i, j = path.closest_approach(30.0)
    assert distance == pytest.approx(10.0, abs=1e-9)
    assert path.points[i][1] == pytest.approx(0, abs=1e-9) and path.points[j][1] == pytest.approx(10, abs=1e-9)
    # Further than the gap is not looked at.
    assert path.closest_approach(9.0)[0] == math.inf


def test_an_end_frame_is_read_off_a_location():
    location = Location((1, 2, 3), (1, 0, 0), 90)
    end = EndFrame.from_location(location, lead=5)
    assert end.origin == pytest.approx((1, 2, 3))
    assert end.z == pytest.approx((0, -1, 0), abs=1e-12)
    assert end.x == pytest.approx((1, 0, 0), abs=1e-12)
    assert end.lead == 5


def test_a_route_needs_ends_at_both_extremes():
    with pytest.raises(ValueError, match="two or more ends"):
        build_knots([EndFrame((0, 0, 0), (0, 0, 1)), (1, 2, 3)])
    with pytest.raises(ValueError, match="starts and finishes at an end"):
        build_knots([(5, 5, 5), EndFrame((0, 0, 0), (0, 0, 1)), EndFrame((9, 0, 0), (0, 0, 1))])


# -- The canonical form (D5) ----------------------------------------------------


def _route(dx=0.0):
    return [EndFrame((dx, 0, 0), (0, 0, 1), lead=10), (40.25, 10, 60), EndFrame((80, 0, 0), (0, 0, 1), lead=10)]


def test_equal_routes_are_byte_identical():
    assert canonical_json(_route()) == canonical_json(_route())
    # Built separately, from equal numbers spelled differently.
    other = [EndFrame([0, 0, 0], [0, 0, 2], lead=10.0), [40.25, 10.0, 60.0], EndFrame([80, 0, 0], [0, 0, 1], lead=10)]
    assert canonical_json(other) == canonical_json(_route())


def test_a_micrometre_move_of_an_end_changes_the_route():
    assert canonical_json(_route(0.001)) != canonical_json(_route())


def test_jitter_below_the_rounding_does_not():
    assert canonical_json(_route(1e-8)) == canonical_json(_route())
    assert canonical_json(_route(-3e-8)) == canonical_json(_route())


def test_the_canonical_form_is_sorted_and_rounded():
    text = canonical_json(_route())
    assert text.startswith('{"ends":')
    assert "-0.0," not in text and "-0.0]" not in text
    document = json.loads(text)
    for point in document["path"]["points"]:
        for value in point:
            assert round(value, 6) == value


def test_each_end_carries_the_via_points_on_the_way_to_it():
    """The JSON mirrors the YAML (D12): 'via' is listed on the end it leads to."""
    grommet = EndFrame((50, 0, 50), (1, 0, 0))
    stops = [
        EndFrame((0, 0, 0), (0, 0, 1)),
        (10, 5, 30),
        grommet,
        (70, -5, 40),
        (90, 0, 20),
        EndFrame((100, 0, 0), (0, 0, 1)),
    ]
    document = json.loads(canonical_json(stops))
    assert [end["via"] for end in document["ends"]] == [[], [[10, 5, 30]], [[70, -5, 40], [90, 0, 20]]]
    assert document["ends"][1]["origin"] == [50, 0, 50]
    path = document["path"]
    assert len(path["points"]) == len(path["z"]) == len(path["x"])
    assert [path["points"][k] for k in path["knots"]][2] == [50, 0, 50]
