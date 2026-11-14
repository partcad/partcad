#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Computed and stacked CMF declarations (docs/source/config_cmf.rst, "Parametric declarations").

A catalogue states a grade of a material by what it is made of - a butadiene
fraction, a temper - and works its numbers and its colour out of that; a
declaration of its own made from another ('type: enrich') names one grade, and
may have parameters of its own that it maps onto its source's. Pinned here:

* a material's numbers may be expressions, and what they come to is held to
  the range the schema gives a number written out;
* an enrich is its own declaration under its own name, with every field of the
  instance it is made from but what names that one (its ids and aliases), its
  references made absolute where the source wrote them, and its own fields on
  top;
* enriches stack, and a chain of them that leads back to itself is reported
  rather than waited on;
* an enrich's ids are its own, for a converter to find it by.
"""

import threading
import types

import jsonschema
import pytest
import yaml

import partcad as pc
import partcad.logging as pc_logging
from partcad import cmf, cmf_conventions
from partcad import material as pc_material
from partcad.lint.all import get_partcad_schema

VENDOR = {
    "colors": {
        "natural": {"display": "#A8A9AD"},
        "brass": {
            "parameters": {"zinc": {"type": "float", "default": 0.3, "min": 0.05, "max": 0.4}},
            "display": "%interpolate_color(zinc, [0.05, 0.4], ['#B87333', '#E1C16E'])%",
            "manufacturable": False,
        },
        "shown-natural": {"display": ":natural"},
    },
    "materials": {
        "al-6061": {
            "parameters": {"temper": {"type": "string", "default": "T6", "enum": ["O", "T4", "T6"]}},
            "full": "Aluminium 6061-%temper%",
            "desc": "Aluminium 6061",
            "url": "https://example.com/6061",
            "density": 2700,
            "yieldStrength": "%pick(temper, ['O', 'T4', 'T6'], [55e6, 145e6, 276e6])%",
            "color": ":natural",
            "ids": {"step": "AL6061"},
            "aliases": ["aa6061"],
            "tags": ["machinable"],
        },
        "abs": {
            "parameters": {"butadiene": {"type": "float", "default": 0.2, "min": 0.05, "max": 0.3}},
            "full": "Acrylonitrile Butadiene Styrene",
            "density": "%1040 + 100 * butadiene%",
            "display": ":natural",
        },
        "abs-alias": {"type": "alias", "source": ":abs;butadiene=0.1"},
    },
}

ROOT = {
    "dependencies": {"vendor": {"type": "local", "path": "vendor"}},
    "colors": {
        "warm": {"type": "enrich", "source": "//vendor:brass", "with": {"zinc": 0.4}, "ids": {"ldraw": "334"}},
    },
    "finishes": {
        "satin": {"desc": "Satin", "display": {"roughness": 0.6, "metallic": 0}, "ids": {"vdi3400": "27"}},
        "satin-again": {"type": "enrich", "source": ":satin", "desc": "Satin, as Acme calls it"},
    },
    "materials": {
        "t4": {
            "type": "enrich",
            "source": "//vendor:al-6061",
            "with": {"temper": "T4"},
            "desc": "Aluminium 6061 in the T4 temper",
        },
        "t4-acme": {"type": "enrich", "source": ":t4", "ids": {"acme": "A-6061-T4"}, "density": 2710},
        "abs-high-impact": {
            "type": "enrich",
            "source": "//vendor:abs",
            "parameters": {
                "izod": {"type": "float", "default": 30, "min": 15, "max": 45, "desc": "notched Izod, kJ/m^2"}
            },
            "with": {"butadiene": "%round(interpolate(izod, [15, 45], [0.15, 0.25]), 3)%"},
            "desc": "ABS, %izod% kJ/m^2 notched Izod",
        },
        "through-alias": {"type": "enrich", "source": "//vendor:abs-alias"},
        "loop-a": {"type": "enrich", "source": ":loop-b"},
        "loop-b": {"type": "enrich", "source": ":loop-a"},
        "nowhere": {"type": "enrich", "source": ":nothing"},
        "too-much": {
            "type": "enrich",
            "source": "//vendor:abs",
            "with": {"butadiene": 0.9},
            "aliases": ["too-much-butadiene"],
        },
        "through-too-much": {"type": "enrich", "source": ":too-much-butadiene"},
        "heavy": {
            "parameters": {"k": {"type": "float", "default": 1}},
            "density": "%1000 - 2000 * k%",
        },
        "unreadable": {"density": "%1000 * nothing%"},
        "exponent": {"youngsModulus": "69e9"},
    },
}


@pytest.fixture(autouse=True)
def _no_errors_left_behind():
    yield
    pc_logging.reset_errors()


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "partcad.yaml").write_text(yaml.safe_dump(VENDOR))
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(ROOT))
    return pc.Context(str(tmp_path))


def _get(ctx, kind, name, package="//"):
    return ctx.get_project(package).get_cmf(kind, name, quiet=True)


def _failure(ctx, kind, name, package="//"):
    return ctx.get_project(package).cmf_failure(kind, name)


# --------------------------------------------------------------------------- #
# Computed numbers                                                            #
# --------------------------------------------------------------------------- #


def test_a_material_s_numbers_may_be_computed(ctx):
    assert _get(ctx, "material", "abs", "//vendor").density == 1060
    assert _get(ctx, "material", "abs;butadiene=0.3", "//vendor").density == pytest.approx(1070)
    assert _get(ctx, "material", "al-6061;temper=O", "//vendor").yield_strength == 55e6


def test_a_computed_number_outside_its_range_refuses_that_instance(ctx):
    """Named with the field, the value and the instance: a negative density is never handed on."""
    assert _get(ctx, "material", "heavy;k=0.25").density == 500
    assert _get(ctx, "material", "heavy") is None
    assert _failure(ctx, "material", "heavy") == (
        "The material '//:heavy' cannot be used: its 'density' is -1000, and has to be above 0"
    )


def test_an_expression_that_cannot_be_evaluated_is_no_number(ctx):
    """'expr.resolve' leaves it the text it was written as, and text is not a density."""
    assert _get(ctx, "material", "unreadable") is None
    assert "its 'density' is '%1000 * nothing%', which is text and not a number" in _failure(
        ctx, "material", "unreadable"
    )


def test_a_number_yaml_reads_as_text_is_still_that_number(ctx):
    """YAML 1.1 reads '69e9' as text; a material that wrote it was read at 69e9 before, and still is."""
    exponent = _get(ctx, "material", "exponent")
    assert exponent is not None
    assert exponent.youngs_modulus == 69e9
    assert exponent.config["youngsModulus"] == 69e9


def test_the_ranges_are_the_schema_s():
    """One range per number, written twice - here and in the schema - and held together here."""
    properties = get_partcad_schema()["definitions"]["materials"]["patternProperties"]["^\\S(?:.*\\S)?$"]["oneOf"]
    declared = next(branch for branch in properties if branch.get("type") == "object")["properties"]
    for key, bounds in pc_material.NUMBERS.items():
        number, expression = declared[key]["oneOf"]
        assert {k: v for k, v in number.items() if k != "type"} == bounds, key
        assert expression == {"$ref": "#/definitions/expression"}


@pytest.mark.parametrize("density", ["%1040 + 100 * b%", 1040, 1040.5])
def test_the_schema_takes_a_number_or_an_expression(density):
    jsonschema.validate({"materials": {"m": {"density": density}}}, get_partcad_schema())


@pytest.mark.parametrize("density", ["1040", "heavy", "%a% and %b%", 0, -1])
def test_the_schema_refuses_anything_else(density):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"materials": {"m": {"density": density}}}, get_partcad_schema())


def test_the_schema_takes_everything_above():
    jsonschema.validate(VENDOR, get_partcad_schema())
    # All but the one number YAML reads as text, which is there to be refused.
    root = {**ROOT, "materials": {k: v for k, v in ROOT["materials"].items() if k != "exponent"}}
    jsonschema.validate(root, get_partcad_schema())


@pytest.mark.parametrize(
    "declaration",
    [
        {"type": "enrich"},  # names nothing
        {"source": ":x", "with": {"a": 1}},  # 'with' is an enrich's
        {"type": "alias", "source": ":x", "with": {"a": 1}},  # an alias names its values in its 'source'
        {"type": "enrich", "source": ":x", "with": {"a": "b,c"}},  # a value a name cannot spell
        {"type": "inherit", "source": ":x"},
    ],
)
def test_the_schema_refuses_an_enrich_that_is_not_one(declaration):
    for section in ("colors", "materials", "finishes"):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({section: {"x": declaration}}, get_partcad_schema())


# --------------------------------------------------------------------------- #
# Enrich                                                                      #
# --------------------------------------------------------------------------- #


def test_an_enrich_is_its_own_declaration_under_its_own_name(ctx):
    t4 = _get(ctx, "material", "t4")
    assert t4.reference() == "//:t4"
    assert t4.enriches == "//vendor:al-6061;temper=T4"
    # Canonical as itself: a reference to it is not rewritten into its source's.
    assert cmf.canonical(ctx, "material", ":t4", "//") == "//:t4"


def test_an_enrich_takes_its_source_instance_s_fields(ctx):
    t4 = _get(ctx, "material", "t4")
    assert t4.full == "Aluminium 6061-T4"  # rendered by the source, with the enrich's 'with'
    assert t4.yield_strength == 145e6
    assert t4.density == 2700
    assert t4.url == "https://example.com/6061"
    assert t4.tags == ["machinable"]


def test_an_enrich_does_not_take_what_names_its_source(ctx):
    """Its ids and aliases are the source's names, and its parameters and 'type' make the source a template."""
    t4 = _get(ctx, "material", "t4")
    assert t4.ids == {}
    assert t4.aliases == []
    assert "parameters" not in t4.config
    assert t4.config["type"] == "enrich"


