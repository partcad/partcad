#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""'material' is contributed by the part type, not invented by the part.

Parameters are otherwise the object's own business: the schema takes any name
matching its pattern, and nothing but the script behind the part knows what one
means. 'material' is different - PartCAD itself acts on it, in the
manufacturing and quoting path - so it only means anything on a type that can
honour it, and the types that can are the ones producing a single homogeneous
body. Declaring it anywhere else is a per-object error: the package keeps
loading, that one part does not.
"""

import asyncio

import pytest
import yaml

import partcad as pc

ACCEPTING_TYPES = ["stl", "cadquery", "build123d", "sdf", "extrude"]
REJECTING_TYPES = ["step", "kicad"]


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


def _material(value="//pub/std/manufacturing/material/plastic:pla"):
    return {"material": {"type": "string", "default": value}}


@pytest.mark.parametrize("part_type", ACCEPTING_TYPES)
def test_material_is_accepted_by_the_homogeneous_types(tmp_path, part_type):
    """One body of one thing, so one 'material:' can be true of the whole part."""
    pc.logging.reset_errors()
    package = _write_package(tmp_path, {"body": _part(part_type, parameters=_material())})

    project = pc.Context(str(package)).get_project("//")

    assert "body" in project.parts
    assert project.get_broken_object_reason("part", "body") is None
    assert pc.logging.had_errors is False


@pytest.mark.parametrize("part_type", REJECTING_TYPES)
def test_material_is_rejected_by_the_types_that_can_carry_many(tmp_path, part_type):
    """A STEP file may hold many solids, each already stating its own material.

    Per object, not per package: the sibling part is declared after the bad one
    and still has to load, and the command still has to report a failure.
    """
    pc.logging.reset_errors()
    package = _write_package(
        tmp_path,
        {
            "body": _part(part_type, parameters=_material()),
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
    assert "material" in reason
    assert part_type in reason
    assert "does not accept" in reason


@pytest.mark.parametrize("part_type", REJECTING_TYPES)
def test_asking_for_a_rejected_part_by_name_returns_none(tmp_path, part_type):
    package = _write_package(tmp_path, {"body": _part(part_type, parameters=_material())})
    ctx = pc.Context(str(package))

    assert ctx.get_part("//:body") is None


@pytest.mark.parametrize("part_type", ACCEPTING_TYPES + REJECTING_TYPES)
def test_any_other_parameter_name_is_left_alone(tmp_path, part_type):
    """Only the policed names may ever be rejected; the rest stay arbitrary.

    Including on the types that reject 'material' - what is restricted is the
    one name PartCAD gives a meaning to, not the right to declare parameters.
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


def test_get_mcftt_still_reads_the_declared_material(tmp_path):
    """The consumer of 'parameters.material' is unchanged by any of the above."""
    package = _write_package(tmp_path, {"body": _part("stl", parameters=_material("//pub:brass"))})

    part = pc.Context(str(package)).get_part("//:body")

    assert asyncio.run(part.get_mcftt("material")) == "//pub:brass"


def test_the_material_is_part_of_the_cache_key(tmp_path):
    """Two parts alike but for their material are two shapes, not one.

    'parameters' is what 'Shape.__init__' folds into the hash, and 'material'
    only stays honest as a parameter for as long as that keeps being true: a
    part made of brass must not be served out of the cache entry a part made of
    steel wrote. Nothing else asserted this.
    """
    package = _write_package(
        tmp_path,
        {
            "brass": _part("stl", path="body.stl", parameters=_material("//pub:brass")),
            "steel": _part("stl", path="body.stl", parameters=_material("//pub:steel")),
            "brass_again": _part("stl", path="body.stl", parameters=_material("//pub:brass")),
        },
    )

    project = pc.Context(str(package)).get_project("//")
    keys = {name: project.parts[name].hash.get() for name in ["brass", "steel", "brass_again"]}

    assert None not in keys.values()
    assert keys["brass"] != keys["steel"]
    # ...and the name is not what made them differ.
    assert keys["brass"] == keys["brass_again"]
