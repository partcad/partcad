#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`measure.py`, the helper the `gen-sketch` skill ships beside its `SKILL.md`.

It is what turns a drawing into numbers, and an agent comparing those numbers
against a target has no way to tell a wrong reading from a right one: a radius
reported as a diameter, or a Y read the wrong way up, is still a plausible
number. So each drawing here is written by hand, in the shape PartCAD's SVG
renderer writes one, with the answer worked out beside it.

It is loaded from the skills library rather than imported, because it is not a
module of any package -- `pc init` copies it into a user's repository beside the
skill -- and without writing bytecode, so that running the tests leaves nothing
in the library for the wheel or `pc init` to carry along.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[3] / "ai-agents" / "common" / "skills" / "gen-sketch" / "measure.py"


@pytest.fixture(scope="module")
def measure():
    spec = importlib.util.spec_from_file_location("measure", HELPER)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def render(body, overlays="", width="513.0mm", view_box="-50.1 -30.1 100.2 60.2"):
    """An SVG laid out the way PartCAD's renderer writes one: model numbers inside a flipped group."""
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<svg width="%s" height="308.2mm" viewBox="%s" version="1.1" xmlns="http://www.w3.org/2000/svg">\n'
        '  <g transform="scale(1,-1)" stroke-linecap="round">\n'
        '    <g fill="none" stroke="rgb(218,165,32)" stroke-width="0.2" id="Visible">\n'
        "%s\n"
        "    </g>\n"
        "%s\n"
        "  </g>\n"
        "</svg>\n"
    ) % (width, view_box, body, overlays)


def line(x1, y1, x2, y2):
    return '      <line x1="%.10f" y1="%.10f" x2="%.10f" y2="%.10f" />' % (x1, y1, x2, y2)


def polygon_lines(points):
    return "\n".join(line(*p, *q) for p, q in zip(points, points[1:] + points[:1]))


# The 100 x 60 plate every drawing below sits on, centred on the origin.
PLATE = polygon_lines([(-50, -30), (50, -30), (50, 30), (-50, 30)])


def measured(measure, tmp_path, svg, **options):
    path = tmp_path / "drawing.svg"
    path.write_text(svg)
    return measure.analyse(measure.read_svg(str(path), **options))


def close(a, b, tolerance=1e-6):
    return abs(a - b) <= tolerance


def test_a_rectangle_is_its_extent_and_four_edges(measure, tmp_path):
    report = measured(measure, tmp_path, render(PLATE))

    assert close(report["extent"]["width"], 100.0)
    assert close(report["extent"]["height"], 60.0)
    assert [s["at"] for s in report["vertical"]] == pytest.approx([-50.0, 50.0])
    assert [s["from_origin"] for s in report["vertical"]] == pytest.approx([0.0, 100.0])
    assert [s["at"] for s in report["horizontal"]] == pytest.approx([-30.0, 30.0])
    assert all(close(s["length"], 60.0) for s in report["vertical"])
    assert not report["circles"] and not report["arcs"] and not report["lines"]


def test_the_numbers_are_the_models_whatever_the_flip(measure, tmp_path):
    """A hole at (42, 22) in the model is written cy="22" inside the scale(1,-1): it is at y = +22, not -22."""
    report = measured(measure, tmp_path, render(PLATE + '\n      <circle cx="42.0" cy="22.0" r="2.5" />'))

    (hole,) = report["circles"]
    assert close(hole["diameter"], 5.0)
    assert (hole["x"], hole["y"]) == pytest.approx((42.0, 22.0))
    assert (hole["from_left"], hole["from_bottom"]) == pytest.approx((92.0, 52.0))
    assert hole["source"] == "exact"


