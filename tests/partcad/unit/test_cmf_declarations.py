#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Colours, materials and finishes as CMF declarations (docs/design/cmf.md).

Pinned here: what a declaration says about itself (its display, whether it is a
claim, what other systems call it), how one is found (by name, through an alias
or another name of it, as an instance of a parametric one), what a reference to
one becomes when it is written into a name, and that every part and assembly
type takes the CMF parameters.
"""

import asyncio
import logging
import os
import sys
import textwrap
import types

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad import cmf, factory
from partcad.lint.all import get_partcad_schema
from partcad_utils.utils import escape_name, format_parameterized_name, parse_parameterized_name, unescape_name

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import css_color  # noqa: E402

VENDOR = """
colors:
  Medium Stone Grey:
    display: "#969696"
    ids: {lego: "194", ldraw: 71, bricklink: "86"}
    aliases: [Light Bluish Gray]
  rgba:
    parameters:
      color: {type: string, default: "000000FF"}
    display: "#%color%"
    manufacturable: false
"""

ROOT = """
dependencies:
  vendor:
    type: local
    path: vendor
colors:
  stone:
    type: alias
    source: //vendor:Medium Stone Grey
  red: "#C91A09"
  "PA12, glass filled":
    display: "oklch(62.8% 0.2577 29.23)"
  natural:
    display: "#A8A9AD"
  shown-as-stone:
    display: ":stone"
  loop-a: {type: alias, source: ":loop-b"}
  loop-b: {type: alias, source: ":loop-a"}
finishes:
  satin:
    desc: Satin, VDI 3400 Ref 27
    ids: {vdi3400: "27"}
    display: {roughness: 0.6, metallic: 0}
  as-molded: As it comes out of the mould
materials:
  alu:
    full: Aluminium 6061-T6
    density: 2700
    color: ":natural"
parts:
  box:
    type: step
    path: box.step
  red-box:
    type: step
    path: box.step
    parameters:
      color: {type: string, default: ":red"}
  brick:
    type: stl
    path: box.stl
assemblies:
  wall:
    type: assy
