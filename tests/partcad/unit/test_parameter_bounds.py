#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'min' and 'max' on a numeric parameter, of every kind of object that has parameters.

A parametric declaration is only as good as the range its model holds over: a
material's density interpolated between two measured grades is a guess past
them, and a part's hole pattern has a smallest plate it fits. So an 'int' or a
'float' parameter may state its range, both ends included, and a value outside
it is refused wherever it comes from - a reference, the user's override, the
default itself - naming the parameter, the value, the bound and the object.
Pinned here for a part, an interface's construction parameter and a CMF
declaration, and for what 'pc lint' says of a declaration before anything
loads it. A declared 'enum' is held the same way: a value that is not one of
those it lists is refused with them named.
"""

import pytest
import yaml

import partcad as pc
import partcad.logging as pc_logging
from partcad import config as pc_config
from partcad_utils import parameters
from partcad_utils.assy_lint import CODE_PARAMETERS, PARTCAD_SCHEMA, get_schema, validate_source
from partcad_utils.user_config import UserConfig, user_config

PACKAGE = {
    "parts": {
        "plate": {
            "type": "basic",
            "cuboid": ["%holes * 10%", "%width%", "%thickness%"],
            "parameters": {
                "holes": {"type": "int", "default": 3, "min": 1, "max": 10},
                "width": {"type": "float", "default": 20.0, "min": 5, "max": 100},
                # Bounded at one end only.
                "thickness": {"type": "float", "default": 2.0, "min": 0.5},
            },
        },
        "bolt": {
            "type": "basic",
            "cuboid": 1,
            "parameters": {
                "finish": {"type": "string", "default": "plain", "enum": ["plain", "zinc"]},
                "size": {"type": "int", "default": 3, "enum": ["3", "4"]},
            },
        },
        "gold-bolt": {
            "type": "basic",
            "cuboid": 1,
            "parameters": {"finish": {"type": "string", "default": "gold", "enum": ["plain", "zinc"]}},
        },
        "too-wide": {
            "type": "basic",
            "cuboid": 1,
            "parameters": {"width": {"type": "float", "default": 200.0, "max": 100}},
        },
    },
    "interfaces": {
        "m-hole": {
            # A construction parameter states its type, and with it may state a
            # range: it is no freedom of movement for having one.
            "parameters": {
                "size": {"type": "float", "default": 3.0, "min": 1.6, "max": 30},
                "head": {"type": "string", "default": "flat", "enum": ["flat", "round"]},
                "slide": {"dir": [1, 0, 0], "min": 0, "max": 5},
            },
        },
    },
    "materials": {
        "steel-4340": {
            "parameters": {
                "condition": {"type": "string", "default": "quenched-and-tempered", "enum": ["quenched-and-tempered"]}
            },
            "density": 7850,
        },
        "abs": {
            "parameters": {"butadiene": {"type": "float", "default": 0.2, "min": 0.05, "max": 0.3}},
            "density": "%1040 + 100 * butadiene%",
        },
    },
}


@pytest.fixture(autouse=True)
def _no_errors_left_behind():
    yield
    pc_logging.reset_errors()


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    return pc.Context(str(tmp_path))


# --------------------------------------------------------------------------- #
# The rule, as both ends read it                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "declaration, value, says",
    [
        ({"type": "int", "min": 1, "max": 10}, 11, "cannot be 11: its 'max' is 10"),
        ({"type": "int", "min": 1, "max": 10}, 0, "cannot be 0: its 'min' is 1"),
        ({"type": "float", "min": 0.05, "max": 0.3}, 0.31, "cannot be 0.31: its 'max' is 0.3"),
        # A declaration with no type is a float, and is bounded as one.
        ({"min": 15.0}, 14.5, "cannot be 14.5: its 'min' is 15"),
    ],
)
def test_a_value_outside_the_range_is_named_with_the_bound_it_breaks(declaration, value, says):
    problem = parameters.bound_problem(declaration, value, "p", "//pkg:thing")
    assert problem == "The parameter 'p' of '//pkg:thing' " + says


@pytest.mark.parametrize("value", [1, 10, 5.5])
def test_the_ends_are_in_the_range(value):
    assert parameters.bound_problem({"type": "float", "min": 1, "max": 10}, value, "p", "x") is None


def test_a_default_outside_the_range_says_it_is_the_default():
    problems = parameters.declaration_problems({"type": "int", "default": 30, "max": 10}, "n", "//pkg:thing")
    assert problems == ["The parameter 'n' of '//pkg:thing' defaults to 30, and its 'max' is 10"]


@pytest.mark.parametrize(
    "declaration, says",
    [
        ({"type": "string", "default": "a", "min": 1}, "is a string, and only an int or a float"),
        ({"type": "array", "default": [1], "max": 3}, "is an array, and only an int or a float"),
        ({"type": "float", "min": "1"}, "The 'min' of the parameter 'p' of 'x' is '1', not a number"),
        ({"type": "float", "min": 5, "max": 1}, "has a 'min' of 5 above its 'max' of 1"),
    ],
)
def test_bounds_that_cannot_hold_are_refused(declaration, says):
    (problem,) = parameters.declaration_problems(declaration, "p", "x")
    assert says in problem


def test_a_construction_parameter_states_its_type_and_may_then_state_a_range():
    """An interface's 'parameters:' holds both kinds, and 'min'/'max' alone still means a freedom of movement."""
    assert not parameters.is_movement_parameter("size", {"type": "float", "default": 3, "min": 1})
    assert not parameters.is_movement_parameter("n", {"type": "int", "max": 4})
    assert parameters.is_movement_parameter("slide", {"dir": [1, 0, 0], "min": 0, "max": 5})
    assert parameters.is_movement_parameter("slide", {"type": "move", "dir": [1, 0, 0], "min": 0})
    # The six names are movement whatever they say.
    assert parameters.is_movement_parameter("moveX", {"type": "float", "min": 0})


