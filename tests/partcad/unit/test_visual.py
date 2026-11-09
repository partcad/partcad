#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part's 'visual:': drawn in its place in a picture, and nowhere else (see 'partcad.visual').

Two halves. The substitution itself - which parts of a tree are drawn as what,
where, and under which names - is asked of 'visual.substitute_async' over
'basic' parts, which are written rather than built, so no sandbox is involved.
Then where it happens: a render implementation of this package's own writes down
what it was handed, and is asked for with and without 'visuals: true', through
the Draft tab's 'visuals=False', and as an export - which is the one place the
guarantee can be seen whole: an implementation that does not draw pictures is
handed the part as it is, with no trace of its visual.
"""

import asyncio
import json
import textwrap

import pytest

import partcad as pc
from partcad import output, shape_envelope, visual

CONFIG = """
sketches:
  profile:
    type: basic
    rectangle: {side-x: 10, side-y: 10}

parts:
  box:
    type: basic
    cuboid: [10, 10, 10]
    visual: look
  look:
    type: basic
    private: true
    cylinder: {radius: 3, height: 30}
  sized:
    type: basic
    cuboid: ["%size%", 10, 10]
    visual: look-sized;height=99
    parameters:
      size: {type: float, default: 10.0}
      color: {type: string, default: ":red"}
  look-sized:
    type: basic
    private: true
    cylinder: {radius: "%size%", height: "%height%"}
    parameters:
      size: {type: float, default: 1.0}
      height: {type: float, default: 1.0}
      color: {type: string, default: ""}
  plain:
    type: basic
    cuboid: [5, 5, 5]
  plain-drawn:
    type: basic
    cuboid: [5, 5, 5]
    visual: look
  box-alias:
    type: alias
    source: box
  box-moved:
    type: alias
    source: box
    offset: [[100, 0, 0], [0, 0, 1], 0]
  box-scaled:
    type: alias
    source: box
    scale: 2
  # Records the assembly it flattens as its 'source_resolved', as a reference does.
  pair-compound:
    type: compound
    source: pair
  narcissus:
    type: basic
    cuboid: [1, 1, 1]
    visual: narcissus
  lost:
    type: basic
    cuboid: [1, 1, 1]
    visual: nowhere
  borrows:
    type: basic
    cuboid: [1, 1, 1]
    visual: //kept:secret-look
  # A public part of another package, whose visual is private to that package.
  their-thing:
    type: alias
    source: //kept:public-thing

colors:
  red:
    display: "#FF0000"
    manufacturable: false

assemblies:
  pair:
    type: assy
    path: pair.assy
  theirs:
    type: assy
    path: theirs.assy

render:
  dump:
    path: dump.py
    extension: json
  dump-visuals:
    path: dump.py
    extension: json
    visuals: true

export:
  dump-export:
    path: dump.py
    extension: json
    visuals: true
"""

PAIR = """
links:
  - part: box
    name: left
    location: [[-50, 0, 0], [0, 0, 1], 0]
  - part: box
    name: right
    location: [[50, 0, 0], [0, 0, 1], 90]
  - part: plain
    name: plain
"""

KEPT = """
parts:
  secret-look:
    type: basic
    private: true
    cylinder: {radius: 2, height: 20}
  public-thing:
    type: basic
    cuboid: [8, 8, 8]
    visual: secret-look
"""

# Another package's public part, placed here twice.
THEIRS = """
links:
  - part: //kept:public-thing
    name: one
  - part: //kept:public-thing
    name: two
    location: [[50, 0, 0], [0, 0, 1], 0]
"""

# What every implementation below writes: what it was handed, node by node - the
# name, the link, what it is drawn as, and how much volume its geometry has.
DUMP = """
import json


def process(path, request):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    nodes = []

    def walk(node):
        shape = node.get("shape")
        if shape is not None:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape, props)
            nodes.append(
                {
                    "name": node.get("name"),
                    "label": node.get("label"),
                    "visual": node.get("visual"),
                    "volume": round(props.Mass(), 3),
                }
            )
        for child in node.get("assembly") or []:
            walk(child)

    walk(request["shape_tree"])
    with open(path, "w") as f:
        json.dump(nodes, f, sort_keys=True)
    return {"success": True, "exception": None, "files": []}
