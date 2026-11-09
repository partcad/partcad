#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A printed part, the design it is a print of, and the process that prints it.

'additive' is the one method whose `source:` is not something that goes into
the machine. What a printer is handed is a *design*, and what comes out is that
design as the process can make it -- so the declaration names the design, may
name what the part is drawn as, and says how the inside is filled:

    printed:
      manufacturing:
        method: additive
        source: design        # what it is a print of, and what it is drawn as
        fff:
          walls: 3
          infill: 20%

The checks are driven with the analysis stubbed, as 'test_subtractive.py' does
it: what is being tested is what the check does with the answers, and the
analysis has tests of its own.
"""

import asyncio

import jsonschema
import pytest
import yaml

import partcad as pc
from partcad import procurement
from partcad.build_plan import _part_problems
from partcad.lint.all import get_partcad_schema
from partcad.manufacturing_instructions import describe
from partcad.part_config import PartConfiguration
from partcad.part_config_manufacturing import (
    IMPLIED_TYPE_KEY,
    METHOD_ADDITIVE,
    PROCESS_DEFAULTS,
    PROCESS_FFF,
    PartConfigManufacturing,
    implied_type,
    parse_fraction,
)
from partcad.qual.basic import manufacturability_analysis
from partcad.qual.basic.manufacturability_additive_solid import ManufacturabilityAdditiveSolidTest


def _manufacturing(**section):
    return PartConfigManufacturing({"manufacturing": section})


#
# What the declaration says
#


def test_a_printed_part_names_its_design():
    data = _manufacturing(method="additive", source="design")
    assert data.method == METHOD_ADDITIVE
    assert data.design == "design"
    assert data.visual is None
    assert data.missing_fields() == []
    assert data.process_error is None and data.machine_error is None


def test_a_printed_part_that_names_none_is_its_own_design():
    """What every 'additive' part written before the design could be named means, and still means."""
    data = _manufacturing(method="additive")
    assert data.design is None
    assert data.missing_fields() == []
    assert data.processes == {}
    assert data.process_error is None


def test_only_a_print_has_a_design():
    """Every other method's 'source:' is what goes into the machine: stock, or a blank."""
    assert _manufacturing(method="subtractive", source="stock").design is None
    assert _manufacturing(method="sheet_metal", source="blank", instructions="bends").design is None


def test_the_process_settings_are_read_into_their_units():
    data = _manufacturing(
        method="additive",
        source="design",
        fff={
            "nozzle": "0.6 mm",
            "layerHeight": 0.3,
            "lineWidth": "0.03 in",
            "walls": 3,
            "topLayers": 5,
            "bottomLayers": 0,
            "infill": "20%",
            "infillPattern": "Gyroid",
            "desc": "Logo side up",
        },
    )
    assert data.process_error is None
    process = data.process
    assert process is not None and process.kind == PROCESS_FFF
    assert process.get("nozzle") == pytest.approx(0.6)
    assert process.get("layerHeight") == pytest.approx(0.3)
    assert process.get("lineWidth") == pytest.approx(0.762)
    assert process.get("walls") == 3
    assert process.get("bottomLayers") == 0
    assert process.get("infill") == pytest.approx(0.2)
    assert process.get("infillPattern") == "gyroid"
    assert process.get("desc") == "Logo side up"


def test_what_a_process_leaves_out_is_assumed_only_where_something_is_worked_out():
    """'settings()' fills the gaps with the usual defaults; 'options' is what was said."""
    data = _manufacturing(method="additive", fff={"infill": 0.4})
    process = data.process
    assert process.options == {"infill": 0.4}
    settings = process.settings()
    assert settings["infill"] == 0.4
    assert settings["walls"] == PROCESS_DEFAULTS[PROCESS_FFF]["walls"]
    assert "desc" not in settings
    assert process.to_data()["process"] == PROCESS_FFF


