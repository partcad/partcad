#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a STEP file says about itself and about the things inside it.

'wrappers/step_metadata.py' reads it in the wrapper - the process the file is
already open in - and the wrapper puts it on the envelope beside the BREP, so
the core stores and reports it without knowing a STEP file was involved.

It is read as text rather than through OCCT, and not for want of a kernel: XCAF
gives names, layers and colours and has nowhere to put an arbitrary
'PROPERTY_DEFINITION', which is the half this exists for - an 'angle' and a
'radius' written against a bend reach PartCAD this way, the way XDATA is how
they reach it from a DXF. So the keys come out lower-cased and the values as the
file states them, exactly as 'dxf_metadata' produces them.

What it must *not* read is the shape of a product. A
'SHAPE_DEFINITION_REPRESENTATION' is a 'PROPERTY_DEFINITION_REPRESENTATION' by
subtyping, and every STEP file holding a solid has one; following it would
report each of them as a property set stating nothing.
"""

import os
import sys

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import step_metadata  # noqa: E402

HEADER = (
    "HEADER;\n"
    "FILE_DESCRIPTION(('a bent bracket','sheet metal'),'2;1');\n"
    "FILE_NAME('bracket.step','2026-09-16T10:00:00',('R Kuzmenko'),('PartCAD'),\n"
    "  'Open CASCADE STEP processor 7.7','FreeCAD','none');\n"
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));\n"
    "ENDSEC;\n"
)

# A product, and the two records between it and anything stated against it.
PRODUCT = (
    "#1=PRODUCT('bracket','bracket','a bent bracket',(#2));\n"
    "#3=PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#1,.NOT_KNOWN.);\n"
    "#4=PRODUCT_DEFINITION('design','',#3,#5);\n"
    "#6=PRODUCT_DEFINITION_SHAPE('','',#4);\n"
)


def _write(tmp_path, body, header=HEADER, name="bracket.step"):
    """A STEP file whose DATA section is 'body', in the exchange structure."""
    path = tmp_path / name
    path.write_text("ISO-10303-21;\n" + header + "DATA;\n" + body + "\nENDSEC;\nEND-ISO-10303-21;\n")
    return str(path)


def _property(ident, name, owner, items):
    """A property set: the definition, the link, the representation, the items."""
    refs = ",".join("#%d" % (ident + 3 + offset) for offset in range(len(items)))
    return (
        "#%d=PROPERTY_DEFINITION('%s','',#%d);\n" % (ident, name, owner)
        + "#%d=PROPERTY_DEFINITION_REPRESENTATION(#%d,#%d);\n" % (ident + 1, ident, ident + 2)
        + "#%d=REPRESENTATION('%s',(%s),#900);\n" % (ident + 2, name, refs)
        + "".join("#%d=%s;\n" % (ident + 3 + offset, item) for offset, item in enumerate(items))
    )


def test_the_header_is_read(tmp_path):
    """What the file says about its own making."""
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));")

    assert step_metadata.read(path)["File"] == {
        "description": ["a bent bracket", "sheet metal"],
        "name": "bracket.step",
        "timestamp": "2026-09-16T10:00:00",
        "author": ["R Kuzmenko"],
        "organization": ["PartCAD"],
        "preprocessor": "Open CASCADE STEP processor 7.7",
        "originatingSystem": "FreeCAD",
        "schema": ["AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }"],
    }


def test_an_author_the_exporter_left_empty_is_not_an_author(tmp_path):
    """Every STEP exporter writes "('')" for a field it was not told."""
    header = "HEADER;\nFILE_NAME('b.step','',(''),(''),'','','');\nENDSEC;\n"
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));", header=header)

    assert step_metadata.read(path)["File"] == {"name": "b.step"}


def test_a_header_entity_named_inside_a_string_is_not_the_header(tmp_path):
    """Only the first match is read, so a decoy costs the whole record.

    A file whose FILE_DESCRIPTION says it was "exported via FILE_NAME(x)" states
    one FILE_NAME. Searched without regard for strings, the sentence is found
    first and the real record is never looked at - so the name, the timestamp
    and the author all come back empty rather than wrong, which is harder to
    notice.
    """
    header = (
        "HEADER;\n"
        "FILE_DESCRIPTION(('exported via FILE_NAME(legacy.step)'),'2;1');\n"
        "FILE_NAME('bracket.step','2026-09-16T10:00:00',('R Kuzmenko'),('PartCAD'),'occt','FreeCAD','none');\n"
        "FILE_SCHEMA(('AP242'));\n"
        "ENDSEC;\n"
    )
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));", header=header)

    read = step_metadata.read(path)["File"]
    assert read["name"] == "bracket.step"
    assert read["author"] == ["R Kuzmenko"]
    assert read["description"] == ["exported via FILE_NAME(legacy.step)"]


def test_the_products_are_named(tmp_path):
    """What the file calls the things it holds, which a property hangs off."""
    path = _write(tmp_path, PRODUCT)

    assert step_metadata.read(path)["Products"] == [
        {"id": "bracket", "name": "bracket", "description": "a bent bracket"}
    ]


def test_the_layers_and_how_much_is_on_each(tmp_path):
    """STEP's own answer to a DXF layer. The count is reported, not the items."""
    path = _write(
        tmp_path,
        "#50=PRESENTATION_LAYER_ASSIGNMENT('BEND_UP','bends that go up',(#9));\n"
        "#51=PRESENTATION_LAYER_ASSIGNMENT('OUTLINE','',(#9,#8,#7));\n",
    )

    assert step_metadata.read(path)["Layers"] == [
        {"name": "BEND_UP", "description": "bends that go up", "elements": 1},
        {"name": "OUTLINE", "description": "", "elements": 3},
    ]


