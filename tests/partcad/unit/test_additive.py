#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A printed part, the design it is a print of, and the printer that prints it.

'additive' is the one method whose `source:` is not something that goes into
the machine. What a printer is handed is a *design*, and what comes out is that
design as the process can make it -- so the declaration names the design, and
names the printer the way a subtractive part names its machine:

    printed:
      manufacturing:
        method: additive
        source: design        # what it is a print of, and what a picture draws
        fff:                  # a machine, read as a router or a laser is
          toolAxis: -Z
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
    MACHINE_FFF,
    MANUFACTURED_TYPE,
    METHOD_ADDITIVE,
    PRINT_DEFAULTS,
    ROUTED_MACHINES,
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
    assert data.missing_fields() == []
    assert data.machine_error is None


def test_a_printed_part_that_names_none_is_its_own_design():
    """What every 'additive' part written before the design could be named means, and still means."""
    data = _manufacturing(method="additive")
    assert data.design is None
    assert data.missing_fields() == []
    # No printer named is the usual one, as a part naming no machine is cut on
    # a router: undeclared, so that 'pc cam' over a package passes it over and
    # a print service is told nothing about it, but there to route on demand.
    assert list(data.machines) == [MACHINE_FFF]
    assert data.machine.declared is False
    assert data.machine_error is None


def test_only_a_print_has_a_design():
    """Every other method's 'source:' is what goes into the machine: stock, or a blank."""
    assert _manufacturing(method="subtractive", source="stock").design is None
    assert _manufacturing(method="sheet_metal", source="blank", instructions="bends").design is None


def test_the_printer_settings_are_read_into_their_units():
    data = _manufacturing(
        method="additive",
        source="design",
        fff={
            "along": "-Y",
            "nozzle": "0.6 mm",
            "filament": "2.85 mm",
            "feed": "50 mm/s",
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
    assert data.machine_error is None
    printer = data.machine
    assert printer is not None and printer.kind == MACHINE_FFF
    # The axis is a machine's, read as a router's is: the build orientation.
    assert printer.tool_axis == "-Y"
    assert printer.vector == (0.0, -1.0, 0.0)
    # Own keys, a laser's kerf's kind.
    assert printer.get("nozzle") == pytest.approx(0.6)
    assert printer.get("filament") == pytest.approx(2.85)
    # The router's own feed, read the way 'pc cam' reads it.
    assert printer.get("feed") == pytest.approx(3000.0)
    assert printer.get("layerHeight") == pytest.approx(0.3)
    assert printer.get("lineWidth") == pytest.approx(0.762)
    assert printer.get("walls") == 3
    assert printer.get("bottomLayers") == 0
    assert printer.get("infill") == pytest.approx(0.2)
    assert printer.get("infillPattern") == "gyroid"
    assert printer.get("desc") == "Logo side up"
    assert printer.to_data()["machine"] == MACHINE_FFF
    assert printer.to_data()["filament"] == pytest.approx(2.85)
    assert "infill" in printer.job_options() and "nozzle" not in printer.job_options()


def test_what_a_printer_leaves_out_is_assumed_only_where_something_is_worked_out():
    """'settings()' fills the gaps with the usual defaults; 'options' is what was said."""
    data = _manufacturing(method="additive", fff={"infill": 0.4})
    printer = data.machine
    assert printer.options == {"infill": 0.4}
    assert printer.tool_axis == "-Z"
    settings = printer.settings()
    assert settings["infill"] == 0.4
    assert settings["walls"] == PRINT_DEFAULTS[MACHINE_FFF]["walls"]
    assert "desc" not in settings and "feed" not in settings


def test_an_empty_printer_subsection_names_the_printer_and_nothing_else():
    data = _manufacturing(method="additive", fff=None)
    assert data.machine_error is None
    assert data.machine.options == {}


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
        ({"feed": 1200}, "write it under 'fff:'"),
        ({"toolAxis": "-Y"}, "write it under 'fff:'"),
        ({"fff": {"toolAxis": "-Y", "along": "-Y"}}, "which are one thing"),
        ({"fff": {"toolAxis": "sideways"}}, "is not an axis"),
        ({"fff": {"diameter": 6}}, "'fff:' does not take diameter"),
        ({"fff": {"speed": 60}}, "'fff:' does not take speed"),
        ({"fff": {"infill": 20}}, "more than all of it"),
        ({"fff": {"walls": 2.5}}, "not a count"),
        ({"fff": {"walls": True}}, "not a count"),
        ({"fff": {"layerHeight": 0}}, "not a positive length"),
        ({"fff": {"infillPattern": ""}}, "not the name of a pattern"),
        ({"fff": "yes"}, "is not a section"),
        ({"source": "design", "visual": "render"}, "write it on the part itself"),
        ({"source": ""}, "not a reference to a part"),
        ({"bogus": 1}, "does not take 'bogus:'"),
    ],
)
def test_a_declaration_that_cannot_be_read_is_recorded_rather_than_raised(section, said):
    """Loading a package must not fail over one part's declaration; the check reports it."""
    data = _manufacturing(method="additive", **section)
    assert data.machine_error is not None
    assert said in data.machine_error
    assert data.machines == {}


