#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What colour a drawing draws a shape in.

A part that states a colour ('properties: color: "#RRGGBB"') is drawn in it, and
one that states none is drawn in goldenrod - the colour OCCT draws a shape
nobody coloured, and the colour the IDE's Digital Thread draws it in too.

This file checks it four ways. The colour rules on their own: what a colour is,
how one is written, and how a sub-assembly's colour reaches what is inside it.
That the IDE's copy of the default is the same colour. With the real kernel, in
this process and handed the shape as the export wrapper hands it - the geometry
and the tree it came from - that a drawing of several colours is still one
hidden-line drawing: a red part in front of a goldenrod one hides it. And end to
end, through a package and the sandbox, that 'pc render' draws an assembly's
parts in the colours they state.
"""

import importlib.util
import os
import re
import sys
import textwrap

import pytest

import partcad as pc
from partcad import output
from partcad.render import resolve_viewport

WRAPPERS_DIR = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "wrappers")
RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]
REPOSITORY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

sys.path.append(WRAPPERS_DIR)
import appearance  # noqa: E402
import ocp_serialize  # noqa: E402
import wrapper_export  # noqa: E402

GOLDENROD = "rgb(218,165,32)"
RED = "rgb(255,0,0)"

# --------------------------------------------------------------------------- #
# The rules                                                                   #
# --------------------------------------------------------------------------- #


def test_the_default_is_occts_goldenrod():
    # Quantity_NOC_GOLDENROD, as the sRGB it is defined in.
    assert appearance.DEFAULT_COLOR == "#DAA520"
    assert appearance.parse(appearance.DEFAULT_COLOR) == (218, 165, 32, 1.0)


@pytest.mark.parametrize(
    "text, parsed",
    [
        ("#DAA520", (218, 165, 32, 1.0)),
        ("#daa520", (218, 165, 32, 1.0)),
        ("daa520", (218, 165, 32, 1.0)),
        (" #DAA520 ", (218, 165, 32, 1.0)),
        ("#FF000080", (255, 0, 0, 128 / 255.0)),
        ("#000000FF", (0, 0, 0, 1.0)),
    ],
)
def test_a_colour_is_six_or_eight_hex_digits(text, parsed):
    assert appearance.parse(text) == parsed


@pytest.mark.parametrize("text", ["red", "#DAA52", "#DAA5200", "#GGGGGG", " +fffff", "-1-1-1", "", None, 0xDAA520])
def test_anything_else_is_not_a_colour(text):
    assert appearance.parse(text) is None
    assert appearance.normalize(text) is None


@pytest.mark.parametrize(
    "text, normalized",
    [
        ("#daa520", "#DAA520"),
        ("DAA520", "#DAA520"),
        # Opaque is the same colour as no alpha at all.
        ("#daa520ff", "#DAA520"),
        ("#daa52080", "#DAA52080"),
    ],
)
def test_one_colour_is_written_one_way(text, normalized):
    assert appearance.normalize(text) == normalized


def _part(name, color=None):
    """A leaf of the shape tree, with no geometry worth decoding."""
    node = {"name": name, ocp_serialize.KEY_BREP: "unused"}
    if color is not None:
        node["properties"] = {"color": color}
    return node


def _assembly(*children, color=None, location=None):
    node = {"name": None, ocp_serialize.KEY_ASSEMBLY: list(children)}
    if color is not None:
        node["properties"] = {"color": color}
    if location is not None:
        node[ocp_serialize.KEY_LOCATION] = location
    return node


def test_a_shape_that_states_nothing_is_goldenrod():
    assert appearance.colors_of(_part(":plain")) == ["#DAA520"]
    assert appearance.colors_of(_assembly(_part(":a"), _part(":b"))) == ["#DAA520"]


def test_a_colour_is_inherited_by_what_states_none():
    tree = _assembly(
        _part(":plain"),
        _assembly(_part(":inside"), _part(":bolt", "#0000ff"), color="#ff0000"),
        _part(":green", "#00FF00"),
    )
    # In the order they are met; the bolt keeps its own colour inside the red
    # sub-assembly, and nothing outside the sub-assembly is red.
    assert appearance.colors_of(tree) == ["#DAA520", "#FF0000", "#0000FF", "#00FF00"]


def test_stating_the_default_is_the_default():
    tree = _assembly(_part(":plain"), _part(":stated", "#daa520"))
    assert appearance.colors_of(tree) == ["#DAA520"]


def test_a_colour_that_is_not_one_is_ignored_and_said_once():
    warnings = []
    tree = _assembly(_part(":bolt", "red"), _part(":bolt", "red"), _part(":nut", "#00f"))

    assert appearance.colors_of(tree, warnings) == ["#DAA520"]
    assert warnings == [
        "Ignoring the colour 'red' of :bolt, which is not #RRGGBB or #RRGGBBAA",
        "Ignoring the colour '#00f' of :nut, which is not #RRGGBB or #RRGGBBAA",
    ]


def test_the_ide_draws_in_the_same_default():
    """The Digital Thread's copy of the default is this colour.

    A webview cannot import Python, so 'ide/vscode/src/webview/appearance.ts'
    keeps a copy; this is what keeps the copy honest.
    """
    path = os.path.join(REPOSITORY, "ide", "vscode", "src", "webview", "appearance.ts")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    (declared,) = re.findall(r"^export const DEFAULT_COLOR = 0x([0-9a-fA-F]{6});$", source, re.MULTILINE)
    assert "#" + declared.upper() == appearance.DEFAULT_COLOR


# --------------------------------------------------------------------------- #
# The real renderer, in this process                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def real_svg():
    """'render_svg.py' with the real kernel, as the sandbox runs it."""
    spec = importlib.util.spec_from_file_location(
        "partcad.builtin.render.render_svg", os.path.join(RENDER_DIR, "render_svg.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _box(width, depth, height, x=0.0, y=0.0, z=0.0):
    """An encoded box, as a leaf of the shape tree carries it."""
    import build123d as bd

    box = bd.Pos(x, y, z) * bd.Box(width, depth, height, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN))
    return ocp_serialize.encode(box.wrapped)


def _layers(svg):
    """Every layer of the drawing, as {id: (stroke, its <line>s)}.

    A layer is a '<g>' with an 'id', holding what is drawn on it and no group of
    its own; the one '<g>' around them all, which flips the page, has no 'id'
    and is not matched.
    """
    layers = {}
    for match in re.finditer(r'<g ([^>]*\bid="[^"]*"[^>]*)>(.*?)</g>', svg, re.DOTALL):
        attributes = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group(1)))
        lines = [
            tuple(float(value) for value in line)
            for line in re.findall(r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', match.group(2))
        ]
        layers[attributes["id"]] = (attributes.get("stroke"), lines)
    return layers


def _draw(real_svg, tmp_path, tree, reproducible, view="front"):
    """Draw 'tree' as the export wrapper hands it to the renderer: decoded both ways."""
    path = str(tmp_path / "drawing.svg")
    request = {"wrapped": tree, "shape_kind": "assembly", "reproducible": reproducible}
    request.update(resolve_viewport(view))
    result = real_svg.process(path, wrapper_export.decode(request))
    assert result["success"], result
    with open(path, encoding="utf-8") as f:
        return _layers(f.read()), result


@pytest.mark.parametrize("reproducible", [True, False])
def test_a_shape_in_no_colour_is_drawn_in_goldenrod(real_svg, tmp_path, reproducible):
    layers, result = _draw(real_svg, tmp_path, _box(10, 10, 10), reproducible)

    assert list(layers) == ["Visible"]
    stroke, lines = layers["Visible"]
    assert stroke == GOLDENROD
    assert len(lines) == 4
    assert "warnings" not in result


@pytest.mark.parametrize("reproducible", [True, False])
def test_geometry_with_no_tree_is_drawn_in_goldenrod(real_svg, tmp_path, reproducible):
    """What a script that imports the renderer and hands it geometry alone gets."""
    tree = _box(10, 10, 10)
    tree["properties"] = {"color": "#FF0000"}
    path = str(tmp_path / "drawing.svg")
    request = {"wrapped": ocp_serialize.decode(tree), "shape_kind": "part", "reproducible": reproducible}
    request.update(resolve_viewport("front"))
    assert real_svg.process(path, request)["success"]

    with open(path, encoding="utf-8") as f:
        layers = _layers(f.read())
    assert {layer: stroke for layer, (stroke, _lines) in layers.items()} == {"Visible": GOLDENROD}


@pytest.mark.parametrize("reproducible", [True, False])
def test_a_part_that_states_a_colour_is_drawn_in_it(real_svg, tmp_path, reproducible):
    tree = _box(10, 10, 10)
    tree["properties"] = {"color": "#ff0000"}

    layers, _result = _draw(real_svg, tmp_path, tree, reproducible)

    assert list(layers) == ["Visible-FF0000"]
    stroke, lines = layers["Visible-FF0000"]
    assert stroke == RED
    assert len(lines) == 4


@pytest.mark.parametrize("reproducible", [True, False])
def test_a_part_in_front_hides_the_one_behind_it_whatever_colour_either_is(real_svg, tmp_path, reproducible):
    """Several colours are one hidden-line drawing, not one drawing per colour.

    A 100 x 100 plate stands behind a red 40-wide block that covers the middle
    of the plate's bottom edge. From the front, the plate's bottom edge is drawn
    either side of the block and not behind it - which is only true if the
    block was in the way when the plate was projected.
    """
    plate = _box(100, 10, 100, y=50)
    block = _box(40, 10, 30, x=30, z=-10)
    block["properties"] = {"color": "#FF0000"}

    layers, _result = _draw(real_svg, tmp_path, _assembly(plate, block), reproducible)

    assert {layer: stroke for layer, (stroke, _lines) in layers.items()} == {
        "Visible": GOLDENROD,
        "Visible-FF0000": RED,
    }
    # The block is in front of everything: all four sides of it.
    assert len(layers["Visible-FF0000"][1]) == 4
    # The plate's bottom edge, y = 0 on the page: what is left of it lies
    # outside the block, and all of the rest of it is still drawn.
    bottom = [line for line in layers["Visible"][1] if abs(line[1]) < 1e-6 and abs(line[3]) < 1e-6]
    assert bottom, "the plate's bottom edge is not drawn at all"
    for x1, _y1, x2, _y2 in bottom:
        assert max(x1, x2) <= 30 + 1e-6 or min(x1, x2) >= 70 - 1e-6, "drawn behind the block"
    drawn = sum(abs(x2 - x1) for x1, _y1, x2, _y2 in bottom)
    assert drawn == pytest.approx(60, abs=1e-3)


@pytest.mark.parametrize("reproducible", [True, False])
def test_a_colour_nothing_of_is_seen_gets_no_layer(real_svg, tmp_path, reproducible):
    """A part hidden behind the others altogether has nothing to draw.

    Its layer would be an empty '<g>' in the file - noise, and a colour listed
    for a drawing that shows none of it. A drawing in one colour keeps its one
    layer whatever is in it, as it always has.
    """
    plate = _box(100, 10, 100)
    hidden = _box(20, 10, 20, x=40, y=50, z=40)
    hidden["properties"] = {"color": "#FF0000"}

    layers, _result = _draw(real_svg, tmp_path, _assembly(plate, hidden), reproducible)

    assert {layer: stroke for layer, (stroke, _lines) in layers.items()} == {"Visible": GOLDENROD}


@pytest.mark.parametrize("reproducible", [True, False])
def test_a_sub_assembly_is_drawn_where_it_is_placed(real_svg, tmp_path, reproducible):
    """Decoding a leaf at a time keeps every location above it."""
    moved = _assembly(_box(10, 10, 10), location=[[100, 0, 0], [0, 0, 1], 0], color="#00ff00")
    tree = _assembly(_box(10, 10, 10), _assembly(moved, location=[[0, 0, 50], [0, 0, 1], 0]))

    layers, _result = _draw(real_svg, tmp_path, tree, reproducible)

    xs = [x for x1, _y1, x2, _y2 in layers["Visible-00FF00"][1] for x in (x1, x2)]
    ys = [y for _x1, y1, _x2, y2 in layers["Visible-00FF00"][1] for y in (y1, y2)]
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((100, 110, 50, 60), abs=1e-3)


def test_a_colour_that_is_not_one_is_reported(real_svg, tmp_path):
    tree = _box(10, 10, 10)
    tree["name"] = ":bolt"
    tree["properties"] = {"color": "red"}

    layers, result = _draw(real_svg, tmp_path, tree, False)

    assert list(layers) == ["Visible"]
    assert result["warnings"] == ["Ignoring the colour 'red' of :bolt, which is not #RRGGBB or #RRGGBBAA"]


def test_line_color_writes_exactly_the_colour_asked_for(real_svg):
    """'ExportSVG' truncates every channel it writes; half of them used to come out one low."""
    for channel in range(256):
        color = real_svg.line_color((channel, channel, channel))
        assert [int(value * 255) for value in tuple(color)[:3]] == [channel] * 3


# --------------------------------------------------------------------------- #
# End to end, through a package and the sandbox                               #
# --------------------------------------------------------------------------- #

CONFIG = """
parts:
  plain:
    type: build123d
    path: box.py
  red:
    type: build123d
    path: box.py
    properties:
      color: "#FF0000"