def test_an_empty_process_subsection_names_the_process_and_nothing_else():
    data = _manufacturing(method="additive", fff=None)
    assert data.process_error is None
    assert data.process.options == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("20%", 0.2), (" 7.5 % ", 0.075), ("0.2", 0.2), (0.2, 0.2), (0, 0.0), (1, 1.0), ("100%", 1.0)],
)
def test_a_fraction_is_a_percentage_or_a_share(value, expected):
    assert parse_fraction(value, "'infill:'") == pytest.approx(expected)


@pytest.mark.parametrize("value", [20, "20", "120%", "-5%", True, "most", [0.2], "nan"])
def test_a_fraction_that_is_not_one_is_refused(value):
    """A bare number above 1 is twenty percent to one reader and two thousand to another."""
    with pytest.raises(ValueError):
        parse_fraction(value, "'infill:'")


@pytest.mark.parametrize(
    ("section", "said"),
    [
        ({"infill": "20%"}, "write it under 'fff:'"),
        ({"walls": 3, "fff": {}}, "write it under 'fff:'"),
        ({"fff": {"speed": 60}}, "'fff:' does not take 'speed:'"),
        ({"fff": {"infill": 20}}, "more than all of it"),
        ({"fff": {"walls": 2.5}}, "not a count"),
        ({"fff": {"walls": True}}, "not a count"),
        ({"fff": {"layerHeight": 0}}, "not a positive length"),
        ({"fff": {"infillPattern": ""}}, "not the name of a pattern"),
        ({"fff": "yes"}, "is not a section"),
        ({"visual": "render"}, "there is no 'source:' design"),
        ({"source": ""}, "not a reference to a part"),
        ({"bogus": 1}, "does not take 'bogus:'"),
    ],
)
def test_a_declaration_that_cannot_be_read_is_recorded_rather_than_raised(section, said):
    """Loading a package must not fail over one part's declaration; the check reports it."""
    data = _manufacturing(method="additive", **section)
    assert data.process_error is not None
    assert said in data.process_error
    assert data.processes == {}
    # Not the router's business: 'pc cam' visits a part whose 'machine_error'
    # is set, and a printer's typo is nothing it has a program for.
    assert data.machine_error is None


def test_a_cut_on_a_printed_part_is_still_refused_as_a_cut():
    """The keys a cut takes are refused in the words every other method hears."""
    data = _manufacturing(method="additive", source="design", diameter=3)
    assert "describes no cut" in data.machine_error
    assert data.process_error is None


#
# A printed part with no geometry of its own
#


def test_a_printed_part_with_no_type_is_its_design():
    implied = implied_type({"manufacturing": {"method": "additive", "source": "design"}})
    assert implied == {"type": "alias", "source": "design", IMPLIED_TYPE_KEY: "additive"}


def test_a_printed_part_with_a_visual_is_drawn_as_the_visual():
    implied = implied_type({"manufacturing": {"method": "additive", "source": "design", "visual": "render"}})
    assert implied["source"] == "render"


@pytest.mark.parametrize(
    "config",
    [
        {"type": "stl", "manufacturing": {"method": "additive", "source": "design"}},
        {"source": "other", "manufacturing": {"method": "additive", "source": "design"}},
        {"manufacturing": {"method": "additive"}},
        {"manufacturing": {"method": "additive", "visual": "render"}},
        {"manufacturing": {"method": "subtractive", "source": "stock"}},
        {"manufacturing": "additive"},
        {},
        "//other:part",
    ],
)
def test_nothing_else_is_given_a_type(config):
    """A part with a geometry of its own keeps it, and a declaration missing its type is reported as before."""
    assert implied_type(config) is None


#
# In a package
#