# --------------------------------------------------------------------------- #
# A part                                                                      #
# --------------------------------------------------------------------------- #


def test_a_value_in_the_range_makes_the_instance(ctx):
    assert ctx.get_part("//:plate;holes=10,width=5") is not None
    assert ctx.get_part("//:plate;thickness=0.5") is not None
    assert not pc_logging.had_errors


@pytest.mark.parametrize(
    "reference, says",
    [
        ("//:plate;holes=11", "The parameter 'holes' of 'plate;holes=11' cannot be 11: its 'max' is 10"),
        ("//:plate;holes=0", "The parameter 'holes' of 'plate;holes=0' cannot be 0: its 'min' is 1"),
        ("//:plate;width=4.5", "The parameter 'width' of 'plate;width=4.5' cannot be 4.5: its 'min' is 5"),
        (
            "//:plate;thickness=0.1",
            "The parameter 'thickness' of 'plate;thickness=0.1' cannot be 0.1: its 'min' is 0.5",
        ),
    ],
)
def test_a_value_outside_the_range_costs_that_instance(ctx, reference, says):
    assert ctx.get_part(reference) is None
    _base, instance = reference.split(":", 1)
    assert ctx.get_project("//").get_broken_object_reason("part", instance) == says
    # And nothing else: the declaration and its other instances are as they were.
    assert ctx.get_part("//:plate") is not None


def test_a_default_outside_the_range_refuses_the_object(ctx):
    assert ctx.get_part("//:too-wide") is None
    assert "defaults to 200, and its 'max' is 100" in ctx.get_project("//").get_broken_object_reason("part", "too-wide")
    # Whatever value an instance asks for: the declaration is what is wrong.
    assert ctx.get_part("//:too-wide;width=50") is None


def test_an_override_outside_the_range_is_an_error_and_the_default_stands():
    name = "//test:bounded"
    user_config.parameter_config[name] = {"holes": "40"}
    try:
        config = pc_config.apply_user_parameter_overrides(
            {"parameters": {"holes": {"type": "int", "default": 3, "max": 10}}}, name
        )
    finally:
        del user_config.parameter_config[name]
    assert config["parameters"]["holes"]["default"] == 3
    assert pc_logging.had_errors


