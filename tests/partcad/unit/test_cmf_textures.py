#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A colour drawn with an image: its display as a texture (docs/design/cmf.md, section 9.1).

Pinned here: what a colour declaring an image says and what is wrong with one
(the declaration), how the image rides in a part's CMF section and what an
earlier reader of it sees (the payload), how it is laid on a surface (the
mapping), and that each thing that draws surfaces draws it - a shaded picture
and the glTF the IDE is shown - while a drawing of lines draws its colour.
"""

import io
import json
import os
import struct
import sys
import textwrap

import pytest
import yaml

import partcad as pc
from partcad import cmf, cmf_texture, output, shape_envelope

WRAPPERS_DIR = os.path.join(os.path.dirname(pc.__file__), "wrappers")
RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]
for directory in (WRAPPERS_DIR, RENDER_DIR):
    if directory not in sys.path:
        sys.path.append(directory)

import cmf_section  # noqa: E402
import texture_mapping  # noqa: E402
from cmf_section import NONE, CmfSet, Section, Texture  # noqa: E402

# Left half red, right half blue, 40 by 20 pixels: its mean is purple, and
# which half is where says which way it was laid.
RED, BLUE = (220, 20, 20), (20, 20, 220)


def _png(size=(40, 20), split=True, fmt="PNG") -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, RED)
    if split:
        for x in range(size[0] // 2, size[0]):
            for y in range(size[1]):
                image.putpixel((x, y), BLUE)
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


PACKAGE = """
colors:
  wood:
    display:
      image: textures/wood.png
      size: 30
  tinted:
    display: {image: textures/wood.png, size: [10, 40], color: "#123456"}
  unsized:
    display: {image: textures/wood.png}
  shown-as-wood:
    display: ":wood"
  outside:
    display: {image: ../elsewhere.png}
  missing:
    display: {image: textures/nothing.png}
  not-an-image:
    display: {image: textures/notes.png}
materials:
  oak:
    density: 700
    color: ":wood"
parts:
  box:
    type: stl
    path: box.stl
    parameters:
      color: {type: string, default: ":wood"}
  oak-box:
    type: stl
    path: box.stl
    parameters:
      material: {type: string, default: ":oak"}
  plain:
    type: stl
    path: box.stl