PACKAGE = {
    "name": "//test",
    "parts": {
        "design": {"type": "stl"},
        "render": {"type": "stl"},
        "printed": {
            "desc": "The design, printed",
            "manufacturing": {"method": "additive", "source": "design", "fff": {"walls": 3, "infill": "20%"}},
        },
        "printed_denser": {
            "manufacturing": {"method": "additive", "source": "design", "fff": {"walls": 3, "infill": "40%"}},
        },
        "drawn_otherwise": {"manufacturing": {"method": "additive", "source": "design", "visual": "render"}},
        "self_printed": {"type": "stl", "manufacturing": {"method": "additive"}},
        "typed_with_visual": {
            "type": "stl",
            "manufacturing": {"method": "additive", "source": "design", "visual": "render"},
        },
        "typo": {"manufacturing": {"method": "additive", "source": "design", "fff": {"infill": 20}}},
        "orphan": {"type": "stl", "manufacturing": {"method": "additive", "source": "missing"}},
        "typeless_orphan": {"manufacturing": {"method": "additive", "source": "missing"}},
        "cut": {"type": "stl", "manufacturing": {"method": "subtractive", "source": "design"}},
    },
}


@pytest.fixture
def ctx(tmp_path):
    """The fixture package, with an empty file behind every part that has one.

    Empty because nothing here builds geometry: the check is driven with the
    analysis stubbed.
    """
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    for name, config in PACKAGE["parts"].items():
        if config.get("type") == "stl":
            (tmp_path / (name + ".stl")).write_text("")
    return pc.Context(str(tmp_path))


def _arrange(monkeypatch, open_edges=None):
    """Answer what the check asks, without a sandbox and without geometry.

    'open_edges' maps a part's name to how many open edges its solid has; every
    other part is a closed solid.
    """
    open_edges = open_edges or {}
    built = []

    async def wrapped(self, ctx):
        built.append(self.name)
        return {"name": self.name, "label": self.name, "brep": b"CASCADE Topology V3"}

    async def fake_free_bounds(ctx, envelope):
        return open_edges.get(envelope["name"], 0)

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    monkeypatch.setattr(manufacturability_analysis, "free_bounds_count", fake_free_bounds)
    return built


def _verdict(check, ctx, name):
    return asyncio.run(check.test([], ctx, ctx.get_part("//test:" + name)))


def test_a_printed_part_with_no_type_loads_as_a_reference_to_its_design(ctx):
    part = ctx.get_part("//test:printed")
    assert part is not None
    assert part.config["type"] == "alias"
    assert part.config["source"] == "design"
    assert part.config[IMPLIED_TYPE_KEY] == "additive"
    # What it says about being made is its own, not the design's: a reference
    # restates 'manufacturing:' rather than inheriting it.
    data = PartConfiguration.get_manufacturing_data(part)
    assert data.method == METHOD_ADDITIVE
    assert data.design == "design"
    assert data.process.get("infill") == pytest.approx(0.2)


def test_a_printed_part_with_a_visual_points_at_the_visual(ctx):
    part = ctx.get_part("//test:drawn_otherwise")
    assert part.config["source"] == "render"
    assert PartConfiguration.get_manufacturing_data(part).design == "design"


def test_a_design_is_not_stock(ctx):
    """Nothing of the design goes into the printer, so nobody is asked to procure it.

    Where a subtractive part naming the same object is procured as it -- which is
    the difference the two methods' 'source:' has.
    """
    printed = ctx.get_part("//test:printed")
    assert procurement.stock_name(printed) is None
    assert asyncio.run(procurement.procured_as(ctx, printed)) == []

    cut = ctx.get_part("//test:cut")
    assert procurement.stock_name(cut) == "//test:design"


def test_a_printed_part_passes_when_its_design_is_a_closed_solid(ctx, monkeypatch):
    built = _arrange(monkeypatch)
    check = ManufacturabilityAdditiveSolidTest()
    assert _verdict(check, ctx, "printed") is check.TEST_PASSED
    # The design is what is printed, and so what is asked.
    assert built == ["design"]


def test_the_design_is_asked_rather_than_the_visual(ctx, monkeypatch):
    """A visual may be a mesh nobody would hand to a slicer; the design is what is printed."""
    _arrange(monkeypatch, open_edges={"drawn_otherwise": 7, "render": 7})
    check = ManufacturabilityAdditiveSolidTest()
    assert _verdict(check, ctx, "drawn_otherwise") is check.TEST_PASSED


def test_a_design_that_is_not_solid_fails_naming_the_design(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, open_edges={"design": 3})
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "printed") is check.TEST_FAILED
    assert "The design 'design' is not solid" in caplog.text


