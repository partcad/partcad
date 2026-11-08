#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Writes the glTF fixtures beside it that the web's compression extensions, and a scene, are tested with.

Run it from the repository root, with the encoders it needs installed beside
PartCAD's own environment -- the reference encoders, so that what the reader is
tested against is what the tools that make these files write:

    pip install DracoPy==2.2.0 meshopt==0.1.1
    python tests/partcad/unit/data/import_gltf/make_fixtures.py

'meshopt' is a Python binding of meshoptimizer's own encoder (and needs Python
3.12 or newer); 'DracoPy' binds Google's Draco. The files are checked in, so the
tests need neither.

Every box is the one 'box.glb' holds -- build123d's export of a 10 x 20 x 30 mm box
centred at (100, 0, 0) -- stored another way, so each reads back as that box:

- 'box_draco.glb'        KHR_draco_mesh_compression
- 'box_quantized.glb'    KHR_mesh_quantization: 16-bit positions, the node's scale undoing it
- 'box_meshopt.glb'      EXT_meshopt_compression over KHR_mesh_quantization, as gltfpack
                         writes: version 0 attributes, octahedral normals, a triangle
                         stream, and a fallback buffer with no data
- 'box_meshopt_khr.glb'  KHR_meshopt_compression: version 1 attributes, float positions
                         through the exponential filter, an index sequence

and 'scene.glb' is a scene of several, which the tests read both as a part and as
an assembly (see 'test_part_gltf.py' for what each node is expected to become).