"""


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "textures").mkdir()
    (tmp_path / "textures" / "wood.png").write_bytes(_png())
    (tmp_path / "textures" / "notes.png").write_text("not an image at all")
    (tmp_path / "elsewhere.png").write_bytes(_png())
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent(PACKAGE))
    (tmp_path / "box.stl").write_text("solid box\nendsolid box\n")
    return pc.Context(str(tmp_path))


def _color(ctx, name):
    return cmf.lookup(ctx, "color", name, ctx.get_project(".").name, quiet=True)


# --------------------------------------------------------------------------- #
# The declaration                                                             #
# --------------------------------------------------------------------------- #


def test_a_colour_drawn_with_an_image_is_drawn_as_its_mean_elsewhere(ctx):
    wood = _color(ctx, ":wood")
    texture = cmf.texture_of(ctx, wood)

    assert texture.image == _png()
    assert texture.name == "textures/wood.png"
    # 30 mm across, and half that up: the image is twice as wide as it is tall.
    assert (texture.width, texture.height) == (30.0, 15.0)
    assert texture.mime_type == "image/png"
    # Half red, half blue.
    assert cmf.display(ctx, wood) == (120, 20, 120, 1.0)


def test_a_stated_colour_and_size_are_the_declarations(ctx):
    tinted = _color(ctx, ":tinted")
    texture = cmf.texture_of(ctx, tinted)

    assert (texture.width, texture.height) == (10.0, 40.0)
    assert cmf.display(ctx, tinted) == (0x12, 0x34, 0x56, 1.0)


def test_an_image_covers_a_tenth_of_a_metre_unless_it_says(ctx):
    texture = cmf.texture_of(ctx, _color(ctx, ":unsized"))

    assert (texture.width, texture.height) == (cmf_texture.DEFAULT_SIZE, cmf_texture.DEFAULT_SIZE / 2)


def test_a_colour_naming_a_textured_one_is_drawn_with_its_image(ctx):
    assert cmf.texture_of(ctx, _color(ctx, ":shown-as-wood")) == cmf.texture_of(ctx, _color(ctx, ":wood"))
    assert cmf.display(ctx, _color(ctx, ":shown-as-wood")) == cmf.display(ctx, _color(ctx, ":wood"))


def test_a_plain_colour_has_no_image(tmp_path):
    (tmp_path / "partcad.yaml").write_text("colors:\n  red: '#C91A09'\n")
    ctx = pc.Context(str(tmp_path))

    assert cmf.texture_of(ctx, _color(ctx, ":red")) is None


@pytest.mark.parametrize(
    "name, said",
    [
        ("outside", "outside its package"),
        ("missing", "is not there"),
        ("not-an-image", "neither a PNG nor a JPEG"),
    ],
)
def test_an_image_that_cannot_be_drawn_with_is_the_declarations_error(ctx, name, said):
    color = _color(ctx, ":" + name)

    assert cmf.texture_of(ctx, color) is None
    assert cmf.display(ctx, color) is None
    assert any(said in error for error in color.errors)
    # Said once, however often it is asked.
    assert len(color.errors) == 1


def test_an_image_too_large_to_carry_is_refused(ctx, monkeypatch):
    monkeypatch.setattr(cmf_texture, "MAX_IMAGE_BYTES", 10)
    monkeypatch.setattr(cmf_texture, "_images", {})
    color = _color(ctx, ":wood")

    assert cmf.texture_of(ctx, color) is None
    assert "more than the 10" in color.errors[0]


def test_a_jpeg_is_one_too(tmp_path):
    (tmp_path / "grain.jpg").write_bytes(_png(fmt="JPEG"))
    (tmp_path / "partcad.yaml").write_text("colors:\n  grain:\n    display: {image: grain.jpg, size: 50}\n")
    ctx = pc.Context(str(tmp_path))

    assert cmf.texture_of(ctx, _color(ctx, ":grain")).mime_type == "image/jpeg"


def test_pc_info_and_pc_list_say_it_is_an_image(ctx):
    assert _color(ctx, ":wood").cmf_info()["Display"] == "image textures/wood.png, 30 mm across"
    assert _color(ctx, ":tinted").cmf_info()["Display"] == "image textures/wood.png, 10 x 40 mm"
    assert _color(ctx, ":wood").display_words() == "image textures/wood.png, 30 mm across"


def test_the_cmf_tab_shows_the_image_small(ctx):
    data = cmf.declaration_data(ctx, _color(ctx, ":wood"))

    assert data["display"] == "#781478"
    assert data["texture"]["image"] == "textures/wood.png"
    assert data["texture"]["size"] == [30.0, 15.0]
    assert data["texture"]["thumbnail"].startswith("data:image/png;base64,")


# --------------------------------------------------------------------------- #
# The payload                                                                 #
# --------------------------------------------------------------------------- #


def _texture(**values):
    return Texture(_png(), "wood.png", values.get("width", 30), values.get("height", 15))


def test_a_section_carries_its_images_and_reads_them_back():
    wood = CmfSet(color="//c:wood", rgba=(120, 20, 120, 1.0), texture=_texture(), origin="declared")
    other = CmfSet(color="//c:other", rgba=(1, 2, 3, 1.0), texture=_texture(width=10), origin="declared")
    section = Section([wood, other, CmfSet(material="//c:oak")], 0, [2], [0, 1, NONE])

    data = cmf_section.encode(section)

    assert cmf_section.decode(data) == section
    assert cmf_section.decode(data).sets[1].texture.width == 10.0
    # One image, however many sets are drawn with it.
    assert data.count(_png()) == 1


def test_an_earlier_reader_reads_every_set_without_its_image():
    """What PartCAD before textures read: everything up to the trailer, the colour it is drawn as included."""
    wood = CmfSet(color="//c:wood", rgba=(120, 20, 120, 1.0), texture=_texture(), origin="declared")
    data = cmf_section.encode(Section([wood], 0))

    before = data[: data.index(cmf_section.LOOKS_MAGIC)]
    earlier = cmf_section.decode(before)

    assert earlier.sets[0].rgba == (120, 20, 120, 1.0)
    assert earlier.sets[0].color == "//c:wood"
    assert earlier.sets[0].texture is None


def test_a_set_without_its_colour_is_without_its_image():
    wood = CmfSet(color="//c:wood", rgba=(120, 20, 120, 1.0), texture=_texture())

    assert wood.without(["color"]).texture is None
    assert CmfSet(material="//c:oak").filled_from(wood).texture == wood.texture


def test_a_summary_names_the_image_and_its_digest():
    wood = CmfSet(color="//c:wood", rgba=(120, 20, 120, 1.0), texture=_texture())

    (entry,) = Section([wood], 0).summary()["sets"]

    assert entry["texture"] == {"image": "wood.png", "digest": _texture().digest, "size": [30.0, 15.0]}


def test_a_part_in_a_textured_colour_carries_the_image(ctx):
    part = ctx.get_part(":box")
    declared, _drops = cmf.declared_set(ctx, part)

    assert declared.texture == cmf.texture_of(ctx, _color(ctx, ":wood"))
    assert declared.rgba == (120, 20, 120, 1.0)
    # What every drawing of lines draws it in.
    assert part.config["properties"]["color"] == "#781478"


def test_a_material_claiming_a_textured_colour_draws_with_its_image(ctx):
    declared, _drops = cmf.declared_set(ctx, ctx.get_part(":oak-box"))

    assert declared.texture == cmf.texture_of(ctx, _color(ctx, ":wood"))


def test_the_declared_image_lands_in_the_payload(ctx):
    pytest.importorskip("build123d")
    import build123d as bd
    import ocp_serialize

    part = ctx.get_part(":box")
    envelope = ocp_serialize.encode_shape(bd.Box(10, 20, 30).wrapped)

    applied, recorded = cmf.apply_declared(ctx, part, envelope, {})

    _brep, section = cmf_section.split(shape_envelope.brep_plain(applied[shape_envelope.KEY_BREP]))
    assert section.own().texture.image == _png()
    assert recorded[shape_envelope.METADATA_CMF]["sets"][0]["texture"]["image"] == "textures/wood.png"


def test_an_assembly_is_keyed_on_the_image_itself(ctx, tmp_path):
    part = ctx.get_part(":box")
    before = cmf.key_of(ctx, part)
    assert before["color"]["texture"][0] == _texture().digest

    (tmp_path / "textures" / "wood.png").write_bytes(_png(split=False))
    # A changed file is read again: it is another key in the cache of images.
    after = cmf.key_of(pc.Context(str(tmp_path)), pc.Context(str(tmp_path)).get_part(":box"))

    assert after["color"]["texture"][0] != before["color"]["texture"][0]


def test_a_part_that_states_no_colour_keys_as_it_did(ctx):
    assert cmf.key_of(ctx, ctx.get_part(":plain")).get("color") is None


# --------------------------------------------------------------------------- #
# How an image is laid                                                        #
# --------------------------------------------------------------------------- #


def _unit_box():
    """The twelve triangles of a box from (0, 0, 0) to (1, 2, 3), wound counter-clockwise seen from outside."""
    import numpy as np

    points = np.array([[x, y, z] for x in (0, 1) for y in (0, 2) for z in (0, 3)], dtype=float)

    def index(x, y, z):
        return x * 4 + y * 2 + z

    quads = [
        # (a, b, c, d) counter-clockwise seen from outside, and the outward normal.
        ([index(1, 0, 0), index(1, 1, 0), index(1, 1, 1), index(1, 0, 1)], (1, 0, 0)),
        ([index(0, 0, 0), index(0, 0, 1), index(0, 1, 1), index(0, 1, 0)], (-1, 0, 0)),
        ([index(0, 1, 0), index(0, 1, 1), index(1, 1, 1), index(1, 1, 0)], (0, 1, 0)),
        ([index(0, 0, 0), index(1, 0, 0), index(1, 0, 1), index(0, 0, 1)], (0, -1, 0)),
        ([index(0, 0, 1), index(1, 0, 1), index(1, 1, 1), index(0, 1, 1)], (0, 0, 1)),
        ([index(0, 0, 0), index(0, 1, 0), index(1, 1, 0), index(1, 0, 0)], (0, 0, -1)),
    ]
    corners, normals = [], []
    for (a, b, c, d), normal in quads:
        corners += [[a, b, c], [a, c, d]]
        normals += [normal, normal]
    return points, np.array(corners), np.array(normals, dtype=float)


def test_an_image_is_laid_on_every_side_of_a_box_upright_and_unmirrored():
    """Seen from outside each side, the image's right and up make the side's outward normal: it is not mirrored."""
    import numpy as np

    points, corners, normals = _unit_box()
    uv = texture_mapping.box_uv(points, corners, 1.0, 1.0)

    for triangle, normal in zip(range(len(corners)), normals):
        p = points[corners[triangle]]
        # The directions in space along which u and v grow, from the triangle's corners.
        edges = np.stack([p[1] - p[0], p[2] - p[0]])
        duv = np.stack([uv[triangle][1] - uv[triangle][0], uv[triangle][2] - uv[triangle][0]])
        right, up = np.linalg.lstsq(duv, edges, rcond=None)[0]
        assert np.allclose(np.cross(right, up), normal), (triangle, normal)
        if normal[2] == 0:
            # On a side, the image's top is up.
            assert np.allclose(up, (0, 0, 1))


def test_an_image_is_laid_at_its_size():
    import numpy as np

    points, corners, _normals = _unit_box()
    uv = texture_mapping.box_uv(points * 10.0, corners, 5.0, 15.0)

    # The +X side, 20 mm across (Y) and 30 mm up (Z): four copies across, two up.
    side = uv[0:2].reshape(-1, 2)
    assert np.ptp(side[:, 0]) == pytest.approx(4.0)
    assert np.ptp(side[:, 1]) == pytest.approx(2.0)


def test_gltf_reads_an_image_from_its_top():
    import numpy as np

    assert np.allclose(texture_mapping.gltf_texcoords([[0.25, 0.75]]), [[0.25, -0.75]])


def test_an_image_repeats_and_is_read_between_its_pixels():
    import numpy as np

    image = np.array([[[0.0], [1.0]], [[0.0], [1.0]]])

    # The middle of the left pixel, the middle of the right one, and the edge
    # between the right one and the next copy's left one.
    values = texture_mapping.sample(image, np.array([[0.25, 0.5], [0.75, 0.5], [1.0, 0.5]]))

    assert values[:, 0] == pytest.approx([0.0, 1.0, 0.5])


# --------------------------------------------------------------------------- #
# What draws it                                                               #
# --------------------------------------------------------------------------- #


def _textured_envelope(section):
    pytest.importorskip("build123d")
    import build123d as bd
    import ocp_serialize

    return ocp_serialize.encode_shape(bd.Box(40, 30, 20).wrapped, cmf=section)


def _wood_set():
    return CmfSet(color="//c:wood", rgba=(120, 20, 120, 1.0), texture=Texture(_png(), "wood.png", 40, 20))


def test_a_drawing_of_lines_draws_a_textured_part_as_it_did():
    """'split_by_color' is untouched: the node's colour, the part whole."""
    import appearance
    import ocp_serialize

    envelope = _textured_envelope(Section([_wood_set()], 0))
    envelope[shape_envelope.KEY_PROPERTIES] = {"color": "#781478"}
    whole, tree = ocp_serialize.decode_tree(envelope)

    assert appearance.split_by_color(tree, whole) == [("#781478", whole)]
    ((color, one_sided, _shape, texture),) = appearance.split_by_look(tree, whole)
    assert (color, one_sided, texture) == ("#781478", False, _wood_set().texture)


