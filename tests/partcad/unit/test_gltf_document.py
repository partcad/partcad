#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD's glTF reader ('wrappers/gltf_document.py') and the bodies a mesh is made into ('wrappers/mesh_brep.py').

The files are small glTF documents written here, each saying the one thing a
test is about; what a real exporter writes is in 'test_part_gltf.py'.
"""

import base64
import json
import os
import sys
from collections import Counter

import numpy as np
import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import gltf_document  # noqa: E402
import mesh_brep  # noqa: E402

FLOAT, SHORT, UNSIGNED_SHORT = 5126, 5122, 5123


def _gltf(tmp_path, document, blobs=(), name="model.gltf"):
    """A '.gltf' with every blob in one 'data:' buffer, each a buffer view in order."""
    data = b""
    views = []
    for blob in blobs:
        views.append({"buffer": 0, "byteOffset": len(data), "byteLength": len(blob)})
        data += blob + b"\0" * (-len(blob) % 4)
    document = {"asset": {"version": "2.0"}, **document}
    if blobs:
        uri = "data:application/octet-stream;base64," + base64.b64encode(data).decode()
        document["buffers"] = [{"uri": uri, "byteLength": len(data)}]
        document["bufferViews"] = views
    path = tmp_path / name
    path.write_text(json.dumps(document))
    return path


def _triangle_file(tmp_path, mode=4, indices=None, **document):
    """A file of one mesh of four vertices, a unit square in X and Y, drawn as 'mode' says."""
    positions = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype="<f4")
    blobs = [positions.tobytes()]
    accessors = [{"bufferView": 0, "componentType": FLOAT, "count": 4, "type": "VEC3"}]
    primitive = {"attributes": {"POSITION": 0}, "mode": mode}
    if indices is not None:
        blobs.append(np.asarray(indices, dtype="<u2").tobytes())
        accessors.append({"bufferView": 1, "componentType": UNSIGNED_SHORT, "count": len(indices), "type": "SCALAR"})
        primitive["indices"] = 1
    content = {
        "accessors": accessors,
        "meshes": [{"primitives": [primitive]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        **document,
    }
    return _gltf(tmp_path, content, blobs)


def test_a_required_extension_partcad_does_not_read_is_refused_by_name(tmp_path):
    path = _triangle_file(tmp_path, extensionsRequired=["EXT_some_future_compression", "KHR_texture_transform"])
    with pytest.raises(gltf_document.UnsupportedExtension, match="'EXT_some_future_compression'"):
        gltf_document.Document(path)


def test_a_required_extension_that_only_changes_how_it_looks_is_read_without_it(tmp_path):
    path = _triangle_file(
        tmp_path, indices=[0, 1, 2], extensionsRequired=["KHR_texture_transform", "KHR_materials_unlit"]
    )
    document = gltf_document.Document(path)
    assert len(document.primitives(0)[0].triangles) == 1


def test_every_materials_extension_is_appearance_and_a_name_that_is_no_string_is_no_extension(tmp_path):
    # 'KHR_materials_diffuse_roughness' is not in the list 'APPEARANCE' was
    # written with, and is a material all the same; a list entry that is not a
    # name names nothing, and is not an extension the file could be refused for.
    path = _triangle_file(
        tmp_path, indices=[0, 1, 2], extensionsRequired=["KHR_materials_diffuse_roughness", {"not": "a name"}, 7]
    )
    document = gltf_document.Document(path)
    assert len(document.primitives(0)[0].triangles) == 1


@pytest.mark.parametrize("version", ["1.0", None])
def test_anything_but_gltf_2_is_refused(tmp_path, version):
    asset = {"version": version} if version else {}
    path = tmp_path / "old.gltf"
    path.write_text(json.dumps({"asset": asset}))
    with pytest.raises(gltf_document.GltfError, match="PartCAD reads glTF 2.0"):
        gltf_document.Document(path)


def test_a_glb_is_read_whatever_it_is_called_and_written_back_alike(tmp_path):
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 3}],
        "nodes": [{"name": "only"}],
        "scenes": [{"nodes": [0]}],
    }
    path = tmp_path / "binary.gltf"
    path.write_bytes(gltf_document.write_glb(document, b"\1\2\3"))
    read = gltf_document.Document(path)
    assert read.json == document
    assert read.buffer(0)[:3] == b"\1\2\3"


@pytest.mark.parametrize(
    "mode, indices, triangles",
    [
        (4, [0, 1, 2, 0, 2, 3], [[0, 1, 2], [0, 2, 3]]),
        # A strip turns every other triangle, so that all face the same way
        # (glTF 2.0, section 3.7.2.1: v_i, v_(i + 1 + i % 2), v_(i + 2 - i % 2)).
        (5, [0, 1, 3, 2], [[0, 1, 3], [1, 2, 3]]),
        # A fan is every triangle around the first vertex.
        (6, [0, 1, 2, 3], [[1, 2, 0], [2, 3, 0]]),
    ],
)
def test_triangle_lists_strips_and_fans(tmp_path, mode, indices, triangles):
    document = gltf_document.Document(_triangle_file(tmp_path, mode, indices))
    assert document.primitives(0)[0].triangles.tolist() == triangles


@pytest.mark.parametrize("mode, kind", [(0, "point primitives"), (1, "line primitives"), (3, "line primitives")])
def test_points_and_lines_are_counted_not_read(tmp_path, mode, kind):
    document = gltf_document.Document(_triangle_file(tmp_path, mode))
    assert document.primitives(0) == []
    assert document.dropped == Counter({kind: 1})
    assert gltf_document.warnings_of(document.dropped) == ["Not read, since a shape does not hold them: 1 %s" % kind]


def test_a_mesh_without_indices_is_its_vertices_in_threes(tmp_path):
    document = gltf_document.Document(_triangle_file(tmp_path))
    assert document.primitives(0)[0].triangles.tolist() == [[0, 1, 2]]


def test_a_normalized_strided_and_sparse_accessor(tmp_path):
    # Two VEC3 of normalized shorts, 8 bytes apart, the second replaced by a
    # sparse entry: what the accessor stands for is the floats.
    base = np.array([[32767, 0, -32767, 0], [0, 0, 0, 0]], dtype="<i2").tobytes()
    where = np.array([1], dtype="<u2").tobytes()
    values = np.array([[0, 16384, 0]], dtype="<i2").tobytes()
    content = {
        "accessors": [
            {
                "bufferView": 0,
                "componentType": SHORT,
                "normalized": True,
                "count": 2,
                "type": "VEC3",
                "sparse": {
                    "count": 1,
                    "indices": {"bufferView": 1, "componentType": UNSIGNED_SHORT},
                    "values": {"bufferView": 2},
                },
            }
        ],
    }
    path = _gltf(tmp_path, content, [base, where, values])
    document = gltf_document.Document(path)
    document.json["bufferViews"][0]["byteStride"] = 8
    assert np.allclose(document.accessor(0), [[1.0, 0.0, -1.0], [0.0, 16384 / 32767, 0.0]])


def test_a_buffer_beside_the_file_that_is_not_there_is_named(tmp_path):
    path = tmp_path / "model.gltf"
    path.write_text(json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "mesh%20data.bin", "byteLength": 4}]}))
    with pytest.raises(gltf_document.GltfError, match="'mesh data.bin'"):
        gltf_document.Document(path).buffer(0)


def test_a_buffer_outside_the_file_s_directory_is_not_read(tmp_path):
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"\1" * 64)
    inner = tmp_path / "package"
    inner.mkdir()
    uris = ["..%2Fsecret.bin", "../secret.bin", str(secret)]
    path = inner / "model.gltf"
    path.write_text(json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": u, "byteLength": 4} for u in uris]}))
    document = gltf_document.Document(path)
    for index in range(len(uris)):
        with pytest.raises(gltf_document.GltfError, match="outside the directory the file is in"):
            document.buffer(index)


def test_a_symbolic_link_does_not_lead_a_buffer_out_of_the_file_s_directory(tmp_path):
    (tmp_path / "secret.bin").write_bytes(b"\1" * 64)
    inner = tmp_path / "package"
    inner.mkdir()
    try:
        os.symlink(tmp_path / "secret.bin", inner / "mesh.bin")
    except (OSError, NotImplementedError):
        pytest.skip("No symbolic links here")
    path = inner / "model.gltf"
    path.write_text(json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "mesh.bin", "byteLength": 4}]}))
    with pytest.raises(gltf_document.GltfError, match="outside the directory the file is in"):
        gltf_document.Document(path).buffer(0)


def test_a_draco_primitive_says_what_decodes_it_when_nothing_does(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "DracoPy", None)
    content = {
        "extensionsUsed": ["KHR_draco_mesh_compression"],
        "accessors": [{"componentType": FLOAT, "count": 3, "type": "VEC3"}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "extensions": {"KHR_draco_mesh_compression": {"bufferView": 0, "attributes": {"POSITION": 0}}},
                    }
                ]
            }
        ],
    }
    document = gltf_document.Document(_gltf(tmp_path, content, [b"\0" * 8]))
    with pytest.raises(gltf_document.GltfError, match="DracoPy"):
        document.primitives(0)


def test_a_hidden_node_and_a_skin_are_counted(tmp_path):
    path = _triangle_file(tmp_path)
    document = json.loads(path.read_text())
    document["nodes"] = [
        {"mesh": 0, "extensions": {"KHR_node_visibility": {"visible": False}}},
        {"mesh": 0, "skin": 0},
    ]
    document["scenes"] = [{"nodes": [0, 1]}]
    path.write_text(json.dumps(document))
    read = gltf_document.Document(path)
    assert [node.index for node in read.roots()] == [1]
    assert read.dropped == Counter({"hidden nodes": 1, gltf_document.SKINNED: 1})


def test_a_file_with_no_scenes_shows_every_node_that_is_no_child(tmp_path):
    path = _triangle_file(tmp_path)
    document = json.loads(path.read_text())
    del document["scenes"]
    document["nodes"] = [{"children": [1]}, {"mesh": 0}, {"mesh": 0, "translation": [5, 0, 0]}]
    path.write_text(json.dumps(document))
    placed = gltf_document.Document(path).placed_meshes()
    assert sorted(node.index for node, _world in placed) == [1, 2]


def test_a_node_s_matrix_is_read_column_by_column_and_trs_scale_first():
    matrix = np.arange(16, dtype=float).tolist()
    assert gltf_document.local_matrix({"matrix": matrix})[0].tolist() == [0.0, 4.0, 8.0, 12.0]
    half_turn_about_z = [0.0, 0.0, 1.0, 0.0]
    m = gltf_document.local_matrix({"translation": [1, 2, 3], "rotation": half_turn_about_z, "scale": [2, 1, 1]})
    assert np.allclose(m @ [1, 0, 0, 1], [-1, 2, 3, 1])


def test_a_transform_is_a_rotation_a_translation_and_what_neither_can_say():
    rotation = gltf_document.trs_matrix((0, 0, 0), (0, 0, np.sin(np.pi / 6), np.cos(np.pi / 6)), (1, 1, 1))[:3, :3]
    matrix = np.eye(4)
    matrix[:3, :3] = rotation @ np.diag([2.0, 1.0, -1.0])  # stretched, and mirrored
    matrix[:3, 3] = [1, 2, 3]
    turn, translation, stretch = gltf_document.decompose(matrix)
    assert np.isclose(np.linalg.det(turn), 1.0)
    assert np.allclose(turn @ stretch, matrix[:3, :3])
    assert np.allclose(stretch, stretch.T)
    assert translation.tolist() == [1, 2, 3]
    axis, angle = gltf_document.axis_angle(rotation)
    assert np.allclose(axis, [0, 0, 1]) and angle == pytest.approx(60.0)


def test_gltf_s_up_is_partcad_s_z_and_its_metres_partcad_s_millimetres():
    assert np.allclose(gltf_document.TO_PARTCAD @ [0, 1, 0, 1], [0, 0, 1000, 1])
    assert np.allclose(gltf_document.TO_PARTCAD @ [0, 0, 1, 1], [0, -1000, 0, 1])


def test_a_material_states_only_what_it_says(tmp_path):
    content = {
        "materials": [
            {
                "name": "Paint",
                "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.25, 0, 0.5], "roughnessFactor": 0.3},
                "extras": {"partcad": {"color": "//pkg:paint"}},
            },
            # A texture and nothing else: no colour of its own, and glTF's
            # defaults of 1 are not what it says either.
            {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
            {
                "extensions": {
                    "KHR_materials_pbrSpecularGlossiness": {"diffuseFactor": [1, 1, 1, 1], "glossinessFactor": 0.75}
                }
            },
        ]
    }
    document = gltf_document.Document(_gltf(tmp_path, content))
    paint, textured, glossy = (document.material(index) for index in range(3))
    assert (paint.name, paint.rgba, paint.roughness, paint.metallic) == ("Paint", (0.5, 0.25, 0.0, 0.5), 0.3, None)
    assert paint.extras == {"partcad": {"color": "//pkg:paint"}}
    assert (textured.name, textured.rgba, textured.roughness, textured.metallic) == (None, None, None, None)
    assert (glossy.rgba, glossy.roughness) == ((1.0, 1.0, 1.0, 1.0), 0.25)
    assert document.material(None) is None


# --------------------------------------------------------------------------- #
# Bodies out of triangles                                                     #
# --------------------------------------------------------------------------- #


def _volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _box(size, at, inside_out=False):
    """A box's triangles, a vertex per corner of each - as a mesh drawn for its normals is - facing out."""
    lo, hi = np.asarray(at) - np.asarray(size) / 2, np.asarray(at) + np.asarray(size) / 2
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    triangles = np.array(
        [
            [0, 1, 3],
            [0, 3, 2],
            [4, 6, 7],
            [4, 7, 5],
            [0, 4, 5],
            [0, 5, 1],
            [2, 3, 7],
            [2, 7, 6],
            [0, 2, 6],
            [0, 6, 4],
            [1, 5, 7],
            [1, 7, 3],
        ]
    )
    if inside_out:
        triangles = triangles[:, [0, 2, 1]]
    return corners[triangles].reshape(-1, 3)


