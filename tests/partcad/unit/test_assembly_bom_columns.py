#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the generated bill of materials says about each line, and how it says it.

A published parts list has a column because the parts have the data - a material,
a process, a vendor, an SKU, the file the geometry is in, a picture. These are the
two halves of generating one instead of writing it by hand: '_bom_line()' reads
those off the resolved configuration, and 'bom_blocks_async()' prints the columns
that some line has something to say in and leaves out the rest.

No CAD library and no sandbox: a bill of materials is read off configuration, and
the pictures are stubbed the way a package that has already rendered them would
hand them over.
"""

import asyncio

import pytest

from partcad import document as pc_document
from partcad.assembly import Assembly, _bom_line
from partcad.assembly_guide import ImageSource, bom_blocks_async


class _Part:
    """The little of a part that a bill of materials reads."""

    def __init__(self, name, config, desc=None):
        self.name = name
        self.project_name = "//pkg"
        self.config = config
        self.desc = desc

    def get_final_config(self):
        return self.config

    def get_store_data(self):
        from partcad.shape_config_store import ShapeConfigStore

        return ShapeConfigStore(self.config)


class _Project:
    """A package, as much of one as a bill of materials reads.

    'ctx' is None, which is how 'package_document_link()' says it cannot resolve
    another package's document: the heading is then plain text, which is what
    this file is not about.
    """

    name = "//pkg"
    ctx = None


class _Images(ImageSource):
    """A picture for the objects named, and none for the others."""

    def __init__(self, names):
        self.names = names

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None):
        if shape.name not in self.names:
            return None
        return pc_document.Image(file="/tmp/%s.svg" % shape.name, src="./%s.svg" % shape.name, alt=alt or shape.name)


MACHINED = {
    "type": "step",
    "path": "plate.step",
    "manufacturing": {"method": "subtractive", "parameters": {"finish": "anodized"}},
    "properties": {"material": "//pub:aluminium-5052"},
    "tolerance": 0.02,
}

BOUGHT = {
    "type": "step",
    "path": "bearing.step",
    "vendor": "amazon",
    "sku": "B0D54JSWBZ",
    "count_per_sku": 10,
}

# Nothing declared but the type: the file is implied by the name, the material
# is whatever the script makes it of, and nobody sells it.
PLAIN = {"type": "cadquery"}


def _grouped(*parts):
    """The grouped BoM of an assembly holding these parts, once each."""
    assembly = Assembly("//pkg", {"name": "widget", "type": "assy"})
    assembly.instantiate = lambda _self: True
    for part in parts:
        assembly.add(part, part.name)
    return asyncio.run(assembly.get_bom_grouped_async(None))


def _table(blocks):
    for block in blocks:
        if isinstance(block, pc_document.Table):
            return block
    raise AssertionError("no table in %r" % (blocks,))


#
# What a line carries
#


def test_line_reads_the_manufacturing_data():
    line = _bom_line(_Part("plate", MACHINED, desc="A plate"))
    assert line["desc"] == "A plate"
    assert line["material"] == "//pub:aluminium-5052"
    assert line["method"] == "subtractive"
    assert line["process"] == {"finish": "anodized"}
    assert line["source_file"] == "plate.step"
    assert line["vendor"] is None and line["sku"] is None


def test_several_process_parameters_share_one_cell():
    """Which parameters a process has is the process's business, not a column's."""
    printed = {
        "type": "step",
        "manufacturing": {
            "method": "additive",
            "parameters": {"nozzle": "0.4 mm", "layer height": "0.2 mm", "infill": "45%"},
        },
    }
    rows, _columns = _cells(_Part("finger", printed))
    assert rows["finger"]["Process"] == "nozzle 0.4 mm; layer height 0.2 mm; infill 45%"


def test_line_reads_the_store_data():
    line = _bom_line(_Part("bearing", BOUGHT))
    assert (line["vendor"], line["sku"], line["count_per_sku"]) == ("amazon", "B0D54JSWBZ", 10)
    assert line["method"] is None and line["material"] is None


def test_line_reads_a_material_asked_for_as_a_parameter():
    """The homogeneous types take the material as an input rather than report it."""
    part = _Part("bracket", {"type": "cadquery", "parameters": {"material": {"default": "//pub:pla"}}})
    assert _bom_line(part)["material"] == "//pub:pla"


def test_line_follows_what_an_alias_points_at():
    """An alias reports the vendor of the part it points at, not its own silence."""

    class _Alias(_Part):
        def get_final_config(self):
            return BOUGHT

        def get_store_data(self):
            from partcad.shape_config_store import ShapeConfigStore

            # What 'ShapeConfig.get_store_data()' does: the final configuration,
            # which for an alias is the one it points at.
            return ShapeConfigStore(self.get_final_config())

    line = _bom_line(_Alias("purchased/bearing", {"type": "alias", "source": ":bearing"}))
    assert (line["vendor"], line["sku"]) == ("amazon", "B0D54JSWBZ")


#
# What the table prints
#


def test_columns_appear_where_there_is_something_to_say():
    blocks = asyncio.run(bom_blocks_async(_Project(), _grouped(_Part("plate", MACHINED)), None))
    table = _table(blocks)
    assert table.columns == ["Part", "Count", "Material", "Method", "Process", "File", "Description"]
    assert table.rows[0][:6] == ["plate", 1, "//pub:aluminium-5052", "subtractive", "finish anodized", "`plate.step`"]


def test_columns_are_dropped_where_there_is_not():
    """A package that declares none of it gets the three columns it always had."""
    blocks = asyncio.run(bom_blocks_async(_Project(), _grouped(_Part("bracket", PLAIN)), None))
    assert _table(blocks).columns == ["Part", "Count", "Description"]


def test_a_pack_size_travels_with_the_sku():
    blocks = asyncio.run(bom_blocks_async(_Project(), _grouped(_Part("bearing", BOUGHT)), None))
    table = _table(blocks)
    assert "Vendor" in table.columns and "SKU" in table.columns
    assert "B0D54JSWBZ (10 per pack)" in table.rows[0]


def test_made_and_bought_parts_share_one_table():
    grouped = _grouped(_Part("plate", MACHINED), _Part("bearing", BOUGHT))
    table = _table(asyncio.run(bom_blocks_async(_Project(), grouped, None)))
    assert table.columns == [
        "Part",
        "Count",
        "Material",
        "Method",
        "Process",
        "Vendor",
        "SKU",
        "File",
        "Description",
    ]
    rows = {row[0]: dict(zip(table.columns, row)) for row in table.rows}
    # Each line says what is true of it, and nothing where it has nothing to say.
    assert rows["plate"]["Method"] == "subtractive"
    assert rows["plate"]["Vendor"] == ""
    assert rows["bearing"]["Vendor"] == "amazon"
    assert rows["bearing"]["Method"] == ""


class _Toleranced(_Part):
    """A part that answers how precisely it has to be made, as a shape does.

    Asynchronous because the real one can be reading a STEP file's GD&T to
    answer, which is why the document generator awaits it.
    """

    def __init__(self, name, config, tolerance):
        super().__init__(name, config)
        self.tolerance = tolerance

    async def get_tolerance(self):
        return self.tolerance


def _cells(*parts):
    """The rows of a one-table document, each keyed by its column heading."""
    table = _table(asyncio.run(bom_blocks_async(_Project(), _grouped(*parts), None)))
    return {row[0]: dict(zip(table.columns, row)) for row in table.rows}, table.columns


def test_a_tolerance_is_read_from_the_object_not_from_the_declaration():
    """The declaration is one of three places it can be, and the object knows."""
    rows, columns = _cells(_Toleranced("plate", MACHINED, 0.02), _Toleranced("bracket", PLAIN, 0.1))
    assert "Tolerance" in columns
    assert rows["plate"]["Tolerance"] == "±0.02 mm"
    assert rows["bracket"]["Tolerance"] == "±0.1 mm"


def test_a_part_toleranced_feature_by_feature_says_so():
    """NaN is 'tolerated, feature by feature' rather than 'unknown'."""
    rows, _columns = _cells(_Toleranced("plate", MACHINED, float("nan")))
    assert rows["plate"]["Tolerance"] == "per feature"


def test_nobody_having_said_leaves_the_cell_empty():
    """0.0 is what 'nobody said' reads as, and 'pc test' is what complains."""
    rows, columns = _cells(_Toleranced("plate", MACHINED, 0.0))
    assert "Tolerance" not in columns
    assert "Tolerance" not in rows["plate"]


def test_a_material_is_printed_as_its_own_name():
    """A reference is what resolves it; the name is what a reader reads."""

    class _Material:
        formal = "AL 5052"
        full = "Aluminium alloy 5052"
        name = "aluminium-5052"

    class _Catalogue:
        name = "//pub"

        def get_material(self, name, quiet=False):
            return _Material() if name == "aluminium-5052" else None

    class _Ctx:
        def get_project(self, name):
            return _Catalogue() if name == "//pub" else None

    class _WithCatalogue(_Project):
        ctx = _Ctx()

    grouped = _grouped(_Part("plate", MACHINED))
    table = _table(asyncio.run(bom_blocks_async(_WithCatalogue(), grouped, None)))
    assert dict(zip(table.columns, table.rows[0]))["Material"] == "AL 5052"


def test_a_material_that_resolves_to_nothing_is_printed_as_written():
    """So that the reference to fix is the one the document shows."""

    class _Ctx:
        def get_project(self, name):
            return None

    class _WithoutIt(_Project):
        ctx = _Ctx()

    grouped = _grouped(_Part("plate", MACHINED))
    table = _table(asyncio.run(bom_blocks_async(_WithoutIt(), grouped, None)))
    assert dict(zip(table.columns, table.rows[0]))["Material"] == "//pub:aluminium-5052"


def test_a_thumbnail_takes_a_column_of_its_own():
    grouped = _grouped(_Part("plate", MACHINED))
    blocks = asyncio.run(bom_blocks_async(_Project(), grouped, None, images=_Images({"plate"})))
    table = _table(blocks)
    assert table.columns[:3] == ["Part", "", "Count"]
    assert isinstance(table.rows[0][1], pc_document.Image)


def test_no_thumbnail_column_without_pictures():
    """A document asked for without the projections is readable without them."""
    grouped = _grouped(_Part("plate", MACHINED))
    blocks = asyncio.run(bom_blocks_async(_Project(), grouped, None, images=_Images(set())))
    assert _table(blocks).columns[1] == "Count"


#
# How a picture is written down
#


def test_a_picture_cell_is_a_thumbnail_in_markdown():
    document = pc_document.Document(
        pages=[
            pc_document.Page(
                blocks=[
                    pc_document.Table(
                        columns=["Part", ""],
                        rows=[["plate", pc_document.Image(file="/tmp/plate.svg", src="./plate.svg", alt="plate")]],
                    )
                ]
            )
        ]
    )
    lines = pc_document.render_markdown(document)
    row = [line for line in lines if line.startswith("| plate")][0]
    assert '<img src="./plate.svg"' in row
    assert "max-width: 96px" in row


def test_a_picture_cell_is_a_thumbnail_in_html():
    table = pc_document.Table(
        columns=["Part", ""],
        rows=[["plate", pc_document.Image(src="./plate.svg", alt="plate")]],
    )
    document = pc_document.Document(pages=[pc_document.Page(blocks=[table])])
    html = pc_document.render_html(document)
    assert '<img src="./plate.svg" alt="plate" class="thumbnail">' in html


def test_a_picture_cell_travels_as_data():
    table = pc_document.Table(columns=["Part", ""], rows=[["plate", pc_document.Image(file="/tmp/plate.svg")]])
    document = pc_document.Document(pages=[pc_document.Page(blocks=[table])])
    data = pc_document.to_data(document)
    cell = data["pages"][0]["blocks"][0]["rows"][0][1]
    assert cell["path"] == "/tmp/plate.svg"


@pytest.mark.parametrize("cell", [None, 2, "text"])
def test_an_ordinary_cell_is_still_text(cell):
    table = pc_document.Table(columns=["Part"], rows=[[cell]])
    document = pc_document.Document(pages=[pc_document.Page(blocks=[table])])
    assert pc_document.to_data(document)["pages"][0]["blocks"][0]["rows"][0][0] == ("" if cell is None else str(cell))