def test_an_enrich_s_own_fields_win(ctx):
    assert _get(ctx, "material", "t4").desc == "Aluminium 6061 in the T4 temper"
    acme = _get(ctx, "material", "t4-acme")
    assert acme.density == 2710
    assert acme.ids == {"acme": "A-6061-T4"}


def test_an_inherited_reference_names_what_it_named_where_the_source_wrote_it(ctx):
    """The vendor's ':natural' is the vendor's, read from the enrich's package or any other."""
    t4 = _get(ctx, "material", "t4")
    assert t4.color_claim == "//vendor:natural"
    assert cmf.display(ctx, t4) == (0xA8, 0xA9, 0xAD, 1.0)
    abs_hi = _get(ctx, "material", "abs-high-impact")
    assert abs_hi.display_text == "//vendor:natural"


def test_an_enrich_s_own_parameters_are_rendered_into_what_it_asks_for(ctx):
    """That is what stacks: a toughness of its own, mapped onto its source's composition."""
    default = _get(ctx, "material", "abs-high-impact")
    assert default.reference() == "//:abs-high-impact"
    assert default.enriches == "//vendor:abs;butadiene=0.2"
    assert default.density == pytest.approx(1060)
    assert default.desc == "ABS, 30 kJ/m^2 notched Izod"

    tough = _get(ctx, "material", "abs-high-impact;izod=45")
    assert tough.reference() == "//:abs-high-impact;izod=45"
    assert tough.enriches == "//vendor:abs;butadiene=0.25"
    assert tough.density == pytest.approx(1065)


