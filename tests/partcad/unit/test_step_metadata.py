#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What a STEP file says about itself and about the things inside it.

'step_metadata' reads ISO 10303-21 as text, without a CAD kernel, for the four
things a STEP file states beside its geometry: its header, the products it
names, the layers it puts them on, and the properties hung on either. The last
of those is the one this exists for - it is how an 'angle' and a 'radius'
written against a bend reach PartCAD from a STEP file, the way XDATA is how they
reach it from a DXF - so the keys come out lower-cased and the values as the
file states them, exactly as 'dxf_metadata' produces them.

What it must *not* read is the shape of a product. A
'SHAPE_DEFINITION_REPRESENTATION' is a 'PROPERTY_DEFINITION_REPRESENTATION' by
subtyping, and every STEP file holding a solid has one; following it would
report each of them as a property set stating nothing.
"""

import pytest

from partcad import step_metadata, step_p21

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
    """A STEP file whose DATA section is 'body', wrapped in the exchange structure."""
    path = tmp_path / name
    path.write_text("ISO-10303-21;\n" + header + "DATA;\n" + body + "\nENDSEC;\nEND-ISO-10303-21;\n")
    return str(path)


def _property(ident, name, owner, items):
    """A property set: the definition, the link, the representation, the items."""
    return (
        "#%d=PROPERTY_DEFINITION('%s','',#%d);\n#%d=PROPERTY_DEFINITION_REPRESENTATION(#%d,#%d);\n"
        % (
            ident,
            name,
            owner,
            ident + 1,
            ident,
            ident + 2,
        )
        + "#%d=REPRESENTATION('%s',(%s),#900);\n"
        % (
            ident + 2,
            name,
            ",".join("#%d" % (ident + 3 + offset) for offset in range(len(items))),
        )
        + "".join("#%d=%s;\n" % (ident + 3 + offset, item) for offset, item in enumerate(items))
    )


#
# The header
#


def test_the_header_is_read(tmp_path):
    """All three of the records a STEP file opens with, and every attribute."""
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));")

    assert step_metadata.of_step_file(path)["header"] == {
        "description": ["a bent bracket", "sheet metal"],
        "implementationLevel": "2;1",
        "name": "bracket.step",
        "timestamp": "2026-09-16T10:00:00",
        "author": ["R Kuzmenko"],
        "organization": ["PartCAD"],
        "preprocessor": "Open CASCADE STEP processor 7.7",
        "originatingSystem": "FreeCAD",
        "authorization": "none",
        "schema": ["AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }"],
    }


def test_an_author_the_exporter_left_empty_is_not_an_author(tmp_path):
    """Every STEP exporter writes "('')" for a field it was not told."""
    header = "HEADER;\nFILE_NAME('b.step','',(''),(''),'','','');\nENDSEC;\n"
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));", header=header)

    assert step_metadata.of_step_file(path)["header"] == {"name": "b.step"}


def test_a_file_with_no_header_at_all(tmp_path):
    """Not a STEP file, strictly - and not a reason to fail the rest of the read."""
    path = tmp_path / "bare.step"
    path.write_text("DATA;\n#1=CARTESIAN_POINT('',(0.,0.,0.));\nENDSEC;\n")

    assert step_metadata.of_step_file(str(path))["header"] == {}


#
# Products and layers
#


def test_the_products_are_named(tmp_path):
    """What the file calls the things it holds, which a property hangs off."""
    path = _write(tmp_path, PRODUCT)

    assert step_metadata.of_step_file(path)["products"] == [
        {"id": "bracket", "name": "bracket", "description": "a bent bracket"}
    ]


def test_the_layers_and_how_much_is_on_each(tmp_path):
    """STEP's own answer to a DXF layer. The count is reported, not the items:
    what a reader wants of a layer is that it exists and how much is on it.
    """
    path = _write(
        tmp_path,
        "#50=PRESENTATION_LAYER_ASSIGNMENT('BEND_UP','bends that go up',(#9));\n"
        "#51=PRESENTATION_LAYER_ASSIGNMENT('OUTLINE','',(#9,#8,#7));\n",
    )

    assert step_metadata.of_step_file(path)["layers"] == [
        {"name": "BEND_UP", "description": "bends that go up", "elements": 1},
        {"name": "OUTLINE", "description": "", "elements": 3},
    ]


def test_a_file_that_states_none_of_it(tmp_path):
    """Read, and it says nothing - which is not the same as not read."""
    path = _write(tmp_path, "#1=CARTESIAN_POINT('',(0.,0.,0.));")
    read = step_metadata.of_step_file(path)

    assert read["products"] == []
    assert read["layers"] == []
    assert read["properties"] == []


#
# Properties: the reason this module exists
#


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

    assert step_metadata.of_step_file(path)["properties"] == [
        {
            "name": "bend",
            "owner": "bend 1",
            "ownerType": "feature",
            "handle": "#21",
            "metadata": {"angle": "90", "radius": 1.5, "thickness": 2.0},
        }
    ]


def test_a_property_on_the_product_itself(tmp_path):
    """Reached through the definition and its formation, two hops out."""
    path = _write(
        tmp_path,
        PRODUCT + _property(40, "material", 4, ["DESCRIPTIVE_REPRESENTATION_ITEM('alloy','5052-H32')"]),
    )

    assert step_metadata.of_step_file(path)["properties"] == [
        {
            "name": "material",
            "owner": "bracket",
            "ownerType": "product",
            "handle": "#40",
            "metadata": {"alloy": "5052-H32"},
        }
    ]


def test_a_property_on_the_product_definition_shape(tmp_path):
    """One hop further out again, and the same product at the end of it."""
    path = _write(
        tmp_path,
        PRODUCT + _property(40, "mass", 6, ["REAL_REPRESENTATION_ITEM('grams',12.5)"]),
    )

    assert step_metadata.of_step_file(path)["properties"] == [
        {
            "name": "mass",
            "owner": "bracket",
            "ownerType": "product",
            "handle": "#40",
            "metadata": {"grams": 12.5},
        }
    ]


def test_a_value_written_as_a_complex_instance(tmp_path):
    """A named quantity in a unit, as ( REPRESENTATION_ITEM MEASURE_WITH_UNIT ).

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

    assert step_metadata.of_step_file(path)["properties"][0]["metadata"] == {"angle": 30.0}


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

    assert step_metadata.of_step_file(path)["properties"][0]["metadata"] == {
        "finished": True,
        "painted": False,
        "note": None,
    }


