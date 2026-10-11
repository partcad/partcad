#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which direction a 2D projection is really drawn from.

'viewport_origin' - and every '--view' name, which is shorthand for one - is
the direction a shape is looked at from: '[0, -100, 0]' is the front of any
shape. The projection underneath is told a camera *position* and a point to look
at, and looks along the line between the two. The SVG renderer used to hand it
'viewport_origin' as that position and the centre of the shape as the point, so
the line of sight ran from a point near the origin to the centre of the shape:
only a shape centred on the origin was drawn from the direction asked for. A
post with one corner on the origin came out of '--view front' as an oblique
view of three of its faces, out of '--view top' as a low view of its front, and
out of '--view back' as a view of its front.

The first half of this file checks, without a sandbox, that every projection the
renderer makes looks along the direction asked for. The second half renders
shapes that are nowhere near the origin, through the real renderer, with both
hidden-line algorithms, and measures what comes out.
"""

import importlib.util
import math
import os
import re
import sys
import textwrap
import types

import pytest

import partcad as pc
from partcad import output
from partcad.render import VIEWS, resolve_viewport

RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]

# --------------------------------------------------------------------------- #
# Which way the camera looks, without a sandbox                               #
# --------------------------------------------------------------------------- #


class _Box:
    size = (1.0, 1.0, 1.0)


class _Shape:
    """What 'process' builds out of the wrapped shape."""

    def __init__(self):
        self.wrapped = None

    def center(self):
        # A centre of mass is a numerical integral, which two machines can
        # disagree about in the last bits; a reproducible drawing must not be
        # measured from one.
        raise AssertionError("the projection must not depend on the centre of the shape")


class _Compound:
    def __init__(self, children=None):
        self.children = children

    def bounding_box(self):
        return _Box()


class _Exporter:
    def __init__(self, scale=None, precision=None):
        self.shapes = []

    def add_layer(self, *args, **kwargs):
        pass

    def add_shape(self, shape, layer=None):
        self.shapes.append((layer, shape))

    def write(self, path):
        # Something for the reproducible path to normalize afterwards.
        with open(path, "w", encoding="utf-8") as f:
            f.write("<svg/>")


def _svg_implementation():
    """The SVG implementation, with the CAD kernel replaced by stand-ins."""
    b3d = types.ModuleType("build123d")
    b3d.Solid = types.SimpleNamespace(make_box=lambda *_args: _Shape())
    b3d.Compound = _Compound
    b3d.ExportSVG = _Exporter
    b3d.Edge = types.SimpleNamespace(make_line=lambda start, end: ("edge", start, end))
    b3d.LineType = types.SimpleNamespace(ISO_DASH="ISO_DASH")

    wrapper_common = types.ModuleType("wrapper_common")

    def handle_exception(e):
        raise e

    wrapper_common.handle_exception = handle_exception
    ocp_serialize = types.ModuleType("ocp_serialize")
    ocp_serialize.compound_of = lambda shapes: list(shapes)

    stubs = {
        "build123d": b3d,
        "wrapper_common": wrapper_common,
        "ocp_serialize": ocp_serialize,
        "label_layout": types.ModuleType("label_layout"),
        "stroke_text": types.ModuleType("stroke_text"),
    }
    saved = {key: sys.modules.get(key) for key in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("test_render_svg_impl", os.path.join(RENDER_DIR, "render_svg.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for key, value in saved.items():
            if value is None:
                del sys.modules[key]
            else:
                sys.modules[key] = value
    return module


@pytest.fixture
def render_svg():
    return _svg_implementation()


def _unit(vector):
    length = math.sqrt(sum(component * component for component in vector))
    return [component / length for component in vector]


def _line_of_sight(origin, look_at):
    """The direction a projection from 'origin' towards 'look_at' looks from."""
    return _unit([origin[axis] - look_at[axis] for axis in range(3)])


def _recording(render_svg, monkeypatch):
    """Replace the projection with one that records how it was asked to look."""
    calls = []

    def project(shape, origin, up, look_at, reproducible=False):
        calls.append((origin, up, look_at, reproducible))
        return []

    monkeypatch.setattr(render_svg, "project", project)
    return calls


@pytest.mark.parametrize("reproducible", [True, False])
@pytest.mark.parametrize("view", sorted(VIEWS))
def test_every_projection_looks_along_the_direction_asked_for(render_svg, monkeypatch, tmp_path, view, reproducible):
    """The shape and what is drawn on top of it, through either algorithm."""
    calls = _recording(render_svg, monkeypatch)
    request = dict(resolve_viewport(view))
    request.update(
        {
            "wrapped": object(),
            "shape_kind": "part",
            "reproducible": reproducible,
            "annotations": [[(0, 0, 0), (10, 0, 0)]],
        }
    )

    assert render_svg.process(str(tmp_path / "drawing.svg"), request) == {"success": True, "exception": None}

    # The shape, then the annotations drawn over it - from the one camera, or
    # they would land somewhere else on the page.
    assert len(calls) == 2
    assert calls[0] == calls[1]
    origin, up, look_at, used_reproducible = calls[0]
    assert _line_of_sight(origin, look_at) == pytest.approx(_unit(VIEWS[view][0]))
    assert list(up) == list(VIEWS[view][1])
    assert used_reproducible is reproducible


def test_the_default_corner_is_a_direction_too(render_svg, monkeypatch, tmp_path):
    calls = _recording(render_svg, monkeypatch)

    render_svg.process(str(tmp_path / "drawing.svg"), {"wrapped": object(), "shape_kind": "part"})

    ((origin, _up, look_at, _reproducible),) = calls
    assert _line_of_sight(origin, look_at) == pytest.approx(_unit(VIEWS["iso"][0]))


# --------------------------------------------------------------------------- #
# What the real renderer draws                                                #
# --------------------------------------------------------------------------- #

# A 4x4 post a foot long, with one corner on the origin - so its centre is far
# from the origin along all three axes, which is what the old projection could
# not cope with. 'flagged' adds a fin along the top of its +X side, so that a
# view and its mirror image - the front and the back - can be told apart.
WIDTH, LENGTH, HEIGHT = 88.9, 304.8, 88.9
FIN_WIDTH, FIN_HEIGHT = 20.0, 30.0

SCRIPTS = {
    "post.py": f"""
        import build123d as bd

        post = bd.Box({WIDTH}, {LENGTH}, {HEIGHT}, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN))
        show_object(post.wrapped)
    """,
    "flagged.py": f"""
        import build123d as bd

        post = bd.Box({WIDTH}, {LENGTH}, {HEIGHT}, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN))
        fin = bd.Pos({WIDTH - FIN_WIDTH}, 0, {HEIGHT}) * bd.Box(
            {FIN_WIDTH}, {LENGTH}, {FIN_HEIGHT}, align=(bd.Align.MIN, bd.Align.MIN, bd.Align.MIN)
        )
        show_object((post + fin).wrapped)
    """,
}

CONFIG = """
parts:
  post:
    type: build123d
  flagged:
    type: build123d
  # The same post, aimed by its own configuration rather than by the caller.
  plan:
    type: build123d
    path: post.py
    render:
      svg:
        viewport_origin: [0, 0, 100]
        viewport_up: [0, 1, 0]
