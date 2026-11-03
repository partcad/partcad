#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part's CMF in its payload, through assemblies, in 'pc test' and in a drawing (docs/design/cmf.md).

Pinned here:

- the core writes the CMF a part declares into its payload's CMF section, and
  records the summary every kernel-free reader reads ('apply_declared');
- what the source stated is kept, completed or dropped as 'sourceCmf' says;
- an assembly's CMF passes to its links where nothing else states it, and a
  link's own CMF 'params:' are recorded on the child it places;
- the 'cmf' check: what a part to be made lacks, a display-only colour, an
  assembly drawing what it holds, and an assembly bought whole;
- a drawing colours each face as the section says.
"""

import asyncio
import logging
import os
import sys

import pytest
import yaml

import partcad as pc
from partcad import cmf, shape_envelope
from partcad.test import cmf as cmf_check

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import cmf_section  # noqa: E402
from cmf_section import NONE, CmfSet, Section  # noqa: E402

COLORS = {
    "red": {"display": "#C91A09"},
    "natural": {"display": "#A8A9AD"},
    "preview": {"display": "#00FF00", "manufacturable": False},
}
MATERIALS = {"alu": {"density": 2700, "color": ":natural"}}
FINISHES = {"satin": {"display": {"roughness": 0.6, "metallic": 0}}}


def _declare(**values):
    return {name: {"type": "string", "default": value} for name, value in values.items()}


def _package(tmp_path, parts=None, assemblies=None, files=None, **extra):
    config = {
        "name": "//cmf",
        "manufacturable": True,
        "colors": COLORS,
        "materials": MATERIALS,
        "finishes": FINISHES,
        "parts": parts or {},
        "assemblies": assemblies or {},
        **extra,
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text)
    return pc.Context(str(tmp_path))


def _stl(**parameters):
    part = {"type": "stl", "path": "box.stl"}
    if parameters:
        part["parameters"] = _declare(**parameters)
    return part


def _envelope(section=None):
    """A real payload: a box, with 'section' after its BREP if one is given."""
    pytest.importorskip("build123d")
    import build123d as bd
    import ocp_serialize

    return ocp_serialize.encode_shape(bd.Box(10, 20, 30).wrapped, cmf=section)


def _section_of(envelope):
    return cmf_section.split(shape_envelope.brep_plain(envelope[shape_envelope.KEY_BREP]))[1]


# --------------------------------------------------------------- the payload


def test_a_part_that_states_no_cmf_is_left_as_it_is(tmp_path):
    ctx = _package(tmp_path, {"plain": _stl()}, files={"box.stl": ""})
    part = ctx.get_part("//cmf:plain")
    envelope = _envelope()

    applied, recorded = cmf.apply_declared(ctx, part, envelope, {})

    assert applied is envelope
    assert recorded == {}


def test_the_declared_cmf_lands_in_the_payload_and_its_summary(tmp_path):
    ctx = _package(tmp_path, {"box": _stl(color=":red", material=":alu", finish=":satin")}, files={"box.stl": ""})
    part = ctx.get_part("//cmf:box")
    envelope = _envelope()

    applied, recorded = cmf.apply_declared(ctx, part, envelope, {})

    section = _section_of(applied)
    own = section.own()
    assert (own.color, own.material, own.finish, own.origin) == ("//cmf:red", "//cmf:alu", "//cmf:satin", "declared")
    assert own.rgba == (201, 26, 9, 1.0)
    assert own.roughness == pytest.approx(0.6)
    assert recorded[shape_envelope.METADATA_CMF]["unspecified"] == {}
    # Copied, not changed in place: the envelope may be a cache's.
    assert _section_of(envelope) is None


def test_a_material_s_colour_claim_colours_a_part_that_states_no_colour(tmp_path):
    ctx = _package(tmp_path, {"box": _stl(material=":alu")}, files={"box.stl": ""})
    applied, _ = cmf.apply_declared(ctx, ctx.get_part("//cmf:box"), _envelope(), {})

    own = _section_of(applied).own()
    assert own.color == "//cmf:natural"
    assert own.rgba == (168, 169, 173, 1.0)


def test_the_geometry_is_the_geometry_it_was(tmp_path):
    pytest.importorskip("build123d")
    import ocp_serialize
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    ctx = _package(tmp_path, {"box": _stl(color=":red")}, files={"box.stl": ""})
    applied, _ = cmf.apply_declared(ctx, ctx.get_part("//cmf:box"), _envelope(), {})

    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(ocp_serialize.decode_shape(applied), TopAbs_FACE, faces)
    assert faces.Extent() == 6


def _faces_red_and_bare():
    # The first face red as the source says; the others say nothing.
    return Section(
        [CmfSet(color="//src:red", rgba=(255, 0, 0, 1.0), origin="source:step")], NONE, faces=[0] + [NONE] * 5
    )


def test_what_the_source_states_is_kept_and_the_rest_completed(tmp_path):
    ctx = _package(tmp_path, {"box": _stl(color=":natural")}, files={"box.stl": ""})
    applied, recorded = cmf.apply_declared(ctx, ctx.get_part("//cmf:box"), _envelope(_faces_red_and_bare()), {})

    section = _section_of(applied)
    assert section.face_set(0).color == "//src:red"
    assert {section.face_set(i).color for i in range(1, 6)} == {"//cmf:natural"}
    assert "color" not in recorded[shape_envelope.METADATA_CMF]["unspecified"]


def test_source_cmf_drop_replaces_what_the_source_states(tmp_path):
    parts = {"box": {**_stl(color=":natural"), "parameters": {**_declare(color=":natural", sourceCmf="drop")}}}
    ctx = _package(tmp_path, parts, files={"box.stl": ""})
    applied, _ = cmf.apply_declared(ctx, ctx.get_part("//cmf:box"), _envelope(_faces_red_and_bare()), {})

    section = _section_of(applied)
    assert {section.face_set(i).color for i in range(6)} == {"//cmf:natural"}


def test_one_payload_several_components_carry_is_given_one_section(tmp_path):
    ctx = _package(tmp_path, {"box": _stl(color=":red")}, files={"box.stl": ""})
    piece = _envelope()
    tree = {
        shape_envelope.KEY_ASSEMBLY: [
            {**piece, shape_envelope.KEY_CHILD: 0},
            {**piece, shape_envelope.KEY_CHILD: 1},
        ]
    }

    applied, recorded = cmf.apply_declared(ctx, ctx.get_part("//cmf:box"), tree, {})

    first, second = applied[shape_envelope.KEY_ASSEMBLY]
    assert first[shape_envelope.KEY_BREP] == second[shape_envelope.KEY_BREP]
    assert _section_of(first).own().color == "//cmf:red"
    assert len(recorded[shape_envelope.METADATA_CMF]["sets"]) == 1


def test_summaries_of_several_payloads_add_up():
    one = Section([CmfSet(color="//c:a", rgba=(1, 2, 3, 1.0))], NONE, faces=[0, NONE]).summary()
    other = Section().summary()
    merged = cmf_section.merge_summaries([one, other])
    # Some faces have a colour; neither payload has a material anywhere.
    assert merged["unspecified"] == {"color": "some", "material": "all"}
    assert cmf_section.merge_summaries([one]) is one
    assert cmf_section.merge_summaries([one, Section([CmfSet(material="//m:x")], 0).summary()])["unspecified"] == {
        "color": "some",
        "material": "some",
    }


# -------------------------------------------------------------- assemblies

WALL = """
links:
  - part: brick
    name: one
  - part: red_brick
    name: two
    location: [[0, 20, 0], [0, 0, 1], 0]
  - part: brick
    name: three
    location: [[0, 40, 0], [0, 0, 1], 0]
    params:
      color: :preview