def test_a_tree_drawn_with_no_image_splits_by_look_as_by_colour():
    import appearance
    import ocp_serialize

    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    whole, tree = ocp_serialize.decode_tree(_textured_envelope(Section([red], NONE, faces=[0, 0] + [NONE] * 4)))

    by_sides = appearance.split_by_sides(tree, whole)
    by_look = appearance.split_by_look(tree, whole)

    def faces(shape):
        return len(appearance._faces(shape))

    assert [(color, sided, faces(shape), None) for color, sided, shape in by_sides] == [
        (color, sided, faces(shape), texture) for color, sided, shape, texture in by_look
    ]


def test_the_faces_a_section_draws_with_an_image_are_told_apart():
    import appearance

    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    section = Section([red, _wood_set()], 0, faces=[1, NONE, NONE, NONE, NONE, 1])

    kind, looks = appearance.payload_looks(section, "#DAA520")

    assert kind == appearance.FACES
    assert [texture is not None for _color, texture in looks] == [True, False, False, False, False, True]
    assert looks[1] == ("#FF0000", None)


def test_a_shaded_picture_draws_the_image():
    """The top of a box is drawn with the image: red where its left half is, blue where its right one is."""
    import appearance
    import numpy as np
    import ocp_serialize
    import raster_scene

    whole, tree = ocp_serialize.decode_tree(_textured_envelope(Section([_wood_set()], 0)))
    scene = raster_scene.Scene(appearance.split_by_look(tree, whole), 128)
    camera = raster_scene.Camera(
        direction=(0, 0, 1), up=(0, 1, 0), distance=raster_scene.frame_distance(scene.sphere, 1.0), fov=0, height=25
    )
    picture = raster_scene.draw(scene, camera, np.eye(3), 128, 128).astype(int)

    # Seen from above, +X to the right: the image is 40 mm across, as the box
    # is, and laid from the part's origin - the box's middle - so the box's
    # left half shows the image's right (blue) half and its right half the
    # left (red) one.
    row = picture[64]
    left, right = row[40], row[88]
    assert left[2] > left[0] + 50, left
    assert right[0] > right[2] + 50, right