'meshopt_vectors.json' is what the boxes do not cover of meshoptimizer's codecs:
streams its encoder wrote - attributes in version 0 and 1 (where its channel
modes and control modes show), every filter, triangles and index sequences -
each with what its own decoder makes of them, for 'test_meshopt_decode.py'.
"""

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "..", "..", "..", "..", "src", "partcad", "wrappers"))

import gltf_document  # noqa: E402

FLOAT, BYTE, SHORT, UNSIGNED_SHORT, UNSIGNED_INT = 5126, 5120, 5122, 5123, 5125


class Writer:
    """A '.glb' put together a buffer view at a time."""

    def __init__(self):
        self.binary = bytearray()
        self.json = {
            "asset": {"version": "2.0", "generator": "PartCAD test fixtures"},
            "bufferViews": [],
            "accessors": [],
        }

    def view(self, data: bytes, **extra) -> int:
        offset = len(self.binary)
        self.binary.extend(data)
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        self.json["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), **extra})
        return len(self.json["bufferViews"]) - 1

    def accessor(self, view, component, count, kind, **extra) -> int:
        accessor = {"componentType": component, "count": count, "type": kind, **extra}
        if view is not None:
            accessor["bufferView"] = view
        self.json["accessors"].append(accessor)
        return len(self.json["accessors"]) - 1

    def save(self, name, **document):
        self.json.update(document)
        self.json["buffers"] = [{"byteLength": len(self.binary)}] + self.json.get("buffers", [])
        with open(os.path.join(HERE, name), "wb") as f:
            f.write(gltf_document.write_glb(self.json, bytes(self.binary)))


def box():
    """'(positions, normals, triangles, node)' of 'box.glb', its six primitives made one."""
    document = gltf_document.Document(os.path.join(HERE, "box.glb"))
    positions, normals, triangles = [], [], []
    for primitive in document.json["meshes"][0]["primitives"]:
        offset = sum(len(p) for p in positions)
        positions.append(document.accessor(primitive["attributes"]["POSITION"]))
        normals.append(document.accessor(primitive["attributes"]["NORMAL"]))
        triangles.append(document.accessor(primitive["indices"]).reshape(-1) + offset)
    node = dict(document.json["nodes"][0])
    return np.vstack(positions), np.vstack(normals), np.concatenate(triangles), node


def bounds(values):
    return {"min": values.min(axis=0).tolist(), "max": values.max(axis=0).tolist()}


def draco():
    import DracoPy

    positions, _normals, triangles, node = box()
    encoded = DracoPy.encode(positions.astype(np.float32), triangles.reshape(-1, 3), quantization_bits=24)
    decoded = DracoPy.decode(encoded)
    w = Writer()
    view = w.view(encoded)
    position = w.accessor(None, FLOAT, len(decoded.points), "VEC3", **bounds(np.asarray(decoded.points)))
    indices = w.accessor(None, UNSIGNED_INT, int(np.asarray(decoded.faces).size), "SCALAR")
    extension = {"bufferView": view, "attributes": {"POSITION": 0}}
    primitive = {
        "attributes": {"POSITION": position},
        "indices": indices,
        "extensions": {"KHR_draco_mesh_compression": extension},
    }
    w.save(
        "box_draco.glb",
        extensionsUsed=["KHR_draco_mesh_compression"],
        extensionsRequired=["KHR_draco_mesh_compression"],
        meshes=[{"primitives": [primitive]}],
        nodes=[{**node, "mesh": 0}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )


# Every corner of the box is a multiple of half a millimetre: stored as that many
# half millimetres, exactly, with the node's scale saying how big one is.
STEP = 0.0005


def quantized_positions(positions):
    steps = np.round(positions / STEP).astype(np.int16)
    assert np.allclose(steps * STEP, positions, atol=1e-9)
    return np.hstack([steps, np.zeros((len(steps), 1), np.int16)])  # padded to 8 bytes


def quantized():
    positions, _normals, triangles, node = box()
    w = Writer()
    view = w.view(quantized_positions(positions).tobytes(), byteStride=8, target=34962)
    position = w.accessor(view, SHORT, len(positions), "VEC3", **bounds(np.round(positions / STEP)))
    indices = w.accessor(
        w.view(triangles.astype("<u2").tobytes(), target=34963), UNSIGNED_SHORT, len(triangles), "SCALAR"
    )
    w.save(
        "box_quantized.glb",
        extensionsUsed=["KHR_mesh_quantization"],
        extensionsRequired=["KHR_mesh_quantization"],
        meshes=[{"primitives": [{"attributes": {"POSITION": position}, "indices": indices}]}],
        nodes=[{**node, "mesh": 0, "scale": [STEP] * 3}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )


def meshopt_view(w, data, count, stride, mode, extension, filter_name="NONE", fallback=None):
    """A buffer view compressed with 'extension', its data in buffer 0 and its stand-in in buffer 1."""
    spec = {"buffer": 0, "byteLength": len(data), "byteStride": stride, "count": count, "mode": mode}
    if filter_name != "NONE":
        spec["filter"] = filter_name
    offset = len(w.binary)
    w.binary.extend(data)
    w.binary.extend(b"\0" * (-len(w.binary) % 4))
    spec["byteOffset"] = offset
    view = {
        "buffer": 1,
        "byteOffset": fallback["length"],
        "byteLength": count * stride,
        "extensions": {extension: spec},
    }
    if mode == "ATTRIBUTES":
        view["byteStride"] = stride
    fallback["length"] += count * stride + (-(count * stride) % 4)
    w.json["bufferViews"].append(view)
    return len(w.json["bufferViews"]) - 1


def meshopt_ext():
    import meshopt

    positions, normals, triangles, node = box()
    name = "EXT_meshopt_compression"
    w = Writer()
    fallback = {"length": 0}
    stored = quantized_positions(positions)
    view = meshopt_view(
        w, meshopt.encode_vertex_buffer_level(stored, 2, 0), len(stored), 8, "ATTRIBUTES", name, fallback=fallback
    )
    position = w.accessor(view, SHORT, len(stored), "VEC3", **bounds(np.round(positions / STEP)))
    unit = np.hstack([normals, np.zeros((len(normals), 1))]).astype(np.float32)
    octahedral = meshopt.encode_filter_oct(unit, 4, 8)
    view = meshopt_view(
        w,
        meshopt.encode_vertex_buffer_level(octahedral, 2, 0),
        len(unit),
        4,
        "ATTRIBUTES",
        name,
        "OCTAHEDRAL",
        fallback,
    )
    normal = w.accessor(view, BYTE, len(unit), "VEC3", normalized=True)
    index_data = meshopt.encode_index_buffer(triangles.astype(np.uint16))
    view = meshopt_view(w, index_data, len(triangles), 2, "TRIANGLES", name, fallback=fallback)
    indices = w.accessor(view, UNSIGNED_SHORT, len(triangles), "SCALAR")
    w.json["buffers"] = [{"byteLength": fallback["length"], "extensions": {name: {"fallback": True}}}]
    w.save(
        "box_meshopt.glb",
        extensionsUsed=["KHR_mesh_quantization", name],
        extensionsRequired=["KHR_mesh_quantization", name],
        meshes=[{"primitives": [{"attributes": {"POSITION": position, "NORMAL": normal}, "indices": indices}]}],
        nodes=[{**node, "mesh": 0, "scale": [STEP] * 3}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )


def meshopt_khr():
    import meshopt

    positions, _normals, triangles, node = box()
    name = "KHR_meshopt_compression"
    w = Writer()
    fallback = {"length": 0}
    exponential = meshopt.encode_filter_exp(positions.astype(np.float32), 23)
    data = meshopt.encode_vertex_buffer_level(exponential, 2, 1)
    view = meshopt_view(w, data, len(positions), 12, "ATTRIBUTES", name, "EXPONENTIAL", fallback)
    position = w.accessor(view, FLOAT, len(positions), "VEC3", **bounds(positions))
    view = meshopt_view(
        w,
        meshopt.encode_index_sequence(triangles.astype(np.uint32)),
        len(triangles),
        4,
        "INDICES",
        name,
        fallback=fallback,
    )
    indices = w.accessor(view, UNSIGNED_INT, len(triangles), "SCALAR")
    w.json["buffers"] = [{"byteLength": fallback["length"], "extensions": {name: {"fallback": True}}}]
    w.save(
        "box_meshopt_khr.glb",
        extensionsUsed=[name],
        extensionsRequired=[name],
        meshes=[{"primitives": [{"attributes": {"POSITION": position}, "indices": indices}]}],
        nodes=[{**node, "mesh": 0}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )


def cube(side):
    """A cube of 'side' metres centred at the origin, as glTF has it: its corners, and 12 triangles facing out."""
    h = side / 2
    corners = np.array([[x, y, z] for x in (-h, h) for y in (-h, h) for z in (-h, h)], dtype=np.float32)
    faces = {
        "-x": [[0, 1, 3], [0, 3, 2]],
        "+x": [[4, 6, 7], [4, 7, 5]],
        "-y": [[0, 4, 5], [0, 5, 1]],
        "+y": [[2, 3, 7], [2, 7, 6]],
        "-z": [[0, 2, 6], [0, 6, 4]],
        "+z": [[1, 5, 7], [1, 7, 3]],
    }
    return corners, faces


def scene():
    """A scene of five nodes and a hidden sixth (see the module docstring and 'test_part_gltf.py')."""
    w = Writer()

    def mesh(corners, triangle_groups):
        position = w.accessor(
            w.view(corners.astype("<f4").tobytes(), target=34962), FLOAT, len(corners), "VEC3", **bounds(corners)
        )
        primitives = []
        for triangles, material in triangle_groups:
            flat = np.asarray(triangles, dtype="<u2").reshape(-1)
            primitive = {
                "attributes": {"POSITION": position},
                "indices": w.accessor(w.view(flat.tobytes(), target=34963), UNSIGNED_SHORT, len(flat), "SCALAR"),
            }
            if material is not None:
                primitive["material"] = material
            primitives.append(primitive)
        return primitives

    corners, faces = cube(0.01)
    every = [t for group in faces.values() for t in group]
    not_top = [t for key, group in faces.items() if key != "+y" for t in group]
    small, small_faces = cube(0.002)
    meshes = [
        {"name": "cube", "primitives": mesh(corners, [(every, 0)])},
        # glTF's +Y is PartCAD's +Z: the top of the box is blue, the rest grey.
        {"name": "two_tone", "primitives": mesh(corners, [(faces["+y"], 1), (not_top, 2)])},
        {"name": "rivet", "primitives": mesh(small, [([t for g in small_faces.values() for t in g], None)])},
    ]
    point = w.accessor(w.view(np.zeros((1, 3), "<f4").tobytes()), FLOAT, 1, "VEC3", min=[0, 0, 0], max=[0, 0, 0])
    meshes.append({"name": "marker", "primitives": [{"attributes": {"POSITION": point}, "mode": 0}]})

    # Three rivets in a row, each turned a quarter about Y, the rotation stored as
    # normalized 16-bit integers (KHR_mesh_quantization allows them for instancing).
    translations = np.array([[0.0, 0.0, 0.05], [0.01, 0.0, 0.05], [0.02, 0.0, 0.05]], dtype="<f4")
    quarter = np.array([0.0, np.sqrt(0.5), 0.0, np.sqrt(0.5)])
    rotations = np.tile(np.round(quarter * 32767).astype("<i2"), (3, 1))
    instancing = {
        "attributes": {
            "TRANSLATION": w.accessor(w.view(translations.tobytes()), FLOAT, 3, "VEC3"),
            "ROTATION": w.accessor(w.view(rotations.tobytes()), SHORT, 3, "VEC4", normalized=True),
        }
    }
    nodes = [
        {"name": "root", "children": [1, 2, 3, 4, 5, 6]},
        {"name": "red_box", "mesh": 0, "translation": [0.05, 0.0, 0.0]},
        {"name": "two_tone_box", "mesh": 1, "translation": [0.0, 0.05, 0.0]},
        {"name": "stretched", "mesh": 0, "translation": [-0.05, 0.0, 0.0], "scale": [2.0, 1.0, 1.0]},
        {"name": "rivets", "mesh": 2, "extensions": {"EXT_mesh_gpu_instancing": instancing}},
        {"name": "marker", "mesh": 3},
        {
            "name": "hidden",
            "mesh": 0,
            "translation": [0.0, -0.5, 0.0],
            "extensions": {"KHR_node_visibility": {"visible": False}},
        },
    ]

    def material(name, rgba, roughness, metallic):
        return {
            "name": name,
            "pbrMetallicRoughness": {"baseColorFactor": rgba, "roughnessFactor": roughness, "metallicFactor": metallic},
        }

    w.save(
        "scene.glb",
        extensionsUsed=["EXT_mesh_gpu_instancing", "KHR_mesh_quantization", "KHR_node_visibility"],
        extensionsRequired=["EXT_mesh_gpu_instancing", "KHR_mesh_quantization"],
        materials=[
            material("Red", [1.0, 0.0, 0.0, 1.0], 0.5, 0.0),
            material("Blue", [0.0, 0.0, 1.0, 1.0], 0.2, 1.0),
            material("Grey", [0.21586, 0.21586, 0.21586, 1.0], 0.9, 0.1),
        ],
        meshes=meshes,
        nodes=nodes,
        scenes=[{"nodes": [0]}],
        scene=0,
    )


def vectors():
    """Streams meshoptimizer's encoder wrote, and what its decoder reads them as."""
    import meshopt

    rng = np.random.default_rng(7)
    found = []

    def add(mode, filter_name, encoded, count, stride, decoded, khr=False):
        found.append(
            {
                "mode": mode,
                "filter": filter_name,
                "count": count,
                "stride": stride,
                "khr": khr,
                "encoded": bytes(encoded).hex(),
                "decoded": np.ascontiguousarray(decoded).tobytes().hex(),
            }
        )

    def attributes(rows, version):
        add("ATTRIBUTES", "NONE", meshopt.encode_vertex_buffer_level(rows, 3, version), len(rows), rows.shape[1], rows)

    # Bytes that vary smoothly, wildly and not at all - which is what makes the
    # version 1 encoder choose each of its control modes - in floats (where it
    # chooses XOR deltas), 16-bit integers (2-byte deltas) and bytes.
    # 260 floats cross the end of a block (256 elements of 16 bytes).
    floats = np.cumsum(rng.normal(0, 0.01, (260, 4)), axis=0).astype(np.float32).view(np.uint8)
    shorts = np.cumsum(rng.integers(-3, 4, (100, 4)), axis=0).astype(np.int16).view(np.uint8)
    noise = rng.integers(0, 256, (40, 8), dtype=np.uint8)
    sparse = np.zeros((70, 16), np.uint8)
    sparse[::9] = rng.integers(0, 256, 16)
    for version in (0, 1):
        for rows in (floats, shorts, noise, sparse):
            attributes(np.ascontiguousarray(rows), version)

    def filtered(name, encoded, stride, khr=False):
        stream = meshopt.encode_vertex_buffer_level(np.ascontiguousarray(encoded), 2, 0)
        add(
            "ATTRIBUTES",
            name,
            stream,
            len(encoded),
            stride,
            meshopt.decode_vertex_buffer(stream, len(encoded), stride, name),
            khr,
        )

    unit = rng.normal(size=(30, 3))
    unit /= np.linalg.norm(unit, axis=1, keepdims=True)
    unit = np.hstack([unit, np.ones((30, 1))]).astype(np.float32)
    filtered("OCTAHEDRAL", meshopt.encode_filter_oct(unit, 4, 8), 4)
    filtered("OCTAHEDRAL", meshopt.encode_filter_oct(unit, 8, 12), 8)
    turns = rng.normal(size=(30, 4))
    turns /= np.linalg.norm(turns, axis=1, keepdims=True)
    filtered("QUATERNION", meshopt.encode_filter_quat(turns.astype(np.float32), 8, 12), 8)
    filtered("EXPONENTIAL", meshopt.encode_filter_exp(rng.normal(0, 100, (30, 3)).astype(np.float32), 15), 12)
    colors = rng.random((30, 4)).astype(np.float32)
    filtered("COLOR", meshopt.encode_filter_color(colors, 4, 8), 4, khr=True)
    filtered("COLOR", meshopt.encode_filter_color(colors, 8, 12), 8, khr=True)

    import trimesh

    sphere = trimesh.creation.icosphere(1).faces.astype(np.uint32).reshape(-1)
    reordered, _remap, _unique = meshopt.reorder_mesh(sphere, True, False)
    for indices in (sphere, reordered.astype(np.uint32)):
        for size, dtype in ((2, np.uint16), (4, np.uint32)):
            typed = indices.astype(dtype)
            stream = meshopt.encode_index_buffer(typed)
            add(
                "TRIANGLES",
                "NONE",
                stream,
                len(typed),
                size,
                meshopt.decode_index_buffer(stream, len(typed), size).astype(dtype),
            )
            stream = meshopt.encode_index_sequence(typed)
            add("INDICES", "NONE", stream, len(typed), size, typed)
    with open(os.path.join(HERE, "meshopt_vectors.json"), "w") as f:
        json.dump(found, f, indent=0)
        f.write("\n")


if __name__ == "__main__":
    vectors()
    draco()
    quantized()
    meshopt_ext()
    meshopt_khr()
    scene()
    print(json.dumps(sorted(name for name in os.listdir(HERE) if name.endswith(".glb"))))