def test_a_design_that_is_not_there_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch)
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "orphan") is check.TEST_FAILED
    assert "The design 'missing' it is printed from is not found" in caplog.text


def test_a_part_that_is_a_design_that_is_not_there_is_a_reference_to_nothing(ctx):
    """With no geometry of its own it *is* the design, so it fails the way any reference to nothing does."""
    part = ctx.get_part("//test:typeless_orphan")
    with pytest.raises(Exception, match="missing"):
        PartConfiguration.get_manufacturing_data(part)


def test_a_part_that_is_its_own_design_is_asked_what_it_always_was(ctx, monkeypatch, caplog):
    built = _arrange(monkeypatch, open_edges={"self_printed": 2})
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "self_printed") is check.TEST_FAILED
    assert "The shape is not solid" in caplog.text
    assert built == ["self_printed"]


def test_a_process_that_cannot_be_read_fails_before_anything_is_built(ctx, monkeypatch, caplog):
    built = _arrange(monkeypatch)
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "typo") is check.TEST_FAILED
    assert "more than all of it" in caplog.text
    assert built == []


def test_a_part_with_a_type_of_its_own_says_no_visual(ctx, monkeypatch, caplog):
    """It is drawn as what it is; a second answer is one too many."""
    _arrange(monkeypatch)
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "typed_with_visual") is check.TEST_FAILED
    assert "'visual:'" in caplog.text and "'type: stl'" in caplog.text


def test_the_check_passes_over_a_part_made_some_other_way(ctx, monkeypatch):
    _arrange(monkeypatch, open_edges={"cut": 9})
    check = ManufacturabilityAdditiveSolidTest()
    assert _verdict(check, ctx, "cut") is check.TEST_PASSED


def test_the_verdict_is_keyed_on_the_design_and_the_process(ctx):
    """'manufacturing:' is left out of a part's own hash, so the check keys on what it read."""
    check = ManufacturabilityAdditiveSolidTest()

    def suffix(name):
        return asyncio.run(check.cache_key_suffix(ctx, ctx.get_part("//test:" + name)))

    # A part that is its own design and says nothing else keys as it always did.
    assert suffix("self_printed") == ""
    assert suffix("printed").startswith(".additive=")
    assert suffix("printed") != suffix("printed_denser")


def test_the_instructions_say_what_it_is_printed_from_and_how(ctx):
    data = PartConfiguration.get_manufacturing_data(ctx.get_part("//test:printed"))
    lines = describe(data)
    assert lines[0] == "Printed from the design `design`."
    assert lines[1] == "Print it on a filament printer (FFF); 3 walls, infill 20%."


def test_the_instructions_say_only_what_was_said():
    """A setting left out is the printer's default, which its operator knows better than PartCAD."""
    lines = describe(_manufacturing(method="additive", fff={}))
    assert lines == ["Made additively (3D printed).", "Print it on a filament printer (FFF)."]

    lines = describe(_manufacturing(method="additive", fff={"infill": "100%", "topLayers": 1, "desc": "Upright"}))
    assert lines[1:] == ["Print it on a filament printer (FFF); 1 top layer, infill 100%.", "Upright"]


def test_a_process_that_cannot_be_read_is_a_problem_of_the_build_plan(ctx):
    problems = _part_problems(ctx.get_part("//test:typo"), made=True, bought=True)
    assert any(problem.startswith("How it is printed cannot be read:") for problem in problems)


#
# What 'pc lint' says
#


def _errors(parts):
    return list(jsonschema.Draft7Validator(get_partcad_schema()).iter_errors({"parts": parts}))


def test_the_schema_takes_a_printed_part_with_no_type():
    assert not _errors(
        {
            "printed": {
                "manufacturing": {
                    "method": "additive",
                    "source": "design",
                    "visual": "render",
                    "fff": {"layerHeight": "0.2 mm", "walls": 3, "infill": "20%", "infillPattern": "gyroid"},
                }
            }
        }
    )
    assert not _errors({"printed": {"type": "step", "manufacturing": {"method": "additive", "fff": {"infill": 0.2}}}})


