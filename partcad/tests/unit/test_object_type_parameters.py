#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""'material', 'color' and 'tolerance' are contributed by the part type.

Parameters are otherwise the object's own business: the schema takes any name
matching its pattern, and nothing but the script behind the part knows what one
means. These three are different - PartCAD itself acts on them, in the
manufacturing and quoting path - so they only mean anything on a type that can
honour them, and the types that can are the ones producing a single homogeneous
body. Declaring one anywhere else is a per-object error: the package keeps
loading, that one part does not.
"""

import asyncio

import pytest
import yaml

import partcad as pc
from partcad.part_factory import PartFactory

ACCEPTING_TYPES = ["stl", "cadquery", "build123d", "sdf", "extrude"]
REJECTING_TYPES = ["step", "kicad"]
POLICED = ["material", "color", "tolerance"]


def _write_package(tmp_path, parts):
    """A package of the given parts, with every source file they need on disk.

    The files are never opened here - none of these tests instantiates a shape -
    but the file-backed factories check that the path exists before they will
    create the part at all, so an empty file is enough and is what keeps these
    tests free of a CAD kernel.
    """
    config = {
        "name": "//test",
        "sketches": {"circle": {"type": "basic", "circle": 10.0}},
        "parts": parts,
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    for extension in [".stl", ".py", ".step"]:
        for name in parts:
            (tmp_path / (name + extension)).write_text("")
            path = parts[name].get("path")
            if path:
                (tmp_path / path).write_text("")
    return tmp_path


def _part(part_type, **extra):
    config = {"type": part_type}
    if part_type == "extrude":
        config["sketch"] = "circle"
        config["depth"] = 10.0
    config.update(extra)
    return config


def _declare(name, value=None):
    """One policed parameter, declared the way a part author would declare it."""
    if value is None:
        value = 0.1 if name == "tolerance" else "//pub/std/manufacturing/material/plastic:pla"
    kind = "float" if isinstance(value, float) else "string"
    return {name: {"type": kind, "default": value}}


def test_the_policed_registry_is_the_three_names():
    """The registry is a set of names, not a mapping: policing is per name."""
    assert PartFactory.POLICED_OBJECT_TYPE_PARAMETERS == frozenset(POLICED)
    assert isinstance(PartFactory.POLICED_OBJECT_TYPE_PARAMETERS, frozenset)
    # Nothing is accepted by default; only what a factory opts into is.
    assert PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS == {}


@pytest.mark.parametrize("part_type", ACCEPTING_TYPES)
@pytest.mark.parametrize("name", POLICED)
def test_accepted_by_the_homogeneous_types(tmp_path, part_type, name):
    """One body of one thing, so one value can be true of the whole part."""
    pc.logging.reset_errors()
    package = _write_package(tmp_path, {"body": _part(part_type, parameters=_declare(name))})

    project = pc.Context(str(package)).get_project("//")

    assert "body" in project.parts
    assert project.get_broken_object_reason("part", "body") is None
    assert pc.logging.had_errors is False


@pytest.mark.parametrize("part_type", REJECTING_TYPES)
@pytest.mark.parametrize("name", POLICED)
def test_rejected_by_the_types_that_can_carry_many(tmp_path, part_type, name):
    """A STEP file may hold many solids, each already stating its own material.

    Per object, not per package: the sibling part is declared after the bad one
    and still has to load, and the command still has to report a failure.
    """
    pc.logging.reset_errors()
    package = _write_package(
        tmp_path,
        {
            "body": _part(part_type, parameters=_declare(name)),
            "sibling": _part("stl"),
        },
    )

    project = pc.Context(str(package)).get_project("//")

    assert "body" not in project.parts
    assert "sibling" in project.parts
    assert pc.logging.had_errors is True

    reason = project.get_broken_object_reason("part", "body")
    # The object, the parameter and the type, and what is wrong with the three
    # of them together.
    assert "body" in reason
    assert name in reason
    assert part_type in reason
    assert "does not accept" in reason


@pytest.mark.parametrize("part_type", REJECTING_TYPES)
def test_asking_for_a_rejected_part_by_name_returns_none(tmp_path, part_type):
    package = _write_package(tmp_path, {"body": _part(part_type, parameters=_declare("material"))})
    ctx = pc.Context(str(package))

    assert ctx.get_part("//:body") is None


@pytest.mark.parametrize("part_type", ACCEPTING_TYPES + REJECTING_TYPES)
def test_any_other_parameter_name_is_left_alone(tmp_path, part_type):
    """Only the policed names may ever be rejected; the rest stay arbitrary.

    Including on the types that reject them - what is restricted is the handful
    of names PartCAD gives a meaning to, not the right to declare parameters.
    """
    pc.logging.reset_errors()
    package = _write_package(
        tmp_path,
        {"body": _part(part_type, parameters={"width": {"type": "float", "default": 1.0}})},
    )

    project = pc.Context(str(package)).get_project("//")

    assert "body" in project.parts
    assert project.get_broken_object_reason("part", "body") is None
    assert pc.logging.had_errors is False


@pytest.mark.parametrize("part_type", ACCEPTING_TYPES + REJECTING_TYPES)
def test_a_parameter_carrying_a_color_field_is_not_a_parameter_named_color(tmp_path, part_type):
    """The schema lets any parameter carry 'color:' and 'material:' of its own.

    See 'shape-parameter' in partcad.json, and features/lint.feature, which
    declares exactly this on a parameter called 'kind'. Those fields describe
    what one *value* of that parameter looks like; what is policed is the
    parameter's *name*. A type that rejects a parameter named 'color' must
    still take a parameter of any other name that carries a 'color:' field.
    """
    pc.logging.reset_errors()
    package = _write_package(
        tmp_path,
        {
            "body": _part(
                part_type,
                parameters={
                    "kind": {
                        "type": "string",
                        "enum": ["X", "Y"],
                        "default": "Y",
                        "color": "#FF0000",
                        "material": "steel",
                    }
                },
            )
        },
    )

    project = pc.Context(str(package)).get_project("//")

    assert "body" in project.parts
    assert project.get_broken_object_reason("part", "body") is None
    assert pc.logging.had_errors is False


@pytest.mark.parametrize("name", ["material", "color"])
def test_get_mcftt_still_reads_the_declared_value(tmp_path, name):
    """The consumer of these parameters is unchanged by any of the above."""
    package = _write_package(tmp_path, {"body": _part("stl", parameters=_declare(name, "//pub:brass"))})

    part = pc.Context(str(package)).get_part("//:body")

    assert asyncio.run(part.get_mcftt(name)) == "//pub:brass"


def test_a_declared_tolerance_reads_back_as_a_number(tmp_path):
    package = _write_package(tmp_path, {"body": _part("stl", parameters=_declare("tolerance", 0.25))})

    part = pc.Context(str(package)).get_part("//:body")

    value = part.get_object_type_parameter("tolerance")
    assert isinstance(value, float)
    assert value == 0.25
    # ...and get_mcftt, which reads the declaration as it stands, agrees.
    assert asyncio.run(part.get_mcftt("tolerance")) == 0.25


def test_an_undeclared_tolerance_reads_back_as_the_type_default(tmp_path):
    package = _write_package(tmp_path, {"body": _part("stl")})

    part = pc.Context(str(package)).get_part("//:body")

    assert part.get_object_type_parameter("tolerance") == 0.0
    # The names with no default stay absent instead of being invented.
    assert part.get_object_type_parameter("material") is None
    assert part.get_object_type_parameter("color") is None


def test_a_type_that_accepts_no_tolerance_reports_none(tmp_path):
    """Not 0.0: 'this type has no such parameter' and 'nobody set it' differ."""
    package = _write_package(tmp_path, {"body": _part("step")})

    part = pc.Context(str(package)).get_part("//:body")

    assert part.get_object_type_parameter("tolerance") is None


def test_a_non_numeric_tolerance_is_reported_and_falls_back(tmp_path):
    """Reported and defaulted, the way an unknown manufacturing method is."""
    pc.logging.reset_errors()
    package = _write_package(tmp_path, {"body": _part("stl", parameters=_declare("tolerance", "quite tight"))})

    part = pc.Context(str(package)).get_part("//:body")

    assert part.get_object_type_parameter("tolerance") == 0.0
    assert pc.logging.had_errors is True


def test_reading_a_defaulted_tolerance_does_not_write_it_into_the_configuration(tmp_path):
    """The default is applied on the way out, and only there.

    'Shape.__init__' hashes config["parameters"] into the cache key, so writing
    a default in would move the key of every homogeneous part that never
    mentioned a tolerance - a mass invalidation for a value nobody set.
    """
    package = _write_package(tmp_path, {"body": _part("stl", parameters=_declare("material"))})

    project = pc.Context(str(package)).get_project("//")
    part = project.parts["body"]
    before = part.hash.get()

    assert part.get_object_type_parameter("tolerance") == 0.0

    assert "tolerance" not in part.config["parameters"]
    assert part.hash.get() == before


def test_declaring_the_default_tolerance_is_not_the_same_as_not_declaring_it(tmp_path):
    """Which is the other half of the proof that nothing is injected.

    An explicit 'tolerance: 0.0' is an input like any other and keys the cache;
    an absent one is absent. If the default were written into the configuration
    the two would collapse into one key.
    """
    package = _write_package(
        tmp_path,
        {
            "silent": _part("stl", path="body.stl"),
            "explicit": _part("stl", path="body.stl", parameters=_declare("tolerance", 0.0)),
        },
    )

    project = pc.Context(str(package)).get_project("//")
    keys = {name: project.parts[name].hash.get() for name in ["silent", "explicit"]}

    assert None not in keys.values()
    assert keys["silent"] != keys["explicit"]


@pytest.mark.parametrize("name", POLICED)
def test_a_policed_parameter_is_part_of_the_cache_key(tmp_path, name):
    """Two parts alike but for one of these are two shapes, not one.

    'parameters' is what 'Shape.__init__' folds into the hash, and these only
    stay honest as parameters for as long as that keeps being true: a part made
    of brass must not be served out of the cache entry a part made of steel
    wrote. Nothing else asserted this.
    """
    one, other = (0.1, 0.2) if name == "tolerance" else ("brass", "steel")
    package = _write_package(
        tmp_path,
        {
            "first": _part("stl", path="body.stl", parameters=_declare(name, one)),
            "second": _part("stl", path="body.stl", parameters=_declare(name, other)),
            "first_again": _part("stl", path="body.stl", parameters=_declare(name, one)),
        },
    )

    project = pc.Context(str(package)).get_project("//")
    keys = {n: project.parts[n].hash.get() for n in ["first", "second", "first_again"]}

    assert None not in keys.values()
    assert keys["first"] != keys["second"]
    # ...and the name is not what made them differ.
    assert keys["first"] == keys["first_again"]
