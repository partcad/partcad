#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether a file holds an assembly rather than a part (see 'partcad.assembly_file').

What 'pc import part' refuses without '--compound', pinned per format on the
repository's own files where it has them and on the smallest file that makes
each point where it does not.
"""

import gzip
import json
import struct
from pathlib import Path

import pytest

from partcad import assembly_file

ROOT = Path(__file__).resolve().parents[3]
GLTF = ROOT / "tests" / "partcad" / "unit" / "data" / "import_gltf"


def _step(path, components):
    """A STEP file whose data section places 'components' components, and nothing else that matters here."""
    lines = ["ISO-10303-21;", "HEADER;", "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));", "ENDSEC;", "DATA;"]
    for index in range(components):
        lines.append("#%d=NEXT_ASSEMBLY_USAGE_OCCURRENCE('%d','c','',#1,#2,$);" % (100 + index, index))
    lines += ["ENDSEC;", "END-ISO-10303-21;"]
    path.write_text("\n".join(lines), encoding="ascii")
    return path


def _glb(path, document):
    """'document' as a binary glTF: the header and its JSON chunk."""
    body = json.dumps(document).encode("utf-8")
    body += b" " * (-len(body) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body
    )
    return path


# ---------------------------------------------------------------- STEP


def test_a_step_assembly_is_one():
    reason = assembly_file.assembly_in(ROOT / "examples" / "feature_import" / "AeroAssembly.step", "step")

    assert reason == "its product structure places several components"


def test_a_step_part_is_a_part():
    assert assembly_file.assembly_in(ROOT / "examples" / "produce_part_step" / "bolt.step", "step") is None


def test_a_step_product_placing_one_component_is_a_part(tmp_path):
    """How PartCAD writes a part placed away from the origin: an assembly of it, placed there."""
    assert assembly_file.assembly_in(_step(tmp_path / "placed.step", 1), "step") is None


def test_a_gzipped_step_assembly_is_one(tmp_path):
    plain = _step(tmp_path / "plain.step", 2)
    zipped = tmp_path / "zipped.step"
    zipped.write_bytes(gzip.compress(plain.read_bytes()))

    assert assembly_file.assembly_in(zipped, "step") is not None


def test_a_component_split_between_two_reads_is_counted(tmp_path, monkeypatch):
    path = _step(tmp_path / "split.step", 2)
    first = path.read_bytes().index(b"NEXT_ASSEMBLY_USAGE_OCCURRENCE")
    # Every read ends in the middle of the first keyword, or of the second.
    monkeypatch.setattr(assembly_file, "_CHUNK", first + 10)

    assert assembly_file.assembly_in(path, "step") is not None


# ---------------------------------------------------------------- glTF


def test_a_gltf_scene_of_several_meshes_is_an_assembly():
    assert assembly_file.assembly_in(GLTF / "scene.glb", "gltf") == "its scene places several meshes"


@pytest.mark.parametrize("name", ["box.gltf", "box.glb", "box_draco.glb", "box_meshopt.glb"])
def test_a_gltf_of_one_mesh_is_a_part(name):
    assert assembly_file.assembly_in(GLTF / name, "gltf") is None


def test_one_mesh_drawn_several_times_by_gpu_instancing_is_an_assembly(tmp_path):
    document = {
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "extensions": {"EXT_mesh_gpu_instancing": {"attributes": {"TRANSLATION": 0}}}}],
        "meshes": [{"primitives": []}],
        "accessors": [{"count": 3, "type": "VEC3", "componentType": 5126}],
    }

    assert assembly_file.assembly_in(_glb(tmp_path / "instanced.glb", document), "gltf") is not None


def test_a_gltf_with_no_scene_is_read_from_the_nodes_nothing_holds(tmp_path):
    document = {"nodes": [{"children": [1, 2]}, {"mesh": 0}, {"mesh": 0}], "meshes": [{"primitives": []}]}
    path = tmp_path / "loose.gltf"
    path.write_text(json.dumps(document))

    assert assembly_file.assembly_in(path, "gltf") is not None


def test_what_the_scene_does_not_place_is_not_counted(tmp_path):
    document = {
        "scene": 0,
        "scenes": [{"nodes": [0]}, {"nodes": [1, 2]}],
        "nodes": [{"mesh": 0}, {"mesh": 0}, {"mesh": 0}],
        "meshes": [{"primitives": []}],
    }

    assert assembly_file.assembly_in(_glb(tmp_path / "two_scenes.glb", document), "gltf") is None


# ---------------------------------------------------------------- the rest


def test_a_urdf_is_always_an_assembly(tmp_path):
    assert assembly_file.assembly_in(tmp_path / "robot.urdf", "urdf") == "a URDF describes an assembly"


@pytest.mark.parametrize("kind, content", [("step", b"\x1f\x8bnot gzip"), ("gltf", b"glTF\x02\x00"), ("gltf", b"{")])
def test_a_file_that_cannot_be_read_here_is_left_to_the_part_s_reader(tmp_path, kind, content):
    path = tmp_path / ("broken." + kind)
    path.write_bytes(content)

    assert assembly_file.assembly_in(path, kind) is None


def test_other_formats_are_parts(tmp_path):
    path = tmp_path / "plate.stl"
    path.write_bytes(b"solid plate\nendsolid plate\n")

    assert assembly_file.assembly_in(path, "stl") is None