"""


def _walls(tmp_path, **wall):
    return _package(
        tmp_path,
        {"brick": _stl(), "red_brick": {"type": "enrich", "source": "brick", "with": {"color": ":red"}}},
        {
            "wall": {"type": "assy", "path": "wall.assy", **wall},
            "stone_wall": {"type": "enrich", "source": "wall", "with": {"color": ":natural"}},
        },
        files={"box.stl": "", "brick.stl": "", "wall.assy": WALL},
    )


def _children(ctx, name):
    assembly = ctx.get_assembly(name)
    asyncio.run(assembly.do_instantiate())
    return {child.name: child for child in assembly.connected_children()}


def test_an_assembly_s_cmf_passes_to_what_states_none(tmp_path):
    children = _children(_walls(tmp_path), "//cmf:stone_wall")

    assert children["one"].item.name == "brick;color=//cmf:natural"
    # A variant an enrich fixes stays the variant it is...
    assert children["two"].item.name == "red_brick"
    # ...and so does what a link's own 'params:' say.
    assert children["three"].item.name == "brick;color=//cmf:preview"


def test_a_link_s_own_cmf_is_recorded_on_the_child(tmp_path):
    children = _children(_walls(tmp_path), "//cmf:wall")

    assert children["one"].cmf_parameters == ()
    assert children["three"].cmf_parameters == ("color",)
    assert children["one"].item.name == "brick"


def test_an_assembly_that_sets_cmf_is_reported(tmp_path):
    ctx = _walls(tmp_path)
    for name, setters in [
        ("//cmf:wall", ["the link 'three' sets 'color'"]),
        ("//cmf:stone_wall", ["its own 'color'", "the link 'three' sets 'color'"]),
    ]:
        assembly = ctx.get_assembly(name)
        asyncio.run(assembly.do_instantiate())
        assert cmf.assembly_cmf_setters(assembly) == setters
        assert "vendor" in cmf_check.assembly_findings(ctx, assembly)[0]


def test_an_assembly_bought_whole_is_judged_by_its_own_cmf(tmp_path):
    ctx = _walls(tmp_path, vendor="Acme", sku="W-1")
    assembly = ctx.get_assembly("//cmf:wall")
    asyncio.run(assembly.do_instantiate())

    assert cmf_check.assembly_findings(ctx, assembly) == []
    assert cmf_check.CmfTest().inapplicable(assembly) is None


# ------------------------------------------------------------- the check


class _Built:
    """A part as the check reads it: its package, and the summary recorded with its geometry."""

    def __init__(self, summary):
        self.project_name = "//cmf"
        self._metadata = {shape_envelope.METADATA_CMF: summary} if summary is not None else {}


def test_a_part_to_be_made_needs_a_colour_and_a_material(tmp_path):
    ctx = _package(tmp_path)
    own_only = Section([CmfSet(color="//cmf:red", rgba=(201, 26, 9, 1.0))], 0).summary()

    assert cmf_check.part_findings(ctx, _Built(None)) == ["it states no colour and no material"]
    assert cmf_check.part_findings(ctx, _Built(own_only)) == ["no material on any solid"]


def test_a_display_only_colour_is_not_a_specification(tmp_path):
    ctx = _package(tmp_path)
    preview = Section([CmfSet(color="//cmf:preview", material="//cmf:alu", rgba=(0, 255, 0, 1.0))], 0).summary()
    rgba = Section(
        [CmfSet(color="//builtin/color:rgba;color=00FF00FF", material="//cmf:alu", rgba=(0, 255, 0, 1.0))], 0
    ).summary()

    assert cmf_check.part_findings(ctx, _Built(preview)) == [
        "the color '//cmf:preview' is display-only (manufacturable: false)"
    ]
    assert "display-only" in cmf_check.part_findings(ctx, _Built(rgba))[0]


def test_a_specified_part_passes(tmp_path):
    ctx = _package(tmp_path)
    specified = Section([CmfSet(color="//cmf:red", material="//cmf:alu", finish="//cmf:satin")], 0).summary()

    assert cmf_check.part_findings(ctx, _Built(specified)) == []


def test_a_part_an_assembly_is_made_of_is_held_to_its_cmf_whatever_it_says_of_itself(tmp_path, caplog):
    """The manufacturability walk over a manufacturable assembly's parts forces them to be made."""
    ctx = _package(tmp_path)

    class _NotMade(_Built):
        name = "box"
        config = {}
        is_manufacturable = False

        async def get_wrapped(self, ctx):
            return {}

    part = _NotMade(None)
    check = cmf_check.CmfTest()

    assert check.inapplicable(part) is not None
    assert check.inapplicable(part, forced=True) is None

    with caplog.at_level(logging.WARNING):
        asyncio.run(check.test([check], ctx, part, {}))
    assert "CMF not specified" not in caplog.text

    with caplog.at_level(logging.WARNING):
        asyncio.run(check.test([check], ctx, part, {cmf_check.CmfTest.FORCE_MANUFACTURING: True}))
    assert "CMF not specified: it states no colour and no material" in caplog.text