"""

_LINE = re.compile(r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"')
_PATH = re.compile(r' d="([^"]+)"')
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _segments(svg):
    """Every straight line drawn, as ((x1, y1), (x2, y2)) with +Y up the page.

    Everything these shapes have is straight, and both algorithms write a
    straight edge as a '<line>'; a path is read as the polyline its points make,
    in case one of them ever writes a path instead. The drawing is flipped into
    the page by a 'scale(1,-1)' around it, so a larger Y here is higher up.
    """
    segments = []
    for match in _LINE.finditer(svg):
        x1, y1, x2, y2 = (float(value) for value in match.groups())
        segments.append(((x1, y1), (x2, y2)))
    for match in _PATH.finditer(svg):
        numbers = [float(value) for value in _NUMBER.findall(match.group(1))]
        points = list(zip(numbers[0::2], numbers[1::2]))
        segments.extend(zip(points, points[1:]))
    return segments


def _extent(segments):
    xs = [x for segment in segments for x, _y in segment]
    ys = [y for segment in segments for _x, y in segment]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("render_projection")
    (root / "partcad.yaml").write_text(CONFIG)
    for name, script in SCRIPTS.items():
        (root / name).write_text(textwrap.dedent(script).lstrip())
    return pc.Context(str(root))


def _render(context, tmp_path, name, reproducible, **viewport):
    part = context.get_part(name)
    assert part is not None
    path = str(tmp_path / ("%s.svg" % name))
    part.render(context, "svg", filepath=path, reproducible=reproducible, **viewport)
    assert os.path.exists(path), "nothing was rendered"
    with open(path, encoding="utf-8") as f:
        segments = _segments(f.read())
    assert segments, "the projection is empty"
    return segments


@pytest.mark.slow
@pytest.mark.parametrize("reproducible", [True, False])
@pytest.mark.parametrize(
    "view, size",
    [
        # An elevation of a post seen end on is its square cross-section, and
        # nothing else: four lines.
        ("front", (WIDTH, HEIGHT)),
        ("right", (LENGTH, HEIGHT)),
        ("top", (WIDTH, LENGTH)),
    ],
)
def test_a_named_view_of_a_shape_off_the_origin_is_an_orthographic_view(context, tmp_path, view, size, reproducible):
    segments = _render(context, tmp_path, "post", reproducible, **resolve_viewport(view))

    min_x, min_y, max_x, max_y = _extent(segments)
    assert (max_x - min_x, max_y - min_y) == pytest.approx(size, abs=1e-3)
    # One face, seen square on: its outline and no other edge. The old
    # projection drew three faces from a few degrees off, which is nine.
    assert len(segments) == 4


@pytest.mark.slow
@pytest.mark.parametrize("reproducible", [True, False])
@pytest.mark.parametrize("view, fin_on_the_right", [("front", True), ("back", False)])
def test_the_back_is_looked_at_from_behind(context, tmp_path, view, fin_on_the_right, reproducible):
    """+X is on the right of the front view and on the left of the back one.

    The fin runs along the top of the +X side, so the highest line drawn is its
    top - on the right of the picture when the post is seen from the front, on
    the left when it is seen from behind. The old projection drew '--view back'
    of this post from in front of it.
    """
    segments = _render(context, tmp_path, "flagged", reproducible, **resolve_viewport(view))

    min_x, min_y, max_x, max_y = _extent(segments)
    assert (max_x - min_x, max_y - min_y) == pytest.approx((WIDTH, HEIGHT + FIN_HEIGHT), abs=1e-3)
    (top,) = [segment for segment in segments if all(abs(y - max_y) < 1e-6 for _x, y in segment)]
    middle = (top[0][0] + top[1][0]) / 2.0
    assert (middle > (min_x + max_x) / 2.0) is fin_on_the_right


@pytest.mark.slow
@pytest.mark.parametrize("reproducible", [True, False])
def test_a_configured_viewport_is_a_direction_too(context, tmp_path, reproducible):
    """The package's own 'viewport_origin', not only the command line's."""
    segments = _render(context, tmp_path, "plan", reproducible)

    min_x, min_y, max_x, max_y = _extent(segments)
    assert (max_x - min_x, max_y - min_y) == pytest.approx((WIDTH, LENGTH), abs=1e-3)
    assert len(segments) == 4
