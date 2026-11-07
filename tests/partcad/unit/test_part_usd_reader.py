#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'usd' part type's usd-core reader, run in this process.

'test_part_usd.py' builds the parts of 'data/import_usd' in the sandbox, which
is how the type runs; this drives the same script here, with the 'usd-core'
the test environment installs, against stages written for each case - so that
every way a stage says what it is made of and how it looks is checked one at a
time, where a failure says which.

Skipped where 'usd-core' is not installed: Python 3.10, which the release the
type pins does not support.
"""

import importlib.util
import io
import json
import os
import sys
import textwrap
import zipfile

import numpy
import pytest

pytest.importorskip("pxr")
Image = pytest.importorskip("PIL.Image")

from partcad import output  # noqa: E402

BUILTIN_IMPORT = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]
DATA = os.path.join("tests", "partcad", "unit", "data", "import_usd")


def _module(script):
    spec = importlib.util.spec_from_file_location("%s_in_process" % script[:-3], os.path.join(BUILTIN_IMPORT, script))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


usd_look = _module("usd_look.py")
part_usd = _module("part_usd.py")
cadmpeg_step = _module("cadmpeg_step.py")
cadmpeg_tool = _module("cadmpeg_tool.py")


@pytest.fixture(autouse=True)
def _the_sandbox_s_modules(monkeypatch):
    """The script imports its neighbours by name, as the sandbox puts them on its path: these, for this test only."""
    monkeypatch.setitem(sys.modules, "usd_look", usd_look)
    monkeypatch.setitem(sys.modules, "cadmpeg_step", cadmpeg_step)
    monkeypatch.setitem(sys.modules, "cadmpeg_tool", cadmpeg_tool)


def _stage(tmp_path, body, name="stage.usda", up="Z", meters=0.001, default="Root", extra=""):
    """A stage of 'body' (USDA prims) written to 'tmp_path', and its path."""
    text = '#usda 1.0\n(\n    defaultPrim = "%s"\n    metersPerUnit = %s\n    upAxis = "%s"\n%s)\n\n%s\n' % (
        default,
        meters,
        up,
        extra,
        textwrap.dedent(body),
    )
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _quad(name, x=0.0, binding=None, extra="", api=True, st=True):
    """A 10 mm square at 'x', bound to 'binding' if given, laid at (0.25, 0.25) of a texture unless not 'st'."""
    schemas = '(\n    prepend apiSchemas = ["MaterialBindingAPI"]\n)' if api and binding else ""
    bound = "rel material:binding = <%s>" % binding if binding else ""
    uv = (
        "texCoord2f[] primvars:st = [(0.25, 0.25), (0.25, 0.25), (0.25, 0.25), (0.25, 0.25)] (\n"
        '            interpolation = "faceVarying"\n'
        "        )"
        if st
        else ""
    )
    return """
    def Mesh "%s" %s
    {
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(%s, 0, 0), (%s, 0, 0), (%s, 10, 0), (%s, 10, 0)]
        %s
        %s
        %s
    }
    """ % (name, schemas, x, x + 10, x + 10, x, uv, bound, extra)


def _image(path, colours):
    """A PNG of 'colours' (rows of RGBA, 0-255) at 'path'."""
    Image.fromarray(numpy.asarray(colours, dtype=numpy.uint8), "RGBA").save(path)
    return str(path)


def _looks(model):
    """Each piece's looks, in the order the meshes were read: [[look of each triangle], ...]."""
    return [[model.looks[i] for i in ids.tolist()] for _, _, ids in model.pieces]


def _only(model):
    """The one look every triangle of the model is in."""
    found = {look for piece in _looks(model) for look in piece}
    assert len(found) == 1, found
    return found.pop()


def _material(name, shader, output="surface", children=""):
    return """
    def Material "%s"
    {
        token outputs:%s.connect = </Root/Materials/%s/Shader.outputs:surface>
        %s
        %s
    }
    """ % (name, output, name, textwrap.indent(textwrap.dedent(shader), "        "), children)


def _shader(ident, inputs, outputs="token outputs:surface"):
    return """
    def Shader "Shader"
    {
        uniform token info:id = "%s"
        %s
        %s
    }
    """ % (ident, "\n        ".join(inputs), outputs)


def _materials(*materials):
    return 'def Scope "Materials"\n    {\n%s\n    }' % "\n".join(textwrap.indent(m, "    ") for m in materials)


def _root(*children):
    return 'def Xform "Root"\n{\n%s\n}' % "\n".join(textwrap.indent(textwrap.dedent(c), "    ") for c in children)


# ---------------------------------------------------------------------------
# What is read: which prims, where, when
# ---------------------------------------------------------------------------


def test_a_stage_is_its_default_prim_and_its_meshes_in_millimetres():
    model = part_usd.read(os.path.join(DATA, "bracket.usda"))
    vertices = numpy.vstack([v for v, _, _ in model.pieces])
    assert vertices.min(axis=0) == pytest.approx([0, 0, 0]) and vertices.max(axis=0) == pytest.approx([30, 20, 10])
    assert model.triangle_count() == 12


def test_a_y_up_stage_in_centimetres_is_turned_onto_z_and_its_instances_placed():
    model = part_usd.read(os.path.join(DATA, "scene.usda"))
    vertices = numpy.vstack([v for v, _, _ in model.pieces])
    assert vertices.min(axis=0) == pytest.approx([0, 0, 0], abs=1e-6)
    assert vertices.max(axis=0) == pytest.approx([200, 20, 610], abs=1e-6)


def test_the_prim_asked_for_is_what_is_built_and_slash_is_the_whole_stage():
    path = os.path.join(DATA, "bracket.usda")
    whole = part_usd.read(path, prim="/")
    assert whole.triangle_count() > part_usd.read(path).triangle_count()
    with pytest.raises(ValueError, match="no prim '/Nowhere'"):
        part_usd.read(path, prim="/Nowhere")
    with pytest.raises(ValueError, match="'purpose' is one of"):
        part_usd.read(path, purpose="final")


