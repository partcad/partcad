#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'info.object' -- 'pc info' -- on a colour, a material or a finish.

Against a real context of packages written to a temporary directory, with
nothing built: a declaration needs no geometry. What is pinned here is which
names reach a declaration, which reach an object instead, and what is printed
for one: its configuration, and what it says of itself the way a part's
'Material' says it -- an alias as itself, with the facts of what it resolves to.
"""

import pytest
import yaml

import partcad as pc
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.events import EventEmitter
from partcad_service_json_rpc.core.session import Session

ROOT = {
    "import": {"sub": {"path": "sub"}},
    "colors": {
        "natural": {"display": "#A8A9AD"},
        # A colour and a finish of one name, as a vendor's package has them:
        # each kind of declaration keeps a namespace of its own.
        "Zinc-Plated": {"display": "#BCC4CC", "desc": "Clear zinc plating"},
    },
    "materials": {
        "steel-1018": {
            "formal": "AISI 1018",
            "full": "Low-carbon steel AISI 1018",
            "desc": "Mild steel",
            "url": "https://example.com/1018",
            "density": 7870,
            "youngsModulus": 2.0e11,
            "poissonsRatio": 0.29,
            "yieldStrength": 3.7e8,
            "thermalConductivity": 51.9,
            "mu": 0.6,
            "color": ":natural",
            "tags": ["metal", "weldable"],
            "aliases": ["mild-steel"],
        },
        "water": {"density": 999.1, "viscosity": 0.001138},
        "resin": {
            "parameters": {"density": {"type": "float", "default": 1100}},
            "full": "Resin at %density% kg/m^3",
            "density": "%density%",
        },
        "1018 Steel": {"type": "alias", "source": ":steel-1018", "desc": "What the vendor calls it"},
        "plain-steel": {"type": "alias", "source": ":steel-1018"},
        "nowhere": {"type": "alias", "source": "//missing:steel"},
        # The name of a part as well: a material keeps a namespace of its own.
        "bolt": {"density": 7900, "desc": "The material called bolt"},
    },
    "finishes": {"Zinc-Plated": {"desc": "Zinc plated", "display": {"roughness": 0.3, "metallic": 1}}},
    "parts": {"bolt": {"type": "basic", "cuboid": [1, 1, 1]}},
}

SUB = {
    "materials": {
        "water": {"density": 1000, "desc": "Fresh water"},
        "steel": {"type": "alias", "source": "//:1018 Steel"},
    },
}


class _Log:
    """What PartCAD logged, as the lines a client is sent."""

    def __init__(self):
        self.records = []

    def recorder(self, level):
        def record(msg, *args, **kwargs):
            self.records.append((level, str(msg) % args if args else str(msg)))

        return record

    def info(self):
        """The report: what 'info.object' prints, without the context's own progress lines."""
        return [
            message
            for level, message in self.records
            if level == "info" and not message.startswith(("DONE:", "Using the", "Cloning"))
        ]

    def errors(self):
        return [message for level, message in self.records if level == "error"]

    def facts(self):
        """The 'INFO:' lines of the report, as '{label: value as printed}'."""
        found = {}
        for line in self.info():
            if line.startswith("INFO: "):
                label, _, value = line[len("INFO: ") :].partition(": ")
                found[label] = value
        return found


@pytest.fixture
def session(tmp_path, monkeypatch):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(ROOT, sort_keys=False))
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "partcad.yaml").write_text(yaml.safe_dump(SUB, sort_keys=False))
    session = Session(EventEmitter(lambda event, payload: None))
    session.partcad = pc
    session.partcad_ctx = pc.Context(str(tmp_path))
    return session


@pytest.fixture
def log(monkeypatch):
    log = _Log()
    for level in ("info", "warning", "error"):
        monkeypatch.setattr(pc.logging, level, log.recorder(level))
    return log