def test_a_file_that_states_none_of_it(tmp_path):
    """A section the file says nothing in is left out rather than reported empty."""
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));")

    assert set(step_metadata.read(path)) == {"File"}


def test_a_property_on_a_feature_of_the_shape(tmp_path):
    """Where a sheet metal bend states its angle and its radius.

    Three spellings of a value in one property set, because a file is free to
    use any of them: a string, a measure with the unit beside it, and a bare
    real.
    """
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('bend 1','the first fold',#8,.T.);\n"
        + _property(
            21,
            "bend",
            20,
            [
                "DESCRIPTIVE_REPRESENTATION_ITEM('Angle','90')",
                "MEASURE_REPRESENTATION_ITEM('RADIUS',LENGTH_MEASURE(1.5),#11)",
                "REAL_REPRESENTATION_ITEM('thickness',2.0)",
            ],
        ),
    )

    assert step_metadata.read(path)["Properties"] == [
        {
            "name": "bend",
            "owner": "bend 1",
            "metadata": {"angle": "90", "radius": 1.5, "thickness": 2.0},
        }
    ]


def test_a_property_on_the_product_itself(tmp_path):
    """Reached through the definition and its formation, two hops out."""
    path = _write(
        tmp_path,
        PRODUCT + _property(40, "material", 4, ["DESCRIPTIVE_REPRESENTATION_ITEM('alloy','5052-H32')"]),
    )

    assert step_metadata.read(path)["Properties"] == [
        {"name": "material", "owner": "bracket", "metadata": {"alloy": "5052-H32"}}
    ]


def test_a_property_on_the_product_definition_shape(tmp_path):
    """One hop further out again, and the same product at the end of it."""
    path = _write(tmp_path, PRODUCT + _property(40, "mass", 6, ["REAL_REPRESENTATION_ITEM('grams',12.5)"]))

    assert step_metadata.read(path)["Properties"] == [{"name": "mass", "owner": "bracket", "metadata": {"grams": 12.5}}]