def test_a_cut_on_a_printed_part_is_still_refused_as_a_cut():
    """The keys a cut takes, and no printer does, are refused in the words every other method hears."""
    data = _manufacturing(method="additive", source="design", diameter=3)
    assert "describes no cut" in data.machine_error


#
# How it relates to 'pc cam'
#


class _Shape:
    """Just enough of a part for 'pc cam's own questions."""

    def __init__(self, section):
        self.config = {"manufacturing": section}
        self.name = "printed"

    def get_final_config(self):
        return self.config


def test_a_printer_is_a_machine_pc_cam_routes():
    """`pc cam` writes a printer's route as it writes a router's: the same job, read from the same section."""
    from partcad import cam

    assert MACHINE_FFF in ROUTED_MACHINES
    shape = _Shape({"method": "additive", "source": "design", "fff": {"infill": "20%", "filament": "2.85 mm"}})
    assert cam.declares_job(shape) is True
    job = cam.declared_config(shape)
    # What the route is written with: what was said, over the usual printer --
    # the filament too, which is what the extrusion is counted in.
    assert job["infill"] == pytest.approx(0.2)
    assert job["filament"] == pytest.approx(2.85)
    assert job["layerHeight"] == pytest.approx(PRINT_DEFAULTS[MACHINE_FFF]["layerHeight"])


def test_a_printer_may_name_the_implementation_that_routes_it():
    data = _manufacturing(method="additive", source="design", fff={"implementation": "//slicers:gcode"})
    assert data.machine_error is None
    assert data.machine.get("implementation") == "//slicers:gcode"


def test_a_print_that_names_no_printer_is_routed_only_when_asked():
    """The usual printer is undeclared: a package's run passes the part over, and naming the machine routes it."""
    from partcad import cam

    shape = _Shape({"method": "additive", "source": "design"})
    assert cam.declares_job(shape) is False
    assert cam.declared_config(shape) is None
    assert cam.declared_config(shape, machine=MACHINE_FFF)["infill"] == pytest.approx(
        PRINT_DEFAULTS[MACHINE_FFF]["infill"]
    )


def test_a_machine_that_runs_no_program_is_refused_by_name():
    from partcad import cam

    shape = _Shape({"method": "forming", "source": "cavity", "mold": {"shrinkage": "1%"}})
    with pytest.raises(cam.CamConfigError) as raised:
        cam.declared_config(shape, machine="mold")
    assert "runs no program" in str(raised.value)


def test_a_printer_that_cannot_be_read_is_visited_and_reported_as_a_machine_is():
    from partcad import cam

    shape = _Shape({"method": "additive", "fff": {"infill": 20}})
    assert cam.declares_job(shape) is True
    with pytest.raises(cam.CamConfigError) as raised:
        cam.declared_config(shape)
    assert "more than all of it" in str(raised.value)