def test_a_property_set_that_states_nothing_is_still_reported(tmp_path):
    """The same distinction the DXF reader draws for an un-annotated line.

    "This file states no properties" and "this property set states nothing" are
    different answers, and a check on what a property says has to tell them
    apart.
    """
    path = _write(tmp_path, PRODUCT + _property(40, "empty", 4, []))

    assert step_metadata.of_step_file(path)["properties"] == [
        {"name": "empty", "owner": "bracket", "ownerType": "product", "handle": "#40", "metadata": {}}
    ]


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

    assert step_metadata.of_step_file(path)["properties"] == []


def test_a_property_stated_against_something_this_does_not_follow(tmp_path):
    """Reported, with no owner. It is a property; whose is another question."""
    path = _write(tmp_path, _property(40, "note", 999, ["DESCRIPTIVE_REPRESENTATION_ITEM('by','hand')"]))

    assert step_metadata.of_step_file(path)["properties"] == [
        {"name": "note", "owner": None, "ownerType": None, "handle": "#40", "metadata": {"by": "hand"}}
    ]


#
# Reading the bytes
#


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64, 4096])
def test_the_answer_does_not_depend_on_where_the_reads_fall(tmp_path, monkeypatch, chunk):
    """The file arrives a block at a time and a record straddles the join."""
    monkeypatch.setattr(step_p21, "CHUNK", chunk)
    path = _write(
        tmp_path,
        PRODUCT
        + "#20=SHAPE_ASPECT('the bracket''s fold; near datum A','',#8,.T.);\n"
        + _property(21, "bend", 20, ["DESCRIPTIVE_REPRESENTATION_ITEM('angle','90')"]),
    )

    found = step_metadata.of_step_file(path)["properties"]
    assert found[0]["owner"] == "the bracket's fold; near datum A"
    assert found[0]["metadata"] == {"angle": "90"}


def test_a_comment_where_a_record_would_be(tmp_path):
    """Part 21 allows a comment anywhere, and what is inside one means nothing."""
    path = _write(
        tmp_path,
        PRODUCT
        + "/* #99=PROPERTY_DEFINITION('ghost','',#4); */\n"
        + _property(40, "real", 4, ["DESCRIPTIVE_REPRESENTATION_ITEM('angle','90')"]),
    )

    found = step_metadata.of_step_file(path)["properties"]
    assert [property["name"] for property in found] == ["real"]


#
# What a caller gets, rather than what the file says
#


def test_of_file_refuses_a_format_it_cannot_read(tmp_path):
    """None for a format, a path or a file that is not there - never a guess.

    A 'kicad' part's STEP file does not exist until the part is built, and a
    part fetched from a URL not until it is downloaded.
    """
    path = _write(tmp_path, PRODUCT)

    assert step_metadata.of_file("stl", path) is None
    assert step_metadata.of_file("step", None) is None
    assert step_metadata.of_file("step", str(tmp_path / "absent.step")) is None
    assert step_metadata.of_file("step", path) is not None


def test_an_unreadable_file_is_reported_rather_than_raised(tmp_path, monkeypatch):
    """'pc info' on a part whose file is odd still has the rest to report."""
    path = _write(tmp_path, PRODUCT)
    monkeypatch.setattr(step_p21, "scan", _raise)

    assert step_metadata.of_file("step", path) is None


def _raise(*args, **kwargs):
    """Stand in for a read that fails on the machine rather than on the file."""
    raise OSError("no")


def test_as_info_leaves_out_what_the_file_does_not_state(tmp_path):
    """A run of empty headings buries what 'pc info' does have to say."""
    path = _write(tmp_path, PRODUCT)
    info = step_metadata.as_info(step_metadata.of_step_file(path))

    assert set(info) == {"File", "Products"}
    assert info["Products"][0]["name"] == "bracket"


def test_as_info_of_a_file_that_could_not_be_read():
    """The reader has already said why in the log; 'pc info' just has less."""
    assert step_metadata.as_info(None) == {}