def test_a_material_is_found_by_its_name_and_says_everything_it_states(session, log):
    operations.info_object(session, {"package": "//", "object": "steel-1018"})

    assert log.errors() == []
    lines = log.info()
    # Its configuration first, as an object's is printed, then what it says.
    assert lines[0].startswith("CONFIGURATION: ")
    assert "'density': 7870" in lines[0]
    assert log.facts() == {
        "Path": "'//'",
        "Name": "'steel-1018'",
        "Kind": "'material'",
        "Desc": "'Mild steel'",
        "Manufacturable": "'yes'",
        "Aliases": "'mild-steel'",
        "Url": "'https://example.com/1018'",
        "Color": "':natural'",
        "Formal": "'AISI 1018'",
        "Full": "'Low-carbon steel AISI 1018'",
        "Density": "'7870 kg/m^3'",
        "Youngs modulus": "'2e+11 Pa'",
        "Poissons ratio": "'0.29'",
        "Yield strength": "'3.7e+08 Pa'",
        "Thermal conductivity": "'51.9 W/(m*K)'",
        "Mu": "'0.6'",
        "Tags": "'metal, weldable'",
    }


@pytest.mark.parametrize("name", ["steel-1018", ":steel-1018", "//:steel-1018"])
def test_a_material_is_named_the_way_any_object_is(session, log, name):
    operations.info_object(session, {"package": "//", "object": name})

    assert log.facts()["Density"] == "'7870 kg/m^3'"


def test_a_material_of_another_package_is_named_by_its_package(session, log):
    operations.info_object(session, {"package": "//", "object": "//sub:water"})

    assert log.errors() == []
    assert log.facts()["Path"] == "'//sub'"
    assert log.facts()["Density"] == "'1000 kg/m^3'"


def test_a_fluid_says_its_viscosity(session, log):
    operations.info_object(session, {"package": "//", "object": "water"})

    assert log.facts()["Viscosity"] == "'0.001138 Pa*s'"


@pytest.mark.parametrize(
    "params, density",
    [
        ({"object": "resin;density=1250"}, "1250"),
        ({"object": "resin", "params": ["density=1300"]}, "1300"),
        # Named without values, a parametric declaration is its defaults.
        ({"object": "resin"}, "1100"),
    ],
)
def test_a_parametric_material_is_rendered_with_the_values_it_is_named_with(session, log, params, density):
    operations.info_object(session, {"package": "//", **params})

    assert log.errors() == []
    facts = log.facts()
    assert facts["Density"] == "'%s kg/m^3'" % density
    assert facts["Full"] == "'Resin at %s kg/m^3'" % density
    # The configuration printed is the instance's, with the value in it.
    assert "'default': %s" % density in log.info()[0]


def test_an_alias_is_shown_as_itself_with_the_facts_of_what_it_resolves_to(session, log):
    operations.info_object(session, {"package": "//", "object": ":1018 Steel"})

    assert log.errors() == []
    assert "'type': 'alias'" in log.info()[0]
    facts = log.facts()
    assert facts["Name"] == "'1018 Steel'"
    assert facts["Alias of"] == "':steel-1018'"
    assert facts["Resolves to"] == "'//:steel-1018'"
    # Its own description, where it gives one; everything else is what it names.
    assert facts["Desc"] == "'What the vendor calls it'"
    assert facts["Density"] == "'7870 kg/m^3'"
    assert facts["Youngs modulus"] == "'2e+11 Pa'"
    assert facts["Formal"] == "'AISI 1018'"


def test_an_alias_without_a_description_has_the_one_of_what_it_names(session, log):
    operations.info_object(session, {"package": "//", "object": "plain-steel"})

    assert log.facts()["Desc"] == "'Mild steel'"


def test_a_chain_of_aliases_resolves_to_where_it_ends(session, log):
    operations.info_object(session, {"package": "//", "object": "//sub:steel"})

    facts = log.facts()
    assert facts["Path"] == "'//sub'"
    assert facts["Alias of"] == "'//:1018 Steel'"
    assert facts["Resolves to"] == "'//:steel-1018'"
    assert facts["Density"] == "'7870 kg/m^3'"


def test_an_alias_that_resolves_to_nothing_says_why(session, log):
    operations.info_object(session, {"package": "//", "object": "nowhere"})

    facts = log.facts()
    assert facts["Alias of"] == "'//missing:steel'"
    assert "Density" not in facts
    assert "resolves to nothing" in facts["Errors"]
    assert "'//missing'" in facts["Errors"]