def _seen_from(scene, direction):
    """How many pixels of 'scene' are drawn, seen from 'direction' without perspective: anything not background."""
    import numpy as np
    import raster_scene

    camera = raster_scene.Camera(
        direction=direction, up=(0, 0, 1), distance=raster_scene.frame_distance(scene.sphere, 1.0), fov=0, height=30
    )
    picture = raster_scene.draw(scene, camera, np.eye(3), 64, 64, background=(0, 0, 0))
    return int(np.count_nonzero(picture.sum(axis=2)))


def test_a_one_sided_shape_drawn_with_an_image_is_drawn_from_its_front_only():
    """Wallpaper: a wall in a colour drawn with an image is laid with it, and is still see-through from behind."""
    import appearance
    import ocp_serialize
    import raster_scene

    envelope = _textured_envelope(Section([_wood_set()], 0))
    envelope[shape_envelope.KEY_PROPERTIES] = {"color": "#781478", appearance.ONE_SIDED_KEY: True}
    whole, tree = ocp_serialize.decode_tree(envelope)

    ((color, one_sided, _shape, texture),) = appearance.split_by_look(tree, whole)
    assert (color, one_sided, texture) == ("#781478", True, _wood_set().texture)

    scene = raster_scene.Scene(appearance.split_by_look(tree, whole), 64)
    assert scene.images and (scene.texture >= 0).all() and scene.one_sided.all()
    # A box, one-sided: seen from anywhere, its far faces turn their fronts to
    # the camera from the inside and are drawn, its near ones are not.
    two_sided = raster_scene.Scene(
        [(color, False, shape, texture) for color, _sided, shape, texture in appearance.split_by_look(tree, whole)], 64
    )
    assert 0 < _seen_from(scene, (0.3, -1.0, 0.4)) <= _seen_from(two_sided, (0.3, -1.0, 0.4))