SHARED = """\
parts:
  a:
    type: basic
    cuboid: 1
    parameters:
      holes: {type: int, default: 3, max: 10, shared: true}
      finish: {type: string, default: plain, enum: [plain, zinc], shared: true}
  b:
    type: basic
    cuboid: 1
    parameters:
      holes: {type: int, default: 3, max: 10, shared: true}
      finish: {type: string, default: plain, enum: [plain, zinc], shared: true}
"""


def _shared_values(tmp_path, overrides):
    (tmp_path / "partcad.yaml").write_text(SHARED)
    caller = UserConfig()
    for key, values in overrides.items():
        caller.parameter_config[key] = values
    project = pc.Context(str(tmp_path), user_config=caller).get_project("//")
    declared = project.get_part_config("b")["parameters"]
    return {name: declared[name]["default"] for name in ("holes", "finish")}


@pytest.mark.parametrize(
    "overrides",
    [
        {"//": {"holes": 40}},  # the package's own entry
        {"//:a": {"holes": "40"}},  # one sharing object's, as a command line types it
        {"//": {"finish": "gold"}},
    ],
)
def test_a_shared_parameter_s_override_is_held_to_its_bounds_too(tmp_path, overrides):
    """A shared value is the package's, resolved once for every object sharing it, and checked as any other."""
    assert _shared_values(tmp_path, overrides) == {"holes": 3, "finish": "plain"}
    assert pc_logging.had_errors


def test_a_shared_parameter_s_override_within_its_bounds_is_used(tmp_path):
    assert _shared_values(tmp_path, {"//": {"holes": 10, "finish": "zinc"}}) == {"holes": 10, "finish": "zinc"}
    assert not pc_logging.had_errors


def test_qualifying_a_package_passes_over_what_it_refuses(ctx):
    """'pc qual test' asks for every object, and one refused as it is asked for leaves the package's list then."""
    project = ctx.get_project("//")
    # Raised "dictionary changed size during iteration" when it went over the
    # package's own dictionary of declarations, which refusing one shrinks.
    project.test(ctx, tests=[])
    assert "defaults to 'gold'" in project.get_broken_object_reason("part", "gold-bolt")
    assert "defaults to 200" in project.get_broken_object_reason("part", "too-wide")
    # Asked for after the first of them was refused.
    assert "plate" in project.parts


# --------------------------------------------------------------------------- #
# An interface and a CMF declaration                                          #
# --------------------------------------------------------------------------- #


def test_an_interface_s_bounded_construction_parameter_is_set_by_a_reference(ctx):
    project = ctx.get_project("//")
    assert project.get_interface("m-hole;size=4") is not None
    assert project.get_interface("m-hole;size=40") is None
    assert "cannot be 40: its 'max' is 30" in project.get_broken_object_reason("interface", "m-hole;size=40")


def test_a_cmf_declaration_s_parameter_is_bounded_too(ctx):
    project = ctx.get_project("//")
    assert project.get_cmf("material", "abs;butadiene=0.3", quiet=True).density == pytest.approx(1070)
    assert project.get_cmf("material", "abs;butadiene=0.9", quiet=True) is None
    assert project.cmf_failure("material", "abs;butadiene=0.9") == (
        "The parameter 'butadiene' of '//:abs' cannot be 0.9: its 'max' is 0.3"
    )


# --------------------------------------------------------------------------- #
# What the schema and 'pc lint' say                                           #
# --------------------------------------------------------------------------- #


def _lint(document):
    return [d for d in validate_source(yaml.safe_dump(document), get_schema(PARTCAD_SCHEMA))]


def test_the_package_above_is_one_the_schema_takes():
    assert [d.message for d in _lint({**PACKAGE, "parts": {"plate": PACKAGE["parts"]["plate"]}})] == []