def test_the_check_is_registered_and_catalogued():
    from partcad.test import all as all_tests
    from partcad.test import catalog

    assert "cmf" in [test.name for test in all_tests.tests(4)]
    assert catalog.describe("cmf")["title"]


# ------------------------------------------------------------- drawings


def test_a_drawing_colours_each_face_as_the_section_says():
    pytest.importorskip("build123d")
    import appearance
    import ocp_serialize

    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    grey = CmfSet(color="//c:grey", rgba=(128, 128, 128, 1.0))
    envelope = _envelope(Section([red, grey], 1, faces=[0, 0] + [NONE] * 4))
    whole, tree = ocp_serialize.decode_tree(envelope)

    groups = appearance.split_by_color(tree, whole)

    assert [color for color, _shape in groups] == ["#FF0000", "#808080"]
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    def faces(shape):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, found)
        return found.Extent()

    assert [faces(shape) for _color, shape in groups] == [2, 4]


def test_a_part_in_one_colour_is_drawn_whole():
    """The drawing it was before: nothing split, nothing read but the summary."""
    pytest.importorskip("build123d")
    import appearance
    import ocp_serialize

    envelope = _envelope(Section([CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))], 0))
    whole, tree = ocp_serialize.decode_tree(envelope)

    assert appearance.face_colors(tree) is None
    assert appearance.split_by_color(tree, whole) == [(appearance.DEFAULT_COLOR, whole)]