def test_a_value_written_as_a_complex_instance(tmp_path):
    """A named quantity in a unit: ( REPRESENTATION_ITEM MEASURE_WITH_UNIT ).

    The name and the number are in separate entities of one record, so neither
    half is a key/value pair on its own.
    """
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('bend 2','',#8,.T.);\n"
        + _property(
            21,
            "bend",
            20,
            ["(REPRESENTATION_ITEM('angle')MEASURE_WITH_UNIT(PLANE_ANGLE_MEASURE(30.0),#12))"],
        ),
    )

    assert step_metadata.read(path)["Properties"][0]["metadata"] == {"angle": 30.0}


def test_a_complex_item_reads_only_its_own_record(tmp_path):
    """A part carrying no measure must not reach forward and take the next one's.

    Both halves of a complex instance are looked for inside that one record.
    Matched across the file instead - which is what any unanchored gap between
    the two does, however lazy - a bend stating a 'direction' and a 'radius'
    reported the radius' number under 'direction', and then lost the radius
    entirely, the match having consumed the record that stated it.
    """
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('bend 1','',#8,.T.);\n"
        + _property(
            21,
            "bend",
            20,
            [
                "(REPRESENTATION_ITEM('direction')DESCRIPTIVE_REPRESENTATION_ITEM('up'))",
                "(REPRESENTATION_ITEM('radius')MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#12))",
            ],
        ),
    )

    assert step_metadata.read(path)["Properties"][0]["metadata"] == {"direction": "up", "radius": 1.5}


def test_each_complex_item_keeps_its_own_measure(tmp_path):
    """Two in a row, so neither can be answered by the other's number."""
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('bend 1','',#8,.T.);\n"
        + _property(
            21,
            "bend",
            20,
            [
                "(REPRESENTATION_ITEM('angle')MEASURE_WITH_UNIT(PLANE_ANGLE_MEASURE(90.0),#12))",
                "(REPRESENTATION_ITEM('radius')MEASURE_WITH_UNIT(LENGTH_MEASURE(1.5),#12))",
            ],
        ),
    )

    assert step_metadata.read(path)["Properties"][0]["metadata"] == {"angle": 90.0, "radius": 1.5}


def test_a_record_written_inside_a_quoted_value_is_text(tmp_path):
    """'#99=PRODUCT(' in a value names nothing; a scan that took it for a record
    would invent one, and a bracket in a value is a bracket rather than a list."""
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('bend 1','',#8,.T.);\n"
        + _property(
            21,
            "note",
            20,
            ["(REPRESENTATION_ITEM('note')DESCRIPTIVE_REPRESENTATION_ITEM('see #99=PRODUCT( and 3(a)'))"],
        ),
    )

    read = step_metadata.read(path)
    assert read["Properties"][0]["metadata"] == {"note": "see #99=PRODUCT( and 3(a)"}
    # ...and the invented record is not among the products either.
    assert [product["name"] for product in read["Products"]] == ["bracket"]


def test_a_boolean_and_an_omitted_value(tmp_path):
    """'.T.'/'.F.' are values; '$' is the absence of one and stays None."""
    path = _write(
        tmp_path,
        PRODUCT
        + _property(
            40,
            "state",
            4,
            [
                "BOOLEAN_REPRESENTATION_ITEM('finished',.T.)",
                "BOOLEAN_REPRESENTATION_ITEM('painted',.F.)",
                "DESCRIPTIVE_REPRESENTATION_ITEM('note',$)",
            ],
        ),
    )

    assert step_metadata.read(path)["Properties"][0]["metadata"] == {
        "finished": True,
        "painted": False,
        "note": None,
    }


def test_the_shape_of_a_product_is_not_a_property(tmp_path):
    """'SHAPE_DEFINITION_REPRESENTATION' is a subtype of the link this follows.

    Every STEP file holding a solid states one. Following it would report the
    geometry of every product as a property set holding nothing, which is what
    matching by suffix rather than by name costs.
    """
    path = _write(
        tmp_path,
        PRODUCT + "#7=SHAPE_DEFINITION_REPRESENTATION(#6,#8);\n#8=ADVANCED_BREP_SHAPE_REPRESENTATION('',(#9),#900);\n",
    )

    assert "Properties" not in step_metadata.read(path)