def test_a_shaded_picture_without_pillow_draws_the_colour(monkeypatch):
    import builtins

    import raster_scene

    texture = _wood_set().texture
    real_import = builtins.__import__

    def without_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pil)
    warnings = []

    assert raster_scene._read_image(texture, warnings) is None
    assert "Pillow is not installed" in warnings[0]


def _glb_document(glb):
    length = struct.unpack("<I", glb[12:16])[0]
    document = json.loads(glb[20 : 20 + length])
    binary_start = 20 + length + 8
    return document, glb[binary_start:]


def test_the_glb_carries_the_image_on_the_faces_drawn_with_it():
    import wrapper_gltf

    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    envelope = _textured_envelope(Section([red, _wood_set()], NONE, faces=[0, 1, NONE, NONE, 1, 1]))

    answer = wrapper_gltf.process({"shapes": [{"digest": "d", "brep": envelope["brep"]}], "tolerance": 0.1})
    document, binary = _glb_document(answer["geometry"]["d"])

    (image,) = document["images"]
    view = document["bufferViews"][image["bufferView"]]
    assert binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]] == _png()
    assert image["mimeType"] == "image/png"
    textured = [m for m in document["materials"] if "baseColorTexture" in m["pbrMetallicRoughness"]]
    assert len(textured) == 1
    assert textured[0]["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 1.0, 1.0, 1.0]
    assert textured[0]["extras"] == {"partcadColor": "#781478"}
    assert document["samplers"][0]["wrapS"] == wrapper_gltf._GLTF_REPEAT
    primitives = [p for mesh in document["meshes"] for p in mesh["primitives"]]
    with_image = [p for p in primitives if "TEXCOORD_0" in p["attributes"]]
    assert len(with_image) == 1
    # The face coloured red is still OCCT's, in red.
    colours = [m["pbrMetallicRoughness"].get("baseColorFactor") for m in document["materials"]]
    assert [1.0, 0.0, 0.0, 1.0] in colours


def test_a_part_drawn_whole_with_an_image_is_one_textured_primitive():
    import wrapper_gltf

    envelope = _textured_envelope(Section([_wood_set()], 0))

    answer = wrapper_gltf.process({"shapes": [{"digest": "d", "brep": envelope["brep"]}], "tolerance": 0.1})
    document, _binary = _glb_document(answer["geometry"]["d"])

    primitives = [p for mesh in document["meshes"] for p in mesh["primitives"]]
    assert len(primitives) == 1
    assert set(primitives[0]["attributes"]) == {"POSITION", "NORMAL", "TEXCOORD_0"}
    # In glTF's frame, metres and Y up, as OCCT's writer writes a part: the box
    # is 40 by 30 by 20 mm, centred.
    position = document["accessors"][primitives[0]["attributes"]["POSITION"]]
    assert position["min"] == pytest.approx([-0.02, -0.01, -0.015])
    assert position["max"] == pytest.approx([0.02, 0.01, 0.015])


def test_the_schema_takes_an_image_display():
    import jsonschema

    from partcad.lint.all import get_partcad_schema

    jsonschema.validate(yaml.safe_load(textwrap.dedent(PACKAGE)), get_partcad_schema())
