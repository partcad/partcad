#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the IDE shows of CMF (docs/design/cmf.md, section 9), as the daemon answers it.

Pinned here:

- a line of the bill of materials and of the Build vs Buy table says the
  item's own CMF without building it: what its geometry carries once built,
  what it declares before ('own_info');
- the CMF tab of a declaration says what it is called, what it is drawn in and
  whether it is a claim ('declaration_data');
- the CMF tab of a part or an assembly lists each item the 'cmf' check judges,
  the incomplete ones first ('report_async').
"""

import asyncio
import os
import sys

import pytest
import yaml

import partcad as pc
from partcad import cmf, shape_envelope
from partcad.part import Part

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
from cmf_section import CmfSet, Section  # noqa: E402

COLORS = {
    "red": {"display": "#C91A09", "ids": {"lego": "21", "ldraw": 4}, "aliases": ["bright red"]},
    "natural": {"display": "#A8A9AD"},
    "preview": {"display": "#00FF00", "manufacturable": False, "desc": "A colour for pictures"},
    "signal": {"type": "alias", "source": ":red"},
    "rgba": {
        "parameters": {"color": {"type": "string", "default": "000000FF"}},
        "display": "#%color%",
        "manufacturable": False,
    },
}
MATERIALS = {"alu": {"full": "Aluminium 6061-T6", "density": 2700, "color": ":natural"}}
FINISHES = {"satin": {"desc": "Satin, VDI 3400 Ref 27", "display": {"roughness": 0.6, "metallic": 0}}}


def _declare(**values):
    return {name: {"type": "string", "default": value} for name, value in values.items()}


def _stl(**parameters):
    part = {"type": "stl", "path": "box.stl"}
    if parameters:
        part["parameters"] = _declare(**parameters)
    return part


@pytest.fixture
def ctx(tmp_path):
    config = {
        "name": "//cmf",
        "manufacturable": True,
        "colors": COLORS,
        "materials": MATERIALS,
        "finishes": FINISHES,
        "parts": {
            "plain": _stl(),
            "red-box": _stl(color=":red", material=":alu", finish=":satin"),
            "preview-box": _stl(color=":preview"),
            "bought": {**_stl(color=":red"), "vendor": "acme", "sku": "B-1"},
        },
        "assemblies": {
            "case": {"type": "assy"},
            "kit": {"type": "assy", "vendor": "acme", "sku": "KIT-1", "parameters": _declare(color=":red")},
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    # Found, never read: nothing here builds geometry.
    (tmp_path / "box.stl").write_text("solid box\nendsolid box\n")
    (tmp_path / "case.assy").write_text(
        "links:\n"
        "  - part: plain\n    name: base\n"
        "  - part: red-box\n    name: lid\n"
        "  - part: red-box\n    name: lid-too\n"
        "  - assembly: kit\n    name: kit\n"
    )
    (tmp_path / "kit.assy").write_text("links:\n  - part: plain\n    name: inside\n")
    return pc.Context(str(tmp_path))


def _summary(*sets, unspecified=None):
    summary = Section(list(sets), 0).summary()
    if unspecified is not None:
        summary["unspecified"] = unspecified
    return summary


# ------------------------------------------------- a line of the BOM and of BvB


def test_a_line_says_what_a_part_declares_before_it_is_built(ctx):
    info = cmf.own_info(ctx, ctx.get_part("//cmf:red-box"))

    assert info == {
        "sets": [
            {
                "color": "//cmf:red",
                "material": "//cmf:alu",
                "finish": "//cmf:satin",
                "display": "#C91A09FF",
                "roughness": pytest.approx(0.6),
                "metallic": 0.0,
                "origin": "declared",
            }
        ],
        # Read off its parameters: its source has not been read.
        "declared": True,
    }


def test_a_line_marks_what_is_only_a_picture(ctx):
    info = cmf.own_info(ctx, ctx.get_part("//cmf:preview-box"))

    assert info["sets"][0]["displayOnly"] == ["color"]


def test_a_line_says_what_the_geometry_carries_once_built(ctx):
    part = ctx.get_part("//cmf:red-box")
    part._metadata = {
        shape_envelope.METADATA_CMF: _summary(
            CmfSet(color="//cmf:red", rgba=(201, 26, 9, 1.0), origin="source:step"),
            unspecified={"material": "all"},
        )
    }

    info = cmf.own_info(ctx, part)

    assert info["sets"][0]["origin"] == "source:step"
    assert info["unspecified"] == {"material": "all"}
    assert "declared" not in info


def test_a_line_of_something_that_states_nothing_says_nothing(ctx):
    assert cmf.own_info(ctx, ctx.get_part("//cmf:plain")) is None


def test_a_line_reads_a_part_without_building_it(ctx, monkeypatch):
    async def never(self, ctx):
        raise AssertionError("a column is not worth building a part for")

    monkeypatch.setattr(Part, "get_wrapped", never)

    assert cmf.own_info(ctx, ctx.get_part("//cmf:red-box"))["declared"] is True


# ------------------------------------------------------- a declaration's tab


def _declaration(ctx, kind, name):
    return cmf.declaration_data(ctx, ctx.get_project("//cmf").get_cmf(kind, name))


def test_a_colour_says_what_it_is_drawn_in_and_what_it_is_called(ctx):
    data = _declaration(ctx, "color", "red")

    assert data == {
        "name": "red",
        "kind": "color",
        "package": "//cmf",
        "reference": "//cmf:red",
        "manufacturable": True,
        "ids": {"ldraw": "4", "lego": "21"},
        "aliases": ["bright red"],
        "display": "#C91A09",
        "displayText": "#C91A09",
    }


def test_a_display_only_colour_says_so(ctx):
    data = _declaration(ctx, "color", "preview")

    assert data["manufacturable"] is False
    assert data["desc"] == "A colour for pictures"


def test_an_alias_is_shown_as_itself_with_what_it_names(ctx):
    data = _declaration(ctx, "color", "signal")

    assert data["name"] == "signal"
    assert data["aliasOf"] == ":red"
    # Canonical, as it enters an item's name: the declaration it names.
    assert data["reference"] == "//cmf:red"
    assert data["display"] == "#C91A09"


def test_a_parametric_colour_is_its_defaults(ctx):
    data = _declaration(ctx, "color", "rgba")

    assert data["parametric"] == ["color"]
    assert data["display"] == "#000000"
    assert data["manufacturable"] is False


def test_a_material_says_the_colour_it_claims_and_its_physical_facts(ctx):
    data = _declaration(ctx, "material", "alu")

    assert data["colorClaim"] == "//cmf:natural"
    # Drawn in what it claims, having no look of its own.
    assert data["display"] == "#A8A9AD"
    assert data["facts"] == {"Full": "Aluminium 6061-T6", "Density": "2700 kg/m^3"}


def test_a_finish_says_how_it_looks_and_draws_no_colour(ctx):
    data = _declaration(ctx, "finish", "satin")

    assert (data["roughness"], data["metallic"]) == (pytest.approx(0.6), 0.0)
    assert "display" not in data
    assert data["desc"] == "Satin, VDI 3400 Ref 27"


# ------------------------------------------------- a part's and an assembly's tab


@pytest.fixture
def built(monkeypatch):
    """Every part 'built' with the summary given for it here, and nothing actually built."""
    summaries = {}

    async def get_wrapped(self, ctx):
        self._metadata = {shape_envelope.METADATA_CMF: summaries[self.name]} if self.name in summaries else {}
        return object()

    monkeypatch.setattr(Part, "get_wrapped", get_wrapped)
    return summaries


def test_a_part_s_tab_is_its_one_item(ctx, built):
    built["red-box"] = _summary(
        CmfSet(color="//cmf:red", material="//cmf:alu", rgba=(201, 26, 9, 1.0), origin="declared")
    )

    report = asyncio.run(cmf.report_async(ctx, ctx.get_part("//cmf:red-box")))

    ((item,),) = [report["items"]]
    assert item["name"] == "//cmf:red-box"
    assert item["count"] == 1
    assert item["cmf"]["sets"][0]["color"] == "//cmf:red"
    assert item["findings"] == []


def test_an_assembly_s_tab_lists_what_it_holds_the_incomplete_first(ctx, built):
    built["red-box"] = _summary(CmfSet(color="//cmf:red", material="//cmf:alu", origin="declared"))
    built["plain"] = _summary(unspecified={"color": "all", "material": "all"})

    report = asyncio.run(cmf.report_async(ctx, ctx.get_assembly("//cmf:case")))

    assert [(item["name"], item["kind"], item["count"]) for item in report["items"]] == [
        # Says nothing: what keeps it from being made comes first.
        ("//cmf:plain", "part", 1),
        ("//cmf:red-box", "part", 2),
        # Bought whole, so judged by its own CMF and not looked inside.
        ("//cmf:kit", "assembly", 1),
    ]
    plain, red, kit = report["items"]
    assert plain["findings"] == ["no colour on any face", "no material on any solid"]
    assert red["findings"] == []
    assert kit["findings"] == []
    assert kit["cmf"]["sets"][0]["color"] == "//cmf:red"
    assert report["own"] == {"cmf": None, "findings": []}


def test_a_bought_part_is_not_required_to_say_and_says_why(ctx, built):
    report = asyncio.run(cmf.report_async(ctx, ctx.get_part("//cmf:bought")))

    (item,) = report["items"]
    assert item["findings"] == []
    assert "bought" in item["exempt"]


def test_an_item_that_does_not_build_costs_its_row(ctx, monkeypatch):
    async def nothing(self, ctx):
        return None

    monkeypatch.setattr(Part, "get_wrapped", nothing)

    (item,) = asyncio.run(cmf.report_async(ctx, ctx.get_part("//cmf:red-box")))["items"]

    assert item["error"] == "it did not build"
    assert item["cmf"] is None
