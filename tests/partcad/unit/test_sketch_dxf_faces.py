#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A DXF sketch is everything the drawing draws, not the first face of it.

The DXF reader is CadQuery's, and three things it left out are what this is
about:

* **every face was dropped but one.** The importer returns a face per closed
  outline and the wrapper kept the first, so a drawing of two plates side by
  side, or of an outline on each of two layers, came back as one of them;
* **block references drew nothing.** A block is drawn once and placed with
  INSERT, which is how a drawing repeats a hole or a fastener, and the
  converters know lines and arcs, not references to them;
* **a mirrored arc landed on the wrong side.** MIRROR states a circle in an
  upside-down coordinate system (extrusion (0, 0, -1)), and the converters read
  its centre as if it were the right way up.

Every drawing below is written here with ezdxf and read the way a package reads
one, through the sandbox, so what is checked is the sketch PartCAD hands back.
"""

import asyncio
import math

import ezdxf
import pytest
import yaml
from OCP.BRep import BRep_Builder
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Shape

import partcad as pc
from partcad import shape_envelope


def _square(layout, x, y, size, layer="0"):
    layout.add_lwpolyline(
        [(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
        close=True,
        dxfattribs={"layer": layer},
    )


def _declared(tmp_path, draw, drawn_in=ezdxf.units.MM, **declaration):
    """A package declaring the drawing 'draw' makes, saved in 'drawn_in' ($INSUNITS), and its context."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    document = ezdxf.new("R2010", units=drawn_in)
    draw(document)
    document.saveas(tmp_path / "drawing.dxf")
    (tmp_path / "partcad.yaml").write_text(
        yaml.safe_dump({"name": "//test", "sketches": {"drawing": {"type": "dxf", **declaration}}})
    )
    ctx = pc.Context(str(tmp_path))
    return ctx, ctx.get_sketch("//test:drawing")


def _sketch(tmp_path, draw, drawn_in=ezdxf.units.MM, **declaration):
    """The sketch a package gets for the drawing 'draw' makes, as a shape."""
    ctx, sketch = _declared(tmp_path, draw, drawn_in, **declaration)
    envelope = asyncio.run(sketch.get_wrapped(ctx))
    assert envelope is not None, "the drawing did not import"

    brep = tmp_path / "drawing.brep"
    brep.write_bytes(shape_envelope.brep_plain(envelope["brep"]))
    shape = TopoDS_Shape()
    assert BRepTools.Read_s(shape, str(brep), BRep_Builder())
    return shape


def _count(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def _faces(shape):
    """[(area, (x, y))] for every face of 'shape', sorted by where it is."""
    found = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(explorer.Current(), props)
        centre = props.CentreOfMass()
        found.append((round(props.Mass(), 6), (round(centre.X(), 6), round(centre.Y(), 6))))
        explorer.Next()
    return sorted(found, key=lambda face: face[1])


def test_one_outline_is_one_face(tmp_path):
    """The case every drawing that imported before was: nothing about it moves."""
    shape = _sketch(tmp_path, lambda doc: _square(doc.modelspace(), 0, 0, 10))
    assert _faces(shape) == [(100.0, (5.0, 5.0))]


def test_a_hole_is_still_a_hole(tmp_path):
    """An outline and what is inside it are one face, not two."""

    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10)
        doc.modelspace().add_circle((5, 5), 2)

    shape = _sketch(tmp_path, draw)
    faces = _faces(shape)
    assert len(faces) == 1
    assert faces[0][0] == pytest.approx(100 - math.pi * 4, abs=1e-3)


def test_two_outlines_are_two_faces(tmp_path):
    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10)
        _square(doc.modelspace(), 20, 0, 5)

    shape = _sketch(tmp_path, draw)
    assert _faces(shape) == [(100.0, (5.0, 5.0)), (25.0, (22.5, 2.5))]


def test_an_outline_on_each_layer_is_a_face_each_and_the_filter_picks_between_them(tmp_path):
    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10, layer="PLATE")
        _square(doc.modelspace(), 20, 0, 5, layer="TAB")

    assert len(_faces(_sketch(tmp_path / "all", draw))) == 2
    assert _faces(_sketch(tmp_path / "tab", draw, include=["tab"])) == [(25.0, (22.5, 2.5))]


