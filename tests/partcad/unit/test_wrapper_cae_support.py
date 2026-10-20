#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for 'wrappers/cae_support.py': ports become faces, faces become a mesh.

The geometry half runs here as it runs in a sandbox, on real OCCT shapes: a
pipe whose ends are drawn by circle sketches, a block with a sketch smaller than
the face it sits on, ports with no sketch at all. The meshing half needs gmsh,
which is an implementation's dependency rather than PartCAD's, so it is skipped
where gmsh cannot be imported.
"""

import ctypes
import json
import math
import os
import signal
import struct
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import cae_support  # noqa: E402

build123d = pytest.importorskip("build123d")


def _disc(radius, at, normal=(0, 0, 1)):
    """A circle sketch, placed the way a port's frame places one."""
    return (build123d.Plane(origin=at, z_dir=normal) * build123d.make_face(build123d.Circle(radius))).wrapped


def _pipe_request():
    """The bore of the example's pipe, with both ends drawn by the bore's circle."""
    return {
        "analysis": "cfd",
        "wrapped": build123d.Cylinder(5, 100).wrapped,
        "boundary": [
            {
                "port": "inlet",
                "location": [[0, 0, -50], [0, 0, 1], 0],
                "sketch": [_disc(5, (0, 0, -50))],
                "load": 0.005,
            },
            {
                "port": "outlet",
                "location": [[0, 0, 50], [0, 0, 1], 0],
                "sketch": [_disc(5, (0, 0, 50))],
                "outlet": True,
            },
        ],
    }


def test_a_sketch_the_size_of_a_face_covers_that_face():
    """The pipe's ends: a circle of the bore's radius is the end face, and only it."""
    request = _pipe_request()
    assert cae_support.prepare(request) == []
    inlet, outlet = request["boundary"]
    assert [face["centroid"][2] for face in inlet["faces"]] == [pytest.approx(-50)]
    assert [face["centroid"][2] for face in outlet["faces"]] == [pytest.approx(50)]
    assert inlet["area"] == pytest.approx(78.5398, rel=1e-4)
    # Outward, which is what an implementation reads a direction off.
    assert inlet["faces"][0]["normal"] == pytest.approx([0, 0, -1])
    # The sketch is consumed: geometry has no business in what comes back.
    assert "sketch" not in inlet


def test_a_sketch_smaller_than_its_face_is_imprinted_on_it():
    """An inlet of 2 mm on a 10 mm face splits that face, and covers the disc alone."""
    request = {
        "wrapped": build123d.Box(10, 10, 10).wrapped,
        "boundary": [{"port": "small", "location": [[0, 0, 5], [0, 0, 1], 0], "sketch": [_disc(2, (0, 0, 5))]}],
    }
    assert cae_support.prepare(request) == []
    assert len(cae_support.faces_of(request["wrapped"])) == 7
    (record,) = request["boundary"]
    assert record["area"] == pytest.approx(12.566, rel=1e-3)
    # The face around the hole has its centroid inside the circle; it is still
    # not covered, which is what testing by area rather than by point is for.
    assert len(record["faces"]) == 1


def test_a_port_with_no_sketch_covers_the_face_it_lies_on():
    """The cantilever's root: a frame in the middle of the end face is that face."""
    request = {
        "wrapped": build123d.Box(100, 10, 10).wrapped,
        "boundary": [
            {"port": "root", "location": [[-50, 0, 0], [0, 0, 1], 0]},
            {"port": "inside", "location": [[0, 0, 0], [0, 0, 1], 0]},
        ],
    }
    assert cae_support.prepare(request) == []
    root, inside = request["boundary"]
    assert [face["centroid"][0] for face in root["faces"]] == [pytest.approx(-50)]
    assert root["area"] == pytest.approx(100)
    # In the material rather than on it: no face, and the implementation decides.
    assert inside["faces"] == [] and inside["area"] == 0


