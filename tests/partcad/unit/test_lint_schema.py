#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the constraints the configuration schema puts on a declaration.

'pc lint' validates 'partcad.yaml' against this schema, but only for packages
that load: a configuration broken badly enough to fail the object factories
never gets that far (see 'test_file.py' for what the loader reports instead).
These tests go at the schema directly, so every combination is covered
regardless of what the loader does with it.

The block at the end goes at the package walk instead -- which files each check
claims, and what a finding looks like once it comes back. Since the editor
checks the same file with the same checker, a gap here is a squiggle on a
working file rather than a message nobody reads.
"""

import asyncio
import os

import jsonschema
import jsonschema.exceptions
import pytest

import partcad as pc
from partcad.lint.all import get_partcad_schema
from partcad.lint.schema import AssySchemaLinting, SchemaLinting


def validate(config):
    jsonschema.validate(instance=config, schema=get_partcad_schema())


def failure(config):
    with pytest.raises(jsonschema.exceptions.ValidationError) as err:
        validate(config)
    return err.value


def failures(config):
    """Every error raised for 'config', including those nested inside 'oneOf'.

    'jsonschema.validate' surfaces a single best-match error. Where a branch of
    a 'oneOf' is what failed -- 'parts' is the only kind wrapped in one -- the
    best match is the 'oneOf' itself, and the error that names the offending
    keyword sits underneath it in '.context'. Flatten the tree so a test can
    assert on that error wherever it ended up.
    """
    schema = get_partcad_schema()
    validator = jsonschema.validators.validator_for(schema)(schema)

    def walk(errors):
        for error in errors:
            yield error
            yield from walk(error.context or [])

    return list(walk(validator.iter_errors(config)))


# An object of each kind that carries a source file, in the shortest form that
# declares where to pull that file from.
FILE_BACKED = {
    "parts": {"bolt": {"type": "step"}},
    "sketches": {"outline": {"type": "dxf"}},
    "assemblies": {"rig": {"type": "assy"}},
}


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_file_from_url(kind):
    """'fileFrom: url' plus 'fileUrl' is accepted for every file-backed object"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    config = dict(config, fileFrom="url", fileUrl="https://example.com/vendor/%s" % name)
    validate({kind: {name: config}})


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_file_from_without_file_url(kind):
    """'fileFrom' without 'fileUrl' is rejected, and the object is named"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    error = failure({kind: {name: dict(config, fileFrom="url")}})
    assert error.json_path == "$.%s.%s" % (kind, name)
    assert error.message == "'fileUrl' is a dependency of 'fileFrom'"


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_file_url_without_file_from(kind):
    """'fileUrl' without 'fileFrom' is rejected, and the object is named"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    error = failure({kind: {name: dict(config, fileUrl="https://example.com/vendor/%s" % name)}})
    assert error.json_path == "$.%s.%s" % (kind, name)
    assert error.message == "'fileFrom' is a dependency of 'fileUrl'"


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_unsupported_file_from(kind):
    """'url' is the only source a file can be pulled from so far"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    config = dict(config, fileFrom="ftp", fileUrl="https://example.com/vendor/%s" % name)
    errors = failures({kind: {name: config}})
    assert any(
        error.json_path == "$.%s.%s.fileFrom" % (kind, name) and "'ftp' is not one of ['url']" in error.message
        for error in errors
    ), [(error.json_path, error.message) for error in errors]


# What an 'enrich' may override a parameter with. Overriding parameters asks for
# the instance of an object that has those values, and that instance is named
# '<name>;<parameter>=<value>,...' - so a value cannot carry the characters that
# spelling is made of.


ENRICHABLE = {
    "parts": {"cube": {"type": "enrich", "source": "block"}},
    "sketches": {"outline": {"type": "enrich", "source": "profile"}},
    "assemblies": {"desk": {"type": "enrich", "source": "table"}},
}


@pytest.mark.parametrize("kind", ENRICHABLE.keys())
@pytest.mark.parametrize("value", [20.0, 20, "steel", True, ""])
def test_schema_parameter_override_accepts_a_nameable_value(kind, value):
    name, config = next(iter(ENRICHABLE[kind].items()))
    validate({kind: {name: dict(config, **{"with": {"width": value}})}})


@pytest.mark.parametrize("kind", ENRICHABLE.keys())
@pytest.mark.parametrize("value", ["a,b", "a=b", "a;b"])
def test_schema_parameter_override_rejects_what_cannot_be_named(kind, value):
    name, config = next(iter(ENRICHABLE[kind].items()))
    errors = failures({kind: {name: dict(config, **{"with": {"width": value}})}})
    assert any(
        error.json_path == "$.%s.%s.with.width" % (kind, name) and "does not match" in error.message for error in errors
    ), [(error.json_path, error.message) for error in errors]


# The same constraint on the other side of a parameter: what it is worth when
# nothing overrides it, and what it offers to be set to.


@pytest.mark.parametrize("kind", ENRICHABLE.keys())
def test_schema_a_parameter_default_must_be_nameable(kind):
    config = dict(next(iter(ENRICHABLE[kind].values())), parameters={"grade": {"type": "string", "default": "a,b"}})
    errors = failures({kind: {"widget": config}})
    assert any(error.json_path == "$.%s.widget.parameters.grade.default" % kind for error in errors), [
        (error.json_path, error.message) for error in errors
    ]


@pytest.mark.parametrize("kind", ENRICHABLE.keys())
def test_schema_a_parameter_enum_must_be_nameable(kind):
    config = dict(next(iter(ENRICHABLE[kind].values())), parameters={"grade": {"type": "string", "enum": ["a", "b=c"]}})
    errors = failures({kind: {"widget": config}})
    assert any(error.json_path == "$.%s.widget.parameters.grade.enum[1]" % kind for error in errors), [
        (error.json_path, error.message) for error in errors
    ]


@pytest.mark.parametrize("kind", ENRICHABLE.keys())
def test_schema_a_parameter_default_may_be_any_other_value(kind):
    """Only a string can carry those characters; nothing else is constrained."""
    for default in (20.0, 20, True, ["a", "b"]):
        config = dict(next(iter(ENRICHABLE[kind].values())), parameters={"grade": {"default": default}})
        validate({kind: {"widget": config}})


# What the schema has to accept, because PartCAD's own tooling writes it.


@pytest.mark.parametrize("section", ["dependencies", "sketches", "parts", "assemblies", "scenes", "software"])
def test_schema_an_empty_section_is_the_empty_section(section):
    """'pc init' writes three of these, and 'pc add part' fills one in.

    An empty section parses as null, which is how the loader reads it as well
    ('config_obj.get(section) or {}'). Rejecting it put an error on every new
    package -- invisible while only 'pc lint' checked configurations, and three
    squiggles on an untouched file once the editor did.
    """
    validate({section: None})


def test_schema_every_registered_part_type_is_accepted():
    """A type with a factory behind it that the schema does not know is a gap.

    'sdf' was one: registered in 'globals.py', documented, and used by two of
    the shipped examples, which therefore failed their own schema check.
    'wrapper' is deliberately not here -- it is what constructs a part whose
    'type' names a package-defined partType, not a type anybody writes.
    """
    for part_type in ("cadquery", "build123d", "chili3d", "sdf", "step", "brep", "stl", "3mf", "obj", "scad"):
        validate({"parts": {"widget": {"type": part_type}}})


# The package walk: which check claims which file, and what it reports.


def package(tmp_path, config):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "partcad.yaml").write_text(config)
    return root


def test_the_configuration_check_claims_the_configuration(tmp_path):
    root = package(tmp_path, "desc: a package\n")
    ctx = pc.Context(str(root))
    targets = SchemaLinting("PartcadSchema").get_targets(ctx, ctx.get_project("//"))
    assert [os.path.basename(target) for target in targets] == ["partcad.yaml"]


def test_the_assy_check_does_not_also_claim_it(tmp_path):
    """Both checks know a schema for a file now; only one walks each kind.

    'AssySchemaLinting' picks its targets by asking which files have a schema,
    so the day 'partcad.yaml' got one it would have started checking the
    configuration too -- reporting every finding twice, under two check names.
    """
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n")
    (root / "thing.assy").write_text("links:\n  - part: cube\n")
    ctx = pc.Context(str(root))
    targets = AssySchemaLinting("AssySchema").get_targets(ctx, ctx.get_project("//"))
    assert [os.path.basename(target) for target in targets] == ["thing.assy"]


def test_a_configuration_finding_carries_its_source_position(tmp_path):
    """The same wording, at the same place, as the editor shows for the file."""
    root = package(tmp_path, "desc: a package\nprts:\n  cube:\n    type: cadquery\n")
    ctx = pc.Context(str(root))
    project = ctx.get_project("//")

    check_run = SchemaLinting("PartcadSchema")
    report = asyncio.run(check_run.validate(ctx, project, check_run.get_targets(ctx, project)[0]))
    assert [message for _, message in report.messages] == ["partcad.yaml:2:1: unexpected property 'prts'"]


def test_a_templated_configuration_is_not_reported_as_broken_yaml(tmp_path):
    """'partcad.yaml' is rendered as a Jinja2 template before it is parsed.

    Handing the raw file to 'yaml.safe_load', which is what this check used to
    do, called every templated configuration broken.
    """
    root = package(
        tmp_path,
        "parts:\n{% for size in [10, 20] %}\n  cube_{{ size }}:\n    type: cadquery\n    path: cube.py\n{% endfor %}\n",
    )
    (root / "cube.py").write_text("# a part\n")
    ctx = pc.Context(str(root))
    project = ctx.get_project("//")

    check_run = SchemaLinting("PartcadSchema")
    report = asyncio.run(check_run.validate(ctx, project, check_run.get_targets(ctx, project)[0]))
    assert report.messages == []