"""


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("visual")
    (root / "partcad.yaml").write_text(textwrap.dedent(CONFIG).lstrip() + "\ndependencies:\n  kept:\n    path: kept\n")
    (root / "pair.assy").write_text(textwrap.dedent(PAIR).lstrip())
    (root / "theirs.assy").write_text(textwrap.dedent(THEIRS).lstrip())
    (root / "dump.py").write_text(textwrap.dedent(DUMP).lstrip())
    kept = root / "kept"
    kept.mkdir()
    (kept / "partcad.yaml").write_text(textwrap.dedent(KEPT).lstrip())
    return pc.Context(str(root))


def _substituted(context, name, kind="part"):
    shape = context.get_assembly(name) if kind == "assembly" else context.get_part(name)
    tree = asyncio.run(shape.get_wrapped(context))
    return tree, asyncio.run(visual.substitute_async(context, shape, tree))


def _brep_of(context, name):
    return asyncio.run(context.get_part(name).get_wrapped(context))[shape_envelope.KEY_BREP]


def test_a_part_is_drawn_as_its_visual_and_is_still_itself(context):
    tree, drawn = _substituted(context, "box")
    # The part is the cuboid, and says nothing of what it is drawn as.
    assert visual.NODE_KEY not in tree
    assert tree[shape_envelope.KEY_BREP] != _brep_of(context, "look")
    # The picture's tree is the cylinder, under the part's own name.
    assert drawn.tree["name"] == "//:box"
    assert drawn.tree[visual.NODE_KEY] == "//:look"
    assert drawn.tree[shape_envelope.KEY_BREP] == _brep_of(context, "look")
    assert drawn.keys == [["//:look", asyncio.run(context.get_part("look").get_cache_key_async())]]
    assert drawn.cacheable


def test_every_placement_of_a_part_is_drawn_as_its_visual_where_it_is(context):
    tree, drawn = _substituted(context, "pair", kind="assembly")
    before = tree[shape_envelope.KEY_ASSEMBLY]
    after = drawn.tree[shape_envelope.KEY_ASSEMBLY]
    assert [node["label"] for node in after] == ["left", "right", "plain"]
    for old, new in zip(before[:2], after[:2]):
        assert new["location"] == old["location"]
        assert new["name"] == old["name"] == "//:box"
        assert new[visual.NODE_KEY] == "//:look"
    # A part with no visual is the very node it was.
    assert after[2] is before[2]
    # One visual, however many times it is drawn.
    assert [name for name, _key in drawn.keys] == ["//:look"]


def test_a_visual_is_asked_for_with_the_parts_own_parameters_and_its_own_on_top(context):
    _tree, drawn = _substituted(context, "sized")
    name = drawn.tree[visual.NODE_KEY]
    # 'size' and 'color' are declared by both, so passed on - the colour spelled
    # in full, since ':red' means this package wherever it is read; 'height' is
    # the reference's own.
    assert name.startswith("//:look-sized;")
    assert "size=10" in name and "height=99" in name and "color=//:red" in name


def test_an_alias_is_drawn_as_the_visual_of_what_it_stands_for_moved_by_its_offset(context):
    _tree, drawn = _substituted(context, "box-alias")
    assert drawn.tree[visual.NODE_KEY] == "//:look"
    assert drawn.tree["name"] == "//:box-alias"

    _tree, drawn = _substituted(context, "box-moved")
    assert drawn.tree[visual.NODE_KEY] == "//:look"
    assert drawn.tree["location"][0] == pytest.approx([100.0, 0.0, 0.0])


def test_an_alias_that_scales_is_drawn_as_itself(context):
    tree, drawn = _substituted(context, "box-scaled")
    assert drawn.tree is tree
    assert drawn.keys == []


@pytest.mark.parametrize(
    "name, said",
    [
        ("narcissus", "//:narcissus: a part cannot be its own visual"),
        ("lost", "//:lost: its visual 'nowhere' is not a part that can be drawn"),
        ("borrows", "A part '//kept:secret-look' is private to //kept, and a reference written in // cannot name it"),
    ],
)
def test_a_visual_that_cannot_be_had_is_reported_and_the_part_drawn_as_itself(context, caplog, name, said):
    tree, drawn = _substituted(context, name)
    assert drawn.tree is tree
    assert said in caplog.text


def test_the_tree_of_the_3d_view_is_drawn_with_visuals_and_every_other_is_not(context):
    box = context.get_part("box")
    plain = asyncio.run(box.get_representation(context))
    assert visual.NODE_KEY not in plain
    drawn = asyncio.run(box.get_representation(context, visuals=True))
    assert drawn[visual.NODE_KEY] == "//:look"


def test_only_a_render_implementation_that_says_so_draws_pictures(context):
    """PartCAD's own pictures say it; its DXF, its exports and anything that does not say it do not."""
    box = context.get_part("box")

    def visuals_of(format_name):
        impl, _path = box.output_getopts(context, format_name, context.get_project("//"))
        asyncio.run(output.materialize_script(context, impl))
        return impl.visuals

    for picture in ("svg", "png", "jpeg", "mp4", "webm"):
        assert visuals_of(picture), picture
    for drawing in ("dxf", "step", "stl", "gltf", "dump", "dump-export"):
        assert not visuals_of(drawing), drawing
    assert visuals_of("dump-visuals")