def test_a_block_draws_where_it_is_placed(tmp_path):
    """Placed twice, a block is two of what it draws -- turned and scaled as placed."""

    def draw(doc):
        block = doc.blocks.new("PAD")
        _square(block, 0, 0, 2)
        doc.modelspace().add_blockref("PAD", (10, 0))
        doc.modelspace().add_blockref("PAD", (0, 10), dxfattribs={"xscale": 2, "yscale": 2, "rotation": 90})

    shape = _sketch(tmp_path, draw)
    assert _faces(shape) == [(16.0, (-2.0, 12.0)), (4.0, (11.0, 1.0))]


def test_layer_zero_in_a_block_is_the_layer_of_the_reference(tmp_path):
    """What AutoCAD means by layer 0 in a block, and what a layer filter sees."""

    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10, layer="PLATE")
        block = doc.blocks.new("PAD")
        _square(block, 0, 0, 2)  # layer 0
        _square(block, 3, 0, 1, layer="MARK")  # a layer of its own, kept
        doc.modelspace().add_blockref("PAD", (20, 0), dxfattribs={"layer": "PADS"})

    assert _faces(_sketch(tmp_path / "pads", draw, include=["PADS"])) == [(4.0, (21.0, 1.0))]
    assert _faces(_sketch(tmp_path / "mark", draw, include=["MARK"])) == [(1.0, (23.5, 0.5))]
    assert len(_faces(_sketch(tmp_path / "rest", draw, exclude=["PADS"]))) == 2


def test_blocks_inside_blocks_and_a_grid_of_them(tmp_path):
    def draw(doc):
        pad = doc.blocks.new("PAD")
        _square(pad, 0, 0, 1)
        pair = doc.blocks.new("PAIR")
        pair.add_blockref("PAD", (0, 0))
        pair.add_blockref("PAD", (2, 0))
        grid = doc.modelspace().add_blockref("PAIR", (0, 0))
        grid.grid(size=(2, 3), spacing=(5, 10))

    faces = _faces(_sketch(tmp_path, draw))
    assert len(faces) == 2 * 2 * 3
    assert {centre for _, centre in faces} == {
        (x + dx + 0.5, y + 0.5) for x in (0, 10, 20) for y in (0, 5) for dx in (0, 2)
    }


def test_a_drawing_that_is_all_blocks_imports(tmp_path):
    """Common in what other tools export, and an import failure before."""

    def draw(doc):
        block = doc.blocks.new("PLATE")
        _square(block, 0, 0, 10)
        doc.modelspace().add_blockref("PLATE", (5, 5))

    assert _faces(_sketch(tmp_path, draw)) == [(100.0, (10.0, 10.0))]


def test_a_mirrored_circle_is_where_it_was_mirrored_to(tmp_path):
    """MIRROR about the Y axis writes centre (5, 0) and extrusion (0, 0, -1): (-5, 0) in the drawing."""

    def draw(doc):
        doc.modelspace().add_circle((5, 0), 1, dxfattribs={"extrusion": (0, 0, -1)})

    [(area, centre)] = _faces(_sketch(tmp_path, draw))
    assert area == pytest.approx(math.pi, abs=1e-3)
    assert centre == pytest.approx((-5.0, 0.0), abs=1e-6)


def test_a_block_placed_mirrored_is_mirrored(tmp_path):
    def draw(doc):
        block = doc.blocks.new("HOLE")
        block.add_circle((3, 0), 1)
        doc.modelspace().add_blockref("HOLE", (0, 0), dxfattribs={"xscale": -1})

    [(_, centre)] = _faces(_sketch(tmp_path, draw))
    assert centre == pytest.approx((-3.0, 0.0), abs=1e-6)


def test_open_lines_in_a_block_are_still_wires(tmp_path):
    """The fallback for bend lines works on what a block draws too."""

    def draw(doc):
        block = doc.blocks.new("BEND")
        block.add_line((0, 0), (10, 0))
        doc.modelspace().add_blockref("BEND", (0, 0))
        doc.modelspace().add_blockref("BEND", (0, 5))

    shape = _sketch(tmp_path, draw)
    assert _count(shape, TopAbs_FACE) == 0
    assert _count(shape, TopAbs_EDGE) == 2


def test_a_reference_to_a_block_that_is_not_there_draws_nothing_and_says_so(tmp_path, caplog):
    """What every reference drew before, so a drawing that imported then imports now."""

    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10)
        block = doc.blocks.new("PAD")
        _square(block, 0, 0, 2)
        doc.modelspace().add_blockref("PAD", (20, 0)).dxf.name = "MISSING"

    assert _faces(_sketch(tmp_path, draw)) == [(100.0, (5.0, 5.0))]
    assert "block reference(s) were left out" in caplog.text
    assert "MISSING" in caplog.text


