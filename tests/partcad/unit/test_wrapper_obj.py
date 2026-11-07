#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 'obj' part type: an OBJ mesh read into OCCT faces ('wrapper_obj').

What is read ('parse') and what is made of it ('build') are tested here, in
this process, on files the tests write; and the two cases that used to end the
sandbox or put a face in the wrong place are also tested through PartCAD, the
way a package declaring an 'obj' part reads it.
"""

import asyncio
import importlib.util
import os
import sys

import pytest
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape

import partcad as pc

WRAPPERS = os.path.join(os.path.dirname(pc.__file__), "wrappers")
sys.path.append(WRAPPERS)


def _module():
    spec = importlib.util.spec_from_file_location("wrapper_obj_under_test", os.path.join(WRAPPERS, "wrapper_obj.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper_obj = _module()


def _parse(text):
    return wrapper_obj.parse(text.splitlines(keepends=True))


def _faces(shape):
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, found)
    return found.Extent()


def _area(shape):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props.Mass()


TRIANGLE = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]

# A quad with one corner lifted off the plane of the other three.
NON_PLANAR_QUAD = """# one non-planar quad
v 0 0 0
v 1 0 0
v 1 1 1
v 0 1 0
f 1 2 3 4
"""


# --- Negative indices ------------------------------------------------------


def test_negative_index_counts_back_from_the_vertices_defined_so_far():
    vertices, faces = _parse("v 9 9 9\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n")
    assert [vertices[i] for i in faces[0]] == TRIANGLE


def test_negative_index_ignores_vertices_defined_after_the_face():
    vertices, faces = _parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\nv 5 5 5\nv 6 6 6\n")
    assert [vertices[i] for i in faces[0]] == TRIANGLE


def test_negative_indices_of_successive_faces_each_count_from_their_own_line():
    vertices, faces = _parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\nv 0 0 1\nf -4 -3 -1\n")
    assert faces == [[0, 1, 2], [0, 1, 3]]


def test_negative_index_reaching_before_the_first_vertex_is_named():
    with pytest.raises(wrapper_obj.ObjError, match=r"line 3: .*vertex -3.*only 2 vertices are defined before it"):
        _parse("v 0 0 0\nv 1 0 0\nf -3 -2 -1\nv 0 1 0\n")


# --- Face forms ------------------------------------------------------------


@pytest.mark.parametrize(
    "face",
    ["f 1 2 3", "f 1/1 2/2 3/3", "f 1/1/1 2/2/1 3/3/1", "f 1//1 2//1 3//1", "f -3/-3/-1 -2/-2/-1 -1/-1/-1"],
)
def test_face_forms_name_the_same_vertices(face):
    text = "v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\n" + face + "\n"
    vertices, faces = _parse(text)
    assert vertices == TRIANGLE
    assert faces == [[0, 1, 2]]


def test_texture_and_normal_lines_are_not_vertices():
    vertices, _ = _parse("v 0 0 0\nvt 0.5 0.5\nvn 0 0 1\nvp 0.2\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    assert vertices == TRIANGLE


# --- Comments and whitespace -----------------------------------------------


def test_trailing_comments_are_ignored():
    vertices, faces = _parse("v 0 0 0 # origin\nv 1 0 0#x\nv 0 1 0\nf 1 2 3 # the face\n# f 3 2 1\n")
    assert vertices == TRIANGLE
    assert faces == [[0, 1, 2]]


def test_any_whitespace_separates_fields():
    vertices, faces = _parse("v\t0 0 0\n   v  1\t0  0   \n\tv 0 1 0\r\n\n   \nf\t1  2\t3\r\n")
    assert vertices == TRIANGLE
    assert faces == [[0, 1, 2]]


def test_a_vertex_keeps_xyz_whatever_follows_them():
    # 'w', and the r g b of a vertex colour (MeshLab, ZBrush, Open3D).
    vertices, _ = _parse("v 0 0 0 1\nv 1 0 0 1 0 0\nv 0 1 0 0.2 0.4 0.6\nf 1 2 3\n")
    assert vertices == TRIANGLE


# --- Groups ----------------------------------------------------------------


def test_objects_and_groups_keep_every_face():
    text = (
        "o first\nv 0 0 0\nv 1 0 0\nv 0 1 0\ng side\nusemtl red\ns 1\nf 1 2 3\n"
        "o second\nv 0 0 1\nv 1 0 1\nv 0 1 1\ng top bottom\nf 4 5 6\n"
    )
    vertices, faces = _parse(text)
    assert len(vertices) == 6
    # Indices are global to the file, not to the object or group.
    assert faces == [[0, 1, 2], [3, 4, 5]]


# --- Undefined vertices ----------------------------------------------------


def test_face_beyond_the_defined_vertices_is_named():
    with pytest.raises(wrapper_obj.ObjError, match=r"line 4: .*vertex 7.*defines only 3"):
        _parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 7\n")


def test_vertex_zero_is_named():
    with pytest.raises(wrapper_obj.ObjError, match=r"line 4: .*vertex 0"):
        _parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2\n")


def test_a_positive_index_may_name_a_vertex_defined_later():
    vertices, faces = _parse("f 1 2 3\nv 0 0 0\nv 1 0 0\nv 0 1 0\n")
    assert [vertices[i] for i in faces[0]] == TRIANGLE


@pytest.mark.parametrize(
    "text, message",
    [
        ("v 0 0\n", r"line 1: a vertex needs x, y and z"),
        ("v 0 zero 0\n", r"line 1: .* is not a vertex"),
        ("v 0 0 0\nv 1 0 0\nf 1 2\n", r"line 3: a face needs at least 3 vertices"),
        ("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 two 3\n", r"line 4: 'two' is not a vertex index"),
    ],
)
def test_malformed_lines_are_named(text, message):
    with pytest.raises(wrapper_obj.ObjError, match=message):
        _parse(text)


# --- Building faces --------------------------------------------------------


def test_a_planar_polygon_stays_one_face():
    vertices, faces = _parse("v 0 0 0\nv 2 0 0\nv 2 1 0\nv 1 2 0\nv 0 1 0\nf 1 2 3 4 5\n")
    compound, skipped = wrapper_obj.build(vertices, faces)
    assert skipped == 0
    assert _faces(compound) == 1
    assert _area(compound) == pytest.approx(3.0)


def test_a_non_planar_quad_becomes_two_triangles():
    vertices, faces = _parse(NON_PLANAR_QUAD)
    compound, skipped = wrapper_obj.build(vertices, faces)
    assert skipped == 0
    assert _faces(compound) == 2
    # Fan from vertex 1: (0,0,0) (1,0,0) (1,1,1), and (0,0,0) (1,1,1) (0,1,0).
    assert _area(compound) == pytest.approx(2 * (2**0.5 / 2))


# An L, listed from the corner beside its notch, with one corner lifted off
# the plane. The fan from that first corner would cover the notch
# (1..2, 1..2), which is outside the L.
CONCAVE = [(2, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0.5), (0, 0, 0), (2, 0, 0)]


def _xy_area(a, b, c):
    return ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2


def test_a_concave_polygon_is_cut_into_triangles_inside_it():
    cut = wrapper_obj.triangles(CONCAVE)
    assert len(cut) == 4
    areas = [_xy_area(*(CONCAVE[i] for i in corners)) for corners in cut]
    # Every triangle turns the polygon's way, and together they cover its 3 square units once.
    assert all(area > 0 for area in areas)
    assert sum(areas) == pytest.approx(3.0)
    for corners in cut:
        x = sum(CONCAVE[i][0] for i in corners) / 3
        y = sum(CONCAVE[i][1] for i in corners) / 3
        assert not (x > 1 and y > 1), "a triangle covers the notch"


def test_a_convex_polygon_is_cut_into_the_fan_from_its_first_corner():
    hexagon = [(2, 0, 0), (1, 2, 0), (-1, 2, 0), (-2, 0, 0.5), (-1, -2, 0), (1, -2, 0)]
    assert wrapper_obj.triangles(hexagon) == [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)]


# A non-planar quad facing each axis, listed both ways round: whichever axis
# the plane is projected along, and whichever way it faces, it is two triangles.
FACING = {
    "x": [(0, 0, 0), (0, 1, 0), (0.01, 1, 1), (0, 0, 1)],
    "y": [(0, 0, 0), (0, 0, 1), (1, 0.01, 1), (1, 0, 0)],
    "z": [(0, 0, 0), (1, 0, 0), (1, 1, 0.01), (0, 1, 0)],
}


@pytest.mark.parametrize("axis", sorted(FACING))
@pytest.mark.parametrize("reverse", [False, True])
def test_a_non_planar_quad_is_cut_whichever_way_it_faces(axis, reverse):
    quad = FACING[axis][::-1] if reverse else FACING[axis]
    cut = wrapper_obj.triangles(quad)
    assert cut is not None and len(cut) == 2
    assert sorted(i for corners in cut for i in corners) == [0, 0, 1, 2, 2, 3]


def test_a_polygon_crossing_itself_is_left_out_and_counted():
    # A bow tie, lifted at one corner so that it is not planar either.
    vertices, faces = _parse("v 0 0 0\nv 1 1 0\nv 1 0 0.5\nv 0 1 0\nf 1 2 3 4\n")
    assert wrapper_obj.triangles([vertices[i] for i in faces[0]]) is None
    compound, skipped = wrapper_obj.build(vertices, faces)
    assert skipped == 1
    assert _faces(compound) == 0


def test_a_polygon_whose_projection_crosses_itself_has_no_triangles():
    # Edges 1-2 and 3-4 cross at (1, 1) in the plane it is closest to; ear
    # clipping alone cut it, the second triangle turning the other way.
    assert wrapper_obj.triangles([(0, 0, 0), (3, 3, 0), (0, 2, 0), (2, 0, 0.1)]) is None


def test_a_concave_non_planar_polygon_builds_inside_its_outline():
    text = "".join("v %g %g %g\n" % point for point in CONCAVE) + "f 1 2 3 4 5 6\n"
    vertices, faces = _parse(text)
    compound, skipped = wrapper_obj.build(vertices, faces)
    assert skipped == 0
    assert _faces(compound) == 4


def test_a_face_occt_cannot_make_is_left_out_and_counted():
    # All three corners the same point: OCCT makes no wire of it, let alone a face.
    vertices, faces = _parse("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 1 1\nf 1 2 3\n")
    compound, skipped = wrapper_obj.build(vertices, faces)
    assert skipped == 1
    assert _faces(compound) == 1


# --- Through PartCAD -------------------------------------------------------


def _part(tmp_path, text):
    (tmp_path / "mesh.obj").write_text(text)
    (tmp_path / "partcad.yaml").write_text("parts:\n  mesh:\n    type: obj\n")
    ctx = pc.Context(str(tmp_path))
    part = ctx.get_part(":mesh")
    assert part is not None
    return asyncio.run(part.get_wrapped(ctx))


def test_non_planar_quad_through_partcad(tmp_path):
    """It used to end the sandbox with SIGSEGV: a null face added to the compound."""
    wrapped = _part(tmp_path, NON_PLANAR_QUAD)
    assert wrapped["metadata"]["measurements"]["bbox"] == pytest.approx([0, 0, 0, 1, 1, 1])


def test_negative_index_through_partcad(tmp_path):
    """'-1' at the end of the file used to be read as the vertex before the last."""
    wrapped = _part(tmp_path, "v 0 0 7\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n")
    assert wrapped["metadata"]["measurements"]["bbox"] == pytest.approx([0, 0, 0, 1, 1, 0])