def test_a_circle_the_projection_drew_as_a_polygon_is_fitted(measure, tmp_path):
    """The polygonal projection writes a hole as line segments whose ends lie on it."""
    points = [
        (-42 + 2.5 * math.cos(2 * math.pi * k / 26), -22 + 2.5 * math.sin(2 * math.pi * k / 26)) for k in range(26)
    ]
    report = measured(measure, tmp_path, render(PLATE + "\n" + polygon_lines(points)))

    (hole,) = report["circles"]
    assert close(hole["diameter"], 5.0, 1e-8)
    assert (hole["from_left"], hole["from_bottom"]) == pytest.approx((8.0, 8.0))
    assert hole["source"] == "fitted" and hole["segments"] == 26
    assert not hole.get("approximate")
    assert not report["lines"]


def test_a_hexagon_is_an_outline_and_not_a_circle(measure, tmp_path):
    corners = [(30 + 6 * math.cos(math.pi * k / 3), 6 * math.sin(math.pi * k / 3)) for k in range(6)]
    report = measured(measure, tmp_path, render(PLATE + "\n" + polygon_lines(corners)))

    assert not report["circles"]
    (outline,) = report["loops"]
    assert close(outline["widest"], 12.0)  # across the corners
    assert close(outline["narrowest"], 12.0 * math.cos(math.pi / 6))  # across the flats, 10.392
    assert (outline["x"], outline["y"]) == pytest.approx((30.0, 0.0))


def test_a_full_circle_written_as_two_arcs_is_one_circle(measure, tmp_path):
    """What build123d writes for a closed circle it does not write as <circle>."""
    path = '      <path d="M 2.5,0.0 A 2.5,2.5 0.0 0,1 -2.5,0.0 A 2.5,2.5 0.0 0,1 2.5,0.0" />'
    report = measured(measure, tmp_path, render(PLATE + "\n" + path))

    (hole,) = report["circles"]
    assert close(hole["diameter"], 5.0)
    assert (hole["x"], hole["y"]) == pytest.approx((0.0, 0.0))
    assert not report["arcs"]


def test_a_slot_is_two_half_circles_the_width_apart(measure, tmp_path):
    """A 30 x 8 slot: its ends are R4 about (-11, 0) and (11, 0), and its sides are 22 long."""
    path = '      <path d="M -11,-4 L 11,-4 A 4,4 0 0,1 11,4 L -11,4 A 4,4 0 0,1 -11,-4" />'
    report = measured(measure, tmp_path, render(PLATE + "\n" + path))

    assert len(report["arcs"]) == 2
    assert all(close(a["radius"], 4.0) and close(a["sweep"], 180.0) for a in report["arcs"])
    assert sorted(a["x"] for a in report["arcs"]) == pytest.approx([-11.0, 11.0])
    sides = [s for s in report["horizontal"] if abs(s["at"]) < 5]
    assert [s["at"] for s in sides] == pytest.approx([-4.0, 4.0])
    assert all(close(s["length"], 22.0) for s in sides)


def test_arc_flags_written_without_a_separator(measure, tmp_path):
    """'0 015,5' is large-arc 0, sweep 1, then the point (5, 5): a quarter circle of radius 5."""
    report = measured(measure, tmp_path, render(PLATE + '\n      <path d="M 0,0 a5,5 0 015,5" />'))

    (arc,) = report["arcs"]
    assert close(arc["radius"], 5.0)
    assert close(arc["sweep"], 90.0)


def test_the_overlays_are_not_geometry(measure, tmp_path):
    ports = '    <g id="Ports">\n%s\n    </g>' % line(0, 0, 500, 0)
    svg = render(PLATE, overlays=ports)

    assert close(measured(measure, tmp_path, svg)["extent"]["width"], 100.0)
    everything = measured(measure, tmp_path, svg, all_layers=True)
    assert close(everything["extent"]["width"], 550.0)
    assert everything["read"] == ["Ports", "Visible"]