#
# A printed part with no geometry of its own
#


def test_a_printed_part_with_no_type_is_what_its_printer_makes():
    """Kept as a BREP file: PartCAD declares no default part type, so nothing makes 'step' the one to imply."""
    implied = implied_type({"manufacturing": {"method": "additive", "source": "design"}})
    assert implied == {"type": MANUFACTURED_TYPE, IMPLIED_TYPE_KEY: "brep"}


@pytest.mark.parametrize("fmt", ["brep", "step", "sdf"])
def test_a_part_may_say_what_its_own_geometry_is_kept_in(fmt):
    implied = implied_type({"type": fmt, "manufacturing": {"method": "additive", "source": "design"}})
    assert implied == {"type": MANUFACTURED_TYPE, IMPLIED_TYPE_KEY: fmt}


@pytest.mark.parametrize(
    "section",
    [
        {"method": "subtractive", "source": "stock", "instructions": "outline"},
        {"method": "forming", "source": "cavity"},
        {"method": "forming", "source": "cavity", "mold": {"shrinkage": "1.5%"}},
    ],
)
def test_a_cut_or_a_molded_part_is_what_its_machine_makes_too(section):
    assert implied_type({"manufacturing": section})["type"] == MANUFACTURED_TYPE


def test_what_a_printed_part_is_drawn_as_is_no_part_of_its_type():
    """A part's 'visual:' is a picture's business (see 'partcad.visual'); the part is the design, printed."""
    implied = implied_type({"visual": "render", "manufacturing": {"method": "additive", "source": "design"}})
    assert implied["type"] == MANUFACTURED_TYPE


@pytest.mark.parametrize(
    "config",
    [
        {"type": "stl", "manufacturing": {"method": "additive", "source": "design"}},
        {"source": "other", "manufacturing": {"method": "additive", "source": "design"}},
        {"manufacturing": {"method": "additive"}},
        {"visual": "render", "manufacturing": {"method": "additive"}},
        {"manufacturing": {"method": "subtractive", "source": "stock"}},
        # Cut along its own file, which it therefore has.
        {"type": "step", "manufacturing": {"method": "subtractive", "source": "stock"}},
        # Fetched, and so read rather than written.
        {
            "type": "step",
            "fileFrom": "url",
            "fileUrl": "https://example.com/p.step",
            "manufacturing": {"method": "additive", "source": "d"},
        },
        {"manufacturing": {"method": "sheet_metal", "source": "blank", "instructions": "bends"}},
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
        # A part of its own that names its design: an as-printed model, say.
        "as_printed": {"type": "stl", "manufacturing": {"method": "additive", "source": "design"}},
        "self_printed": {"type": "stl", "manufacturing": {"method": "additive"}},
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


def test_a_printed_part_with_no_type_loads_as_what_its_printer_makes(ctx):
    part = ctx.get_part("//test:printed")
    assert part is not None
    assert part.config["type"] == MANUFACTURED_TYPE
    assert part.config[IMPLIED_TYPE_KEY] == "brep"
    data = PartConfiguration.get_manufacturing_data(part)
    assert data.method == METHOD_ADDITIVE
    assert data.design == "design"
    assert data.machine.get("infill") == pytest.approx(0.2)


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


def test_the_design_is_asked_rather_than_the_part(ctx, monkeypatch):
    """The part may be an as-printed mesh nobody would hand to a slicer; the design is what is printed."""
    built = _arrange(monkeypatch, open_edges={"as_printed": 7})
    check = ManufacturabilityAdditiveSolidTest()
    assert _verdict(check, ctx, "as_printed") is check.TEST_PASSED
    assert built == ["design"]


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


def test_a_part_made_after_a_design_that_is_not_there_fails_to_build_naming_it(ctx):
    """Before anything is sent to a sandbox: there is nothing to route."""
    part = ctx.get_part("//test:typeless_orphan")
    assert asyncio.run(part.get_wrapped(ctx)) is None
    assert part.errors == ["//test:typeless_orphan: it is made from 'missing', which is not found"]


def test_a_part_that_is_its_own_design_is_asked_what_it_always_was(ctx, monkeypatch, caplog):
    built = _arrange(monkeypatch, open_edges={"self_printed": 2})
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "self_printed") is check.TEST_FAILED
    assert "The shape is not solid" in caplog.text
    assert built == ["self_printed"]


def test_a_printer_that_cannot_be_read_fails_before_anything_is_built(ctx, monkeypatch, caplog):
    built = _arrange(monkeypatch)
    check = ManufacturabilityAdditiveSolidTest()
    with caplog.at_level("ERROR"):
        assert _verdict(check, ctx, "typo") is check.TEST_FAILED
    assert "more than all of it" in caplog.text
    assert built == []


def test_the_check_passes_over_a_part_made_some_other_way(ctx, monkeypatch):
    _arrange(monkeypatch, open_edges={"cut": 9})
    check = ManufacturabilityAdditiveSolidTest()
    assert _verdict(check, ctx, "cut") is check.TEST_PASSED


def test_the_verdict_is_keyed_on_the_design_and_the_printer(ctx):
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


def test_a_printer_that_cannot_be_read_is_a_problem_of_the_build_plan(ctx):
    problems = _part_problems(ctx.get_part("//test:typo"), made=True, bought=True)
    assert any(problem.startswith("The machine it is made on cannot be read:") for problem in problems)


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
                    "fff": {"layerHeight": "0.2 mm", "walls": 3, "infill": "20%", "infillPattern": "gyroid"},
                },
                "visual": "render",
            }
        }
    )
    # A part of its own may name its design, and be drawn as something else again.
    assert not _errors(
        {"printed": {"type": "step", "visual": "render", "manufacturing": {"method": "additive", "source": "design"}}}
    )
    assert not _errors({"printed": {"type": "step", "manufacturing": {"method": "additive", "fff": {"infill": 0.2}}}})
    assert not _errors(
        {"printed": {"manufacturing": {"method": "additive", "source": "d", "fff": {"implementation": "//s:g"}}}}
    )