@pytest.mark.parametrize(
    "parameter",
    [
        {"type": "string", "default": "a", "min": 1},  # only a number has a range
        {"type": "int", "default": 1, "max": "ten"},
        {"type": "bool", "default": True, "max": 1},
    ],
)
def test_the_schema_refuses_a_range_on_what_is_not_a_number(parameter):
    def part(declaration):
        return {"parts": {"p": {"type": "basic", "cuboid": 1, "parameters": {"x": declaration}}}}

    unbounded = {key: value for key, value in parameter.items() if key not in ("min", "max")}
    assert _lint(part(unbounded)) == []
    found = _lint(part(parameter))
    assert {d.code for d in found} == {"schema", CODE_PARAMETERS}


def test_lint_reports_a_default_outside_the_range_where_it_is_declared():
    found = [d for d in _lint({"parts": {"too-wide": PACKAGE["parts"]["too-wide"]}}) if d.code == CODE_PARAMETERS]
    assert [(d.path, d.message) for d in found] == [
        (
            "$.parts.too-wide.parameters.width",
            "The parameter 'width' of 'too-wide' defaults to 200, and its 'max' is 100",
        )
    ]


def test_lint_reports_it_for_a_material_too():
    material = {"parameters": {"b": {"type": "float", "default": 0.5, "min": 0.6}}, "density": 1000}
    found = [d for d in _lint({"materials": {"m": material}}) if d.code == CODE_PARAMETERS]
    assert [d.path for d in found] == ["$.materials.m.parameters.b"]


@pytest.mark.parametrize("kind", [None, 5, ["int"]])
def test_a_range_on_a_parameter_whose_type_is_no_name_is_said_rather_than_failing_to_say_it(tmp_path, kind):
    declaration = {"type": kind, "min": 1}
    (problem,) = parameters.declaration_problems(declaration, "n", "p")
    assert problem == (
        "The parameter 'n' of 'p' is of the type %r, and only an int or a float parameter states a 'min' or a 'max'"
        % (kind,)
    )
    document = {"parts": {"p": {"type": "basic", "cuboid": 1, "parameters": {"n": declaration}}}}
    assert [d.message for d in _lint(document) if d.code == CODE_PARAMETERS] == [problem]
    # And PartCAD refuses the object for it, saying the same.
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(document))
    ctx = pc.Context(str(tmp_path))
    assert ctx.get_part("//:p") is None
    assert "is of the type %r" % (kind,) in ctx.get_project("//").get_broken_object_reason("part", "p")


# A 'partcad.yaml' with nothing to render it with is checked masked (see
# 'assy_lint.mask_template'): what a template gives is filler text there.
TEMPLATED = """\
parts:
  p:
    type: basic
    cuboid: 1
    parameters:
      low:
        type: int
        default: 3
        min: {{ lower }}
      picked:
        type: string
        default: {{ finish }}
        enum: [plain, zinc]
      typed:
        type: {{ kind }}
        default: 3
        min: 1
      sometimes:
        type: int
        default: 30
        {% if strict %}
        max: 10
        {% endif %}
      crossed:
        type: int
        desc: {{ what }}
        default: 3
        min: 5
        max: 1
"""


def test_lint_says_nothing_that_depends_on_what_a_template_gives():
    found = [d for d in validate_source(TEMPLATED, get_schema(PARTCAD_SCHEMA)) if d.code == CODE_PARAMETERS]
    # Only what is written out in full: both bounds of 'crossed'.
    assert [(d.path, d.message) for d in found] == [
        (
            "$.parts.p.parameters.crossed",
            "The parameter 'crossed' of 'p' has a 'min' of 5 above its 'max' of 1: no value is both",
        )
    ]


def test_lint_leaves_an_interface_s_freedom_of_movement_alone():
    """'slide' states 'min' and 'max' as a range of movement, which is no default to hold to them."""
    interface = {"parameters": {"slide": {"dir": [1, 0, 0], "min": 0, "max": 5, "default": 9}}}
    assert [d for d in _lint({"interfaces": {"i": interface}}) if d.code == CODE_PARAMETERS] == []