def test_on_an_edge_the_face_the_frame_faces_wins():
    """Two faces meet at an edge; Z out of one of them says which is meant."""
    request = {
        "wrapped": build123d.Box(10, 10, 10).wrapped,
        # Z turned onto -X, so the frame faces along the X face's normal.
        "boundary": [{"port": "edge", "location": [[5, 0, -5], [0, 1, 0], -90]}],
    }
    cae_support.prepare(request)
    (record,) = request["boundary"]
    assert [face["centroid"][0] for face in record["faces"]] == [pytest.approx(5)]


def test_a_sketch_that_misses_the_part_is_a_warning():
    """A condition that does nothing is said out loud, and nothing is guessed: no surface is near it either."""
    request = {
        "wrapped": build123d.Box(10, 10, 10).wrapped,
        "boundary": [{"port": "off", "location": [[0, 0, 9], [0, 0, 1], 0], "sketch": [_disc(2, (0, 0, 9))]}],
    }
    warnings = cae_support.prepare(request)
    assert len(warnings) == 1 and "'off'" in warnings[0]
    assert request["boundary"][0]["faces"] == []


def _solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    explorer, count = TopExp_Explorer(shape, TopAbs_SOLID), 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def test_a_sketch_on_no_surface_loads_the_surface_near_its_port():
    """A hole's outline over the hole, a sketch beside its face: the surface within 'port_radius' of the port is loaded."""
    request = {
        "wrapped": build123d.Box(10, 10, 10).wrapped,
        # 0.2 mm off the top face; 5 % of 10 mm reaches 0.5 mm, so the top face
        # is loaded over a disc of radius sqrt(0.5^2 - 0.2^2).
        "boundary": [{"port": "hole", "location": [[0, 0, 5.2], [0, 0, 1], 0], "sketch": [_disc(1, (0, 0, 5.2))]}],
    }
    warnings = cae_support.prepare(request)
    assert len(warnings) == 1 and "'hole'" in warnings[0] and "within 0.5 mm" in warnings[0]
    (record,) = request["boundary"]
    assert [face["centroid"][2] for face in record["faces"]] == [pytest.approx(5)]
    assert record["area"] == pytest.approx(math.pi * (0.5**2 - 0.2**2), rel=1e-3)
    # The faces are divided where the sphere meets them, and the solid is not.
    assert _solids(request["wrapped"]) == 1


def test_two_ports_whose_surroundings_overlap_each_load_their_own():
    """Two adjacent gear teeth, as it were: their spheres cross on one face, and each still covers its own disc."""
    request = {
        "wrapped": build123d.Box(10, 10, 10).wrapped,
        "boundary": [
            {"port": "a", "location": [[0, 0, 5.2], [0, 0, 1], 0], "sketch": [_disc(1, (0, 0, 5.2))]},
            {"port": "b", "location": [[0.6, 0, 5.2], [0, 0, 1], 0], "sketch": [_disc(1, (0.6, 0, 5.2))]},
        ],
    }
    warnings = cae_support.prepare(request)
    assert len(warnings) == 2 and all("within 0.5 mm" in warning for warning in warnings)
    disc = math.pi * (0.5**2 - 0.2**2)
    assert [record["area"] for record in request["boundary"]] == [pytest.approx(disc, rel=1e-3)] * 2
    assert _solids(request["wrapped"]) == 1