assemblies:
  pair:
    type: assy
"""

BOX = """
import build123d as bd

show_object(bd.Box(10, 10, 10).wrapped)
"""

PAIR = """
links:
  - part: plain
  - part: red
    location: [[20, 0, 0], [0, 0, 1], 0]
"""


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("render_colors")
    (root / "partcad.yaml").write_text(CONFIG)
    (root / "box.py").write_text(textwrap.dedent(BOX).lstrip())
    (root / "pair.assy").write_text(textwrap.dedent(PAIR).lstrip())
    return pc.Context(str(root))


@pytest.mark.slow
@pytest.mark.parametrize("file_type", ["svg", "png"])
def test_pc_render_draws_each_part_in_its_colour(context, tmp_path, file_type):
    assembly = context.get_assembly("pair")
    assert assembly is not None
    path = str(tmp_path / ("pair." + file_type))

    assembly.render(context, file_type, filepath=path, reproducible=True, **resolve_viewport("front"))

    if file_type == "svg":
        with open(path, encoding="utf-8") as f:
            layers = _layers(f.read())
        assert {layer: stroke for layer, (stroke, _lines) in layers.items()} == {
            "Visible": GOLDENROD,
            "Visible-FF0000": RED,
        }
        return
    from PIL import Image

    colors = {color for _count, color in Image.open(path).convert("RGB").getcolors(1 << 24)}
    # Anti-aliased, so not only the two colours themselves; but both of them.
    assert (218, 165, 32) in colors
    assert (255, 0, 0) in colors