def test_a_file_that_is_not_a_stage_is_said_to_be_none(tmp_path):
    path = tmp_path / "not.usda"
    path.write_text("#usda 1.0\n(\n this is not usd")
    with pytest.raises(Exception):
        part_usd.read(str(path))


def test_time_is_what_a_viewer_opens_at_unless_one_is_asked_for(tmp_path):
    from pxr import Usd

    timed = Usd.Stage.Open(
        _stage(tmp_path, _root(), "timed.usda", extra="    startTimeCode = 12\n    endTimeCode = 20\n")
    )
    assert part_usd._time_code(Usd, timed, None) == (Usd.TimeCode(12), False)
    untimed = Usd.Stage.Open(_stage(tmp_path, _root(), "untimed.usda"))
    assert part_usd._time_code(Usd, untimed, "default") == (Usd.TimeCode.EarliestTime(), False)
    assert part_usd._time_code(Usd, untimed, "7.5") == (Usd.TimeCode(7.5), True)
    with pytest.raises(ValueError, match="'time' is a number or 'default'"):
        part_usd._time_code(Usd, untimed, "noon")


def test_animated_points_are_read_at_the_time_asked_for(tmp_path):
    path = _stage(
        tmp_path,
        _root("""
            def Mesh "Moving"
            {
                int[] faceVertexCounts = [3]
                int[] faceVertexIndices = [0, 1, 2]
                point3f[] points.timeSamples = {
                    0: [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                    10: [(0, 0, 0), (5, 0, 0), (0, 5, 0)],
                }
            }
            """),
    )
    assert numpy.vstack([v for v, _, _ in part_usd.read(path).pieces]).max() == pytest.approx(1)
    assert numpy.vstack([v for v, _, _ in part_usd.read(path, time=10).pieces]).max() == pytest.approx(5)


def test_a_skinned_character_is_posed_at_the_time_asked_for(tmp_path):
    path = _stage(
        tmp_path,
        """
        def SkelRoot "Root" (
            prepend apiSchemas = ["SkelBindingAPI"]
        )
        {
            rel skel:skeleton = </Root/Skeleton>
            rel skel:animationSource = </Root/Skeleton/Walk>

            def Skeleton "Skeleton" (
                prepend apiSchemas = ["SkelBindingAPI"]
            )
            {
                uniform token[] joints = ["Hip"]
                uniform matrix4d[] bindTransforms = [((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))]
                uniform matrix4d[] restTransforms = [((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))]
                rel skel:animationSource = </Root/Skeleton/Walk>

                def SkelAnimation "Walk"
                {
                    uniform token[] joints = ["Hip"]
                    float3[] translations.timeSamples = {0: [(0, 0, 0)], 10: [(100, 0, 0)]}
                    quatf[] rotations = [(1, 0, 0, 0)]
                    half3[] scales = [(1, 1, 1)]
                }
            }

            def Mesh "Body" (
                prepend apiSchemas = ["SkelBindingAPI"]
            )
            {
                int[] faceVertexCounts = [3]
                int[] faceVertexIndices = [0, 1, 2]
                point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
                int[] primvars:skel:jointIndices = [0, 0, 0] (
                    elementSize = 1
                    interpolation = "vertex"
                )
                float[] primvars:skel:jointWeights = [1, 1, 1] (
                    elementSize = 1
                    interpolation = "vertex"
                )
                matrix4d primvars:skel:geomBindTransform = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
                rel skel:skeleton = </Root/Skeleton>
            }
        }
        """,
    )
    posed = numpy.vstack([v for v, _, _ in part_usd.read(path, time=10).pieces])
    assert posed[:, 0].min() == pytest.approx(100)


def test_what_is_hidden_or_of_another_purpose_is_left_out(tmp_path):
    path = _stage(
        tmp_path,
        _root(
            _quad("Shown"),
            """
            def Xform "Hidden"
            {
                token visibility = "invisible"
            %s
            }
            """ % textwrap.indent(textwrap.dedent(_quad("Inside", 20)), "    "),
            """
            def Xform "Stand"
            {
                uniform token purpose = "proxy"
            %s
            }
            """ % textwrap.indent(textwrap.dedent(_quad("Proxy", 40)), "    "),
        ),
    )
    assert part_usd.read(path).triangle_count() == 2
    assert part_usd.read(path, purpose="proxy").triangle_count() == 4
    assert part_usd.read(path, purpose="all").triangle_count() == 4


def test_a_point_instancer_places_its_prototype_at_every_point(tmp_path):
    path = _stage(
        tmp_path,
        _root(
            """
            def PointInstancer "Scatter"
            {
                point3f[] positions = [(0, 0, 0), (100, 0, 0), (200, 0, 0)]
                int[] protoIndices = [0, 0, 1]
                rel prototypes = [</Root/Scatter/Prototypes/Tile>, </Root/Scatter/Prototypes/Missing>]

                def Scope "Prototypes"
                {
            %s
                }
            }
            """ % textwrap.indent(textwrap.dedent(_quad("Tile")), "        "),
        ),
    )
    model = part_usd.read(path)
    vertices = numpy.vstack([v for v, _, _ in model.pieces])
    assert model.triangle_count() == 4
    assert sorted({round(x) for x in vertices[:, 0]}) == [0, 10, 100, 110]


def test_a_point_instancer_with_no_instances_is_nothing(tmp_path):
    path = _stage(
        tmp_path,
        _root(
            """
            def PointInstancer "Empty"
            {
                point3f[] positions = []
                int[] protoIndices = []
                rel prototypes = [</Root/Empty/Tile>]
            %s
            }
            """ % textwrap.indent(textwrap.dedent(_quad("Tile")), "    "),
        ),
    )
    assert part_usd.read(path).pieces == []


