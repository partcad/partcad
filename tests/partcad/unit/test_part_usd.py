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
KEYED_FOR = 1


def _module(script):
    spec = importlib.util.spec_from_file_location("%s_under_test" % script[:-3], os.path.join(BUILTIN_IMPORT, script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


part_usd = _module("part_usd.py")


@pytest.fixture(scope="module")
def declared():
    with open(os.path.join(BUILTIN_IMPORT, "partcad.yaml")) as f:
        return yaml.safe_load(f)["partTypes"]["usd"]


# ---------------------------------------------------------------------------
# What is declared
# ---------------------------------------------------------------------------


def test_the_type_reads_a_stage_with_the_usd_core_it_pins(declared):
    assert declared["path"] == "part_usd.py"
    assert declared["extension"] == "usd"
    (requirement,) = declared["pythonRequirements"]
    assert requirement.startswith("usd-core==")


def test_a_stage_that_is_no_solid_is_a_part_all_the_same(declared):
    """What a renderer draws need not close: a stage is built and reported, not failed."""
    assert not declared.get("requireSolid")


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


def test_cadmpeg_s_meshes_are_placed_by_their_occurrences_and_turned_onto_z():
    groups, dropped = part_usd.cadir_groups(_cadir())
    ((vertices, triangles),) = groups.values()
    # (10, 0, 0) is (10, 0, 50) in the triangle's parent, and (200, 0, -20) in
    # the stage, Y up: (200, 20, 0) with Z up. As usd-core reads the same stage.
    assert vertices.round(6).tolist() == [[200, 0, 0], [200, 20, 0], [200, 0, 60]]
    assert triangles.tolist() == [[0, 1, 2]]
    assert dropped == {}


def test_cadmpeg_s_stage_is_its_default_prim_unless_a_prim_is_asked_for():
    assert sum(len(t) for _, t in part_usd.cadir_groups(_cadir())[0].values()) == 1
    assert sum(len(t) for _, t in part_usd.cadir_groups(_cadir(), prim="/")[0].values()) == 2
    assert sum(len(t) for _, t in part_usd.cadir_groups(_cadir(), prim="/Studio")[0].values()) == 1
    with pytest.raises(ValueError, match="no prim"):
        part_usd.cadir_groups(_cadir(), prim="/Nowhere")


def test_what_cadmpeg_says_is_hidden_is_not_built():
    hidden = _cadir(
        occurrences=[_occurrence("/World"), _occurrence("/World/arm", "/World", visible=False),
                     _occurrence("/World/arm/m", "/World/arm")]  # fmt: skip
    )
    assert part_usd.cadir_groups(hidden)[0] == {}


def test_a_colour_is_the_triangle_group_s_else_the_mesh_s_else_the_body_s_and_a_texture_gives_none():
    model = _cadir(
        appearances=[
            {"id": "blue", "base_color": {"r": 0.0, "g": 0.0, "b": 1.0, "a": 1.0}},
            {"id": "textured", "base_color": {"r": 0.5, "g": 0.5, "b": 0.5}, "textures": [{"slot": "diffuseColor"}]},
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
    groups, _ = part_usd.cadir_groups(model, prim="/")
    assert {rgba: len(t) for rgba, (_, t) in groups.items()} == {(0, 0, 255, 1.0): 1, (255, 0, 0, 1.0): 1, None: 1}


def test_a_b_rep_body_is_counted_and_left_out():
    model = _cadir()
    model["model"]["bodies"][0]["regions"] = ["r0"]
    model["model"]["tessellations"] = [model["model"]["tessellations"][1]]
    groups, dropped = part_usd.cadir_groups(model)
    assert groups == {}
    assert dropped == {"B-rep body (read it with 'usd-core')": 1}


def test_too_many_triangles_from_cadmpeg_says_what_to_do():
    with pytest.raises(part_usd.TooManyTriangles, match="build a 'prim'"):
        part_usd.cadir_groups(_cadir(), prim="/", max_triangles=1)


def test_the_cadmpeg_reader_refuses_what_it_cannot_read_rather_than_reading_something_else(tmp_path):
    with pytest.raises(ValueError, match="purpose"):
        part_usd.read_cadmpeg(str(tmp_path / "x.usda"), str(tmp_path), purpose="proxy", cadmpeg="cadmpeg")
    with pytest.raises(ValueError, match="time"):
        part_usd.read_cadmpeg(str(tmp_path / "x.usda"), str(tmp_path), time="12", cadmpeg="cadmpeg")


def test_an_unknown_reader_is_refused():
    answer = part_usd.run({"path": "stage.usda", "parameters": {"reader": "blender"}})
    assert "'reader' is one of usd-core, cadmpeg" in answer["exception"]


def _count(shape, kind):
    """How many distinct sub-shapes of 'kind': an edge two faces share is one."""
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found.Extent()


SQUARES = {
    (255, 0, 0, 1.0): (numpy.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float), numpy.array([[0, 1, 2], [0, 2, 3]])),
    None: (numpy.array([[0, 0, 1], [1, 0, 1], [0, 1, 1]], float), numpy.array([[0, 1, 2]])),
}  # fmt: skip


@pytest.mark.parametrize("surface, faces, edges", [("faces", 3, 8), ("auto", 3, 8), ("mesh", 2, 0)])
def test_the_shape_is_a_face_per_triangle_or_a_mesh_per_colour(surface, faces, edges):
    shape, cmf = part_usd.build(SQUARES, surface)
    assert _count(shape, TopAbs_FACE) == faces
    # Two triangles sharing an edge share it: 5 edges a square, not 6.
    assert _count(shape, TopAbs_EDGE) == edges
    red = {"rgba": [255, 0, 0, 1.0]}
    assert cmf == {"faces": [red] * (faces - 1) + [None]}


def test_a_closed_mesh_of_faces_is_a_valid_closed_shell_and_the_solid_it_bounds():
    cube = numpy.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    triangles = numpy.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))])
    shape, _ = part_usd.build({None: (cube, triangles)}, "faces")
    assert BRepCheck_Analyzer(shape).IsValid()
    # Every face facing out: the solid PartCAD states of it is a cube, not nothing.
    import sys

    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import wrapper_common

    solid = wrapper_common.solidify(shape)
    assert wrapper_common.solid_problems(solid) == []
    assert _volume(solid) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="'surface' is one of"):
        part_usd.build({None: (cube, triangles)}, "nurbs")


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