def test_any_other_svg_is_read_through_its_transforms(measure, tmp_path):
    """No Visible layer, so everything is read; Y points down the page, so it is turned up."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
        '<g transform="translate(10,20) scale(2)"><circle cx="1" cy="1" r="1" /></g>'
        "</svg>"
    )
    (circle,) = measured(measure, tmp_path, svg)["circles"]

    assert close(circle["diameter"], 4.0)
    assert (circle["x"], circle["y"]) == pytest.approx((12.0, -22.0))


def test_an_ellipse_has_two_diameters(measure, tmp_path):
    """A circle of 10 on a face, seen in an isometric view: 10 across one way, 10 / sqrt(3) the other."""
    minor = 10.0 / math.sqrt(3.0)
    svg = render(
        PLATE
        + '\n      <ellipse cx="0" cy="0" rx="5" ry="%.10f" />' % (minor / 2)
        + '\n      <g transform="rotate(30)"><ellipse cx="0" cy="0" rx="4" ry="1" /></g>'
    )
    ellipses = sorted(measured(measure, tmp_path, svg)["ellipses"], key=lambda e: -e["major"])

    assert close(ellipses[0]["major"], 10.0) and close(ellipses[0]["minor"], minor)
    assert close(ellipses[0]["angle"] % 180.0, 0.0)
    assert close(ellipses[1]["major"], 8.0) and close(ellipses[1]["minor"], 2.0)


def test_a_polygon_drawn_from_an_ellipse_is_that_ellipse_and_not_an_arc(measure, tmp_path):
    """The polygonal projection of a hole seen at a slant: its vertices are on the ellipse, so it is one."""
    points = [(20 * math.cos(2 * math.pi * k / 48) / 2, 12 * math.sin(2 * math.pi * k / 48) / 2) for k in range(48)]
    report = measured(measure, tmp_path, render(PLATE + "\n" + polygon_lines(points)))

    assert not report["circles"] and not report["arcs"] and not report["loops"]
    (ellipse,) = report["ellipses"]
    assert close(ellipse["major"], 20.0) and close(ellipse["minor"], 12.0)
    assert close(ellipse["angle"] % 180.0, 0.0) and close(ellipse["sweep"], 360.0)
    assert ellipse["source"] == "fitted"


def polyline_lines(points):
    return "\n".join(line(*p, *q) for p, q in zip(points, points[1:]))


def test_an_open_polygon_of_an_ellipse_is_an_elliptic_arc(measure, tmp_path):
    """A fillet seen in an isometric view: a quarter ellipse between two straight edges it is tangent to."""
    a, b = 10.0, 5.0
    arc = [(a * math.cos(math.pi / 2 * k / 12), b * math.sin(math.pi / 2 * k / 12)) for k in range(13)]
    edges = [(a, -40.0)] + arc + [(-40.0, b)]
    report = measured(measure, tmp_path, render(PLATE + "\n" + polyline_lines(edges)))

    (ellipse,) = report["ellipses"]
    assert close(ellipse["major"], 20.0) and close(ellipse["minor"], 10.0)
    assert close(ellipse["sweep"], 90.0)
    assert (ellipse["x"], ellipse["y"]) == pytest.approx((0.0, 0.0), abs=1e-6)


def test_an_arc_cut_on_a_chord_by_the_hidden_line_algorithm_is_still_the_arc(measure, tmp_path):
    """Where a curve goes behind something, the polygonal projection ends it on a chord, off the curve."""
    arc = [(10 * math.cos(math.radians(d)), 10 * math.sin(math.radians(d))) for d in range(0, 91, 10)]
    end = (10 * math.cos(math.radians(100)), 10 * math.sin(math.radians(100)))
    cut = ((arc[-1][0] + end[0]) / 2.0, (arc[-1][1] + end[1]) / 2.0)  # half way along the next chord
    report = measured(measure, tmp_path, render(PLATE + "\n" + polyline_lines(arc + [cut])))

    (piece,) = report["arcs"]
    assert close(piece["radius"], 10.0, 1e-8)
    assert piece["sweep"] == pytest.approx(95.0, abs=0.05)
    assert not report["lines"]


def test_an_edge_drawn_twice_is_one_edge(measure, tmp_path):
    """The exact projection draws a chamfer seen edge on twice; it is still one edge."""
    report = measured(measure, tmp_path, render(PLATE + "\n" + line(-50, -30, -50, 30)))

    assert [s["length"] for s in report["vertical"]] == pytest.approx([60.0, 60.0])
    assert not report["lines"]


def test_an_edge_broken_where_another_meets_it_is_one_edge(measure, tmp_path):
    """The polygonal projection breaks a straight edge where a third edge touches it; the exact one does not."""
    body = "\n".join([line(0, 0, 30, 30), line(30, 30, 40, 40), line(30, 30, 45, 20)])
    report = measured(measure, tmp_path, render(PLATE + "\n" + body))

    lengths = sorted(round(line_["length"], 6) for line_ in report["lines"])
    assert lengths == pytest.approx(sorted([round(40 * math.sqrt(2), 6), round(math.hypot(15, 10), 6)]))


def test_the_extent_reaches_a_fitted_circles_true_edge(measure, tmp_path):
    """No vertex of this polygon is at the circle's left or right, and the drawing is still 10 wide."""
    points = [
        (5 * math.cos(math.radians(7 + k * 360 / 26)), 5 * math.sin(math.radians(7 + k * 360 / 26))) for k in range(26)
    ]
    report = measured(measure, tmp_path, render(polygon_lines(points)))

    assert close(report["extent"]["width"], 10.0, 1e-8) and close(report["extent"]["height"], 10.0, 1e-8)