def test_shapes_are_meshed_and_what_is_no_surface_is_counted(tmp_path):
    path = _stage(
        tmp_path,
        _root(
            'def Sphere "Ball"\n{\n    double radius = 2\n}',
            'def Cylinder "Rod"\n{\n    uniform token axis = "X"\n}',
            'def Cone "Spike"\n{\n    uniform token axis = "Y"\n}',
            'def Capsule "Pill"\n{\n}',
            'def Cube "Box"\n{\n}',
            'def BasisCurves "Hair"\n{\n    int[] curveVertexCounts = [2]\n    point3f[] points = [(0, 0, 0), (1, 1, 1)]\n}',
            'def Points "Dust"\n{\n    point3f[] points = [(0, 0, 0)]\n}',
        ),
    )
    model = part_usd.read(path)
    assert len(model.pieces) == 5
    assert model.dropped == {"BasisCurves": 1, "Points": 1}
    assert part_usd.describe(model.dropped) == "1 BasisCurves, 1 Points"
    ball = model.pieces[0][0]
    assert numpy.linalg.norm(ball, axis=1).max() == pytest.approx(2)
    rod = model.pieces[1][0]
    assert rod[:, 0].max() - rod[:, 0].min() == pytest.approx(2)  # the cylinder's height, along X
    spike = model.pieces[2][0]
    assert spike[:, 1].max() == pytest.approx(1)  # the cone's tip, along Y


def test_a_hole_is_left_out_a_left_handed_mesh_turned_and_a_malformed_one_counted(tmp_path):
    path = _stage(
        tmp_path,
        _root(
            """
            def Mesh "Holed"
            {
                int[] faceVertexCounts = [3, 3]
                int[] faceVertexIndices = [0, 1, 2, 0, 2, 3]
                int[] holeIndices = [1]
                point3f[] points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
            }
            """,
            """
            def Mesh "Left"
            {
                uniform token orientation = "leftHanded"
                int[] faceVertexCounts = [3]
                int[] faceVertexIndices = [0, 1, 2]
                point3f[] points = [(0, 0, 5), (1, 0, 5), (0, 1, 5)]
            }
            """,
            """
            def Mesh "Broken"
            {
                int[] faceVertexCounts = [4]
                int[] faceVertexIndices = [0, 1, 2]
                point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
            }
            """,
        ),
    )
    model = part_usd.read(path)
    assert [len(t) for _, t, _ in model.pieces] == [1, 1]
    assert model.pieces[1][1].tolist() == [[0, 2, 1]]
    assert model.dropped == {"Mesh (malformed)": 1}


def test_a_mirroring_placement_winds_its_triangles_back(tmp_path):
    path = _stage(
        tmp_path,
        _root("""
            def Xform "Mirror"
            {
                float3 xformOp:scale = (-1, 1, 1)
                uniform token[] xformOpOrder = ["xformOp:scale"]

                def Mesh "Triangle"
                {
                    int[] faceVertexCounts = [3]
                    int[] faceVertexIndices = [0, 1, 2]
                    point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
                }
            }
            """),
    )
    assert part_usd.read(path).pieces[0][1].tolist() == [[0, 2, 1]]


def test_a_stage_larger_than_asked_for_is_refused():
    with pytest.raises(part_usd.TooManyTriangles, match="more than 5 triangles"):
        part_usd.read(os.path.join(DATA, "bracket.usda"), max_triangles=5)


# ---------------------------------------------------------------------------
# What a face looks like
# ---------------------------------------------------------------------------


def test_each_face_of_the_looks_fixture_is_in_its_look():
    model = part_usd.read(os.path.join(DATA, "looks.usda"))
    tiles, marker, pane = _looks(model)
    assert [look[1] for look in tiles] == [(255, 0, 0, 1.0)] * 2 + [(0, 0, 255, 1.0)] * 2 + [(188, 188, 188, 1.0)] * 2
    assert {look[0] for look in tiles} == {"Painted", "Steel"}
    assert {look[:2] for look in marker} == {("displayColor", (255, 255, 0, 1.0))}
    assert {(look[0], look[2], look[3]) for look in pane} == {("Brushed", 0.3, 1.0)}


def test_a_preview_surface_s_texture_is_scaled_biased_and_falls_back_when_it_cannot_be_read(tmp_path):
    _image(tmp_path / "grey.png", [[[128, 128, 128, 255]]])

    def texture(name, inputs):
        return _material(
            name,
            _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor.connect = </Root/Materials/%s/Tex.outputs:rgb>"
                                          % name, "float inputs:opacity = 0.5"]),  # fmt: skip
            children=_shader("UsdUVTexture", inputs, "float3 outputs:rgb").replace('"Shader"', '"Tex"'),
        )

    path = _stage(
        tmp_path,
        _root(
            _quad("Scaled", 0, "/Root/Materials/Scaled"),
            _quad("Fallen", 20, "/Root/Materials/Fallen"),
            _quad("Linear", 40, "/Root/Materials/Linear"),
            _materials(
                texture(
                    "Scaled",
                    [
                        "asset inputs:file = @grey.png@",
                        "float4 inputs:scale = (0.5, 1, 1, 1)",
                        "float4 inputs:bias = (0, 0, 0.5, 0)",
                    ],
                ),
                texture("Fallen", ["asset inputs:file = @missing.exr@", "float4 inputs:fallback = (0, 1, 0, 1)"]),
                texture("Linear", ["asset inputs:file = @grey.png@", 'token inputs:sourceColorSpace = "raw"']),
            ),
        ),
    )
    scaled, fallen, linear = (_only_piece(piece) for piece in _looks(part_usd.read(path)))
    grey = 128 / 255
    grey_linear = float(usd_look.linear_of_srgb(grey))
    expect = usd_look.srgb_of_linear([grey_linear * 0.5, grey_linear, grey_linear + 0.5])
    assert scaled[1][:3] == tuple(int(round(v)) for v in expect) and scaled[1][3] == 0.5
    assert fallen[1][:3] == (0, 255, 0)
    assert linear[1][:3] == tuple(int(round(v)) for v in usd_look.srgb_of_linear([grey] * 3))


