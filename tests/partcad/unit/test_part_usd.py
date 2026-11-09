#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 'usd' part type: an OpenUSD stage, read with usd-core or with cadmpeg.

What is declared is checked without a sandbox: the type, the release of
cadmpeg it reads with, and that its script is keyed for both. What the script
does with what a reader found - placing CADIR's meshes, turning a Y-up stage
onto Z, the colours, the faces it builds - is checked in this process, with
numpy and OCP. What is read is checked by building the parts of
'data/import_usd' in the sandbox, each one with both readers, and holding the
two to the same shape.
"""

import asyncio
import importlib.util
import os
import uuid

import numpy
import pytest
import yaml
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape

import partcad as pc
from partcad import code_version, output

BUILTIN_IMPORT = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]
PACKAGE = "tests/partcad/unit/data/import_usd/partcad.yaml"

# The cadmpeg release the script was last keyed for, and the cache version it
# was keyed with: a release that reads OpenUSD further reads the same stage
# into other geometry, under the same key unless this moves with it.
USD_KEYED_FOR = "0.6.8"
KEYED_FOR = 3


def _module(script):
    spec = importlib.util.spec_from_file_location("%s_under_test" % script[:-3], os.path.join(BUILTIN_IMPORT, script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


part_usd = _module("part_usd.py")
usd_look = _module("usd_look.py")


@pytest.fixture(scope="module")
def declared():
    with open(os.path.join(BUILTIN_IMPORT, "partcad.yaml")) as f:
        return yaml.safe_load(f)["partTypes"]["usd"]


# ---------------------------------------------------------------------------
# What is declared
# ---------------------------------------------------------------------------


def test_the_type_reads_a_stage_with_the_usd_core_it_pins_and_its_images_with_the_pillow_the_renderers_pin(declared):
    assert declared["path"] == "part_usd.py"
    assert declared["extension"] == "usd"
    usd_core, usd_core_for_3_10, pillow = declared["pythonRequirements"]
    # 26.11 is Python 3.11 and newer; a package on 3.10 gets the last release that has it.
    assert usd_core == 'usd-core==26.11; python_version >= "3.11"'
    assert usd_core_for_3_10 == 'usd-core==25.11; python_version < "3.11"'
    with open(os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]], "partcad.yaml")) as f:
        renderers = yaml.safe_load(f)["render"]
    pinned = {r for each in renderers.values() if isinstance(each, dict) for r in each.get("pythonRequirements") or []}
    assert pillow in pinned and pillow.startswith("pillow==")


def test_a_stage_that_is_no_solid_is_a_part_all_the_same(declared):
    """What a renderer draws need not close: a stage is built and reported, not failed."""
    assert not declared.get("requireSolid")


def test_the_files_a_part_lists_are_what_it_is_kept_for_besides_its_own(ctx):
    """A wrapper part's 'dependencies' are part of its cache key, as an OpenSCAD part's are."""
    here = os.path.abspath(os.path.dirname(PACKAGE))
    listed = ctx.get_part(":bracket_listed")
    assert [os.path.abspath(path) for path in listed.cache_dependencies] == [
        os.path.join(here, name) for name in ("bracket.usda", "halves.bmp")
    ]
    # A part that names none depends on its own file, and on what its build reports.
    assert [os.path.abspath(path) for path in ctx.get_part(":bracket").cache_dependencies] == [
        os.path.join(here, "bracket.usda")
    ]


def test_the_type_says_it_reports_the_files_it_reads(declared):
    assert declared["reportsDependencies"] is True


def test_the_script_is_keyed_for_the_cadmpeg_it_reads_openusd_with():
    tool = _module("cadmpeg_tool.py")
    assert tool.USD_VERSION == USD_KEYED_FOR, (
        "cadmpeg_tool.py reads OpenUSD with cadmpeg %s, and part_usd.py was keyed for %s. Raise its CACHE_VERSION, "
        "then update USD_KEYED_FOR and KEYED_FOR here." % (tool.USD_VERSION, USD_KEYED_FOR)
    )
    assert code_version.declared(os.path.join(BUILTIN_IMPORT, "part_usd.py")) == KEYED_FOR
    # Another release, beside the one every other format is read with.
    assert set(tool.USD_ASSETS) == set(tool.ASSETS)


def test_every_spelling_of_a_stage_is_the_usd_type():
    from partcad.shape import PART_EXTENSION_ALIASES

    assert {alias for alias, aliased in PART_EXTENSION_ALIASES.items() if aliased == "usd"} == {"usda", "usdc", "usdz"}


# ---------------------------------------------------------------------------
# What the script makes of what a reader found
# ---------------------------------------------------------------------------


def test_a_polygon_is_a_fan_and_a_hole_is_left_out():
    triangles = part_usd.fan([4, 3, 3], [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], holes=[2])
    assert triangles.tolist() == [[0, 1, 2], [0, 2, 3], [4, 5, 6]]


def test_a_polygon_s_triangles_know_their_face_and_their_face_vertices():
    triangles, corners, faces = part_usd.fan_corners([4, 3], [7, 8, 9, 10, 11, 12, 13])
    assert triangles.tolist() == [[7, 8, 9], [7, 9, 10], [11, 12, 13]]
    # What a face-varying primvar is indexed by: the place in the face-vertex list.
    assert corners.tolist() == [[0, 1, 2], [0, 2, 3], [4, 5, 6]]
    assert faces.tolist() == [0, 0, 1]


def test_corners_are_welded_and_triangles_of_no_area_dropped():
    vertices = numpy.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1e-6, 0, 0], [2, 0, 0]], dtype=float)
    points, triangles = part_usd.welded(vertices, numpy.array([[0, 1, 2], [3, 1, 2], [0, 1, 4]]))
    # The first two corners are one; the third triangle is a line, and dropped.
    assert len(points) == 4
    assert triangles.tolist() == [[0, 2, 1], [0, 2, 1]]


def _occurrence(path, parent=None, transform=None, definition=None, visible=None):
    found = {
        "id": "o" + path,
        "native_ref": path,
        "prototype": {"scope": "local", "definition": definition or "d" + path},
        "parent": {"kind": "occurrence", "occurrence": "o" + parent} if parent else {"kind": "root"},
        "transform": transform or [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
        "scale": [1, 1, 1],
    }
    if visible is not None:
        found["visible"] = visible
    return found


TRIANGLE = {"kind": "list", "vertices": [(0, 0, 0), (10, 0, 0), (0, 10, 0)], "triangles": [[0, 1, 2]]}


def _cadir(up="Y", default="World", occurrences=None, **model):
    return {
        "units": {"length": "millimeter"},
        "source": {"attributes": {"default_prim": default, "up_axis": up}},
        "model": {
            "occurrences": occurrences
            or [
                _occurrence("/World"),
                _occurrence("/World/arm", "/World", [[0, 0, 2, 100], [0, 2, 0, 0], [-2, 0, 0, 0]]),
                _occurrence("/World/arm/m", "/World/arm", [[1, 0, 0, 0], [0, 3, 0, 0], [0, 0, 1, 50]]),
                _occurrence("/Studio"),
                _occurrence("/Studio/floor", "/Studio"),
            ],
            "product_definitions": [
                {"id": "d/World/arm/m", "bodies": ["b/m"]},
                {"id": "d/Studio/floor", "bodies": ["b/floor"]},
            ],
            "bodies": [{"id": "b/m", "color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}}, {"id": "b/floor"}],
            "tessellations": [
                {"id": "t/m", "body": "b/m", "mesh": TRIANGLE},
                {"id": "t/f", "body": "b/floor", "mesh": TRIANGLE},
            ],
            **model,
        },
    }


def _triangles(model):
    return sum(len(triangles) for _, triangles, _ in model.pieces)


def test_cadmpeg_s_meshes_are_placed_by_their_occurrences_and_turned_onto_z():
    model = part_usd.cadir_model(_cadir())
    dropped = model.dropped
    ((vertices, triangles, _),) = model.pieces
    # (10, 0, 0) is (10, 0, 50) in the triangle's parent, and (200, 0, -20) in
    # the stage, Y up: (200, 20, 0) with Z up. As usd-core reads the same stage.
    assert vertices.round(6).tolist() == [[200, 0, 0], [200, 20, 0], [200, 0, 60]]
    assert triangles.tolist() == [[0, 1, 2]]
    assert dropped == {}


def test_cadmpeg_s_stage_is_its_default_prim_unless_a_prim_is_asked_for():
    assert _triangles(part_usd.cadir_model(_cadir())) == 1
    assert _triangles(part_usd.cadir_model(_cadir(), prim="/")) == 2
    assert _triangles(part_usd.cadir_model(_cadir(), prim="/Studio")) == 1
    with pytest.raises(ValueError, match="no prim"):
        part_usd.cadir_model(_cadir(), prim="/Nowhere")


def test_what_cadmpeg_says_is_hidden_is_not_built():
    hidden = _cadir(
        occurrences=[_occurrence("/World"), _occurrence("/World/arm", "/World", visible=False),
                     _occurrence("/World/arm/m", "/World/arm")]  # fmt: skip
    )
    assert part_usd.cadir_model(hidden).pieces == []


def test_a_look_is_the_triangle_group_s_else_the_mesh_s_else_the_body_s_and_a_texture_not_found_gives_no_colour():
    model = _cadir(
        appearances=[
            {"id": "blue", "name": "Blue", "base_color": {"r": 0.0, "g": 0.0, "b": 1.0, "a": 1.0}},
            {"id": "textured", "name": "Wood", "base_color": {"r": 0.5, "g": 0.5, "b": 0.5},
             "textures": [{"slot": "diffuseColor", "paths": ["wood.png"]}]},
        ],
        appearance_bindings=[
            {"target": {"kind": "triangle_group", "id": {"tessellation": "t/m", "group": "/World/arm/m/blue"}},
             "appearance": "blue"},
            {"target": {"kind": "tessellation", "id": "t/f"}, "appearance": "textured"},
        ],
    )  # fmt: skip
    mesh = dict(TRIANGLE, vertices=[(0, 0, 0), (10, 0, 0), (0, 10, 0), (10, 10, 0)], triangles=[[0, 1, 2], [1, 3, 2]])
    model["model"]["tessellations"][0] = {
        "id": "t/m",
        "body": "b/m",
        "mesh": mesh,
        "triangle_groups": [{"source_id": "/World/arm/m/blue", "triangles": [1]}],
    }
    read = part_usd.cadir_model(model, prim="/")
    counted = {}
    for _, _, looks in read.pieces:
        for look in looks.tolist():
            counted[read.looks[look]] = counted.get(read.looks[look], 0) + 1
    assert counted == {
        ("Blue", (0, 0, 255, 1.0), None, None, None): 1,
        ("displayColor", (255, 0, 0, 1.0), None, None, None): 1,
        # The texture is in no package here: the look is the appearance's, and no colour is made up.
        ("Wood", None, None, None, None): 1,
    }


def test_a_b_rep_body_is_counted_and_left_out():
    model = _cadir()
    model["model"]["bodies"][0]["regions"] = ["r0"]
    model["model"]["tessellations"] = [model["model"]["tessellations"][1]]
    read = part_usd.cadir_model(model)
    assert read.pieces == []
    assert read.dropped == {"B-rep body (read it with 'usd-core')": 1}


def test_too_many_triangles_from_cadmpeg_says_what_to_do():
    with pytest.raises(part_usd.TooManyTriangles, match="build a 'prim'"):
        part_usd.cadir_model(_cadir(), prim="/", max_triangles=1)


def test_the_cadmpeg_reader_refuses_what_it_cannot_read_rather_than_reading_something_else(tmp_path):
    with pytest.raises(ValueError, match="purpose"):
        part_usd.read_cadmpeg(str(tmp_path / "x.usda"), str(tmp_path), purpose="proxy", cadmpeg="cadmpeg")
    with pytest.raises(ValueError, match="time"):
        part_usd.read_cadmpeg(str(tmp_path / "x.usda"), str(tmp_path), time="12", cadmpeg="cadmpeg")


def test_an_unknown_reader_is_refused():
    answer = part_usd.run({"path": "stage.usda", "parameters": {"reader": "blender"}})
    assert "'reader' is one of usd-core, cadmpeg" in answer["exception"]


# ---------------------------------------------------------------------------
# What a face looks like ('usd_look'), where it needs no usd-core
# ---------------------------------------------------------------------------


def test_an_mdl_preset_is_read_as_the_material_it_calls():
    kind, arguments = usd_look.parse_mdl_preset(
        """mdl 1.4;
        using ::OmniPBR import OmniPBR;
        // a comment: color(9, 9, 9)
        export material Aluminium_Brushed_A(*)
         = OmniPBR(
            diffuse_texture: texture_2d("../textures/T_Albedo.png", ::tex::gamma_srgb),
            diffuse_color_constant: color(0.1, 0.2f, 0.3),
            enable_ORM_texture: true,
            metallic_texture_influence: 1.0,
            reflection_roughness_constant: 0.35,
            normalmap_texture: texture_2d("../textures/T_Normal.png", ::tex::gamma_linear));""",
        "Aluminium_Brushed_A",
    )
    assert kind == "OmniPBR"
    assert arguments == {
        "diffuse_texture": ("asset", "../textures/T_Albedo.png"),
        "diffuse_color_constant": (0.1, 0.2, 0.3),
        "enable_ORM_texture": True,
        "metallic_texture_influence": 1.0,
        "reflection_roughness_constant": 0.35,
        "normalmap_texture": ("asset", "../textures/T_Normal.png"),
    }
    assert usd_look.parse_mdl_preset("mdl 1.4; export material X() = df::diffuse_reflection_bsdf();") is None


def test_what_an_mdl_preset_names_is_found_beside_it_in_its_package_or_out_of_one():
    assert usd_look._beside("/a/b.usdz[materials/x.mdl]", "../textures/t.png") == "/a/b.usdz[textures/t.png]"
    assert usd_look._beside("/a/materials/x.mdl", "../textures/t.png") == os.path.normpath("/a/textures/t.png")


def test_a_file_is_read_out_of_a_package_or_off_the_disk(tmp_path):
    import zipfile

    with zipfile.ZipFile(tmp_path / "p.usdz", "w") as z:
        z.writestr("textures/t.txt", b"inside")
    (tmp_path / "t.txt").write_bytes(b"outside")
    assert usd_look.read_bytes("%s[textures/t.txt]" % (tmp_path / "p.usdz")) == b"inside"
    assert usd_look.read_bytes(str(tmp_path / "t.txt")) == b"outside"
    assert usd_look.read_bytes("%s[nothing]" % (tmp_path / "p.usdz")) is None


def test_colours_read_face_by_face_are_a_palette_of_at_most_max_looks():
    count = 5000
    rng = numpy.random.default_rng(1)
    rgb = rng.uniform(0, 255, (count, 3))
    nothing = numpy.full(count, numpy.nan)
    looks, ids = usd_look.settle(
        numpy.zeros(count, dtype=int), rgb, nothing, nothing, nothing, numpy.full(count, -1), ["Paint"], []
    )
    assert 1 < len(looks) <= usd_look.MAX_LOOKS
    assert len(ids) == count and ids.max() == len(looks) - 1
    # Each is near the colour it was read as - on average, for colours as spread as these can be.
    drawn = numpy.array([looks[i][1][:3] for i in ids], dtype=float)
    assert numpy.abs(drawn - rgb).mean() <= 16


def test_a_palette_keeps_a_dark_colour_s_hue():
    """What rounding each channel to a coarse step does not: (40, 55, 58) stays a grey-green, not teal."""
    count = 4000
    rng = numpy.random.default_rng(2)
    rgb = numpy.vstack([rng.normal((40, 55, 58), 3, (count // 2, 3)), rng.normal((200, 120, 40), 3, (count // 2, 3))])
    nothing = numpy.full(count, numpy.nan)
    looks, ids = usd_look.settle(
        numpy.zeros(count, dtype=int), rgb, nothing, nothing, nothing, numpy.full(count, -1), ["Board"], []
    )
    drawn = numpy.array([looks[i][1][:3] for i in ids], dtype=float)
    assert numpy.abs(drawn[: count // 2].mean(axis=0) - (40, 55, 58)).max() < 4


def test_a_look_says_nothing_it_was_not_told():
    count = 3
    looks, ids = usd_look.settle(
        numpy.array([0, 0, 1]),
        numpy.array([[255.0, 0, 0], [255.0, 0, 0], [numpy.nan] * 3]),
        numpy.array([numpy.nan, numpy.nan, 0.5]),
        numpy.array([0.2, 0.2, numpy.nan]),
        numpy.array([1.0, 1.0, numpy.nan]),
        numpy.array([0, 0, -1]),
        ["Steel", "displayColor"],
        ["metal"],
    )
    assert sorted(looks, key=str) == sorted(
        [("Steel", (255, 0, 0, 1.0), 0.2, 1.0, "metal"), ("displayColor", None, None, None, None)], key=str
    )
    assert ids[0] == ids[1] != ids[2]
    assert count == len(ids)


def test_linear_and_srgb_are_each_other_s_inverse():
    values = numpy.linspace(0, 1, 11)
    assert usd_look.srgb_of_linear(usd_look.linear_of_srgb(values)) / 255.0 == pytest.approx(values, abs=1e-9)
    assert usd_look.srgb_of_linear([0.5]).round().tolist() == [188.0]


def _count(shape, kind):
    """How many distinct sub-shapes of 'kind': an edge two faces share is one."""
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found.Extent()


RED = ("Paint", (255, 0, 0, 1.0), 0.4, 1.0, "steel")
SQUARES = part_usd.Model(
    [
        (numpy.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float), numpy.array([[0, 1, 2], [0, 2, 3]]),
         numpy.array([0, 0])),
        (numpy.array([[0, 0, 1], [1, 0, 1], [0, 1, 1]], float), numpy.array([[0, 1, 2]]), numpy.array([1])),
    ],
    [RED, (None, None, None, None, None)],
    {},
)  # fmt: skip


@pytest.mark.parametrize("surface, faces, edges", [("faces", 3, 8), ("auto", 3, 8), ("mesh", 2, 0)])
def test_the_shape_is_a_face_per_triangle_or_a_mesh_per_look(surface, faces, edges):
    shape, cmf = part_usd.build(SQUARES, surface)
    assert _count(shape, TopAbs_FACE) == faces
    # Two triangles sharing an edge share it: 5 edges a square, not 6.
    assert _count(shape, TopAbs_EDGE) == edges
    red = {"color": "Paint", "rgba": [255, 0, 0, 1.0], "roughness": 0.4, "metallic": 1.0, "material": "steel"}
    assert cmf == {"convention": "usd", "faces": [red] * (faces - 1) + [None]}


def test_a_look_is_said_as_the_usd_convention_s_set_with_nothing_made_up():
    assert part_usd.entry(("Glass", None, None, None, None)) == {"color": "Glass"}
    assert part_usd.entry((None, None, None, None, None)) is None
    assert part_usd.entry(None) is None


def test_a_closed_mesh_of_faces_is_a_valid_closed_shell_and_the_solid_it_bounds():
    cube = numpy.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    triangles = numpy.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))])
    closed = part_usd.Model([(cube, triangles, numpy.zeros(len(triangles), dtype=int))], [RED], {})
    shape, _ = part_usd.build(closed, "faces")
    assert BRepCheck_Analyzer(shape).IsValid()
    # Every face facing out: the solid PartCAD states of it is a cube, not nothing.
    import sys

    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import wrapper_common

    solid = wrapper_common.solidify(shape)
    assert wrapper_common.solid_problems(solid) == []
    assert _volume(solid) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="'surface' is one of"):
        part_usd.build(closed, "nurbs")


# ---------------------------------------------------------------------------
# What is read, by each reader, in the sandbox
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(PACKAGE)


def _built(ctx, name):
    import sys

    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import ocp_serialize

    part = ctx.get_part(name)
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    return ocp_serialize.decode_shape(envelope)


def _box(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    return [round(v, 3) for v in box.Get()]


def _volume(shape):
    total = 0.0
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, found)
    for index in range(1, found.Extent() + 1):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(found.FindKey(index), props)
        total += props.Mass()
    return total


@pytest.mark.slow
@pytest.mark.parametrize("name", [":bracket", ":bracket_cadmpeg"])
def test_a_closed_box_is_the_solid_it_bounds_and_nothing_beside_it(ctx, name):
    """The default prim, in millimetres; not the proxy, not the studio floor; closed, so a solid of 6000 mm^3."""
    shape = _built(ctx, name)
    assert _box(shape) == pytest.approx([0, 0, 0, 30, 20, 10], abs=1e-3)
    assert _volume(shape) == pytest.approx(6000.0, rel=1e-6)


@pytest.mark.slow
def test_both_readers_place_a_y_up_stage_in_centimetres_the_same_way(ctx):
    """A turned and scaled parent, three native instances, Y turned onto Z, centimetres made millimetres."""
    by_usd_core = _box(_built(ctx, ":scene"))
    assert by_usd_core == pytest.approx([0, 0, 0, 200, 20, 610], abs=1e-3)
    assert _box(_built(ctx, ":scene_cadmpeg")) == pytest.approx(by_usd_core, abs=1e-3)


@pytest.mark.slow
def test_each_face_is_in_the_look_its_stage_says_and_partcad_draws_it_so(ctx):
    """An image laid by UVs, a subset in a metal, a displayColor and an MDL preset, each to its faces, as a part."""
    from partcad import cmf

    part = ctx.get_part(":looks")
    asyncio.run(part.get_wrapped(ctx))
    summary = cmf.summary_of(part)
    by_display = {entry.get("display"): entry for entry in summary["sets"]}
    # Nothing in the package claims these names, so each is drawn as the stage says it looks.
    assert by_display["#FF0000FF"]["faces"] == 2 and by_display["#0000FFFF"]["faces"] == 2
    # A finish's values are kept a byte each: within 1/255 of what the stage says.
    near = lambda value: pytest.approx(value, abs=1 / 255)  # noqa: E731
    assert by_display["#FF0000FF"]["roughness"] == near(0.8)
    steel = by_display["#BCBCBCFF"]
    assert (steel["faces"], steel["roughness"], steel["metallic"]) == (2, near(0.2), near(1.0))
    assert by_display["#FFFF00FF"]["faces"] == 12
    brushed = by_display["#597C95FF"]
    assert (brushed["roughness"], brushed["metallic"]) == (near(0.3), near(1.0))
    assert {entry["origin"] for entry in summary["sets"]} == {"source:usd"}
    assert summary["unspecified"].get("color", 0) == 0


_ROOT_LAYER = """#usda 1.0
(
    defaultPrim = "Root"
    metersPerUnit = 0.001
    upAxis = "Z"
    subLayers = [@./layers/geometry.usda@]
)
"""

_GEOMETRY_LAYER = """#usda 1.0
(
    metersPerUnit = 0.001
    upAxis = "Z"
)