def test_a_bezier_curve_is_a_spline_and_is_not_fitted(measure, tmp_path):
    """A spline is written as Bezier curves; over a short run some ellipse is always close to one."""
    report = measured(measure, tmp_path, render(PLATE + '\n      <path d="M -20,0 C -10,15 0,-10 20,5" />'))

    assert not report["ellipses"] and not report["arcs"] and not report["circles"]
    (spline,) = report["splines"]
    assert spline["start"] == pytest.approx([-20.0, 0.0]) and spline["end"] == pytest.approx([20.0, 5.0])
    assert spline["length"] > 40.0


def test_a_circle_drawn_as_bezier_curves_is_approximate(measure, tmp_path):
    """Four cubic curves are how most drawing programs write a circle; they are round to about 3e-4 of it."""
    k = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0) * 10.0
    d = "M 10,0 C 10,%f %f,10 0,10 C -%f,10 -10,%f -10,0 C -10,-%f -%f,-10 0,-10 C %f,-10 10,-%f 10,0 Z" % ((k,) * 8)
    (circle,) = measured(measure, tmp_path, render(PLATE + '\n      <path d="%s" />' % d))["circles"]

    assert close(circle["diameter"], 20.0, 0.02)
    assert circle["approximate"] is True


# --- two projections of one drawing ----------------------------------------------

# The same drawing twice: as the exact projection writes it, its curves as
# curves, and as the polygonal one does, its curves as polygons.
HOLE = '      <circle cx="-42.0" cy="-22.0" r="2.5" />'
SLOT = '      <path d="M -11,-4 L 11,-4 A 4,4 0 0,1 11,4 L -11,4 A 4,4 0 0,1 -11,-4" />'


def polygonal_hole(diameter=5.0, shift=(0.0, 0.0)):
    r = diameter / 2.0
    return polygon_lines(
        [
            (-42 + shift[0] + r * math.cos(2 * math.pi * k / 26), -22 + shift[1] + r * math.sin(2 * math.pi * k / 26))
            for k in range(26)
        ]
    )


def polygonal_slot(shift=(0.0, 0.0)):
    sx, sy = shift
    right = [(11 + sx + 4 * math.sin(math.pi * k / 12), sy - 4 * math.cos(math.pi * k / 12)) for k in range(13)]
    left = [(-11 + sx - 4 * math.sin(math.pi * k / 12), sy + 4 * math.cos(math.pi * k / 12)) for k in range(13)]
    return polygon_lines(right + left)


def shifted_plate(shift):
    sx, sy = shift
    return polygon_lines([(-50 + sx, -30 + sy), (50 + sx, -30 + sy), (50 + sx, 30 + sy), (-50 + sx, 30 + sy)])


def compared(measure, tmp_path, first, second):
    return measure.compare(measured(measure, tmp_path, first), measured(measure, tmp_path, second))