@pytest.mark.parametrize(
    "part",
    [
        # No design, so nothing to be with no type of its own.
        {"manufacturing": {"method": "additive"}},
        {"manufacturing": {"method": "subtractive", "source": "stock"}},
        # A geometry of its own and a visual: two answers.
        {"type": "step", "manufacturing": {"method": "additive", "source": "design", "visual": "render"}},
        # A visual stands for a design.
        {"type": "step", "manufacturing": {"method": "additive", "visual": "render"}},
        # A print process is a printer's.
        {"type": "step", "manufacturing": {"method": "subtractive", "source": "stock", "fff": {}}},
        {"type": "step", "manufacturing": {"method": "additive", "fff": {"infill": 20}}},
        {"type": "step", "manufacturing": {"method": "additive", "fff": {"speed": 60}}},
        {"type": "step", "manufacturing": {"method": "additive", "infill": "20%"}},
    ],
)
def test_the_schema_refuses_what_the_loader_reports(part):
    assert _errors({"p": part})


#
# What a print service is told
#


def test_a_print_service_is_told_the_design_and_the_settings_as_stated():
    """Its own defaults fill the rest: they are better than PartCAD's guess at them."""
    data = _manufacturing(method="additive", source="design", fff={"walls": 3, "infill": "20%", "desc": "Logo side up"})
    assert data.print_data() == {
        "method": "additive",
        "design": "design",
        "processes": {"fff": {"walls": 3, "infill": 0.2}},
    }
    assert _manufacturing(method="additive").print_data() == {"method": "additive"}


def test_nothing_is_told_about_what_is_not_printed_or_cannot_be_read():
    assert _manufacturing(method="subtractive", source="stock").print_data() is None
    assert _manufacturing(method="additive", fff={"infill": 20}).print_data() is None


CMF_PACKAGE = {
    "name": "//test",
    "parts": {
        "design": {
            "type": "stl",
            "parameters": {"material": {"type": "string", "default": "//pub:pla"}},
        },
        "render": {"type": "stl"},
        "printed": {"manufacturing": {"method": "additive", "source": "design", "fff": {"infill": "20%"}}},
        "drawn_otherwise": {"manufacturing": {"method": "additive", "source": "design", "visual": "render"}},
    },
}


@pytest.fixture
def cmf_ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(CMF_PACKAGE))
    for name in ("design", "render"):
        (tmp_path / (name + ".stl")).write_text("")
    return pc.Context(str(tmp_path))


def test_a_printed_part_is_made_of_what_its_design_is_made_of(cmf_ctx):
    """A reference states no material, and is its source's: the cart used to order it as made of nothing."""
    printed = cmf_ctx.get_part("//test:printed")
    assert asyncio.run(printed.get_mcft("material")) == "//pub:pla"


def test_the_cart_carries_how_it_is_printed(cmf_ctx):
    from partcad.plugin_provider_data_cart import ProviderCartItem

    item = ProviderCartItem()
    asyncio.run(item.set_spec(cmf_ctx, "//test:printed#2"))
    composed = item.compose()
    assert composed["material"] == "//pub:pla"
    assert composed["manufacturing"] == {
        "method": "additive",
        "design": "design",
        "processes": {"fff": {"infill": 0.2}},
    }

    plain = ProviderCartItem()
    asyncio.run(plain.set_spec(cmf_ctx, "//test:render"))
    assert "manufacturing" not in plain.compose()


def test_a_manufacturer_is_sent_the_design_rather_than_the_visual(cmf_ctx):
    """A visual may be a mesh nobody would slice; the design is what is printed."""
    from partcad.plugin_factory_provider_manufacturer import _sent_geometry

    drawn_otherwise = cmf_ctx.get_part("//test:drawn_otherwise")
    sent = asyncio.run(_sent_geometry(cmf_ctx, drawn_otherwise))
    assert sent.name == "design"

    render = cmf_ctx.get_part("//test:render")
    assert asyncio.run(_sent_geometry(cmf_ctx, render)) is render
