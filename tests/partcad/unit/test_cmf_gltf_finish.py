#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The finish a face is drawn as, in the glTF the IDE draws (docs/design/cmf.md, section 9).

A face whose CMF set says a roughness or a metalness is a primitive of its own,
written by PartCAD ('wrapper_gltf._with_looks'), with a material that says the
finish as glTF does and as 'extras.partcadFinish', which is what the viewer
reads ('ide/vscode/src/webview/finish.ts'). Every other face is OCCT's, as it
always was, and a payload with no finish is the same bytes it was.
"""

import io
import json
import os
import struct
import sys

import pytest

import partcad as pc

WRAPPERS_DIR = os.path.join(os.path.dirname(pc.__file__), "wrappers")
RENDER_DIR = os.path.join(os.path.dirname(pc.__file__), "builtin", "render")
for directory in (WRAPPERS_DIR, RENDER_DIR):
    if directory not in sys.path:
        sys.path.append(directory)

from cmf_section import NONE, CmfSet, Section  # noqa: E402

TOLERANCE = 0.1


def _envelope(section):
    pytest.importorskip("build123d")
    import build123d as bd
    import ocp_serialize

    return ocp_serialize.encode_shape(bd.Box(40, 30, 20).wrapped, cmf=section)


def _document(glb):
    length = struct.unpack("<I", glb[12:16])[0]
    return json.loads(glb[20 : 20 + length])


def _glb(envelope):
    """What the IDE is sent for 'envelope': 'wrapper_gltf.process', as the core asks it."""
    import wrapper_gltf

    answer = wrapper_gltf.process({"shapes": [{"digest": "d", "brep": envelope["brep"]}], "tolerance": TOLERANCE})
    assert answer["failed"] == {}
    return bytes(answer["geometry"]["d"])


def _png():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 4), (120, 20, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


def _primitives(document):
    return [primitive for mesh in document["meshes"] for primitive in mesh["primitives"]]


def _brushed():
    """A red set with a finish: brushed steel's numbers, as 'roughness' and 'metallic' are kept (a byte each)."""
    return CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0), finish="//f:brushed", roughness=0.25, metallic=1.0)


def test_a_part_drawn_whole_with_a_finish_is_one_primitive_that_says_it():
    document = _document(_glb(_envelope(Section([_brushed()], 0))))

    (primitive,) = _primitives(document)
    assert set(primitive["attributes"]) == {"POSITION", "NORMAL"}
    material = document["materials"][primitive["material"]]
    pbr = material["pbrMetallicRoughness"]
    # Red, in linear light, as glTF's factors are.
    assert pbr["baseColorFactor"] == [1.0, 0.0, 0.0, 1.0]
    assert pbr["metallicFactor"] == pytest.approx(1.0)
    assert pbr["roughnessFactor"] == pytest.approx(0.25, abs=1 / 255)
    assert material["extras"]["partcadColor"] == "#FF0000"
    finish = material["extras"]["partcadFinish"]
    assert finish["metallic"] == pytest.approx(1.0)
    assert finish["roughness"] == pytest.approx(0.25, abs=1 / 255)
    assert "alphaMode" not in material
    # No image, so no empty arrays glTF forbids.
    for key in ("images", "textures", "samplers"):
        assert key not in document
    # In glTF's frame, metres and Y up, as OCCT's writer writes a part.
    position = document["accessors"][primitive["attributes"]["POSITION"]]
    assert position["min"] == pytest.approx([-0.02, -0.01, -0.015])
    assert position["max"] == pytest.approx([0.02, 0.01, 0.015])
    # Every triangle of the box: 6 faces, 2 triangles each at least.
    indices = document["accessors"][primitive["indices"]]
    assert indices["count"] >= 36 and indices["count"] % 3 == 0


def test_the_faces_with_a_finish_are_apart_and_the_rest_are_occt_s():
    plain = CmfSet(color="//c:blue", rgba=(0, 0, 255, 1.0))
    document = _document(_glb(_envelope(Section([plain, _brushed()], NONE, faces=[0, 1, NONE, NONE, 1, 1]))))

    finished = [m for m in document["materials"] if "partcadFinish" in m.get("extras", {})]
    assert len(finished) == 1
    assert finished[0]["extras"]["partcadColor"] == "#FF0000"
    # The blue face is OCCT's, in blue, and says no finish.
    colours = [m["pbrMetallicRoughness"].get("baseColorFactor") for m in document["materials"]]
    assert [0.0, 0.0, 1.0, 1.0] in colours
    assert len(_primitives(document)) >= 2