def test_a_glb_has_a_material_per_colour_its_faces_are_in():
    pytest.importorskip("build123d")
    import json
    import struct

    import wrapper_gltf

    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    envelope = _envelope(Section([red], NONE, faces=[0, 0] + [NONE] * 4))

    answer = wrapper_gltf.process({"shapes": [{"digest": "d", "brep": envelope["brep"]}], "tolerance": 0.1})
    glb = answer["geometry"]["d"]
    length = struct.unpack("<I", glb[12:16])[0]
    document = json.loads(glb[20 : 20 + length])

    assert [m["pbrMetallicRoughness"]["baseColorFactor"] for m in document["materials"]] == [[1.0, 0.0, 0.0, 1.0]]
    assert sorted(p.get("material", -1) for mesh in document["meshes"] for p in mesh["primitives"]) == [-1, 0]


def test_pc_info_says_what_the_cmf_comes_to(tmp_path):
    ctx = _package(tmp_path)
    summary = Section(
        [CmfSet(color="//cmf:preview", material="//cmf:alu", rgba=(0, 255, 0, 1.0), origin="declared")], 0
    ).summary()

    info = cmf.info_of(ctx, summary, "//cmf")

    assert info == {
        "sets": [
            {
                "color": "//cmf:preview",
                "material": "//cmf:alu",
                "displayOnly": ["color"],
                "display": "#00FF00FF",
                "origin": "declared",
                "faces": "all",
                "solids": "all",
            }
        ]
    }
    assert list(info["sets"][0])[:2] == ["color", "material"]


def test_two_packages_sharing_a_part_s_geometry_each_get_their_own_cmf(tmp_path):
    """Applied as the part is read, never cached: the key does not cover what a declaration says."""
    pytest.importorskip("build123d")
    roots = []
    for name, display in [("one", "#C91A09"), ("two", "#0055BF")]:
        root = tmp_path / name
        root.mkdir()
        (root / "partcad.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "//" + name,
                    "colors": {"brand": {"display": display}},
                    "parts": {"box": {"type": "build123d", "path": "box.py", "parameters": _declare(color=":brand")}},
                }
            )
        )
        (root / "box.py").write_text("from build123d import Box\nshow_object(Box(1, 2, 3))\n")
        roots.append(root)

    seen = []
    for root, name in zip(roots, ["one", "two"]):
        ctx = pc.Context(str(root))
        part = ctx.get_part("//%s:box" % name)
        envelope = asyncio.run(part.get_wrapped(ctx))
        seen.append(_section_of(envelope).own().color)

    assert seen == ["//one:brand", "//two:brand"]