# --------------------------------------------------------------------------- #
# 'enum'                                                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "declaration, value, problem",
    [
        ({"type": "string", "enum": ["plain", "zinc"]}, "zinc", None),
        ({"type": "string", "enum": ["plain", "zinc"]}, "gold", "cannot be 'gold': its 'enum' allows 'plain', 'zinc'"),
        # Compared as a name spells them: the integer 3 is the '3' listed.
        ({"type": "int", "enum": ["3", "4"]}, 3, None),
        ({"type": "int", "enum": ["3", "4"]}, 5, "cannot be 5: its 'enum' allows '3', '4'"),
        # No 'enum', or an array, which an 'enum' of single values does not describe.
        ({"type": "string"}, "anything", None),
        ({"type": "array", "enum": ["A", "B"]}, ["A", "C"], None),
    ],
)
def test_a_value_has_to_be_one_the_enum_allows(declaration, value, problem):
    found = parameters.value_problem(declaration, value, "p", "//pkg:thing")
    assert found == (None if problem is None else "The parameter 'p' of '//pkg:thing' " + problem)


def test_a_default_not_in_the_enum_says_it_is_the_default():
    problems = parameters.declaration_problems({"type": "string", "default": "z", "enum": ["a", "b"]}, "k", "x")
    assert problems == ["The parameter 'k' of 'x' defaults to 'z', and its 'enum' allows 'a', 'b'"]


def test_a_part_s_reference_has_to_name_a_value_its_enum_allows(ctx):
    assert ctx.get_part("//:bolt;finish=zinc,size=4") is not None
    assert ctx.get_part("//:bolt;finish=gold") is None
    assert ctx.get_project("//").get_broken_object_reason("part", "bolt;finish=gold") == (
        "The parameter 'finish' of 'bolt;finish=gold' cannot be 'gold': its 'enum' allows 'plain', 'zinc'"
    )
    assert ctx.get_part("//:bolt;size=5") is None
    assert ctx.get_part("//:bolt") is not None


def test_a_default_not_in_the_enum_refuses_the_object(ctx):
    assert ctx.get_part("//:gold-bolt") is None
    assert "defaults to 'gold', and its 'enum' allows 'plain', 'zinc'" in ctx.get_project(
        "//"
    ).get_broken_object_reason("part", "gold-bolt")


def test_an_interface_s_enum_holds(ctx):
    project = ctx.get_project("//")
    assert project.get_interface("m-hole;head=round") is not None
    assert project.get_interface("m-hole;head=domed") is None
    assert "cannot be 'domed': its 'enum' allows 'flat', 'round'" in project.get_broken_object_reason(
        "interface", "m-hole;head=domed"
    )


def test_a_material_s_condition_has_to_be_one_it_lists(ctx):
    """What a catalogue relied on 'pick' failing for: a condition nobody measured is refused by name."""
    project = ctx.get_project("//")
    assert project.get_cmf("material", "steel-4340;condition=quenched-and-tempered", quiet=True) is not None
    assert project.get_cmf("material", "steel-4340;condition=normalized", quiet=True) is None
    assert project.cmf_failure("material", "steel-4340;condition=normalized") == (
        "The parameter 'condition' of '//:steel-4340' cannot be 'normalized': its 'enum' allows 'quenched-and-tempered'"
    )


def test_an_override_not_in_the_enum_is_an_error_and_the_default_stands():
    name = "//test:enumerated"
    user_config.parameter_config[name] = {"finish": "gold"}
    try:
        config = pc_config.apply_user_parameter_overrides(
            {"parameters": {"finish": {"type": "string", "default": "plain", "enum": ["plain", "zinc"]}}}, name
        )
    finally:
        del user_config.parameter_config[name]
    assert config["parameters"]["finish"]["default"] == "plain"
    assert pc_logging.had_errors


def test_lint_reports_a_default_not_in_the_enum():
    found = [d for d in _lint({"parts": {"gold-bolt": PACKAGE["parts"]["gold-bolt"]}}) if d.code == CODE_PARAMETERS]
    assert [d.path for d in found] == ["$.parts.gold-bolt.parameters.finish"]