def test_a_texture_that_cannot_be_read_gives_the_channel_asked_for_of_its_fallback(tmp_path):
    """A roughness read off a texture's green is the fallback's green when the image is not there, not its red."""
    shader = _shader(
        "UsdPreviewSurface",
        [
            "color3f inputs:diffuseColor = (1, 1, 1)",
            "float inputs:roughness.connect = </Root/Materials/Rough/Tex.outputs:g>",
            "float inputs:metallic.connect = </Root/Materials/Rough/Tex.outputs:b>",
        ],
    )
    texture = _shader(
        "UsdUVTexture",
        ["asset inputs:file = @missing.exr@", "float4 inputs:fallback = (0.1, 0.7, 0.3, 1)"],
        "float outputs:g\n        float outputs:b",
    ).replace('"Shader"', '"Tex"')
    path = _stage(
        tmp_path,
        _root(_quad("Tile", 0, "/Root/Materials/Rough"), _materials(_material("Rough", shader, children=texture))),
    )
    assert _only(part_usd.read(path))[2:4] == (0.7, 0.3)


def _only_piece(looks):
    assert len(set(looks)) == 1, set(looks)
    return looks[0]


def test_a_texture_with_no_st_is_laid_by_another_coordinate_set_or_drawn_in_its_mean(tmp_path):
    _image(tmp_path / "split.png", [[[255, 0, 0, 255], [0, 0, 255, 255]]])
    shader = _shader(
        "UsdPreviewSurface",
        ["color3f inputs:diffuseColor.connect = </Root/Materials/Split/Tex.outputs:rgb>"],
    )
    texture = _shader("UsdUVTexture", ["asset inputs:file = @split.png@"], "float3 outputs:rgb").replace(
        '"Shader"', '"Tex"'
    )
    other_uv = """
    texCoord2f[] primvars:uv1 = [(0.9, 0.5), (0.9, 0.5), (0.9, 0.5), (0.9, 0.5)] (
        interpolation = "faceVarying"
    )
    """
    path = _stage(
        tmp_path,
        _root(
            _quad("Other", 0, "/Root/Materials/Split", other_uv, st=False),
            _quad("None", 20, "/Root/Materials/Split", st=False),
            _materials(_material("Split", shader, children=texture)),
        ),
    )
    other, mean = (_only_piece(piece) for piece in _looks(part_usd.read(path)))
    assert other[1][:3] == (0, 0, 255)
    # The mean of red and blue, in sRGB as the image is.
    assert mean[1][:3] == (128, 0, 128)


def test_a_primvar_reader_colours_a_face_with_its_primvar_or_its_fallback(tmp_path):
    def reader(name, varname):
        return _material(
            name,
            _shader(
                "UsdPreviewSurface",
                ["color3f inputs:diffuseColor.connect = </Root/Materials/%s/Reader.outputs:result>" % name],
            ),
            children=_shader(
                "UsdPrimvarReader_float3",
                ['string inputs:varname = "%s"' % varname, "float3 inputs:fallback = (0, 0, 1)"],
                "float3 outputs:result",
            ).replace('"Shader"', '"Reader"'),
        )

    tinted = 'color3f[] primvars:tint = [(1, 0, 0)] (\n    interpolation = "uniform"\n)'
    path = _stage(
        tmp_path,
        _root(
            _quad("Tinted", 0, "/Root/Materials/Tint", tinted),
            _quad("Untinted", 20, "/Root/Materials/Absent"),
            _materials(reader("Tint", "tint"), reader("Absent", "nothing")),
        ),
    )
    tinted, untinted = (_only_piece(piece) for piece in _looks(part_usd.read(path)))
    assert tinted[1][:3] == (255, 0, 0)
    assert untinted[1][:3] == (0, 0, 255)


@pytest.mark.parametrize(
    "interpolation, values, alpha",
    [
        ("constant", "[0.5]", 0.5),
        ("uniform", "[0.25]", 0.25),
        ("vertex", "[0.2, 0.2, 0.4, 0.4]", 0.3),
        ("faceVarying", "[1, 1, 1, 1]", 1.0),
    ],
)
def test_display_opacity_is_read_however_it_is_interpolated(tmp_path, interpolation, values, alpha):
    extra = """
    color3f[] primvars:displayColor = [(0, 1, 0)]
    float[] primvars:displayOpacity = %s (
        interpolation = "%s"
    )
    """ % (values, interpolation)
    path = _stage(tmp_path, _root(_quad("Glass", 0, None, extra)))
    looks = _looks(part_usd.read(path))[0]
    assert {look[1][:3] for look in looks} == {(0, 255, 0)}
    assert [look[1][3] for look in looks] == pytest.approx([alpha] * 2, abs=0.051)


def test_a_material_of_a_shader_this_cannot_read_is_drawn_in_display_color(tmp_path):
    path = _stage(
        tmp_path,
        _root(
            _quad("Odd", 0, "/Root/Materials/Odd", "color3f[] primvars:displayColor = [(1, 0, 1)]"),
            _materials(_material("Odd", _shader("SomeoneElsesSurface", []))),
        ),
    )
    look = _only(part_usd.read(path))
    assert look[0] == "Odd" and look[1][:3] == (255, 0, 255) and look[2] is None