def test_what_a_drawing_is_keyed_on_covers_each_node_s_cmf():
    """A part given another colour is drawn again, not served the old drawing from the cache.

    A drawing or an export of a tree is keyed on the shape's key and the tree's
    description, and the shape's key does not cover CMF: it is applied as the
    shape is read. So the description keeps each node's CMF summary, and a node
    with none describes as it always did.
    """

    def tree(color):
        child = {"name": "panel", "brep": b"geometry", "metadata": {"measurements": {"volume": 1.0}}}
        if color is not None:
            child["metadata"]["cmf"] = {"sets": [{"color": color, "display": "#B40000FF", "faces": "all"}]}
        return {"name": "sidepod", "assembly": [child]}

    plain = shape_envelope.description(tree(None))
    assert plain == {"name": "sidepod", "assembly": [{"name": "panel"}]}

    red = shape_envelope.description(tree("//pub/universe/lego:Bright Red"))
    black = shape_envelope.description(tree("//pub/universe/lego:Black"))
    assert red["assembly"][0]["cmf"]["sets"][0]["color"] == "//pub/universe/lego:Bright Red"
    assert red != black
    assert "measurements" not in str(red)


def test_an_assembly_is_keyed_on_what_its_items_cmf_comes_to(tmp_path):
    """Its cached tree holds its parts as they were read, CMF and all, so a colour drawn otherwise is a new key.

    A part's own key does not cover CMF (see the test above): it would serve
    the old colours inside the assembly's tree. An assembly whose items state
    none keeps the key it had.
    """
    from partcad import cmf as pc_cmf

    def key(display):
        root = tmp_path / display.lstrip("#")
        root.mkdir()
        ctx = _package(
            root,
            {"brick": _stl(), "red_brick": {"type": "enrich", "source": "brick", "with": {"color": ":red"}}},
            {"wall": {"type": "assy", "path": "wall.assy"}},
            files={"box.stl": "", "brick.stl": "", "wall.assy": WALL},
            colors=dict(COLORS, red={"display": display}),
        )
        return asyncio.run(ctx.get_assembly("//cmf:wall").get_cache_key_async()), ctx

    red, ctx = key("#C91A09")
    darker, _ = key("#7A0E06")
    assert red is not None and darker is not None
    assert red != darker

    # An item that states nothing adds only what its source's CMF would be
    # converted by: its package declares colours.
    assert set(pc_cmf.key_of(ctx, ctx.get_part("//cmf:brick"))) == {"version", "scope"}
    described = pc_cmf.key_of(ctx, ctx.get_part("//cmf:red_brick"))
    assert described["color"]["reference"] == "//cmf:red"
    assert described["color"]["manufacturable"] is True


def test_an_assembly_is_keyed_on_how_its_items_finishes_are_drawn(tmp_path):
    """A finish's roughness and metallic are in the payload as much as a colour's display is."""

    def described(roughness):
        root = tmp_path / str(roughness)
        root.mkdir()
        ctx = _package(
            root,
            {"box": _stl(finish=":satin")},
            files={"box.stl": ""},
            finishes={"satin": {"display": {"roughness": roughness, "metallic": 0}}},
        )
        return cmf.key_of(ctx, ctx.get_part("//cmf:box"))

    satin = described(0.6)
    assert satin["finish"]["roughness"] == 0.6 and satin["finish"]["metallic"] == 0
    assert described(0.2) != satin


def test_a_package_may_require_its_parts_cmf(tmp_path):
    """'cmf: {require: true}' on the package is read through the context: the object carries no package."""
    (tmp_path / "strict").mkdir()
    (tmp_path / "lenient").mkdir()
    required = _package(tmp_path / "strict", {"plain": _stl()}, files={"box.stl": ""}, cmf={"require": True})
    lenient = _package(tmp_path / "lenient", {"plain": _stl()}, files={"box.stl": ""})
    assert cmf_check._required(required, required.get_part("//cmf:plain")) is True
    assert cmf_check._required(lenient, lenient.get_part("//cmf:plain")) is False


def test_own_parameters_resolve_an_alias_through_the_context(tmp_path):
    """A part naming ':stone', an alias, states the declaration the alias names."""
    ctx = _package(
        tmp_path,
        {"box": _stl(color=":stone")},
        files={"box.stl": ""},
        colors=dict(COLORS, stone={"type": "alias", "source": ":red"}),
    )
    part = ctx.get_part("//cmf:box")
    assert cmf.own_parameters(part, ctx) == {"color": "//cmf:red"}


def test_a_source_section_rides_through_a_transform():
    """An 'offset' or a 'scale' rebuilds the payload with no section, and the source's is laid back."""
    stated = _faces_red_and_bare()
    with_section = _envelope(stated)
    assert cmf.payload_section(with_section).faces == stated.faces

    rebuilt = _envelope()
    assert cmf.payload_section(rebuilt) is None
    restored = cmf.with_payload_section(rebuilt, cmf.payload_section(with_section))
    assert _section_of(restored).faces == stated.faces
    # A payload that carries a section of its own keeps it.
    assert cmf.with_payload_section(with_section, Section([], NONE)) is with_section


