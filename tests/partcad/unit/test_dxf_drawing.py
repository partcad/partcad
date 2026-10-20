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
    document = ezdxf.new("R2010")
    _square(document.blocks.new("PAD"), 0, 0, 1)
    assert dxf_drawing.endless_blocks(document) == set()


def test_blocks_inside_blocks_are_finite():
    document = ezdxf.new("R2010")
    _square(document.blocks.new("PAD"), 0, 0, 1)
    document.blocks.new("PAIR").add_blockref("PAD", (0, 0))
    document.blocks.new("QUAD").add_blockref("PAIR", (0, 0))
    assert dxf_drawing.endless_blocks(document) == set()


def test_a_block_that_places_itself_is_endless_and_so_is_whatever_places_it():
    document = ezdxf.new("R2010")
    document.blocks.new("LOOP").add_blockref("LOOP", (1, 0))
    document.blocks.new("VIA").add_blockref("LOOP", (0, 0))
    _square(document.blocks.new("PAD"), 0, 0, 1)
    assert dxf_drawing.endless_blocks(document) == {"loop", "via"}


def test_two_blocks_that_place_each_other_are_both_endless():
    document = ezdxf.new("R2010")
    document.blocks.new("PING").add_blockref("PONG", (0, 0))
    document.blocks.new("PONG").add_blockref("Ping", (0, 0))  # names are not case-sensitive
    assert dxf_drawing.endless_blocks(document) == {"ping", "pong"}


def test_a_block_that_places_one_that_is_not_defined_is_finite():
    """The missing reference is left out when it is reached; the block around it is fine."""
    document = ezdxf.new("R2010")
    ref = document.blocks.new("OUTER").add_blockref("PAD", (0, 0))
    ref.dxf.name = "MISSING"
    assert dxf_drawing.endless_blocks(document) == set()


#
# Exploding them
#


def test_a_drawing_with_no_blocks_is_left_as_it_is():
    document = ezdxf.new("R2010")
    _square(document.modelspace(), 0, 0, 10, layer="PLATE")
    assert dxf_drawing.explode_blocks(document) == []
    assert _kinds(document) == [("LWPOLYLINE", "PLATE")]


def test_layer_zero_in_a_block_takes_the_layer_of_the_reference():
    document = ezdxf.new("R2010")
    block = document.blocks.new("PAD")
    _square(block, 0, 0, 1)
    block.add_circle((0, 0), 1, dxfattribs={"layer": "MARK"})
    document.modelspace().add_blockref("PAD", (5, 0), dxfattribs={"layer": "PADS"})

    assert dxf_drawing.explode_blocks(document) == []
    assert _kinds(document) == [("CIRCLE", "MARK"), ("LWPOLYLINE", "PADS")]


def test_nested_blocks_and_grids_are_exploded_all_the_way_down():
    document = ezdxf.new("R2010")
    _square(document.blocks.new("PAD"), 0, 0, 1)
    pair = document.blocks.new("PAIR")
    pair.add_blockref("PAD", (0, 0))
    pair.add_blockref("PAD", (2, 0))
    document.modelspace().add_blockref("PAIR", (0, 0), dxfattribs={"layer": "GRID"}).grid(size=(2, 3), spacing=(5, 10))

    assert dxf_drawing.explode_blocks(document) == []
    assert _kinds(document) == [("LWPOLYLINE", "GRID")] * (2 * 2 * 3)


def test_references_that_cannot_be_followed_are_left_out_and_counted():
    document = ezdxf.new("R2010")
    _square(document.modelspace(), 0, 0, 10)
    document.blocks.new("LOOP").add_blockref("LOOP", (1, 0))
    document.modelspace().add_blockref("LOOP", (0, 0))
    document.modelspace().add_blockref("LOOP", (0, 5))
    _square(document.blocks.new("PAD"), 0, 0, 1)
    document.modelspace().add_blockref("PAD", (0, 0)).dxf.name = "MISSING"

    warnings = dxf_drawing.explode_blocks(document)

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
    document = ezdxf.new("R2010")
    draw(document)
    path = str(tmp_path / "drawing.dxf")
    document.saveas(path)
    return path


def test_a_mirrored_circle_is_restated_where_it_was_mirrored_to(tmp_path):
    path = _saved(tmp_path, lambda doc: doc.modelspace().add_circle((5, 0), 1, dxfattribs={"extrusion": (0, 0, -1)}))

    layers, warnings = dxf_drawing.read(path)

    [circle] = layers["0"]
    assert warnings == []
    assert tuple(circle.dxf.extrusion) == (0, 0, 1)
    assert tuple(circle.dxf.center)[:2] == pytest.approx((-5, 0))


def test_layers_are_selected_without_regard_to_case(tmp_path):
    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10, layer="PLATE")
        _square(doc.modelspace(), 20, 0, 5, layer="TAB")

    path = _saved(tmp_path, draw)

    assert sorted(dxf_drawing.read(path)[0]) == ["PLATE", "TAB"]
    assert sorted(dxf_drawing.read(path, include=["tab"])[0]) == ["TAB"]
    assert sorted(dxf_drawing.read(path, exclude=["Tab"])[0]) == ["PLATE"]


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

    layers, warnings = dxf_drawing.read(_saved(tmp_path, draw))
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