def test_the_final_material_draws_unless_its_colour_cannot_be_read_and_then_the_preview(tmp_path):
    exr = _material(
        "Final",
        _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor.connect = </Root/Materials/Final/Tex.outputs:rgb>"]),
        children=_shader("UsdUVTexture", ["asset inputs:file = @final.exr@"], "float3 outputs:rgb").replace(
            '"Shader"', '"Tex"'
        ),
    )
    preview = _material("Preview", _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor = (0, 0, 1)"]))
    both = """
    def Mesh "Both" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
        rel material:binding:full = </Root/Materials/Final>
        rel material:binding:preview = </Root/Materials/Preview>
    }
    """
    path = _stage(tmp_path, _root(both, _materials(exr, preview)))
    assert _only(part_usd.read(path))[:2] == ("Preview", (0, 0, 255, 1.0))


def test_materialx_and_pbr_surfaces_in_the_stage_are_read(tmp_path):
    standard = _shader(
        "ND_standard_surface_surfaceshader",
        [
            "color3f inputs:base_color = (1, 0, 0)",
            "float inputs:base = 0.5",
            "float inputs:metalness = 1",
            "float inputs:specular_roughness = 0.4",
            "float inputs:transmission = 1",
        ],
    )
    opaque = _shader(
        "ND_standard_surface_surfaceshader",
        ["color3f inputs:base_color = (0, 1, 0)", "color3f inputs:opacity = (0.5, 0.5, 0.5)"],
    )
    open_pbr = _shader(
        "ND_open_pbr_surface_surfaceshader",
        [
            "color3f inputs:base_color = (0, 0, 1)",
            "float inputs:base_weight = 0.5",
            "float inputs:base_metalness = 0.75",
            "float inputs:specular_roughness = 0.6",
            "float inputs:geometry_opacity = 0.4",
        ],
    )
    see_through = _shader("ND_open_pbr_surface_surfaceshader", ["float inputs:transmission_weight = 1"])
    gltf = _shader(
        "ND_gltf_pbr_surfaceshader",
        [
            "color3f inputs:base_color = (1, 1, 0)",
            "float inputs:roughness = 0.1",
            "float inputs:metallic = 0",
            "float inputs:alpha = 0.9",
        ],
    )
    names = ["Standard", "Opaque", "OpenPbr", "SeeThrough", "Gltf"]
    shaders = [standard, opaque, open_pbr, see_through, gltf]
    path = _stage(
        tmp_path,
        _root(
            *[_quad(name, 20 * i, "/Root/Materials/%s" % name) for i, name in enumerate(names)],
            _materials(*[_material(name, shader, "mtlx:surface") for name, shader in zip(names, shaders)]),
        ),
    )
    looks = {look[0]: look for look in (_only_piece(piece) for piece in _looks(part_usd.read(path)))}
    half_red = int(round(usd_look.srgb_of_linear(0.5)))
    assert looks["Standard"][1] == (half_red, 0, 0, 0.3) and looks["Standard"][2:4] == (0.4, 1.0)
    assert looks["Opaque"][1] == (0, 255, 0, 0.5)
    assert looks["OpenPbr"][1] == (0, 0, half_red, 0.4) and looks["OpenPbr"][2:4] == (0.6, 0.75)
    assert looks["SeeThrough"][1][3] == 0.3
    assert looks["Gltf"][1] == (255, 255, 0, 0.9) and looks["Gltf"][2:4] == (0.1, 0.0)


def test_a_simready_name_says_what_a_face_is_made_of_and_a_physics_binding_names_one_too(tmp_path):
    plain = _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor = (1, 1, 1)"])
    physics = """
    def Mesh "Bolt" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        rel material:binding = </Root/Materials/Painted>
    }
    """
    path = _stage(
        tmp_path,
        _root(
            _quad("Pane", 0, "/Root/Materials/translucent__glass__pane"),
            _quad("Can", 20, "/Root/Materials/opaque__metal__can"),
            physics,
            _materials(
                _material("translucent__glass__pane", plain),
                _material(
                    "opaque__metal__can",
                    _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor = (0.5, 0.5, 0.5)"]),
                ),
                _material(
                    "Painted",
                    plain,
                ).replace(
                    'def Material "Painted"\n    {',
                    'def Material "Painted" (\n        prepend apiSchemas = ["MaterialBindingAPI"]\n    )\n    {\n'
                    "        rel material:binding:physics = </Root/Materials/Steel>",
                ),
                'def Material "Steel"\n{\n}',
            ),
        ),
    )
    pane, can, bolt = (_only_piece(piece) for piece in _looks(part_usd.read(path)))
    assert pane[4] == "glass" and pane[1][3] == 0.6
    # A metal says how it looks where the material does not: UsdPreviewSurface says roughness 0.5, metallic 0.
    assert can[4] == "metal" and can[2:4] == (0.5, 0.0)
    assert bolt[0] == "Painted"


def test_nvidia_s_materials_are_read_off_their_shader_inputs(tmp_path):
    _image(tmp_path / "albedo.png", [[[255, 255, 255, 255]]])
    # ORM: occlusion, roughness in green, metallic in blue.
    _image(tmp_path / "orm.png", [[[255, 51, 204, 255]]])

    def mdl(name, module, inputs):
        return """
        def Material "%s"
        {
            token outputs:mdl:surface.connect = </Root/Materials/%s/Shader.outputs:out>

            def Shader "Shader"
            {
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @%s.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "%s"
                %s
                token outputs:out
            }
        }
        """ % (name, name, module, module, "\n            ".join(inputs))

    materials = [
        mdl(
            "Pbr",
            "OmniPBR",
            [
                "asset inputs:diffuse_texture = @albedo.png@",
                "color3f inputs:diffuse_tint = (1, 0, 0)",
                "float inputs:albedo_add = 0",
                "float inputs:albedo_brightness = 0.5",
                "bool inputs:enable_ORM_texture = 1",
                "asset inputs:ORM_texture = @orm.png@",
                "float inputs:reflection_roughness_texture_influence = 1",
                "float inputs:metallic_texture_influence = 1",
                "bool inputs:enable_opacity = 1",
                "float inputs:opacity_constant = 0.8",
            ],
        ),
        mdl(
            "Plain",
            "OmniPBR",
            [
                "color3f inputs:diffuse_color_constant = (0, 0, 1)",
                "color3f inputs:diffuse_tint = (1, 1, 1)",
                "float inputs:albedo_add = 0.1",
                "float inputs:reflection_roughness_texture_influence = 1",
                "asset inputs:reflectionroughness_texture = @orm.png@",
                "float inputs:metallic_texture_influence = 1",
                "asset inputs:metallic_texture = @orm.png@",
            ],
        ),
        mdl("Glass", "OmniGlass", ["color3f inputs:glass_color = (0, 1, 0)", "float inputs:frosting_roughness = 0.2"]),
        mdl(
            "Surface",
            "OmniSurface",
            [
                "color3f inputs:diffuse_reflection_color = (1, 1, 1)",
                "float inputs:metalness = 0.5",
                "bool inputs:enable_specular_transmission = 1",
                "float inputs:specular_transmission_weight = 1",
            ],
        ),
    ]
    names = ["Pbr", "Plain", "Glass", "Surface"]
    path = _stage(
        tmp_path,
        _root(*[_quad(n, 20 * i, "/Root/Materials/%s" % n) for i, n in enumerate(names)], _materials(*materials)),
    )
    pbr, plain, glass, surface = (_only_piece(piece) for piece in _looks(part_usd.read(path)))
    assert pbr[1][:3] == (int(round(usd_look.srgb_of_linear(0.5))), 0, 0) and pbr[1][3] == 0.8
    assert pbr[2:4] == (0.2, 0.8)
    assert plain[1][:3] == tuple(int(round(v)) for v in usd_look.srgb_of_linear([0.1, 0.1, 1.0]))
    # The roughness and metallic textures are each read from their red channel: 1.
    assert plain[2:4] == (1.0, 1.0)
    assert glass[1][:3] == tuple(int(round(v)) for v in usd_look.srgb_of_linear([0.3, 1.0, 0.3]))
    assert glass[1][3] == 0.25 and glass[2:4] == (0.2, 0.0)
    assert surface[1][3] == 0.3 and surface[3] == 0.5


def test_a_materialx_document_a_layer_references_is_read_for_what_it_does_not_compose(tmp_path):
    (tmp_path / "textures").mkdir()
    _image(tmp_path / "textures" / "wood.png", [[[0, 255, 0, 255]]])
    (tmp_path / "looks.mtlx").write_text(textwrap.dedent("""\
            <?xml version="1.0"?>
            <materialx version="1.38" fileprefix="textures/">
              <standard_surface name="SR_chrome" type="surfaceshader">
                <input name="base_color" type="color3" value="1, 0, 0" />
                <input name="base" type="float" value="0.5" />
                <input name="metalness" type="float" value="1" />
                <input name="specular_roughness" type="float" value="0.1" />
                <input name="transmission" type="float" value="0.5" />
              </standard_surface>
              <surfacematerial name="Chrome" type="material">
                <input name="surfaceshader" type="surfaceshader" nodename="SR_chrome" />
              </surfacematerial>
              <nodegraph name="NG_wood">
                <image name="albedo" type="color3">
                  <input name="file" type="filename" value="wood.png" />
                </image>
                <output name="out" type="color3" nodename="albedo" />
              </nodegraph>
              <open_pbr_surface name="SR_wood" type="surfaceshader">
                <input name="base_color" type="color3" nodegraph="NG_wood" output="out" />
              </open_pbr_surface>
              <surfacematerial name="Wood" type="material">
                <input name="surfaceshader" type="surfaceshader" nodename="SR_wood" />
              </surfacematerial>
              <nodegraph name="NG_paint">
                <constant name="blue" type="color3">
                  <input name="value" type="color3" value="0, 0, 1" />
                </constant>
                <dot name="through" type="color3">
                  <input name="in" type="color3" nodename="blue" />
                </dot>
                <output name="result" type="color3" nodename="through" />
              </nodegraph>
              <gltf_pbr name="SR_paint" type="surfaceshader">
                <input name="base_color" type="color3" nodegraph="NG_paint" />
                <input name="roughness" type="float" value="0.7" />
              </gltf_pbr>
              <surfacematerial name="Paint" type="material">
                <input name="surfaceshader" type="surfaceshader" nodename="SR_paint" />
              </surfacematerial>
              <UsdPreviewSurface name="SR_preview" type="surfaceshader">
                <input name="diffuseColor" type="color3" value="1, 1, 0" />
                <input name="opacity" type="float" value="0.5" />
              </UsdPreviewSurface>
              <surfacematerial name="Preview" type="material">
                <input name="surfaceshader" type="surfaceshader" nodename="SR_preview" />
              </surfacematerial>
              <unknown_surface name="SR_odd" type="surfaceshader" />
              <surfacematerial name="Odd" type="material">
                <input name="surfaceshader" type="surfaceshader" nodename="SR_odd" />
              </surfacematerial>
            </materialx>
            """))
    names = ["Chrome", "Wood", "Paint", "Preview", "Odd", "Absent"]
    quads = [_quad(n, 20 * i, "/Root/Materials/%s" % n, "color3f[] primvars:displayColor = [(1, 1, 1)]")
             for i, n in enumerate(names)]  # fmt: skip
    path = _stage(
        tmp_path,
        _root(*quads, 'def Scope "Materials" (\n    prepend references = @looks.mtlx@</MaterialX>\n)\n{\n}'),
    )
    looks = [_only_piece(piece) for piece in _looks(part_usd.read(path))]
    chrome, wood, paint, preview, odd, absent = looks
    half_red = int(round(usd_look.srgb_of_linear(0.5)))
    assert chrome[:4] == ("Chrome", (half_red, 0, 0, 0.65), 0.1, 1.0)
    assert wood[:2] == ("Wood", (0, 255, 0, 1.0))
    assert paint[:3] == ("Paint", (0, 0, 255, 1.0), 0.7)
    assert preview[:2] == ("Preview", (255, 255, 0, 0.5))
    # What the document has no surface of, or nothing at all, is drawn in its displayColor.
    assert odd[:2] == ("displayColor", (255, 255, 255, 1.0)) and absent == odd


def test_a_materialx_document_that_cannot_be_read_has_no_materials(tmp_path):
    broken = tmp_path / "broken.mtlx"
    broken.write_text("<materialx><unclosed>")
    assert usd_look.MtlxDocument(str(broken)).elements == {}
    assert usd_look.MtlxDocument(str(tmp_path / "missing.mtlx")).surface("Anything", None) is None


def test_the_files_a_package_holds_are_read_inside_it_and_inside_a_package_in_it(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("textures/a.txt", b"inner")
    with zipfile.ZipFile(tmp_path / "outer.usdz", "w") as z:
        z.writestr("inner.usdz", inner.getvalue())
    package = str(tmp_path / "outer.usdz")
    assert usd_look.read_bytes("%s[inner.usdz[textures/a.txt]]" % package) == b"inner"
    assert usd_look.read_bytes("%s[missing.usdz[textures/a.txt]]" % package) is None


def test_an_image_too_large_to_decode_is_read_as_none(tmp_path, monkeypatch):
    path = _image(tmp_path / "large.png", numpy.zeros((4, 4, 4)))
    assert usd_look._read_image(path).shape == (4, 4, 4)
    monkeypatch.setattr(usd_look, "MAX_DECODED_PIXELS", 15)
    assert usd_look._read_image(path) is None
    (tmp_path / "not.png").write_bytes(b"not an image")
    assert usd_look._read_image(str(tmp_path / "not.png")) is None


def test_looks_of_many_colours_and_finishes_are_rounded_until_there_are_few_enough(monkeypatch):
    count = 64
    rgb = numpy.column_stack([numpy.arange(count) * 4.0, numpy.zeros(count), numpy.zeros(count)])
    roughness = numpy.linspace(0, 1, count)
    nothing = numpy.full(count, numpy.nan)
    arrays = (numpy.zeros(count, dtype=numpy.int64), rgb, nothing, roughness, nothing, numpy.full(count, -1))
    monkeypatch.setattr(usd_look, "MAX_LOOKS", 32)
    looks, ids = usd_look.settle(*arrays, ["Gradient"], [])
    assert len(looks) <= 32 and sorted(set(ids.tolist())) == list(range(len(looks)))
    # Past what the coarsest rounding makes of them, there are as many as that leaves: each
    # roughness to the nearest half.
    monkeypatch.setattr(usd_look, "MAX_LOOKS", 2)
    looks, ids = usd_look.settle(*arrays, ["Gradient"], [])
    assert {look[2] for look in looks} == {0.0, 0.5, 1.0}
    looks, ids = usd_look.settle(*(a[:0] for a in arrays), [], [])
    assert looks == [] and len(ids) == 0


# ---------------------------------------------------------------------------
# What is built, and what the script answers
# ---------------------------------------------------------------------------


def test_a_stage_is_built_as_faces_or_as_a_mesh_per_look():
    model = part_usd.read(os.path.join(DATA, "looks.usda"))
    shape, cmf = part_usd.build(model, "faces")
    assert shape is not None and cmf["convention"] == "usd" and len(cmf["faces"]) == model.triangle_count()
    shape, cmf = part_usd.build(model, "mesh")
    assert shape is not None and len(cmf["faces"]) == len(model.looks)
    with pytest.raises(ValueError, match="'surface' is one of"):
        part_usd.build(model, "voxels")


def test_the_script_answers_with_the_shape_its_cmf_and_what_it_left_out(tmp_path, capsys):
    answer = part_usd.run(
        {"path": os.path.join(DATA, "looks.usda"), "parameters": {"surface": "mesh", "maxTriangles": "1e6"}}
    )
    assert set(answer) == {"shape", "cmf", "dependencies"}
    # What it was read from besides the stage: the image and the MDL preset its looks name.
    assert answer["dependencies"] == ["brushed.mdl", "halves.bmp"]
    curves = _stage(
        tmp_path,
        _root(
            'def BasisCurves "Hair"\n{\n    int[] curveVertexCounts = [2]\n    point3f[] points = [(0, 0, 0), (1, 1, 1)]\n}'
        ),
    )
    answer = part_usd.run({"path": curves, "parameters": {}})
    assert answer == {"exception": "stage.usda shows no mesh (only 1 BasisCurves)"}
    assert "left out what is not a mesh: 1 BasisCurves" in capsys.readouterr().err
    answer = part_usd.run({"path": curves, "parameters": {"purpose": "final"}})
    assert "'purpose' is one of" in answer["exception"]


def test_a_stage_reports_the_layers_it_composed_and_the_files_its_looks_came_from(tmp_path):
    """What a stage of loose layers was read from: a sublayer, a reference, a texture, and one outside its folder."""
    (tmp_path / "layers").mkdir()
    (tmp_path / "textures").mkdir()
    elsewhere = tmp_path.parent / ("%s-elsewhere" % tmp_path.name)
    elsewhere.mkdir()
    _image(tmp_path / "textures" / "red.png", [[[255, 0, 0, 255]]])
    _stage(tmp_path, _root(_quad("Floor")), name="layers/floor.usda")
    _stage(elsewhere, _root(_quad("Shelf", 40)), name="shelf.usda")
    texture = _material(
        "Red",
        _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor.connect = </Root/Materials/Red/Tex.outputs:rgb>"]),
        children=_shader("UsdUVTexture", ["asset inputs:file = @../textures/red.png@"], "float3 outputs:rgb").replace(
            '"Shader"', '"Tex"'
        ),
    )
    _stage(tmp_path, _root(_quad("Tile", 20, "/Root/Materials/Red"), _materials(texture)), name="layers/tiles.usda")
    shelf = str(elsewhere / "shelf.usda").replace(os.sep, "/")
    path = _stage(
        tmp_path,
        """
        def Xform "Root" (
            prepend references = [@./layers/tiles.usda@</Root>, @%s@</Root>]
        )
        {
        }
        """ % shelf,
        extra="    subLayers = [@./layers/floor.usda@]\n",
    )
    model = part_usd.read(path)
    assert model.triangle_count() == 6
    said = part_usd.reported(model.files, path)
    assert sorted(said) == sorted(
        ["layers/floor.usda", "layers/tiles.usda", "textures/red.png", os.path.abspath(str(elsewhere / "shelf.usda"))]
    )
    # cadmpeg composes a stage itself, so what it was read from is what USD's own walk of it finds.
    walked = part_usd.reported(part_usd.stage_files(path), path)
    assert set(said) <= set(walked)
    assert part_usd.stage_files(str(tmp_path / "missing.usda")) in ([], None)


def test_what_a_stage_names_that_is_not_there_is_reported_too(tmp_path):
    """Keyed as missing, a sublayer or a texture that appears later builds the part again."""
    (tmp_path / "layers").mkdir()
    texture = _material(
        "Gone",
        _shader("UsdPreviewSurface", ["color3f inputs:diffuseColor.connect = </Root/Materials/Gone/Tex.outputs:rgb>"]),
        children=_shader("UsdUVTexture", ["asset inputs:file = @../textures/gone.png@"], "float3 outputs:rgb").replace(
            '"Shader"', '"Tex"'
        ),
    )
    _stage(tmp_path, _root(_quad("Tile", 0, "/Root/Materials/Gone"), _materials(texture)), name="layers/tile.usda")
    path = _stage(tmp_path, "", extra="    subLayers = [@./layers/tile.usda@, @./layers/later.usda@]\n")
    said = part_usd.reported(part_usd.read(path).files, path)
    assert {"layers/tile.usda", "layers/later.usda", "textures/gone.png"} <= set(said)


def test_a_stage_that_cannot_be_walked_says_its_files_are_not_known(monkeypatch):
    from pxr import UsdUtils

    def cannot(*_args, **_kwargs):
        raise RuntimeError("not today")

    monkeypatch.setattr(UsdUtils, "ComputeAllDependencies", cannot)
    path = os.path.join(DATA, "looks.usda")
    assert part_usd.stage_files(path) is None
    assert part_usd.read(path).files is None
    assert part_usd.run({"path": path, "parameters": {"surface": "mesh"}})["dependencies"] is None


def test_a_package_is_one_file_and_reports_nothing_else():
    assert part_usd._on_disk("/a/b.usdz[c/d.png]") == "/a/b.usdz"
    assert part_usd._on_disk("/a/b.usda") == "/a/b.usda"
    assert part_usd.reported(["/a/stage.usdz", "/a/stage.usdz"], "/a/stage.usdz") == []


# ---------------------------------------------------------------------------
# The cadmpeg reader, with what cadmpeg would write
# ---------------------------------------------------------------------------


def _cadir(tmp_path):
    return {
        "units": {"length": "millimeter"},
        "source": {"attributes": {"up_axis": "Z", "default_prim": "Root"}},
        "model": {
            "occurrences": [{"id": "o", "native_ref": "/Root", "prototype": {"definition": "d"}}],
            "product_definitions": [{"id": "d", "bodies": ["b"]}],
            "bodies": [{"id": "b"}],
            "tessellations": [
                {
                    "id": "t",
                    "body": "b",
                    "mesh": {"kind": "list", "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0], "triangles": [[0, 1, 2]]},
                }
            ],
            "appearances": [
                {
                    "id": "a",
                    "name": "Wood",
                    "base_color": {"r": 1, "g": 1, "b": 1, "a": 1},
                    "textures": [{"slot": "diffuseColor", "paths": ["./textures/wood.png"]}],
                }
            ],
            "appearance_bindings": [{"appearance": "a", "target": {"kind": "body", "id": "b"}}],
        },
    }


def test_the_cadmpeg_reader_reads_what_cadmpeg_writes_and_a_texture_s_mean_from_the_package(tmp_path, monkeypatch):
    image = io.BytesIO()
    Image.fromarray(numpy.full((2, 2, 4), [0, 0, 255, 255], dtype=numpy.uint8), "RGBA").save(image, "PNG")
    package = tmp_path / "wood.usdz"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("wood.usda", "#usda 1.0\n")
        z.writestr("textures/wood.png", image.getvalue())

    def convert(command):
        with open(command[command.index("-o") + 1], "w") as f:
            json.dump(_cadir(tmp_path), f)

    monkeypatch.setattr(cadmpeg_step, "run", convert)
    model = part_usd.read_cadmpeg(str(package), str(tmp_path), cadmpeg="cadmpeg")
    assert model.looks == [("Wood", (0, 0, 255, 1.0), None, None, None)]
    monkeypatch.setattr(part_usd, "CADIR_MAX_MB", 0)
    with pytest.raises(part_usd.TooManyTriangles, match="read it with 'usd-core'"):
        part_usd.read_cadmpeg(str(package), str(tmp_path), cadmpeg="cadmpeg")


def test_a_texture_is_only_found_in_a_package_that_is_one(tmp_path):
    (tmp_path / "broken.usdz").write_bytes(b"not a zip")
    assert part_usd._texture_mean(str(tmp_path / "stage.usda"), ["a.png"]) is None
    assert part_usd._texture_mean(str(tmp_path / "broken.usdz"), ["a.png"]) is None
    with zipfile.ZipFile(tmp_path / "empty.usdz", "w") as z:
        z.writestr("stage.usda", "#usda 1.0\n")
    assert part_usd._texture_mean(str(tmp_path / "empty.usdz"), ["a.png"]) is None
    appearance = {"textures": [{"slot": "baseColor", "paths": ["a.png"]}]}
    assert part_usd._appearance_rgba(appearance, str(tmp_path / "empty.usdz")) is None
    assert part_usd._appearance_rgba("not an appearance") is None