def test_an_enrich_s_own_bounds_hold(ctx):
    assert _get(ctx, "material", "abs-high-impact;izod=50") is None
    assert _failure(ctx, "material", "abs-high-impact;izod=50") == (
        "The parameter 'izod' of '//:abs-high-impact' cannot be 50: its 'max' is 45"
    )


def test_an_enrich_asking_its_source_for_what_it_refuses_says_so(ctx):
    assert _get(ctx, "material", "too-much") is None
    assert _failure(ctx, "material", "too-much") == (
        "is an enrich of '//vendor:abs;butadiene=0.9', which cannot be made: "
        "The parameter 'butadiene' of '//vendor:abs' cannot be 0.9: its 'max' is 0.3"
    )


def test_why_one_cannot_be_made_is_said_by_any_name_it_has(ctx):
    """One of its 'aliases:' is the declaration, and so is the reason it cannot be made."""
    why = (
        "is an enrich of '//vendor:abs;butadiene=0.9', which cannot be made: "
        "The parameter 'butadiene' of '//vendor:abs' cannot be 0.9: its 'max' is 0.3"
    )
    assert _get(ctx, "material", "too-much-butadiene") is None
    assert _failure(ctx, "material", "too-much-butadiene") == why
    assert (
        cmf.why_unresolved(ctx, "material", ":too-much-butadiene", "//")
        == "'//:too-much-butadiene' cannot be made: " + why
    )
    # And an enrich made from it says that, rather than that there is no such material.
    assert _get(ctx, "material", "through-too-much") is None
    assert _failure(ctx, "material", "through-too-much") == (
        "is an enrich of '//:too-much-butadiene', which cannot be made: " + why
    )