def test_a_name_a_declaration_lists_among_its_aliases_is_that_declaration(session, log):
    operations.info_object(session, {"package": "//", "object": "mild-steel"})

    assert log.facts()["Name"] == "'steel-1018'"


def test_a_name_nothing_has_is_not_found_as_a_missing_object_is(session, log):
    operations.info_object(session, {"package": "//", "object": "unobtainium"})

    assert log.info() == []
    assert log.errors()[-1] == "Object //:unobtainium not found"


@pytest.mark.parametrize("flag", ["material", "color", "finish"])
def test_a_declaration_a_flag_names_that_is_not_there_is_not_found_either(session, log, flag):
    operations.info_object(session, {"package": "//", "object": "unobtainium", flag: True})

    assert log.info() == []
    assert log.errors() == [
        "The %s 'unobtainium' is not found in '//'" % flag,
        "Object //:unobtainium not found",
    ]


def test_a_name_an_object_has_is_that_object_and_a_flag_reaches_the_material(session, log, monkeypatch):
    """The part keeps its name: a material is looked for only where no object has the name."""
    asked = []

    class Part:
        config = {"type": "basic"}

        def info(self):
            return {"Volume": 1.0}

    def get_part(path, *args, **kwargs):
        asked.append(path)
        return Part()

    # Stood in for, so that nothing is built: what is pinned is which one is asked.
    monkeypatch.setattr(session.partcad_ctx, "get_part", get_part)

    operations.info_object(session, {"package": "//", "object": "bolt"})
    assert asked == ["//:bolt"]
    assert log.facts() == {"Volume": "1.0"}

    log.records.clear()
    operations.info_object(session, {"package": "//", "object": "bolt", "material": True})
    assert asked == ["//:bolt"]
    assert log.facts()["Kind"] == "'material'"
    assert log.facts()["Desc"] == "'The material called bolt'"


def test_a_name_a_colour_and_a_finish_share_is_both_each_under_its_kind(session, log):
    operations.info_object(session, {"package": "//", "object": "Zinc-Plated"})

    lines = log.info()
    assert lines[0] == "COLOR: //:Zinc-Plated"
    assert "INFO: Display: '#BCC4CC'" in lines
    finish = lines.index("FINISH: //:Zinc-Plated")
    assert "INFO: Display: 'roughness 0.3, metallic 1'" in lines[finish:]
    assert "INFO: Kind: 'color'" in lines[:finish]
    assert "INFO: Kind: 'finish'" in lines[finish:]


@pytest.mark.parametrize("flag, other", [("color", "finish"), ("finish", "color")])
def test_a_flag_says_which_of_them_is_meant(session, log, flag, other):
    operations.info_object(session, {"package": "//", "object": "Zinc-Plated", flag: True})

    lines = log.info()
    # One report, so no heading.
    assert lines[0].startswith("CONFIGURATION: ")
    assert "INFO: Kind: '%s'" % flag in lines
    assert "INFO: Kind: '%s'" % other not in lines


def test_a_walk_reports_the_material_of_that_name_of_every_package_below(session, log):
    operations.info_object(session, {"package": "//", "object": "...:water"})

    assert log.errors() == []
    lines = log.info()
    assert [line for line in lines if line.startswith("MATERIAL: ")] == ["MATERIAL: //:water", "MATERIAL: //sub:water"]
    assert "INFO: Desc: 'Fresh water'" in lines


def test_a_walk_with_a_flag_keeps_to_that_kind(session, log):
    operations.info_object(session, {"package": "//", "object": "...:Zinc-Plated", "finish": True})

    assert [line for line in log.info() if line.endswith(":Zinc-Plated")] == ["FINISH: //:Zinc-Plated"]


def test_a_kind_flag_of_an_object_is_still_taken_at_its_word(session, log, monkeypatch):
    """'-s' on a material's name asks for a sketch, and finds none: the flags of objects are unchanged."""
    asked = []
    monkeypatch.setattr(session.partcad_ctx, "get_sketch", lambda path, *a, **k: asked.append(path))

    operations.info_object(session, {"package": "//", "object": "water", "sketch": True})

    assert asked == ["//:water"]
    assert log.errors()[-1] == "Object //:water not found"