def test_a_freeform_face_near_the_port_is_loaded_whole():
    """A curve drawn on a freeform face is one a mesher may not mesh, so such a face is not divided."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert

    # The same box with every face a B-spline surface.
    request = {
        "wrapped": BRepBuilderAPI_NurbsConvert(build123d.Box(10, 10, 10).wrapped).Shape(),
        "boundary": [{"port": "hole", "location": [[0, 0, 5.2], [0, 0, 1], 0], "sketch": [_disc(1, (0, 0, 5.2))]}],
    }
    warnings = cae_support.prepare(request)
    assert len(warnings) == 1 and "within 0.5 mm" in warnings[0] and "(100 mm^2)" in warnings[0]
    (record,) = request["boundary"]
    assert [face["centroid"][2] for face in record["faces"]] == [pytest.approx(5)]
    assert record["area"] == pytest.approx(100.0, rel=1e-6)


def test_the_implementation_s_port_radius_is_how_far_that_reaches():
    request = {
        "wrapped": build123d.Box(10, 10, 10).wrapped,
        "port_radius": 0.1,
        "boundary": [{"port": "hole", "location": [[0, 0, 5.2], [0, 0, 1], 0], "sketch": [_disc(1, (0, 0, 5.2))]}],
    }
    cae_support.prepare(request)
    assert request["boundary"][0]["area"] == pytest.approx(math.pi * (1.0**2 - 0.2**2), rel=1e-3)


def test_a_sketch_on_a_face_is_not_widened():
    """Only a sketch that covers nothing falls back: one that covers its face covers that, exactly."""
    request = _pipe_request()
    request["port_radius"] = 0.5
    assert cae_support.prepare(request) == []
    assert request["boundary"][0]["area"] == pytest.approx(78.5398, rel=1e-4)


def test_nothing_to_prepare_is_not_an_error():
    """A request with no boundary is handed on untouched."""
    request = {"wrapped": build123d.Box(1, 1, 1).wrapped}
    assert cae_support.prepare(request) == []


def test_condition_groups_names_a_group_per_record_and_reports_the_empty_ones():
    """What 'mesh()' is handed, and which conditions will do nothing."""
    request = {
        "boundary": [
            {"fix": True, "faces": [{"index": 4}]},
            {"fix": False, "faces": [{"index": 5}]},
            {"fix": True, "faces": []},
        ]
    }
    groups, records, empty = cae_support.condition_groups(request, "fix", "FIX")
    assert groups == {"FIX0": [4]}
    assert records == [request["boundary"][0]]
    assert empty == [request["boundary"][2]]


def test_outer_triangles_of_two_tetrahedra_leave_out_the_shared_face():
    """The face two cells share is inside, and is not drawn."""
    cells = [[0, 1, 2, 3], [1, 2, 3, 4]]
    triangles = cae_support.outer_triangles(cells, 4)
    assert len(triangles) == 6
    assert tuple(sorted((1, 2, 3))) not in {tuple(sorted(t)) for t in triangles}


def test_colours_run_cool_to_hot_and_a_flat_field_is_one_colour():
    """Low is the first stop, high the last; no divide by zero on a uniform field."""
    low, high = cae_support.colours_for([0.0, 1.0])
    assert low[:3] == tuple(round(c * 255) for c in cae_support._RAMP[0])
    assert high[:3] == tuple(round(c * 255) for c in cae_support._RAMP[-1])
    assert len(set(cae_support.colours_for([3.0, 3.0, 3.0]))) == 1


def test_write_glb_is_a_valid_binary_gltf(tmp_path):
    """The header, the two chunks, and accessors that agree with the data."""
    path = tmp_path / "result.glb"
    points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    cae_support.write_glb(str(path), points, [(0, 1, 2), (0, 1, 3)], [0, 1, 2, 3])
    blob = path.read_bytes()
    magic, version, length = struct.unpack("<4sII", blob[:12])
    assert (magic, version, length) == (b"glTF", 2, len(blob))
    json_length, json_kind = struct.unpack("<I4s", blob[12:20])
    assert json_kind == b"JSON"
    document = json.loads(blob[20 : 20 + json_length])
    position, colour, index = document["accessors"]
    assert position["count"] == 4 and colour["count"] == 4 and index["count"] == 6
    # Z-up in, Y-up out: (0, 0, 1) becomes (0, 1, 0).
    assert position["max"] == [1, 1, 0] and position["min"] == [0, 0, -1]


def test_mesh_names_the_groups_it_was_given_and_the_rest(tmp_path):
    """The pipe meshed with its inlet and outlet named and every other surface a wall."""
    pytest.importorskip("gmsh")
    request = _pipe_request()
    cae_support.prepare(request)
    inlet, _, _ = cae_support.condition_groups(request, "load", "inlet")
    outlet, _, _ = cae_support.condition_groups(request, "outlet", "outlet")
    path = str(tmp_path / "pipe.msh")
    mesh = cae_support.mesh(request, {**inlet, **outlet}, size=0.05, rest="wall", files=[path])
    assert set(mesh.groups) == {"inlet0", "outlet0", "wall"}
    assert mesh.unmatched == []
    # Metres: the bore is 100 mm long.
    assert mesh.extent == pytest.approx(0.1)
    assert mesh.coordinates[:, 2].max() == pytest.approx(0.05)
    assert mesh.element_count > 0
    with open(path) as f:
        text = f.read()
    assert '"inlet0"' in text and '"wall"' in text and '"body"' in text


def test_a_second_order_mesh_has_straight_edges():
    """Every mid-side node at the middle of its edge, never moved out onto the bore's curve.

    Moved out, the mid-side nodes of the small elements on a tight curve fold
    them inside out, and the solver refuses the whole mesh.
    """
    pytest.importorskip("gmsh")
    request = _pipe_request()
    cae_support.prepare(request)
    mesh = cae_support.mesh(request, {}, size=0.2, order=2)
    at = {int(tag): k for k, tag in enumerate(mesh.node_tags)}
    # gmsh's 10-node tetrahedron: corners 0-3, then the middle of 0-1, 1-2, 2-0, 3-0, 3-2, 3-1.
    (elements,) = [nodes for kind, _tags, nodes in mesh.volumes if kind == 11]
    edges = [(0, 1), (1, 2), (2, 0), (3, 0), (3, 2), (3, 1)]
    for element in elements:
        xyz = mesh.coordinates[[at[int(tag)] for tag in element]]
        for k, (a, b) in enumerate(edges):
            assert xyz[4 + k] == pytest.approx((xyz[a] + xyz[b]) / 2, abs=1e-9)


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason="no SIGPIPE on this platform")
def test_meshing_leaves_sigpipe_ignored():
    """gmsh resets SIGPIPE to 'kill the process'; meshing must not leave it so.

    Asked of the C library rather than of 'signal.getsignal()', which reports
    what Python last set and so cannot see what gmsh did behind its back. This
    is what killed the whole pytest session, at the next test to write to a
    closed pipe, with exit status 141 and no failing test to point at.
    """
    pytest.importorskip("gmsh")
    libc = ctypes.CDLL(None)
    libc.signal.restype = ctypes.c_void_p
    libc.signal.argtypes = [ctypes.c_int, ctypes.c_void_p]

    def disposition():
        previous = libc.signal(int(signal.SIGPIPE), int(signal.SIG_IGN))
        libc.signal(int(signal.SIGPIPE), previous)
        return previous or 0

    assert disposition() == int(signal.SIG_IGN)
    request = _pipe_request()
    cae_support.prepare(request)
    cae_support.mesh(request, {}, size=0.2, rest="wall")
    assert disposition() == int(signal.SIG_IGN)


def test_points_are_matched_within_a_tolerance_not_by_rounding():
    """A solver's copy of a node, printed to fewer digits, is still that node."""
    targets = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0499999999, 0.0, 0.0)]
    points = [(0.05000004, 0.0, 0.0), (0.0, 0.0, 0.0), (0.3, 0.0, 0.0)]
    assert cae_support.match_points(points, targets, 1e-6) == [2, 0, None]


def test_flow_through_integrates_the_velocity_over_a_group():
    """A uniform 2 m/s through a unit square, oriented by the outward normal."""

    class Mesh:
        node_tags = [1, 2, 3, 4]
        coordinates = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        # Wound so gmsh's own normal points down, against the outward normal.
        groups = {"outlet0": [(1, 3, 2), (1, 4, 3)]}

    def velocity(_k):
        return (0.0, 0.0, 2.0)

    assert cae_support.flow_through(Mesh(), "outlet0", velocity, [0, 0, 1]) == pytest.approx(2.0)
    assert cae_support.flow_through(Mesh(), "outlet0", velocity) == pytest.approx(-2.0)
    assert cae_support.flow_through(Mesh(), "outlet0", lambda _k: None, [0, 0, 1]) == 0.0
    assert cae_support.outward_normal({"faces": [{"normal": None}, {"normal": [0, 0, 1]}]}) == [0, 0, 1]
    assert cae_support.outward_normal({"faces": []}) is None