def test_an_enrich_of_nothing_says_why(ctx):
    assert _get(ctx, "material", "nowhere") is None
    assert (
        _failure(ctx, "material", "nowhere") == "is an enrich of '//:nothing', and '//' declares no material 'nothing'"
    )


def test_an_enrich_of_an_enrich(ctx):
    acme = _get(ctx, "material", "t4-acme")
    assert acme.enriches == "//:t4"
    assert acme.desc == "Aluminium 6061 in the T4 temper"
    assert acme.yield_strength == 145e6
    assert acme.color_claim == "//vendor:natural"


def test_an_enrich_follows_an_alias_to_what_it_names(ctx):
    found = _get(ctx, "material", "through-alias")
    assert found.enriches == "//vendor:abs;butadiene=0.1"
    assert found.density == pytest.approx(1050)


def test_a_colour_and_a_finish_are_enriched_the_same_way(ctx):
    warm = _get(ctx, "color", "warm")
    assert warm.enriches == "//vendor:brass;zinc=0.4"
    assert warm.display_text == "#E1C16E"
    assert warm.manufacturable is False  # taken from the source, as every field is
    assert warm.ids == {"ldraw": "334"}

    satin = _get(ctx, "finish", "satin-again")
    assert satin.enriches == "//:satin"
    assert (satin.roughness, satin.metallic) == (0.6, 0.0)
    assert satin.desc == "Satin, as Acme calls it"
    assert satin.ids == {}


def test_a_display_naming_a_colour_is_made_absolute_too(tmp_path):
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "partcad.yaml").write_text(yaml.safe_dump(VENDOR))
    root = {
        "dependencies": {"vendor": {"type": "local", "path": "vendor"}},
        "colors": {"natural": {"display": "#000000"}, "mine": {"type": "enrich", "source": "//vendor:shown-natural"}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(root))
    ctx = pc.Context(str(tmp_path))
    mine = _get(ctx, "color", "mine")
    # The vendor's 'natural', and not this package's black one of the same name.
    assert mine.display_text == "//vendor:natural"
    assert cmf.display(ctx, mine) == (0xA8, 0xA9, 0xAD, 1.0)


def test_an_enrich_of_itself_is_reported_and_does_not_wait_on_itself(ctx, caplog):
    """A chain of enriches that leads back to where it started is an error, not a hang."""
    answers = {}

    def ask(name):
        answers[name] = ctx.get_project("//").get_cmf("material", name)

    threads = [threading.Thread(target=ask, args=(name,), daemon=True) for name in ("loop-a", "loop-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a loop of enriches waited on itself"
    assert answers == {"loop-a": None, "loop-b": None}
    assert _failure(ctx, "material", "loop-a") == (
        "The material '//:loop-a' is an enrich that leads back to itself: //:loop-a -> //:loop-b -> //:loop-a"
    )
    assert pc_logging.had_errors


def test_an_alias_of_an_enrich_made_from_that_alias_is_a_loop_and_does_not_wait_on_itself(tmp_path):
    """Asked for by the alias: the enrich it names asks for the alias again, on the same thread.

    Not under the alias's lock, which a thread would wait on itself for: the
    enrich's own loop check is what answers.
    """
    materials = {"self-named": {"type": "enrich", "source": ":also", "aliases": ["also"]}}
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"materials": materials}))
    project = pc.Context(str(tmp_path)).get_project("//")
    answers = {}
    asking = threading.Thread(
        target=lambda: answers.setdefault("also", project.get_cmf("material", "also", quiet=True)), daemon=True
    )
    asking.start()
    asking.join(timeout=60)
    assert not asking.is_alive(), "asking for an alias waited on its own lock"
    assert answers == {"also": None}
    assert project.cmf_failure("material", "self-named") == (
        "The material '//:self-named' is an enrich that leads back to itself: //:self-named -> //:self-named"
    )