@pytest.mark.parametrize("copies", [1, 2])
def test_a_block_that_places_itself_draws_nothing_and_says_so(tmp_path, caplog, copies):
    """AutoCAD will not write one; something else can, and exploding it would never end.

    Placed twice, it would double with every level, so a depth limit is no
    answer: the cycle is found in the block definitions before anything is
    exploded. So is a block that only reaches itself through another one.
    """

    def draw(doc):
        _square(doc.modelspace(), 0, -20, 10)
        loop = doc.blocks.new("LOOP")
        _square(loop, 0, 0, 1)
        for n in range(copies):
            loop.add_blockref("LOOP", (2 * (n + 1), 0))
        via = doc.blocks.new("VIA")
        via.add_blockref("LOOP", (0, 0))
        doc.modelspace().add_blockref("LOOP", (0, 0))
        doc.modelspace().add_blockref("VIA", (0, 5))

    assert _faces(_sketch(tmp_path, draw)) == [(100.0, (5.0, -15.0))]
    assert 'block "LOOP" places itself' in caplog.text
    assert 'block "VIA" places itself' in caplog.text


#
# What the numbers are in
#


def test_a_drawing_in_inches_is_a_sketch_in_millimetres(tmp_path):
    """A one-inch square is 25.4 mm across: '$INSUNITS' says what the numbers are."""
    shape = _sketch(tmp_path, lambda doc: _square(doc.modelspace(), 0, 0, 1), drawn_in=1)
    [(area, centre)] = _faces(shape)
    assert area == pytest.approx(25.4 * 25.4, rel=1e-6)
    assert centre == pytest.approx((12.7, 12.7))


def test_the_declaration_says_what_a_drawing_saved_wrongly_is(tmp_path):
    """A drawing saved as metres whose numbers are millimetres, as ezdxf saves them unless told."""
    shape = _sketch(tmp_path, lambda doc: _square(doc.modelspace(), 0, 0, 10), drawn_in=6, units="mm")
    assert _faces(shape) == [(100.0, (5.0, 5.0))]


#
# Faces where outlines close, wires where they do not
#


def test_an_outline_and_its_bend_lines_are_a_face_and_two_lines(tmp_path, caplog):
    """Not three lines: the outline closes, the bend lines do not, and each is what it is."""

    def draw(doc):
        _square(doc.modelspace(), 0, 0, 100, layer="OUTLINE")
        doc.modelspace().add_line((0, 30), (100, 30), dxfattribs={"layer": "BEND_UP"})
        doc.modelspace().add_line((0, 60), (100, 60), dxfattribs={"layer": "BEND_DOWN"})

    shape = _sketch(tmp_path, draw)
    assert _faces(shape) == [(10000.0, (50.0, 50.0))]
    assert _count(shape, TopAbs_EDGE) == 4 + 2
    assert "2 wire(s) of the DXF file do not close" in caplog.text


def test_an_outline_with_a_gap_beside_a_closed_one_is_said_out_loud(tmp_path, caplog):
    def draw(doc):
        _square(doc.modelspace(), 0, 0, 10)
        doc.modelspace().add_lwpolyline([(20, 0), (30, 0), (30, 10), (20, 10)], close=False)

    shape = _sketch(tmp_path, draw)
    assert _faces(shape) == [(100.0, (5.0, 5.0))]
    assert "beside the 1 face(s)" in caplog.text


#
# What the annotations describe
#


def test_the_annotations_describe_what_a_block_placed(tmp_path):
    """The block's bend line where each reference put it, named by its handle in the file."""

    def draw(doc):
        block = doc.blocks.new("BEND")
        block.add_line((0, 0), (100, 0)).set_xdata("PARTCAD", [(1000, "radius=1.5")])
        reference = doc.modelspace().add_blockref("BEND", (0, 30), dxfattribs={"layer": "BEND_UP"})
        reference.set_xdata("PARTCAD", [(1000, "angle=90"), (1000, "direction=up")])

    ctx, sketch = _declared(tmp_path, draw)
    [record] = asyncio.run(sketch.get_annotations(ctx))

    assert (record["type"], record["layer"]) == ("LINE", "BEND_UP")
    assert record["metadata"] == {"angle": "90", "direction": "up", "radius": "1.5"}
    assert len(record["references"]) == 1
    assert record["points"][0][:2] == pytest.approx([0.0, 30.0])
