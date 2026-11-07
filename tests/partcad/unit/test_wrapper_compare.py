#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How far one model's surface is from another's, measured where OCCT lives.

'wrappers/wrapper_compare.py' is the sandbox half of 'pc compare
--surface-distance'. What is pinned here is the measurement against real
geometry whose answer is known by hand: a box against itself is nowhere apart,
a box grown by a millimetre on every side is a millimetre out everywhere --
its corners included, which is what measuring a vertex along each of its faces'
normals rather than along their average is for -- and a box shrunk by one is a
millimetre in on its faces and further at its rim, where no normal meets it and
the nearest point answers instead.

And the choice of points: every vertex, and no two other points closer than the
spacing, with nowhere on the surface further than about a spacing from one.
"""

import math
import os
import sys

import pytest
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.gp import gp_Pnt
from OCP.Poly import Poly_Array1OfTriangle, Poly_Triangle, Poly_Triangulation
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TopoDS import TopoDS_Face

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_compare  # noqa: E402


def _box(x0, y0, z0, x1, y1, z1):
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _reference():
    return _box(0, 0, 0, 10, 20, 30)


def _mesh_of(shape, deflection=0.05):
    """The same surface as one face that is a mesh and nothing else: what an STL part is."""
    BRepMesh_IncrementalMesh(shape, deflection, False, 0.2, True)
    triangles = []
    for face in wrapper_compare._faces(shape):
        triangles += [corners for corners, _normal in wrapper_compare._triangles(face)]
    points = TColgp_Array1OfPnt(1, 3 * len(triangles))
    indices = Poly_Array1OfTriangle(1, len(triangles))
    for i, corners in enumerate(triangles):
        for j, corner in enumerate(corners):
            points.SetValue(3 * i + j + 1, gp_Pnt(*corner))
        indices.SetValue(i + 1, Poly_Triangle(3 * i + 1, 3 * i + 2, 3 * i + 3))
    face = TopoDS_Face()
    BRep_Builder().MakeFace(face, Poly_Triangulation(points, indices))
    return face


# --- choosing the points ----------------------------------------------------------


def test_every_vertex_is_measured_and_no_two_other_points_are_closer_than_the_spacing():
    """Every vertex is a sample however close to another; every other sample keeps the spacing from all of them."""
    spacing = 2.0
    samples, area = wrapper_compare.sample(_reference(), spacing)
    assert area == pytest.approx(2 * (10 * 20 + 20 * 30 + 10 * 30))
    kinds = [item.kind for item in samples]
    assert kinds.count("vertex") == 8
    # 4 + 9 + 14 points inside each of the box's twelve edges, four of each.
    assert kinds.count("edge") == 4 * (4 + 9 + 14)
    points = [item.point for item in samples]
    for i, item in enumerate(samples):
        if item.kind == "vertex":
            continue
        for j, other in enumerate(points):
            if i != j:
                assert math.dist(item.point, other) >= spacing * (1 - 1e-6), (item.point, other)


def test_nowhere_on_the_surface_is_much_further_than_the_spacing_from_a_point():
    """Nothing much larger than the spacing can hide between two samples."""
    spacing = 2.0
    samples, _area = wrapper_compare.sample(_reference(), spacing)
    points = [item.point for item in samples]
    # A lattice over the face x = 10, finer than the spacing.
    for i in range(41):
        for j in range(61):
            probe = (10.0, i * 0.5, j * 0.5)
            assert min(math.dist(probe, point) for point in points) <= 1.6 * spacing, probe


def test_a_point_of_a_face_is_on_the_face_with_its_outward_normal():
    """A face's samples are on the exact surface, not on its triangles, and point out of the solid."""
    sphere = BRepPrimAPI_MakeSphere(10).Shape()
    samples, _area = wrapper_compare.sample(sphere, 1.0)
    faces = [item for item in samples if item.kind == "face"]
    assert faces
    for item in faces:
        # On the sphere itself, not on the triangles it was found through ...
        assert math.dist(item.point, (0, 0, 0)) == pytest.approx(10.0, abs=1e-9)
        # ... and pointing out of it.
        (normal,) = item.normals
        assert sum(n * p / 10.0 for n, p in zip(normal, item.point)) == pytest.approx(1.0, abs=1e-6)


def test_the_spaced_points_look_only_around_themselves():
    """Closer than the spacing is too close; exactly the spacing, or anywhere further, is far enough."""
    spaced = wrapper_compare.Spaced(1.0)
    spaced.add((0.0, 0.0, 0.0))
    assert not spaced.far((0.5, 0.5, 0.0))
    # Exactly one spacing apart is far enough: a lattice puts points there.
    assert spaced.far((1.0, 0.0, 0.0))
    assert spaced.far((0.0, -1.0, 0.0))
    assert spaced.far((5.0, 5.0, 5.0))


def test_a_spacing_that_would_take_too_many_points_is_refused_saying_which_would_do():
    """Too fine a spacing is refused before any point is taken, naming one that would do."""
    with pytest.raises(ValueError, match=r"measure them at least [0-9.]+ mm apart"):
        wrapper_compare.sample(_reference(), 0.001)


def test_a_model_with_no_surface_has_nothing_to_measure_from():
    """A vertex has no surface to sample, and a spacing of nothing is no spacing."""
    vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 0)).Vertex()
    with pytest.raises(ValueError, match="no surface"):
        wrapper_compare.sample(vertex, 1.0)
    with pytest.raises(ValueError, match="positive length"):
        wrapper_compare.sample(_reference(), 0.0)