def test_an_enrich_of_a_name_holding_a_reserved_character_is_made_from_that_declaration(tmp_path):
    """':a%3Bb' names the declaration 'a;b' whether or not 'with:' adds values: not 'a' with a value 'b'."""
    materials = {
        "a;b": {"parameters": {"k": {"type": "float", "default": 1}}, "density": "%1000 * k%"},
        "plain": {"type": "enrich", "source": ":a%3Bb"},
        "given": {"type": "enrich", "source": ":a%3Bb", "with": {"k": 2}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"materials": materials}))
    ctx = pc.Context(str(tmp_path))
    assert cmf.enrich_source_reference(":a%3Bb", {}, "//") == "//:a%3Bb"
    plain = _get(ctx, "material", "plain")
    assert (plain.enriches, plain.density) == ("//:a%3Bb", pytest.approx(1000))
    given = _get(ctx, "material", "given")
    assert (given.enriches, given.density) == ("//:a%3Bb;k=2", pytest.approx(2000))


def test_an_enrich_is_made_when_it_is_first_asked_for(ctx):
    """Not as its package loads: it may be made from a package nothing else loads."""
    project = ctx.get_project("//")
    assert "t4" not in project.materials
    assert project.get_material("t4") is _get(ctx, "material", "t4")
    assert "t4" in project.materials


def test_info_says_what_an_enrich_is_made_from(ctx):
    info = _get(ctx, "material", "t4").info()
    assert info["Enriches"] == "//vendor:al-6061;temper=T4"
    assert info["Desc"] == "Aluminium 6061 in the T4 temper"
    assert info["Color"] == "//vendor:natural"
    assert _get(ctx, "color", "warm").cmf_info()["Enriches"] == "//vendor:brass;zinc=0.4"
    # And the IDE's CMF tab, which shows what 'pc info' says.
    data = cmf.declaration_data(ctx, _get(ctx, "material", "t4"))
    assert data["reference"] == "//:t4"
    assert data["facts"]["Enriches"] == "//vendor:al-6061;temper=T4"


def test_an_enrich_lends_what_its_material_says(ctx):
    """What a part made of it weighs and is analysed with: the enrich's own numbers, inherited or stated."""
    assert pc_material.physics_of(_get(ctx, "material", "t4-acme")) == {"density": 2710}
    assert pc_material.analysis_of(_get(ctx, "material", "t4"))["yield_strength"] == 145e6


def test_the_explorer_lists_an_enrich_without_loading_its_source_s_package(ctx):
    from partcad_service_json_rpc.core import operations

    session = types.SimpleNamespace(emitter=types.SimpleNamespace(warning=lambda message: None))
    project = ctx.get_project("//")
    items = {item["name"]: item for item in operations._cmf_items(session, project, "material")}
    assert items["t4"] == {
        "name": "t4",
        "type": "enrich",
        "desc": "Aluminium 6061 in the T4 temper",
        "manufacturable": True,
    }
    # Nor through one of its own enriches made from it: described by what it says.
    assert items["t4-acme"] == {"name": "t4-acme", "type": "enrich", "desc": "enrich of :t4", "manufacturable": True}
    assert "t4" not in project.materials and "t4-acme" not in project.materials
    assert "//vendor" not in ctx.projects
    _get(ctx, "material", "t4")
    assert "//vendor" in ctx.projects  # which is what made it worth not doing
    # One made from its own package's declarations alone is made, and described by what it is.
    finishes = {item["name"]: item for item in operations._cmf_items(session, project, "finish")}
    assert finishes["satin-again"] == {
        "name": "satin-again",
        "type": "enrich",
        "desc": "Satin, as Acme calls it",
        "manufacturable": True,
    }
    assert "satin-again" in project.finishes