def Xform "Root"
{
    def Mesh "Tile"
    {
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(0, 0, 0), (%(size)s, 0, 0), (%(size)s, 10, 0), (0, 10, 0)]
    }
}
"""


@pytest.mark.slow
def test_a_part_is_built_again_when_a_layer_its_stage_composes_changes(tmp_path):
    """Nothing lists the layer: the type reports it as it builds the part, and the part is keyed on it from then on."""
    (tmp_path / "layers").mkdir()
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump({"name": "//layered", "parts": {"tile": {"type": "usd", "path": "tile.usda"}}})
    )
    # Its own stage, which no earlier run has put in the shared cache: the cache
    # is keyed on content, not on where the package is.
    (tmp_path / "tile.usda").write_text(_ROOT_LAYER.replace("(\n", '(\n    doc = "%s"\n' % uuid.uuid4(), 1))
    (tmp_path / "layers" / "geometry.usda").write_text(_GEOMETRY_LAYER % {"size": 10})

    def built():
        ctx = pc.Context(str(tmp_path / "partcad.yaml"))
        part = ctx.get_part(":tile")
        cached = asyncio.run(part.is_cached_async(ctx))
        return _box(_built(ctx, ":tile"))[3], cached

    assert built() == (pytest.approx(10), False)
    assert built() == (pytest.approx(10), True)
    (tmp_path / "layers" / "geometry.usda").write_text(_GEOMETRY_LAYER % {"size": 25})
    assert built() == (pytest.approx(25), False)


@pytest.mark.slow
def test_a_part_is_built_again_when_a_layer_its_stage_names_but_lacks_appears(tmp_path):
    """Keyed on the layer as missing, the part is read back until it is there, and built again when it is."""
    (tmp_path / "layers").mkdir()
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump({"name": "//layered", "parts": {"tile": {"type": "usd", "path": "tile.usda"}}})
    )
    root = _ROOT_LAYER.replace("(\n", '(\n    doc = "%s"\n' % uuid.uuid4(), 1)
    (tmp_path / "tile.usda").write_text(
        root.replace("@./layers/geometry.usda@", "@./layers/later.usda@, @./layers/geometry.usda@")
    )
    (tmp_path / "layers" / "geometry.usda").write_text(_GEOMETRY_LAYER % {"size": 10})

    def built():
        ctx = pc.Context(str(tmp_path / "partcad.yaml"))
        cached = asyncio.run(ctx.get_part(":tile").is_cached_async(ctx))
        return _box(_built(ctx, ":tile"))[3], cached

    assert built() == (pytest.approx(10), False)
    assert built() == (pytest.approx(10), True)
    # The stronger layer, over the same mesh, when it turns up.
    later = (
        (_GEOMETRY_LAYER % {"size": 40})
        .replace('def Xform "Root"', 'over "Root"')
        .replace('def Mesh "Tile"', 'over "Tile"')
    )
    (tmp_path / "layers" / "later.usda").write_text(later)
    assert built() == (pytest.approx(40), False)
