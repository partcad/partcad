#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a DXF drawing draws, read before CadQuery sees any of it.

'dxf_drawing' explodes block references, turns mirrored entities the right way
up and selects layers -- everything about reading a DXF sketch that is about the
drawing rather than about geometry. It imports ezdxf and no CAD library, so
unlike the rest of the reader it is tested here, in process; what CadQuery then
builds from it is tested through the sandbox in 'test_sketch_dxf_faces.py'.
"""

import os
import sys

import ezdxf
import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import dxf_drawing  # noqa: E402


def _square(layout, x, y, size, layer="0"):
    layout.add_lwpolyline(
        [(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
        close=True,
        dxfattribs={"layer": layer},
    )


def _kinds(document):
    """[(type, layer)] of everything in modelspace, sorted."""
    return sorted((entity.dxftype(), entity.dxf.layer) for entity in document.modelspace())


#
# Which blocks would never finish exploding
#


def test_a_block_that_places_nothing_is_finite():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    _square(document.blocks.new("PAD"), 0, 0, 1)
    assert dxf_drawing.endless_blocks(document) == set()


def test_blocks_inside_blocks_are_finite():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    _square(document.blocks.new("PAD"), 0, 0, 1)
    document.blocks.new("PAIR").add_blockref("PAD", (0, 0))
    document.blocks.new("QUAD").add_blockref("PAIR", (0, 0))
    assert dxf_drawing.endless_blocks(document) == set()


def test_a_block_that_places_itself_is_endless_and_so_is_whatever_places_it():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    document.blocks.new("LOOP").add_blockref("LOOP", (1, 0))
    document.blocks.new("VIA").add_blockref("LOOP", (0, 0))
    _square(document.blocks.new("PAD"), 0, 0, 1)
    assert dxf_drawing.endless_blocks(document) == {"loop", "via"}


def test_two_blocks_that_place_each_other_are_both_endless():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    document.blocks.new("PING").add_blockref("PONG", (0, 0))
    document.blocks.new("PONG").add_blockref("Ping", (0, 0))  # names are not case-sensitive
    assert dxf_drawing.endless_blocks(document) == {"ping", "pong"}


def test_a_block_that_places_one_that_is_not_defined_is_finite():
    """The missing reference is left out when it is reached; the block around it is fine."""
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    ref = document.blocks.new("OUTER").add_blockref("PAD", (0, 0))
    ref.dxf.name = "MISSING"
    assert dxf_drawing.endless_blocks(document) == set()


#
# Exploding them
#


def test_a_drawing_with_no_blocks_is_left_as_it_is():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    _square(document.modelspace(), 0, 0, 10, layer="PLATE")
    assert dxf_drawing.explode_blocks(document)[0] == []
    assert _kinds(document) == [("LWPOLYLINE", "PLATE")]


def test_layer_zero_in_a_block_takes_the_layer_of_the_reference():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    block = document.blocks.new("PAD")
    _square(block, 0, 0, 1)
    block.add_circle((0, 0), 1, dxfattribs={"layer": "MARK"})
    document.modelspace().add_blockref("PAD", (5, 0), dxfattribs={"layer": "PADS"})

    assert dxf_drawing.explode_blocks(document)[0] == []
    assert _kinds(document) == [("CIRCLE", "MARK"), ("LWPOLYLINE", "PADS")]


def test_nested_blocks_and_grids_are_exploded_all_the_way_down():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    _square(document.blocks.new("PAD"), 0, 0, 1)
    pair = document.blocks.new("PAIR")
    pair.add_blockref("PAD", (0, 0))
    pair.add_blockref("PAD", (2, 0))
    document.modelspace().add_blockref("PAIR", (0, 0), dxfattribs={"layer": "GRID"}).grid(size=(2, 3), spacing=(5, 10))

    assert dxf_drawing.explode_blocks(document)[0] == []
    assert _kinds(document) == [("LWPOLYLINE", "GRID")] * (2 * 2 * 3)


def test_references_that_cannot_be_followed_are_left_out_and_counted():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    _square(document.modelspace(), 0, 0, 10)
    document.blocks.new("LOOP").add_blockref("LOOP", (1, 0))
    document.modelspace().add_blockref("LOOP", (0, 0))
    document.modelspace().add_blockref("LOOP", (0, 5))
    _square(document.blocks.new("PAD"), 0, 0, 1)
    document.modelspace().add_blockref("PAD", (0, 0)).dxf.name = "MISSING"

    warnings, _ = dxf_drawing.explode_blocks(document)

    assert len(warnings) == 2
    assert (
        warnings[0]
        == '2 block reference(s) were left out: block "LOOP" places itself, directly or through other blocks'
    )
    assert warnings[1].startswith("1 block reference(s) were left out: ")
    assert "MISSING" in warnings[1]
    assert _kinds(document) == [("LWPOLYLINE", "0")]


#
# Reading a drawing
#


def _saved(tmp_path, draw):
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    draw(document)
    path = str(tmp_path / "drawing.dxf")
    document.saveas(path)
    return path


def test_a_mirrored_circle_is_restated_where_it_was_mirrored_to(tmp_path):
    path = _saved(tmp_path, lambda doc: doc.modelspace().add_circle((5, 0), 1, dxfattribs={"extrusion": (0, 0, -1)}))

    drawing = dxf_drawing.read(path)
    layers, warnings = drawing.layers, drawing.warnings

    [circle] = layers["0"]
    assert warnings == []
    assert tuple(circle.dxf.extrusion) == (0, 0, 1)
    assert tuple(circle.dxf.center)[:2] == pytest.approx((-5, 0))


def test_layers_are_selected_without_regard_to_case(tmp_path):
    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10, layer="PLATE")
        _square(doc.modelspace(), 20, 0, 5, layer="TAB")

    path = _saved(tmp_path, draw)

    assert sorted(dxf_drawing.read(path).layers) == ["PLATE", "TAB"]
    assert sorted(dxf_drawing.read(path, include=["tab"]).layers) == ["TAB"]
    assert sorted(dxf_drawing.read(path, exclude=["Tab"]).layers) == ["PLATE"]


def test_a_selection_that_matches_no_layer_is_refused(tmp_path):
    path = _saved(tmp_path, lambda doc: _square(doc.modelspace(), 0, 0, 10, layer="PLATE"))
    with pytest.raises(ValueError, match="no DXF layers selected"):
        dxf_drawing.read(path, include=["NOTES"])


def test_include_and_exclude_together_are_refused_before_anything_is_read(tmp_path):
    with pytest.raises(ValueError, match="either 'include' or 'exclude' but not both"):
        dxf_drawing.read(str(tmp_path / "not-even-there.dxf"), include=["A"], exclude=["B"])


def test_what_was_left_out_comes_back_with_the_layers(tmp_path):
    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10)
        doc.blocks.new("LOOP").add_blockref("LOOP", (1, 0))
        doc.modelspace().add_blockref("LOOP", (0, 0))

    drawing = dxf_drawing.read(_saved(tmp_path, draw))
    layers, warnings = drawing.layers, drawing.warnings
    assert list(layers) == ["0"]
    assert warnings == [
        '1 block reference(s) were left out: block "LOOP" places itself, directly or through other blocks'
    ]


#
# What a sketch of the shapes is
#


def test_one_shape_is_that_shape():
    assert dxf_drawing.one_shape(["face"], compound=lambda shapes: ("compound", shapes)) == "face"


def test_several_shapes_are_a_compound_of_all_of_them():
    assert dxf_drawing.one_shape(["a", "b"], compound=lambda shapes: ("compound", shapes)) == ("compound", ["a", "b"])


def test_wires_are_always_a_compound():
    compound = dxf_drawing.one_shape(["wire"], compound=lambda shapes: ("compound", shapes), always_compound=True)
    assert compound == ("compound", ["wire"])


def test_nothing_is_not_a_sketch():
    with pytest.raises(ValueError, match="draw nothing"):
        dxf_drawing.one_shape([], compound=list)


#
# What the numbers are in
#


def _in_units(tmp_path, code, draw=None):
    document = ezdxf.new("R2010", units=code)
    document.modelspace().add_line((0, 0), (1, 0))
    if draw:
        draw(document)
    path = str(tmp_path / ("drawing-%d.dxf" % code))
    document.saveas(path)
    return path


@pytest.mark.parametrize(
    "code, factor, name",
    [(1, 25.4, "in"), (4, 1.0, "mm"), (5, 10.0, "cm"), (6, 1000.0, "m"), (2, 304.8, "ft"), (0, 1.0, None)],
)
def test_a_drawing_is_scaled_to_millimetres_by_what_it_says(tmp_path, code, factor, name):
    drawing = dxf_drawing.read(_in_units(tmp_path, code))

    [line] = drawing.layers["0"]
    assert tuple(line.dxf.end)[:2] == pytest.approx((factor, 0.0))
    assert drawing.scale == factor
    assert drawing.units == name
    assert drawing.warnings == []


def test_the_declaration_says_what_the_drawing_does_not(tmp_path):
    """'units:' outranks '$INSUNITS': a drawing saved as metres that is really millimetres."""
    path = _in_units(tmp_path, 6)

    assert dxf_drawing.read(path, units="mm").scale == 1.0
    assert dxf_drawing.read(path, units="unitless").scale == 1.0
    assert dxf_drawing.read(path, units="IN").scale == 25.4
    assert dxf_drawing.read(path, units="auto").scale == 1000.0


def test_a_unit_nobody_knows_is_refused_rather_than_guessed(tmp_path):
    with pytest.raises(ValueError, match="unknown 'units' 'furlong'"):
        dxf_drawing.read(_in_units(tmp_path, 4), units="furlong")


def test_a_code_dxf_gained_since_is_millimetres_with_a_warning(tmp_path):
    path = _in_units(tmp_path, 4)
    document = ezdxf.readfile(path)
    document.header["$INSUNITS"] = 99

    factor, unit, warning = dxf_drawing.millimetres_per_unit(document)

    assert (factor, unit) == (1.0, None)
    assert "unknown (99)" in warning


def test_the_us_survey_foot_is_not_the_international_one():
    assert dxf_drawing.MILLIMETRES_PER_UNIT["us-ft"] == pytest.approx(304.8006096)
    assert dxf_drawing.MILLIMETRES_PER_UNIT["ft"] == 304.8


def test_what_cannot_be_scaled_is_left_out_and_said(monkeypatch):
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    document.modelspace().add_line((0, 0), (1, 0))
    document.modelspace().add_circle((0, 0), 1)

    def refuse(self, matrix):
        raise NotImplementedError("no")

    monkeypatch.setattr(type(document.modelspace().query("CIRCLE")[0]), "transform", refuse)
    warnings = dxf_drawing.scale(document, 25.4)

    assert warnings == ["1 CIRCLE element(s) could not be scaled to millimetres and were left out"]
    assert _kinds(document) == [("LINE", "0")]


#
# Where an exploded element came from
#


def test_an_exploded_element_remembers_its_entity_and_its_reference():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    block = document.blocks.new("BEND")
    line = block.add_line((0, 0), (10, 0))
    reference = document.modelspace().add_blockref("BEND", (0, 5)).dxf.handle  # the reference goes when exploded

    _, origins = dxf_drawing.explode_blocks(document)

    [placed] = document.modelspace()
    origin = origins[placed.dxf.handle]
    assert origin["source"] == line.dxf.handle
    assert origin["references"] == [reference]
    assert not placed.has_xdata(dxf_drawing.SOURCE_APPID)  # the tracing tag does not outlive the read


def test_a_nested_element_names_every_reference_outermost_first():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    pad = document.blocks.new("PAD")
    line = pad.add_line((0, 0), (1, 0))
    pair = document.blocks.new("PAIR")
    inner = pair.add_blockref("PAD", (0, 0)).dxf.handle
    outer = document.modelspace().add_blockref("PAIR", (0, 0)).dxf.handle

    _, origins = dxf_drawing.explode_blocks(document)

    [placed] = document.modelspace()
    assert origins[placed.dxf.handle]["source"] == line.dxf.handle
    assert origins[placed.dxf.handle]["references"] == [outer, inner]


def test_what_a_reference_says_its_elements_inherit_and_the_innermost_wins():
    document = ezdxf.new("R2010", units=ezdxf.units.MM)
    pad = document.blocks.new("PAD")
    pad.add_line((0, 0), (1, 0))
    pair = document.blocks.new("PAIR")
    pair.add_blockref("PAD", (0, 0)).set_xdata("PARTCAD", [(1000, "angle=30")])
    outer = document.modelspace().add_blockref("PAIR", (0, 0))
    outer.set_xdata("PARTCAD", [(1000, "angle=90"), (1000, "radius=2")])

    _, origins = dxf_drawing.explode_blocks(document)

    [placed] = document.modelspace()
    assert origins[placed.dxf.handle]["metadata"] == {"angle": "30", "radius": "2"}


#
# Faces where outlines close, wires where they do not
#


class _Wire:
    def __init__(self, name, closed):
        self.name, self.closed = name, closed


def test_closed_wires_stay_with_their_layer_and_open_ones_go_together():
    wires = {
        "OUTLINE": [_Wire("rim", True), _Wire("gap", False)],
        "BENDS": [_Wire("up", False)],
    }

    closed, open_wires = dxf_drawing.split_closed(wires, lambda wire: wire.closed)

    assert {layer: [w.name for w in found] for layer, found in closed.items()} == {"OUTLINE": ["rim"], "BENDS": []}
    assert [w.name for w in open_wires] == ["gap", "up"]


def _sketch(wires, faces_of=None):
    """'dxf_drawing.sketch' with a kernel that names what it builds."""

    def faces(layer_wires):
        assert layer_wires, "a layer with no closed wire is not handed over"
        return ["face(%s)" % wire.name for wire in layer_wires]

    return dxf_drawing.sketch(
        wires,
        lambda wire: wire.closed,
        faces_of or faces,
        lambda shapes: ("compound", [shape if isinstance(shape, str) else shape.name for shape in shapes]),
    )


def test_one_closed_outline_is_that_face_and_says_nothing():
    assert _sketch({"0": [_Wire("rim", True)]}) == ("face(rim)", None)


def test_outlines_on_several_layers_are_every_face():
    shape, warning = _sketch({"A": [_Wire("rim", True)], "B": [_Wire("lid", True)]})

    assert shape == ("compound", ["face(rim)", "face(lid)"])
    assert warning is None


def test_open_lines_stay_wires_beside_the_faces_and_are_counted():
    shape, warning = _sketch({"OUTLINE": [_Wire("rim", True)], "BENDS": [_Wire("up", False), _Wire("down", False)]})

    assert shape == ("compound", ["face(rim)", "up", "down"])
    assert (
        warning
        == "2 wire(s) of the DXF file do not close, and were imported as wires beside the 1 face(s) the rest bound"
    )


def test_a_drawing_of_open_lines_alone_is_its_wires():
    shape, warning = _sketch({"BENDS": [_Wire("up", False)]})

    assert shape == ("compound", ["up"])
    assert warning == "1 wire(s) of the DXF file do not close, and were imported as wires"


def test_a_closed_wire_that_makes_no_face_makes_the_drawing_wires():
    def unflat(_layer_wires):
        raise ValueError("not planar")

    shape, warning = _sketch({"0": [_Wire("rim", True), _Wire("up", False)]}, faces_of=unflat)

    assert shape == ("compound", ["rim", "up"])
    assert warning == "no face could be built from the DXF file (not planar); imported the wires it draws instead"


@pytest.mark.parametrize("version", ["R12", "R2010"])
def test_a_drawing_that_says_nothing_of_its_units_is_read_as_it_is(tmp_path, version):
    """No '$INSUNITS' at all is not metres, whatever ezdxf's default for a new drawing is.

    R12 has no such variable, and a later drawing can leave it out: both read
    1:1, exactly as every DXF sketch did before units were honoured.
    """
    path = str(tmp_path / "plain.dxf")
    document = ezdxf.new(version)
    document.modelspace().add_line((0, 0), (1, 0))
    document.saveas(path)
    with open(path) as f:
        lines = f.read().split("\n")
    if "$INSUNITS" in lines:
        at = lines.index("$INSUNITS")
        del lines[at - 1 : at + 3]
    with open(path, "w") as f:
        f.write("\n".join(lines))

    assert dxf_drawing.millimetres_per_unit(ezdxf.readfile(path)) == (1.0, None, None)