# --- measuring along the normals ------------------------------------------------


def test_a_model_is_nowhere_apart_from_itself():
    """Every sample measured along a normal, at no distance, and none beyond an allowance of nothing."""
    result = wrapper_compare.surface_distance(_reference(), _reference(), 2.0, allowance=0.0)
    assert result["measured"] == sum(result["points"].values())
    assert result["missed"] == 0
    assert result["nearest"] == 0
    assert result["distance"]["maxAbs"] == 0.0
    assert result["beyond"] == 0


def test_a_grown_box_is_as_far_out_at_its_corners_as_on_its_faces():
    """A corner is measured along each of its faces' normals, not along their average, which would say 1.7 mm."""
    result = wrapper_compare.surface_distance(_reference(), _box(-1, -1, -1, 11, 21, 31), 2.0)
    distance = result["distance"]
    assert distance["min"] == pytest.approx(1.0)
    assert distance["max"] == pytest.approx(1.0)
    assert result["nearest"] == 0
    assert {entry["on"] for entry in result["worst"]} <= {"vertex", "edge", "face"}
    assert result["beyond"] is None  # no allowance was given


def test_a_smaller_model_is_inside_and_its_rim_is_measured_to_its_nearest_point():
    """A millimetre in on the faces; at the rim no normal meets the smaller box, and its corners are sqrt(3) away."""
    result = wrapper_compare.surface_distance(_box(-1, -1, -1, 11, 21, 31), _reference(), 2.0, worst=3)
    distance = result["distance"]
    assert distance["max"] == pytest.approx(-1.0)
    # A corner of the larger box is a millimetre from each face of the smaller.
    assert distance["min"] == pytest.approx(-math.sqrt(3.0))
    assert result["nearest"] > 0
    assert result["missed"] == 0
    assert [entry["how"] for entry in result["worst"]] == ["nearest"] * 3
    assert [entry["on"] for entry in result["worst"]] == ["vertex"] * 3


def test_a_wider_cylinder_is_out_on_its_side_and_level_on_its_ends():
    """Half a millimetre out on the side, and level on the ends the two cylinders share."""
    result = wrapper_compare.surface_distance(
        BRepPrimAPI_MakeCylinder(5, 20).Shape(), BRepPrimAPI_MakeCylinder(5.5, 20).Shape(), 1.0
    )
    assert result["distance"]["max"] == pytest.approx(0.5)
    assert result["distance"]["min"] == pytest.approx(0.0, abs=1e-6)


def test_the_allowance_counts_the_points_further_apart_than_it():
    """Every point is beyond an allowance tighter than the distance, and none beyond a looser one."""
    grown = _box(-1, -1, -1, 11, 21, 31)
    tight = wrapper_compare.surface_distance(_reference(), grown, 2.0, allowance=0.5)
    loose = wrapper_compare.surface_distance(_reference(), grown, 2.0, allowance=1.5)
    assert tight["beyond"] == tight["measured"]
    assert loose["beyond"] == 0
    assert tight["allowance"] == 0.5


def test_a_mesh_on_either_side_measures_as_the_exact_shape_does():
    """A face that is only a mesh is sampled by its triangles and ray cast through its grid, with the exact shape's
    answer.
    """
    grown = _box(-1, -1, -1, 11, 21, 31)
    to_mesh = wrapper_compare.surface_distance(_reference(), _mesh_of(grown), 2.0)
    from_mesh = wrapper_compare.surface_distance(_mesh_of(_reference()), grown, 2.0)
    for result in (to_mesh, from_mesh):
        assert result["distance"]["min"] == pytest.approx(1.0)
        assert result["distance"]["max"] == pytest.approx(1.0)
        assert result["missed"] == 0
    # A face that is only a mesh has no vertices or edges of its own to measure.
    assert from_mesh["points"]["vertex"] == 0
    assert from_mesh["points"]["face"] > 0


def test_a_smaller_mesh_has_its_rim_measured_to_its_nearest_triangle():
    """The rim of a larger reference is measured to the nearest triangle, as to the nearest point of a surface."""
    result = wrapper_compare.surface_distance(_box(-1, -1, -1, 11, 21, 31), _mesh_of(_reference()), 2.0)
    assert result["distance"]["min"] == pytest.approx(-math.sqrt(3.0))
    assert result["nearest"] > 0
    assert result["missed"] == 0


def test_the_nearest_triangle_is_the_nearest_one():
    """The grid search finds what checking every triangle finds, from inside, outside and far off the mesh."""
    mesh = _mesh_of(BRepPrimAPI_MakeSphere(5).Shape(), 0.5)
    triangles = [corners for corners, _normal in wrapper_compare._triangles(mesh)]
    grid = wrapper_compare.Triangles(triangles)
    for probe in [(0, 0, 0), (7, 1, -2), (-3, 9, 4), (0.5, 0.5, 4.9), (20, -20, 3)]:
        found, _at = grid.nearest(probe)
        expected = min(math.dist(probe, wrapper_compare._closest_on_triangle(probe, c)) for c in triangles)
        assert found == pytest.approx(expected, abs=1e-12), probe


def test_a_request_is_dispatched_by_its_operation():
    """'surface' is measured, and any other operation is refused."""
    request = {"operation": "surface", "reference": _reference(), "current": _reference(), "spacing": 5}
    assert wrapper_compare.process(request)["distance"]["maxAbs"] == 0.0
    with pytest.raises(ValueError, match="Unknown compare operation"):
        wrapper_compare.process({"operation": "volume"})