def test_two_projections_of_one_drawing_agree(measure, tmp_path):
    exact = render("\n".join([PLATE, HOLE, SLOT]))
    polygonal = render("\n".join([PLATE, polygonal_hole(), polygonal_slot()]))
    result = compared(measure, tmp_path, exact, polygonal)

    assert result["agree"], result
    assert result["kinds"]["circles"]["paired"] == 1 and result["kinds"]["arcs"]["paired"] == 2


def test_they_are_compared_wherever_each_put_the_origin(measure, tmp_path):
    """The two hidden-line algorithms need not put the model's origin in one place on the picture."""
    exact = render("\n".join([PLATE, HOLE, SLOT]))
    shift = (3.0, 4.0)
    polygonal = render("\n".join([shifted_plate(shift), polygonal_hole(shift=shift), polygonal_slot(shift)]))
    result = compared(measure, tmp_path, exact, polygonal)

    assert result["agree"], result
    assert result["shift"] == pytest.approx([-3.0, -4.0])


def test_a_feature_only_one_projection_drew_is_reported(measure, tmp_path, capsys):
    exact = render("\n".join([PLATE, HOLE, SLOT]))
    polygonal = render("\n".join([PLATE, polygonal_slot()]))
    result = compared(measure, tmp_path, exact, polygonal)

    assert not result["agree"]
    (missing,) = result["kinds"]["circles"]["only_first"]
    assert close(missing["diameter"], 5.0)

    first, second = tmp_path / "exact.svg", tmp_path / "polygonal.svg"
    first.write_text(exact)
    second.write_text(polygonal)
    assert measure.main(["compare", str(first), str(second)]) == 1
    assert "only in the first: diameter 5.0000" in capsys.readouterr().out


def test_a_dimension_the_two_disagree_on_is_reported(measure, tmp_path):
    exact = render("\n".join([PLATE, HOLE]))
    polygonal = render("\n".join([PLATE, polygonal_hole(diameter=5.1)]))
    result = compared(measure, tmp_path, exact, polygonal)

    assert not result["agree"]
    (pair,) = result["kinds"]["circles"]["differing"]
    assert pair["differences"]["diameter"] == pytest.approx(-0.1)


def test_the_steps_of_a_curve_only_one_side_could_fit_are_one_entry(measure, tmp_path):
    """A polygon of a curve that is neither a circle nor an ellipse is reported once, not step by step."""
    wave = [(-20 + 2 * k, 10 + 2 * math.sin(k / 2.0) + 0.1 * k * k / 10) for k in range(16)]
    exact = render("\n".join([PLATE, HOLE]))
    polygonal = render("\n".join([PLATE, polygonal_hole(), polyline_lines(wave)]))
    result = compared(measure, tmp_path, exact, polygonal)

    assert not result["agree"]
    (group,) = result["kinds"]["lines"]["polygons"]["second"]
    assert group["segments"] == 15
    assert not result["kinds"]["lines"]["only_second"]


def test_the_page_says_what_one_unit_is_printed_at(measure, tmp_path):
    """What PartCAD's svg sketch type reads a file at: 101 mm over a viewBox 20.2 wide is 5 mm a unit."""
    report = measured(measure, tmp_path, render(PLATE, width="101.0mm", view_box="-10.1 -9.8 20.2 19.6"))

    assert close(report["page"]["mm_per_unit"], 5.0)
    assert close(report["extent"]["width"], 100.0)  # the units themselves are not rescaled