def test_a_section_written_for_other_geometry_is_drawn_in_the_node_s_colour():
    """A section addressing more faces than the shape has says nothing true of it, and is not a crash."""
    pytest.importorskip("build123d")
    import appearance
    import ocp_serialize

    red = CmfSet(color="//c:red", rgba=(255, 0, 0, 1.0))
    grey = CmfSet(color="//c:grey", rgba=(128, 128, 128, 1.0))
    envelope = _envelope(Section([red, grey], 1, faces=[0, 0] + [NONE] * 6))
    whole, tree = ocp_serialize.decode_tree(envelope)

    groups = appearance.split_by_color(tree, whole)

    assert [color for color, _shape in groups] == [appearance.DEFAULT_COLOR]


def test_a_display_only_colour_is_its_own_reference_and_no_claim(tmp_path, monkeypatch):
    """'//builtin/color:rgba;color=…' states itself in full: no package is asked, and it claims nothing."""
    ctx = _package(tmp_path, {"box": _stl(color="//builtin/color:rgba;color=c91a09ff")}, files={"box.stl": ""})
    asked = []
    real = cmf.lookup

    def recording(ctx, kind, ref, *args, **kwargs):
        asked.append(ref)
        return real(ctx, kind, ref, *args, **kwargs)

    monkeypatch.setattr(cmf, "lookup", recording)
    reference = cmf.canonical(ctx, "color", "//builtin/color:rgba;color=c91a09ff")
    assert reference == "//builtin/color:rgba;color=C91A09FF"
    described = cmf.key_of(ctx, ctx.get_part("//cmf:box"))
    assert described["color"] == {"reference": reference, "display": [201, 26, 9, 1.0], "manufacturable": False}
    assert not [ref for ref in asked if ref.startswith("//builtin/color:rgba")]


def test_an_alias_of_a_parametric_instance_is_listed_by_its_look(tmp_path):
    """An alias naming 'rgba;color=…' shows that colour, and keeps the description it gives itself."""
    from partcad_service_json_rpc.core import operations

    ctx = _package(
        tmp_path,
        files={"box.stl": ""},
        colors=dict(
            COLORS,
            rgba={"parameters": {"color": {"type": "string", "default": "000000FF"}}, "display": "#%color%"},
            signal={"type": "alias", "source": ":rgba;color=C91A09FF", "desc": "the signal red"},
        ),
    )
    rows = operations._cmf_rows(ctx, ctx.get_project("//cmf"), "color")
    assert rows["rgba"].startswith("parametric")
    assert rows["signal"].startswith("#C91A09")
    assert "the signal red" in rows["signal"]


def test_an_edge_that_bounds_no_face_is_drawn_in_the_node_s_colour():
    """Splitting a shape by its faces' colours keeps a free edge, in the node's own colour."""
    pytest.importorskip("build123d")
    import appearance
    import build123d as bd
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    free = bd.Edge.make_line((50, 0, 0), (60, 0, 0)).wrapped
    shape = bd.Compound([bd.Box(10, 20, 30), bd.Edge(free)]).wrapped
    groups = dict(appearance.faces_by_color(shape, ["#FF0000"] * 2 + [None] * 4, "#808080"))

    def edges(group):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(group, TopAbs_EDGE, found)
        return found

    assert set(groups) == {"#FF0000", "#808080"}
    assert edges(groups["#808080"]).Contains(free)
    assert not edges(groups["#FF0000"]).Contains(free)


def test_an_assembly_that_will_not_instantiate_fails_the_check_rather_than_the_run(tmp_path, monkeypatch):
    """A broken link fails the 'cmf' check for that assembly; it does not stop 'pc test'."""
    ctx = _walls(tmp_path)
    assembly = ctx.get_assembly("//cmf:wall")

    async def broken():
        raise RuntimeError("a link names nothing")

    monkeypatch.setattr(assembly, "do_instantiate", broken)
    check = cmf_check.CmfTest()
    failed = []
    monkeypatch.setattr(check, "failed", lambda shape, message: failed.append(message) or False)
    assert asyncio.run(check.test([], ctx, assembly, {})) is False
    assert "a link names nothing" in failed[0]