def test_a_mesh_of_several_closed_pieces_is_a_solid_each_facing_out():
    from OCP.BRepCheck import BRepCheck_Analyzer

    rng = np.random.default_rng(3)
    points = np.vstack(
        [_box([10, 20, 30], [100, 0, 0]), _box([10, 10, 10], [0, 50, 0]), _box([5, 5, 5], [0, 0, 80], True)]
    )
    triangles = np.arange(len(points)).reshape(-1, 3)
    # Some triangles turned the wrong way, which the pieces have to agree on again.
    turned = rng.random(len(triangles)) < 0.3
    triangles[turned] = triangles[turned][:, [0, 2, 1]]
    # And one that bounds nothing.
    points = np.vstack([points, [[0, 0, 0], [1, 0, 0], [2, 0, 0]]])
    triangles = np.vstack([triangles, [[len(points) - 3, len(points) - 2, len(points) - 1]]])

    bodies, dropped = mesh_brep.bodies(points, triangles)

    assert dropped == 1
    assert sorted(round(_volume(body.shape), 6) for body in bodies) == [125.0, 1000.0, 6000.0]
    assert all(body.closed and body.shape.ShapeType().name == "TopAbs_SOLID" for body in bodies)
    assert all(BRepCheck_Analyzer(body.shape).IsValid() for body in bodies)
    # A face per triangle, and each face knows its triangle.
    assert sorted(len(body.faces) for body in bodies) == [12, 12, 12]
    assert sorted(int(t) for body in bodies for t in body.triangles) == list(range(36))


def test_an_open_piece_is_a_shell():
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    bodies, dropped = mesh_brep.bodies(points, np.array([[0, 1, 2], [0, 2, 3]]))
    assert dropped == 0
    assert [(body.closed, body.shape.ShapeType().name) for body in bodies] == [(False, "TopAbs_SHELL")]


def test_a_mesh_of_many_pieces_is_split_in_order():
    """A thousand separate tetrahedra: a piece each, its triangles in the order the mesh has them."""
    tetrahedron = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]])
    count = 1000
    triangles = (tetrahedron[None, :, :] + 4 * np.arange(count)[:, None, None]).reshape(-1, 3)
    # Shuffled, so the pieces are not simply consecutive runs of the list.
    order = np.random.default_rng(5).permutation(len(triangles))
    found = mesh_brep.pieces(triangles[order])
    assert len(found) == count
    assert all(list(piece) == sorted(piece) for piece in found)
    assert sorted(int(t) for piece in found for t in piece) == list(range(len(triangles)))
    assert {tuple(sorted(int(order[t]) // 4 for t in piece)) for piece in found} == {(i,) * 4 for i in range(count)}