def test_the_command_line_prints_the_report(measure, tmp_path, capsys):
    path = tmp_path / "drawing.svg"
    path.write_text(render(PLATE + '\n      <circle cx="42.0" cy="22.0" r="2.5" />'))

    assert measure.main(["svg", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert close(report["circles"][0]["diameter"], 5.0)

    assert measure.main(["svg", str(path)]) == 0
    text = capsys.readouterr().out
    assert "extent: width 100.0000  height 60.0000" in text
    assert "C1  diameter 5.0000" in text


@pytest.mark.parametrize(
    "arguments",
    [
        ["svg", "{file}", "--tolerance", "0"],
        ["svg", "{file}", "--tolerance", "-1"],
        ["compare", "{file}", "{file}", "--agreement", "-0.1"],
        ["image", "{file}", "--threshold", "0"],
        ["image", "{file}", "--threshold", "256"],
    ],
)
def test_a_value_nothing_can_be_measured_with_is_a_usage_error(measure, tmp_path, capsys, arguments):
    """A tolerance of 0 is divided by, and a threshold of 0 makes every pixel ink: refused, not a traceback."""
    path = tmp_path / "drawing.svg"
    path.write_text(render(PLATE))

    with pytest.raises(SystemExit) as excinfo:
        measure.main([argument.format(file=path) for argument in arguments])

    assert excinfo.value.code == 2
    assert "expected" in capsys.readouterr().err


def test_an_agreement_of_zero_asks_for_the_same_numbers(measure, tmp_path, capsys):
    path = tmp_path / "drawing.svg"
    path.write_text(render(PLATE))

    assert measure.main(["compare", str(path), str(path), "--agreement", "0"]) == 0


# --- raster pictures --------------------------------------------------------


@pytest.fixture
def pillow():
    return pytest.importorskip("PIL.Image")


def drawing(pillow, mode="RGB", background=(255, 255, 255), ink=(0, 0, 0)):
    """200 x 100 px: a frame whose sides are at x = 20 and 170 and y = 10 and 90, one pixel wide."""
    picture = pillow.new(mode, (200, 100), background)
    pixels = picture.load()
    for y in range(10, 91):
        pixels[20, y] = ink
        pixels[170, y] = ink
    for x in range(20, 171):
        pixels[x, 10] = ink
        pixels[x, 90] = ink
    return picture


def test_a_row_crosses_each_line_where_it_is(measure, pillow, tmp_path):
    path = tmp_path / "frame.png"
    drawing(pillow).save(path)

    report = measure.measure_image(str(path), rows=[50], columns=[100], px_per_mm=3.0)

    assert [run["centre"] for run in report["rows"][0]["runs"]] == pytest.approx([20.0, 170.0])
    assert [run["centre"] for run in report["columns"][0]["runs"]] == pytest.approx([10.0, 90.0])
    box = report["bbox"]
    assert (box["left"], box["top"], box["right"], box["bottom"]) == (20, 10, 170, 90)
    assert (box["width"], box["height"]) == (151, 81)


def test_a_transparent_background_is_white(measure, pillow, tmp_path):
    """A drawing whose lines reach its frame: the commonest colour is the background, not the border's."""
    path = tmp_path / "frame.png"
    drawing(pillow, mode="RGBA", background=(0, 0, 0, 0), ink=(218, 165, 32, 255)).save(path)

    report = measure.measure_image(str(path), rows=[50])

    assert tuple(report["background"]) == (255, 255, 255)
    assert [run["centre"] for run in report["rows"][0]["runs"]] == pytest.approx([20.0, 170.0])


def test_an_anti_aliased_edge_is_placed_between_its_pixels(measure, pillow, tmp_path):
    """Full ink at x = 50 and half ink at x = 51: the line is a third of a pixel right of 50."""
    picture = pillow.new("L", (100, 20), 255)
    pixels = picture.load()
    for y in range(20):
        pixels[50, y] = 0
        pixels[51, y] = 128
    path = tmp_path / "edge.png"
    picture.save(path)

    (run,) = measure.measure_image(str(path), rows=[10])["rows"][0]["runs"]

    assert run["start"] == 50 and run["end"] == 51
    assert run["centre"] == pytest.approx(50 + 127.0 / (255.0 + 127.0))


def test_calibration_is_pixels_per_millimetre(measure, pillow, tmp_path, capsys):
    path = tmp_path / "frame.png"
    drawing(pillow).save(path)

    assert measure.main(["image", str(path), "--row", "50", "--calibrate", "150=50", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["px_per_mm"] == pytest.approx(3.0)

    assert measure.main(["image", str(path), "--row", "50", "--calibrate", "150=50"]) == 0
    assert "centre to previous centre 150.00 px (50.000 mm)" in capsys.readouterr().out