def _render(context, name, format_name, tmp_path, **kwargs):
    shape = context.get_part(name) if name != "pair" else context.get_assembly(name)
    asyncio.run(shape.render_async(context, format_name, output_dir=str(tmp_path), **kwargs))
    [written] = list(tmp_path.glob("*.json"))
    nodes = json.loads(written.read_text())
    written.unlink()
    return nodes


def test_a_picture_is_drawn_with_the_visuals_and_a_drawing_with_the_parts_as_they_are(context, tmp_path):
    """The Draft tab's guarantee, seen from the implementation: no trace of a visual unless it draws pictures."""
    cuboid = 10.0 * 10.0 * 10.0
    picture = _render(context, "pair", "dump-visuals", tmp_path)
    assert [(node["label"], node["visual"]) for node in picture] == [
        ("left", "//:look"),
        ("right", "//:look"),
        ("plain", None),
    ]
    assert picture[0]["volume"] != pytest.approx(cuboid)

    for nodes in (
        # A file type that does not say it draws pictures.
        _render(context, "pair", "dump", tmp_path),
        # One that does, asked for as the Draft tab asks.
        _render(context, "pair", "dump-visuals", tmp_path, visuals=False),
        # An export, whatever it says.
        _render(context, "pair", "dump-export", tmp_path),
    ):
        assert [node["visual"] for node in nodes] == [None, None, None]
        assert [node["name"] for node in nodes] == ["//:box", "//:box", "//:plain"]
        assert nodes[0]["volume"] == pytest.approx(cuboid)


def test_a_picture_is_keyed_on_the_visuals_it_drew(context, tmp_path):
    """Drawn again with visuals, it is not handed the picture drawn without them, nor the other way round."""
    with_visuals = _render(context, "box", "dump-visuals", tmp_path)
    without = _render(context, "box", "dump-visuals", tmp_path, visuals=False)
    again = _render(context, "box", "dump-visuals", tmp_path)
    assert with_visuals[0]["visual"] == again[0]["visual"] == "//:look"
    assert without[0]["visual"] is None


def test_what_a_part_is_drawn_as_is_no_part_of_its_key(context):
    """Editing a visual redraws pictures; it rebuilds nothing. A cuboid with a visual keys as the cuboid without."""
    plain = context.get_part("plain")
    drawn = context.get_part("plain-drawn")
    asyncio.run(plain.prepare_async())
    asyncio.run(drawn.prepare_async())
    assert asyncio.run(drawn.get_cache_key_async()) == asyncio.run(plain.get_cache_key_async())


def test_another_packages_public_part_is_drawn_as_the_visual_its_own_package_keeps_private(context, caplog):
    """The visual is the reference its own package wrote, so it is allowed; naming it from here is not (see 'borrows')."""
    _tree, drawn = _substituted(context, "theirs", kind="assembly")
    assert [node[visual.NODE_KEY] for node in drawn.tree[shape_envelope.KEY_ASSEMBLY]] == ["//kept:secret-look"] * 2
    assert [name for name, _key in drawn.keys] == ["//kept:secret-look"]

    _tree, drawn = _substituted(context, "their-thing")
    assert drawn.tree[visual.NODE_KEY] == "//kept:secret-look"

    assert "is private to //kept" not in caplog.text
    assert "ERROR" not in caplog.text


def test_another_packages_public_part_renders_with_its_private_visual_without_errors(context, tmp_path, caplog):
    """Through PartCAD's own SVG, as 'pc render' draws it, and through the 3D view's tree."""
    pc.logging.reset_errors()
    assembly = context.get_assembly("theirs")
    results = asyncio.run(assembly.render_async(context, "svg", output_dir=str(tmp_path)))
    assert results["svg"]["success"], results
    assert (tmp_path / "theirs.svg").stat().st_size > 0
    assert assembly.errors == []

    tree = asyncio.run(assembly.get_representation(context, shape_envelope.FORM_GLTF, visuals=True))
    assert [node[visual.NODE_KEY] for node in tree[shape_envelope.KEY_ASSEMBLY]] == ["//kept:secret-look"] * 2
    assert pc.logging.had_errors is False
    assert "ERROR" not in caplog.text


def test_a_compound_of_an_assembly_is_drawn_as_itself_and_nothing_is_reported(context, caplog):
    """Its source is an assembly, not a part a visual could come from: no lookup of it as a part, no error."""
    compound = context.get_part("pair-compound")
    assert asyncio.run(visual.visual_of_async(context, compound)) is None
    assert "not found" not in caplog.text
    assert "ERROR" not in caplog.text