def test_a_property_stated_against_something_this_does_not_follow(tmp_path):
    """Reported, with no owner. It is a property; whose is another question."""
    path = _write(tmp_path, _property(40, "note", 999, ["DESCRIPTIVE_REPRESENTATION_ITEM('by','hand')"]))

    assert step_metadata.read(path)["Properties"] == [{"name": "note", "owner": None, "metadata": {"by": "hand"}}]


def test_a_semicolon_inside_a_string_does_not_end_the_record(tmp_path):
    """The one that bites every STEP file there is.

    'FILE_DESCRIPTION' carries the implementation level, and every exporter
    writes it as '2;1'. A reader that took the argument list to end at the first
    semicolon would read no header at all - and the same trap is set by any
    name or description a person typed a semicolon into.
    """
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('the fold; near datum A','',#8,.T.);\n"
        + _property(21, "bend", 20, ["DESCRIPTIVE_REPRESENTATION_ITEM('angle','90')"]),
    )
    read = step_metadata.read(path)

    assert read["File"]["name"] == "bracket.step"
    assert read["Properties"][0]["owner"] == "the fold; near datum A"
    assert read["Properties"][0]["metadata"] == {"angle": "90"}


def test_a_comment_delimiter_inside_a_string_opens_no_comment(tmp_path):
    """A property whose value mentions a comment is a value, not a hole.

    The comments have to come out before the records are matched, and a scan
    that did not know it was inside a string would take the middle out of this
    one.
    """
    path = _write(
        tmp_path,
        PRODUCT + _property(40, "note", 4, ["DESCRIPTIVE_REPRESENTATION_ITEM('how','use /* draft */ dimensions')"]),
    )

    assert step_metadata.read(path)["Properties"][0]["metadata"] == {"how": "use /* draft */ dimensions"}


def test_the_data_keyword_inside_a_string_does_not_split_the_file(tmp_path):
    """A header that states 'DATA;' would otherwise cut itself in half."""
    header = "HEADER;\nFILE_NAME('DATA;','2026-09-16T10:00:00',(''),(''),'','','');\nENDSEC;\n"
    path = _write(tmp_path, PRODUCT, header=header)
    read = step_metadata.read(path)

    assert read["File"] == {"name": "DATA;", "timestamp": "2026-09-16T10:00:00"}
    assert [p["name"] for p in read["Products"]] == ["bracket"]


def test_a_comment_where_a_record_would_be(tmp_path):
    """Part 21 allows a comment anywhere, and what is inside one means nothing."""
    path = _write(
        tmp_path,
        PRODUCT
        + "/* #99=PROPERTY_DEFINITION('ghost','',#4); */\n"
        + _property(40, "real", 4, ["DESCRIPTIVE_REPRESENTATION_ITEM('angle','90')"]),
    )

    assert [p["name"] for p in step_metadata.read(path)["Properties"]] == ["real"]


def test_a_real_file_exported_by_a_cad_application(tmp_path):
    """The example package's own STEP file: a header and one product, no more.

    A file with no layers and no user properties is the common case, and the
    check that matters on it is that nothing is invented for one.
    """
    path = os.path.join(os.path.dirname(pc.__file__), "..", "..", "examples", "produce_part_step", "bolt.step")
    if not os.path.isfile(path):
        return

    read = step_metadata.read(path)

    # The header is read, and nothing here pins *which* application wrote it.
    # The example is re-exported from time to time - it has been, by a different
    # tool than the one that wrote it when this was written - and a test of this
    # reader has no business failing over that. What it is entitled to is that a
    # real file yields a populated header and one named product.
    header = read["File"]
    assert header["name"]
    assert header["originatingSystem"]
    assert header["schema"]
    assert len(read["Products"]) == 1
    assert read["Products"][0]["name"]

    # ...and that nothing is invented for a file which states neither.
    assert "Layers" not in read
    assert "Properties" not in read