@pytest.mark.parametrize(
    "part",
    [
        {"manufacturing": {"method": "forming", "source": "cavity", "mold": {"shrinkage": "1.5%"}}},
        {"type": "sdf", "manufacturing": {"method": "additive", "source": "design"}},
        {
            "manufacturing": {
                "method": "subtractive",
                "source": "stock",
                "instructions": "outline",
                "cnc": {"diameter": 3},
            }
        },
    ],
)
def test_the_schema_takes_every_part_its_machine_makes(part):
    assert not _errors({"p": part})


@pytest.mark.parametrize(
    "part",
    [
        # No design, so nothing to be with no type of its own.
        {"manufacturing": {"method": "additive"}},
        {"manufacturing": {"method": "subtractive", "source": "stock"}},
        # What a part is drawn as is the part's, not its manufacturing section's.
        {"type": "step", "manufacturing": {"method": "additive", "source": "design", "visual": "render"}},
        # A printer is the additive method's machine.
        {"type": "step", "manufacturing": {"method": "subtractive", "source": "stock", "fff": {}}},
        {"type": "step", "manufacturing": {"method": "additive", "fff": {"infill": 20}}},
        {"type": "step", "manufacturing": {"method": "additive", "fff": {"speed": 60}}},
        {"type": "step", "manufacturing": {"method": "additive", "infill": "20%"}},
        # A cut with nothing to cut out of the stock has to be its own file.
        {"manufacturing": {"method": "subtractive", "source": "stock", "cnc": {"diameter": 3}}},
        # A mold is what forming is done in.
        {"type": "step", "manufacturing": {"method": "additive", "source": "d", "mold": {"shrinkage": 0.01}}},
        {"manufacturing": {"method": "forming", "source": "cavity", "mold": {"shrinkage": "150%"}}},
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
        "machines": {"fff": {"walls": 3, "infill": 0.2}},
    }
    assert _manufacturing(method="additive").print_data() == {"method": "additive"}
    # How it lies on the bed is said where it is not the default, because it
    # decides the print as much as the infill does.
    sideways = _manufacturing(method="additive", fff={"along": "-Y"}).print_data()
    assert sideways["machines"] == {"fff": {"toolAxis": "-Y"}}


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
        "as_printed": {"type": "stl", "manufacturing": {"method": "additive", "source": "design"}},
    },
}