def test_a_finish_with_no_colour_is_in_the_node_s_colour_and_says_only_one_of_two():
    """A set that says a finish and no colour: the node's colour, which the file cannot know."""
    import appearance
    import wrapper_gltf

    rough = CmfSet(finish="//f:matte", roughness=0.8)
    document = _document(_glb(_envelope(Section([rough], NONE, faces=[0, 0, NONE, NONE, NONE, NONE]))))

    (material,) = [m for m in document["materials"] if "partcadFinish" in m.get("extras", {})]
    assert material["extras"]["partcadColor"] is None
    # Unsaid metalness is none, as a shaded 'pc render' draws it.
    assert material["extras"]["partcadFinish"]["metallic"] == 0.0
    assert material["extras"]["partcadFinish"]["roughness"] == pytest.approx(0.8, abs=1 / 255)
    # The default's colour for a reader that knows no 'extras'.
    red, green, blue, _ = appearance.parse(appearance.DEFAULT_COLOR)
    assert material["pbrMetallicRoughness"]["baseColorFactor"][:3] == [
        pytest.approx(wrapper_gltf._linear(channel)) for channel in (red, green, blue)
    ]


def test_an_uncoloured_face_keeps_its_finish_when_faces_are_gathered_by_look():
    """'faces_by_look' fills in the node's colour and keeps the rest of the look: the shaded render's split too."""
    import appearance
    import ocp_serialize

    envelope = _envelope(Section([CmfSet(finish="//f:matte", roughness=0.8)], NONE, faces=[0] + [NONE] * 5))
    shape = ocp_serialize.shape_from_payload(envelope["brep"])
    section = ocp_serialize.cmf_of_payload(envelope["brep"])
    kind, looks = appearance.payload_looks(section, "#00FF00", finishes=True)
    assert kind == appearance.FACES

    gathered = [look for look, _piece in appearance.faces_by_look(shape, looks, ("#00FF00", None, None))]
    finished = [look for look in gathered if look[2] is not None]
    assert len(finished) == 1
    assert finished[0][0] == "#00FF00"
    assert finished[0][2][0] == pytest.approx(0.8, abs=1 / 255)


@pytest.mark.parametrize("section", ["none", "colours", "plain"])
def test_a_payload_with_no_finish_is_the_same_bytes(section):
    """The glb a payload with no finish was before finishes were drawn: OCCT's, coloured as its section says."""
    import appearance
    import ocp_serialize
    import wrapper_gltf

    sections = {
        "none": None,
        "colours": Section(
            [CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0)), CmfSet(color="//c:blue", rgba=(0, 0, 255, 1.0))],
            NONE,
            faces=[0, 1, 0, 1, NONE, NONE],
        ),
        "plain": Section([CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))], 0),
    }
    envelope = _envelope(sections[section])
    drawn = _glb(envelope)

    cmf = ocp_serialize.cmf_of_payload(envelope["brep"])
    assert appearance.payload_looks(cmf, finishes=True) is None
    shape = ocp_serialize.shape_from_payload(envelope["brep"])
    before = wrapper_gltf._to_glb(shape, TOLERANCE, 0.4, appearance.section_face_colors(cmf))
    assert drawn == before
    assert "partcadFinish" not in drawn.decode("latin-1")


def test_a_textured_payload_with_no_finish_is_the_same_bytes():
    """Looks with a finish of None write what looks without one did: '_with_textures' as it was."""
    import appearance
    import ocp_serialize
    import wrapper_gltf
    from cmf_section import Texture

    wood = CmfSet(color="//c:wood", rgba=(120, 20, 120, 1.0), texture=Texture(_png(), "wood.png", 40, 20))
    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    envelope = _envelope(Section([red, wood], NONE, faces=[0, 1, NONE, NONE, 1, 1]))
    cmf = ocp_serialize.cmf_of_payload(envelope["brep"])
    colors = appearance.section_face_colors(cmf)

    def glb(finishes):
        shape = ocp_serialize.shape_from_payload(envelope["brep"])
        looks = appearance.payload_looks(cmf, finishes=finishes)
        return wrapper_gltf._to_glb(shape, TOLERANCE, 0.4, colors, looks)

    assert glb(True) == glb(False) == _glb(envelope)


def test_the_default_roughness_is_the_shaded_render_s():
    import raster_scene
    import wrapper_gltf

    assert wrapper_gltf.DEFAULT_ROUGHNESS == raster_scene.DEFAULT_ROUGHNESS
    assert wrapper_gltf.DEFAULT_METALLIC == 0.0


def test_the_ide_draws_a_finish_with_the_shaded_render_s_numbers():
    """A webview cannot import Python, so 'finish.ts' spells 'raster_scene''s constants again: held here."""
    import re

    import raster_scene

    repository = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    path = os.path.join(repository, "ide", "vscode", "src", "webview", "finish.ts")
    if not os.path.exists(path):
        pytest.skip("the IDE's sources are not beside these tests")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    def constant(name):
        match = re.search(r"export const %s = ([0-9.]+);" % name, text)
        assert match, "'%s' is not in finish.ts as a number" % name
        return float(match.group(1))

    assert constant("DIELECTRIC_F0") == raster_scene.DIELECTRIC_F0
    assert constant("MAX_SHININESS") == raster_scene.MAX_SHININESS
    # The shininess rule itself, as 'shininessOf' writes it.
    assert "Math.max(roughness, 0.05) ** 2" in text and "2 / (alpha * alpha) - 2" in text
    assert raster_scene.shininess_of(0.5) == pytest.approx(30.0)