"""


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "partcad.yaml").write_text(textwrap.dedent(VENDOR))
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent(ROOT))
    # Found, never read: nothing here builds geometry.
    (tmp_path / "box.step").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    (tmp_path / "box.stl").write_text("solid box\nendsolid box\n")
    (tmp_path / "wall.assy").write_text(
        "links:\n"
        "  - part: brick\n    name: grey\n    params: {color: ':stone'}\n"
        "  - part: brick\n    name: grey-too\n    params: {color: '//vendor:Light Bluish Gray'}\n"
    )
    return pc.Context(str(tmp_path))


def _find(ctx, kind, ref):
    return cmf.lookup(ctx, kind, ref, ctx.get_project(".").name, quiet=True)


# --------------------------------------------------------------------------- #
# The display: any CSS colour                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, expected",
    [
        ("#c91a09", "#C91A09"),
        ("#C91A0980", "#C91A0980"),
        ("#fff", "#FFFFFF"),
        ("rgb(201 26 9)", "#C91A09"),
        ("rgb(201, 26, 9, 0.5)", "#C91A0980"),
        ("rgba(100%, 0%, 0%, 50%)", "#FF000080"),
        ("rgb(10 20 30 / 25%)", "#0A141E40"),
        ("hsl(120deg, 100%, 25%)", "#008000"),
        ("hwb(0 0% 0%)", "#FF0000"),
        ("firebrick", "#B22222"),
        ("RebeccaPurple", "#663399"),
        ("transparent", "#00000000"),
        # The same red reached through each of CSS's other spaces.
        ("oklch(62.8% 0.2577 29.23)", "#FF0000"),
        ("oklab(0.628 0.2249 0.1258)", "#FF0000"),
        ("lab(54.29 80.8 69.89)", "#FF0000"),
        ("lch(54.29 106.84 40.85)", "#FF0000"),
        ("color(srgb 1 0 0)", "#FF0000"),
        # Outside sRGB, clipped rather than gamut-mapped.
        ("color(display-p3 1 0 0)", "#FF0000"),
        ("color(srgb-linear 0.5 0.5 0.5)", "#BCBCBC"),
    ],
)
def test_a_display_is_any_css_colour(text, expected):
    assert css_color.normalize(text) == expected


@pytest.mark.parametrize("text", ["bogus", "rgb(1 2)", "#12345", "", None, "hsl(red 1 2)"])
def test_anything_else_is_not_one(text):
    assert css_color.parse(text) is None


def test_the_named_colours_are_css_s_148():
    assert len(css_color.NAMED) == 148
    assert css_color.NAMED["rebeccapurple"] == "663399"


# --------------------------------------------------------------------------- #
# Names a specification writes, and escaping                                 #
# --------------------------------------------------------------------------- #


def test_reserved_characters_round_trip_escaped():
    assert escape_name("PA12, glass filled") == "PA12%2C glass filled"
    assert escape_name("ISO 21920-1:2021") == "ISO 21920-1%3A2021"
    assert unescape_name(escape_name("a%b;c=d,e:f#g*h?i[j]k")) == "a%b;c=d,e:f#g*h?i[j]k"
    # Only the reserved characters' escapes are read: '%41' is the user's text.
    assert unescape_name("50%41") == "50%41"


@pytest.mark.parametrize(
    "name",
    ["obj;m=//pub/std:air", "bends;include=BEND_UP,BEND_DOWN", "obj;a=1,b=2", "obj;label=50%", "obj"],
)
def test_every_name_that_could_be_written_is_spelled_as_it_was(name):
    base, parameters = parse_parameterized_name(name)
    assert format_parameterized_name(base, parameters) == name


def test_a_parameterised_reference_is_one_value():
    for value in ["//pub/std/color:rgba;color=C91A09FF", "//p:rgba;a=1,b=2", "a%2Cb"]:
        name = format_parameterized_name("Brick:3004", {"color": value, "finish": "x"})
        assert parse_parameterized_name(name) == ("Brick:3004", {"color": value, "finish": "x"})


# --------------------------------------------------------------------------- #
# Declarations                                                                #
# --------------------------------------------------------------------------- #


def test_the_short_forms(ctx):
    assert css_color.to_hex(cmf.display(ctx, _find(ctx, "color", ":red"))) == "#C91A09"
    assert _find(ctx, "finish", ":as-molded").desc == "As it comes out of the mould"
    assert _find(ctx, "material", ":alu").full == "Aluminium 6061-T6"


def test_a_declaration_is_a_claim_unless_it_says_not(ctx):
    assert _find(ctx, "color", ":red").manufacturable is True
    assert _find(ctx, "color", "//vendor:rgba;color=C91A09FF").manufacturable is False


def test_what_other_systems_call_it(ctx):
    assert _find(ctx, "color", "//vendor:Medium Stone Grey").ids == {"lego": "194", "ldraw": "71", "bricklink": "86"}


def test_an_alias_is_the_declaration_it_names(ctx):
    found = _find(ctx, "color", ":stone")
    assert found.reference() == "//vendor:Medium Stone Grey"
    assert css_color.to_hex(cmf.display(ctx, found)) == "#969696"


def test_another_name_of_itself(ctx):
    assert _find(ctx, "color", "//vendor:Light Bluish Gray").reference() == "//vendor:Medium Stone Grey"


def test_an_alias_that_leads_back_to_itself_resolves_to_nothing(ctx):
    assert _find(ctx, "color", ":loop-a") is None


def test_a_name_with_reserved_characters_is_found_escaped(ctx):
    found = _find(ctx, "color", ":PA12%2C glass filled")
    assert found.name == "PA12, glass filled"
    assert found.reference() == "//:PA12%2C glass filled"
    assert css_color.to_hex(cmf.display(ctx, found)) == "#FF0000"


def test_a_parametric_declaration(ctx):
    found = _find(ctx, "color", "//vendor:rgba;color=C91A0980")
    assert found.reference() == "//vendor:rgba;color=C91A0980"
    assert css_color.to_hex(cmf.display(ctx, found)) == "#C91A0980"
    # And it reads its colour from the reference alone, where the catalogue is not at hand.
    assert css_color.to_hex(cmf.rgba_of_reference("//pub/std/color:rgba;color=C91A0980")) == "#C91A0980"


def test_a_display_may_name_another_colour(ctx):
    assert css_color.to_hex(cmf.display(ctx, _find(ctx, "color", ":shown-as-stone"))) == "#969696"


def test_a_material_is_drawn_in_the_colour_it_claims(ctx):
    alu = _find(ctx, "material", ":alu")
    assert alu.color_claim == ":natural"
    assert css_color.to_hex(cmf.display(ctx, alu)) == "#A8A9AD"


def test_a_finish_has_display_hints_and_no_colour(ctx):
    satin = _find(ctx, "finish", ":satin")
    assert (satin.roughness, satin.metallic) == (0.6, 0.0)
    assert satin.ids == {"vdi3400": "27"}
    assert cmf.display(ctx, satin) is None


# --------------------------------------------------------------------------- #
# References written into names                                               #
# --------------------------------------------------------------------------- #


def test_a_reference_is_canonicalised(ctx):
    root = ctx.get_project(".").name
    assert cmf.canonical(ctx, "color", ":stone", root) == "//vendor:Medium Stone Grey"
    assert cmf.canonical(ctx, "color", "red", root) == "//:red"
    assert cmf.canonical(ctx, "finish", "satin", root) == "//:satin"
    # One that does not resolve is still made absolute.
    assert cmf.canonical(ctx, "material", ":nothing", root) == "//:nothing"


def test_a_colour_that_is_no_declaration_is_display_only(ctx, caplog):
    root = ctx.get_project(".").name
    with caplog.at_level(logging.WARNING):
        assert cmf.canonical(ctx, "color", "#FF000080", root, quiet=False) == "//pub/std/color:rgba;color=FF000080"
    assert any("display-only" in record.getMessage() for record in caplog.records)
    assert cmf.canonical(ctx, "color", "firebrick", root) == "//pub/std/color:rgba;color=B22222FF"


def test_only_cmf_parameters_are_canonicalised(ctx):
    root = ctx.get_project(".").name
    assert cmf.canonical_parameters(ctx, {"color": ":stone", "finish": "satin", "size": 3}, root) == {
        "color": "//vendor:Medium Stone Grey",
        "finish": "//:satin",
        "size": 3,
    }


@pytest.mark.parametrize(
    "value, drops",
    [(None, ()), ("keep", ()), ("drop", ("color", "material", "finish")), (["finish", "color"], ("color", "finish"))],
)
def test_what_source_cmf_drops(value, drops):
    assert cmf.source_cmf_drops(value) == drops


def test_source_cmf_refuses_anything_else():
    assert cmf.source_cmf_drops("everything") is None
    assert cmf.source_cmf_drops(["texture"]) is None


# --------------------------------------------------------------------------- #
# The CMF parameters, on every type                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kind, type_name",
    [
        ("part", "step"),
        ("part", "stl"),
        ("part", "build123d"),
        ("part", "kicad"),
        ("assembly", "assy"),
        ("assembly", "step"),
    ],
)
def test_every_type_takes_the_cmf_parameters(kind, type_name):
    assert set(cmf.TYPE_PARAMETERS) <= set(factory.accepted_object_type_parameters(kind, type_name))


def test_tolerance_stays_with_the_homogeneous_types():
    assert "tolerance" in factory.accepted_object_type_parameters("part", "build123d")
    assert "tolerance" not in factory.accepted_object_type_parameters("part", "step")


def test_a_part_is_drawn_in_the_colour_it_declares(ctx):
    assert ctx.get_part(":red-box").config["properties"]["color"] == "#C91A09"


def test_a_part_in_a_colour_is_an_instance_of_its_own(ctx):
    grey = ctx.get_part(":box;color=:stone")
    assert grey is not None
    assert grey.config["properties"]["color"] == "#969696"
    assert ctx.get_part(":box").config.get("properties", {}).get("color") is None


def test_a_link_names_the_canonical_colour_whichever_alias_it_used(ctx):
    wall = ctx._get_assembly(":wall")
    asyncio.run(wall.do_instantiate())
    names = [child.item.name for child in wall.children]
    assert names == ["brick;color=//vendor:Medium Stone Grey"] * 2
    assert wall.children[0].item is wall.children[1].item


# --------------------------------------------------------------------------- #
# What the schema takes                                                       #
# --------------------------------------------------------------------------- #


def test_the_schema_takes_the_three_sections():
    jsonschema.validate(yaml.safe_load(textwrap.dedent(ROOT)), get_partcad_schema())
    jsonschema.validate(yaml.safe_load(textwrap.dedent(VENDOR)), get_partcad_schema())


@pytest.mark.parametrize(
    "document",
    [
        {"colors": {" leading": "#fff"}},
        {"finishes": {"x": {"display": {"roughness": 2}}}},
        # Reserved for a visual texture, and not a colour's to state.
        {"colors": {"x": {"texture": "y"}}},
        {"materials": {"x": {"manufacturable": "no"}}},
        {"colors": {"x": {"type": "enrich"}}},
    ],
)
def test_the_schema_refuses(document):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, get_partcad_schema())


def test_a_parametric_declaration_named_without_values_is_its_defaults(ctx):
    """'//pub/std/color:rgba' alone is drawn in its default colour, not in '#%color%'."""
    found = _find(ctx, "color", "//vendor:rgba")

    assert found.reference() == "//vendor:rgba"
    assert cmf.display(ctx, found) == (0, 0, 0, 1.0)


def test_the_listing_shows_each_declaration_by_how_it_looks(ctx):
    """'pc list colors|finishes': the look first, the display-only mark, and an alias by what it names."""
    from partcad_service_json_rpc.core import operations

    project = ctx.get_project("//")
    colors = operations._cmf_rows(ctx, project, "color")
    assert colors["red"].startswith("#C91A09")
    assert colors["stone"].startswith("#969696")
    assert colors["stone"].endswith("(alias of //vendor:Medium Stone Grey)")
    assert colors["loop-a"].startswith("<broken>")
    vendor = operations._cmf_rows(ctx, ctx.get_project("//vendor"), "color")
    assert vendor["rgba"].startswith("parametric")
    assert vendor["rgba"].endswith("(display only)")

    finishes = operations._cmf_rows(ctx, project, "finish")
    assert "Satin, VDI 3400 Ref 27" in finishes["satin"]
    assert "As it comes out of the mould" in finishes["as-molded"]


def _package(tmp_path, colors):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"colors": colors}))
    return pc.Context(str(tmp_path))


def test_a_declaration_named_with_a_reserved_character_is_that_name(tmp_path):
    """'a;b' is a name, not 'a' with a value: its reference escapes it, and resolves back to it."""
    ctx = _package(
        tmp_path,
        {
            "a;b": {"display": "#123456"},
            "p;q": {"parameters": {"color": {"type": "string", "default": "000000FF"}}, "display": "#%color%"},
        },
    )
    project = ctx.get_project("//")

    plain = project.get_cmf("color", escape_name("a;b"))
    assert (plain.base_name, plain.parameter_values) == ("a;b", {})
    assert plain.reference() == "//:a%3Bb"
    assert cmf.lookup(ctx, "color", plain.reference()) is plain

    tinted = project.get_cmf("color", escape_name("p;q") + ";color=FF0000FF")
    assert (tinted.base_name, tinted.parameter_values) == ("p;q", {"color": "FF0000FF"})
    assert cmf.display(ctx, tinted) == (255, 0, 0, 1.0)
    assert cmf.lookup(ctx, "color", tinted.reference()) is tinted

    from partcad_service_json_rpc.core import operations

    rows = operations._cmf_rows(ctx, project, "color")
    assert rows["a;b"].startswith("#123456")

    # And the explorer lists it under its own name, as it lists any other.
    warned = []
    session = types.SimpleNamespace(emitter=types.SimpleNamespace(warning=warned.append))
    items = {item["name"]: item for item in operations._cmf_items(session, project, "color")}
    assert items["a;b"]["display"] == "#123456"
    assert items["p;q"]["display"] == "#000000FF"
    assert warned == []


def test_an_escape_in_a_parametric_declaration_is_no_expression(tmp_path):
    """'%25%' in an escaped reference is a '%' written escaped, not the expression '25'."""
    ctx = _package(
        tmp_path,
        {
            "foo%#bar": {"display": "#ABCDEF"},
            "tinted": {
                "type": "alias",
                "source": ":foo%25%23bar",
                "parameters": {"shade": {"type": "string", "default": "1"}},
            },
        },
    )
    alias = ctx.get_project("//").get_cmf("color", "tinted")
    assert alias.source == ":foo%25%23bar"
    assert cmf.display(ctx, cmf.lookup(ctx, "color", "//:tinted")) == (0xAB, 0xCD, 0xEF, 1.0)


def test_an_alias_naming_nothing_is_listed_as_broken(tmp_path):
    """An alias with no 'source:' is a broken row, not a listing that stops."""
    from partcad_service_json_rpc.core import operations

    ctx = _package(tmp_path, {"orphan": {"type": "alias"}, "red": "#C91A09"})
    rows = operations._cmf_rows(ctx, ctx.get_project("//"), "color")
    assert rows["orphan"].startswith("<broken>")
    assert rows["red"].startswith("#C91A09")
    assert cmf.lookup(ctx, "color", None, quiet=True) is None