@pytest.fixture
def cmf_ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(CMF_PACKAGE))
    for name in ("design", "render", "as_printed"):
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
        "machines": {"fff": {"infill": 0.2}},
    }

    plain = ProviderCartItem()
    asyncio.run(plain.set_spec(cmf_ctx, "//test:render"))
    assert "manufacturing" not in plain.compose()


def test_a_manufacturer_is_sent_the_design_rather_than_the_part(cmf_ctx):
    """The part may be an as-printed mesh nobody would slice; the design is what is printed."""
    from partcad.plugin_factory_provider_manufacturer import _sent_geometry

    as_printed = cmf_ctx.get_part("//test:as_printed")
    sent = asyncio.run(_sent_geometry(cmf_ctx, as_printed))
    assert sent.name == "design"

    render = cmf_ctx.get_part("//test:render")
    assert asyncio.run(_sent_geometry(cmf_ctx, render)) is render


#
# What a picture of it draws (see 'partcad.visual')
#


PICTURE_PACKAGE = """
parts:
  design:
    type: basic
    cuboid: [20, 10, 5]
  look:
    type: basic
    cylinder: {radius: 3, height: 30}
  printed:
    manufacturing: {method: additive, source: design, fff: {infill: 20%}}
  printed-drawn:
    visual: look
    manufacturing: {method: additive, source: design}
  as-printed:
    type: basic
    cuboid: [19, 9, 4]
    manufacturing: {method: additive, source: design}
  as-printed-drawn:
    type: basic
    cuboid: [19, 9, 4]
    visual: look
    manufacturing: {method: additive, source: design}
  self-printed:
    type: basic
    cuboid: [5, 5, 5]
    manufacturing: {method: additive}
"""


@pytest.fixture(scope="module")
def picture_ctx(tmp_path_factory):
    root = tmp_path_factory.mktemp("printed-pictures")
    (root / "partcad.yaml").write_text(PICTURE_PACKAGE.lstrip())
    return pc.Context(str(root))


def _drawn_as(context, name):
    """What a picture of the part draws in its place, or None where it draws the part itself."""
    from partcad import visual

    part = context.get_part(name)
    tree = asyncio.run(part.get_wrapped(context))
    return asyncio.run(visual.substitute_async(context, part, tree)).tree.get(visual.NODE_KEY)


def test_a_part_with_a_geometry_of_its_own_is_drawn_as_its_design(picture_ctx):
    """The source is what the designer had in mind: it is the visual unless another is said."""
    assert _drawn_as(picture_ctx, "as-printed") == "//:design"


def test_a_visual_of_its_own_wins_over_the_design(picture_ctx):
    assert _drawn_as(picture_ctx, "as-printed-drawn") == "//:look"
    assert _drawn_as(picture_ctx, "printed-drawn") == "//:look"


def test_a_printed_part_with_no_geometry_of_its_own_is_drawn_as_its_design(picture_ctx):
    """Its geometry is what its printer makes, bead by bead; a picture draws what the designer had in mind."""
    from partcad import visual

    part = picture_ctx.get_part("printed")
    drawn = asyncio.run(visual.visual_of_async(picture_ctx, part))
    assert drawn is not None and drawn.part.name == "design"


def test_a_part_that_is_its_own_design_is_drawn_as_itself(picture_ctx):
    assert _drawn_as(picture_ctx, "self-printed") is None