def test_the_explorer_neither_renders_nor_follows_an_alias_into_another_package(tmp_path):
    """A source an expression gives is known only once it is made, and an alias is the declaration listing it."""
    from partcad_service_json_rpc.core import operations

    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "partcad.yaml").write_text(yaml.safe_dump(VENDOR))
    root = {
        "dependencies": {"vendor": {"type": "local", "path": "vendor"}},
        "materials": {
            "picked": {
                "type": "enrich",
                "source": "%grade%",
                "parameters": {"grade": {"type": "string", "default": "//vendor:abs"}},
            },
            "far": {"type": "enrich", "source": "//vendor:abs", "aliases": ["far-alias"]},
            "near": {"type": "enrich", "source": ":far-alias"},
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(root))
    ctx = pc.Context(str(tmp_path))
    session = types.SimpleNamespace(emitter=types.SimpleNamespace(warning=lambda message: None))
    items = {item["name"]: item for item in operations._cmf_items(session, ctx.get_project("//"), "material")}
    assert items["picked"] == {"name": "picked", "type": "enrich", "desc": "enrich of %grade%", "manufacturable": True}
    assert items["near"] == {"name": "near", "type": "enrich", "desc": "enrich of :far-alias", "manufacturable": True}
    assert "//vendor" not in ctx.projects
    # And each is what it names once it is made.
    assert _get(ctx, "material", "picked").density == pytest.approx(1060)
    assert _get(ctx, "material", "near").density == pytest.approx(1060)


# --------------------------------------------------------------------------- #
# What a converter finds an enrich by                                         #
# --------------------------------------------------------------------------- #


def test_an_enrich_s_ids_are_its_own_and_a_converter_finds_it_by_them(ctx):
    """How a converter's package (LDraw's) gives a catalogue's values its own system's numbers."""
    assert cmf_conventions.reference_for(ctx, "//", "color", "334", convention="ldraw") == "//:warm"
    # And one id names one declaration: the source's 'step' id is not the enrich's.
    vendor_found = cmf_conventions.reference_for(ctx, "//vendor", "material", "al6061", convention="step")
    assert vendor_found == "//vendor:al-6061"
    assert cmf_conventions.reference_for(ctx, "//", "material", "al6061", convention="step") is None


def test_an_inherited_image_is_read_where_its_source_keeps_it(tmp_path):
    """A texture is a file of the package that declares it, and an enrich elsewhere draws with that one."""
    import io

    from PIL import Image

    (tmp_path / "vendor" / "textures").mkdir(parents=True)
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (92, 58, 33)).save(out, "PNG")
    (tmp_path / "vendor" / "textures" / "walnut.png").write_bytes(out.getvalue())
    (tmp_path / "vendor" / "partcad.yaml").write_text(
        yaml.safe_dump({"colors": {"walnut": {"display": {"image": "textures/walnut.png", "size": 300}}}})
    )
    root = {
        "dependencies": {"vendor": {"type": "local", "path": "vendor"}},
        "colors": {"veneer": {"type": "enrich", "source": "//vendor:walnut", "ids": {"acme": "WV-12"}}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(root))
    ctx = pc.Context(str(tmp_path))
    veneer = _get(ctx, "color", "veneer")
    texture = cmf.texture_of(ctx, veneer)
    assert texture is not None and texture.name == "textures/walnut.png"
    assert cmf.display(ctx, veneer) == (92, 58, 33, 1.0)
    assert veneer.errors == []
