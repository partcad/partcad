#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for checking an ASSY file as a scene rather than as an assembly.

The same document means slightly different things depending on which section of
a package points at it, and the one difference is 'how'. Which of the two a
given file is is not a property of the file, so three places answer it: the
package walk exactly, from the declaration, and each client best effort.
"""

import asyncio
import os
import textwrap

import pytest

import partcad as pc
from partcad.lint.schema import AssySchemaLinting
from partcad_client import lint as client_lint
from partcad_utils import assy_lint

CONNECTED = """\
links:
  - part: cube
    name: block
    location: [[0, 0, 0], [0, 0, 1], 0]

  - part: cylinder
    name: post
    connect:
      name: block
      with: outer
      to: inner
      how:
        stage: "1"
"""

PLACED = """\
links:
  - part: cube
    name: block
    location: [[0, 0, 0], [0, 0, 1], 0]
"""


def check(text, flavor):
    return assy_lint.validate_source(text, assy_lint.schema_for_file("x.assy", flavor))


#
# The schema
#


def test_the_scene_schema_is_the_assembly_schema_without_how():
    """Derived, not copied: only the one rule differs."""
    assembly = assy_lint.get_schema(assy_lint.ASSY_SCHEMA)
    scene = assy_lint.scene_schema(assembly)

    assert "how" in assembly["definitions"]
    assert "how" not in scene["definitions"]
    for section in ("connect", "connectPorts"):
        assert scene["definitions"][section]["properties"]["how"] == {
            "not": {},
            "description": assy_lint.SCENE_NO_HOW,
        }
        # Everything else about the section is untouched.
        assert set(scene["definitions"][section]["properties"]) == set(assembly["definitions"][section]["properties"])

    # And the schema it was derived from is not modified.
    assert "how" in assy_lint.get_schema(assy_lint.ASSY_SCHEMA)["definitions"]


def test_a_scene_may_not_declare_assembly_instructions():
    assert check(CONNECTED, assy_lint.FLAVOR_ASSEMBLY) == []

    findings = check(CONNECTED, assy_lint.FLAVOR_SCENE)
    assert len(findings) == 1
    assert findings[0].severity == assy_lint.SEVERITY_ERROR
    assert findings[0].message == assy_lint.SCENE_NO_HOW
    # On the key that has to go, not on the value under it.
    assert findings[0].line == 11
    assert findings[0].column == 6


def test_a_scene_keeps_every_other_way_of_placing_an_object():
    """Only 'how' is forbidden; 'connect', 'connectPorts' and 'location' stay."""
    for text in (PLACED, CONNECTED.replace('      how:\n        stage: "1"\n', "")):
        assert check(text, assy_lint.FLAVOR_SCENE) == []

    ports = textwrap.dedent(
        """\
        links:
          - part: cube
            name: block
          - part: cylinder
            connectPorts:
              name: block
              with: a
              to: b
              exploded: 5
        """
    )
    assert check(ports, assy_lint.FLAVOR_SCENE) == []


def test_a_scene_is_still_checked_for_everything_else():
    broken = "links:\n  - part: cube\n    locaton: [[0, 0, 0], [0, 0, 1], 0]\n"
    findings = check(broken, assy_lint.FLAVOR_SCENE)
    assert [f.message for f in findings] == ["unexpected property 'locaton'"]


def test_the_derived_schema_is_only_built_once():
    first = assy_lint.schema_for_file("x.assy", assy_lint.FLAVOR_SCENE)
    assert assy_lint.schema_for_file("y.assy", assy_lint.FLAVOR_SCENE) is first


#
# Working out which one a file is: the client's best effort
#


def package(tmp_path, config, name="pkg"):
    root = tmp_path / name
    root.mkdir()
    (root / "partcad.yaml").write_text(config)
    (root / "thing.assy").write_text(CONNECTED)
    return root


def test_a_file_only_a_scene_points_at_is_a_scene(tmp_path):
    root = package(tmp_path, "scenes:\n  thing:\n    type: assy\n")
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_SCENE

    report = client_lint.check_file(str(root / "thing.assy"))
    assert report.flavor == assy_lint.FLAVOR_SCENE
    assert report.failed


def test_a_file_an_assembly_points_at_is_an_assembly(tmp_path):
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n")
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_ASSEMBLY
    assert not client_lint.check_file(str(root / "thing.assy")).failed


def test_an_assembly_wins_over_a_scene(tmp_path):
    """The file has to satisfy the full schema for that assembly to be readable."""
    root = package(
        tmp_path,
        "assemblies:\n  thing:\n    type: assy\nscenes:\n  copy:\n    type: assy\n    path: thing.assy\n",
    )
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_ASSEMBLY


def test_a_file_nothing_points_at_is_read_as_an_assembly(tmp_path):
    """Unknown leans towards the assembly: a false error on correct code is worse."""
    root = package(tmp_path, "parts:\n  cube:\n    type: stl\n")
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_ASSEMBLY

    (tmp_path / "orphan.assy").write_text(CONNECTED)
    assert client_lint.detect_flavor(str(tmp_path / "orphan.assy")) == assy_lint.FLAVOR_ASSEMBLY


def test_a_package_that_cannot_be_parsed_leans_the_same_way(tmp_path):
    """A 'partcad.yaml' is a Jinja2 template; one that will not parse as YAML says nothing."""
    root = package(tmp_path, "scenes:\n  thing:\n  {% this is not yaml\n")
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_ASSEMBLY


def test_a_templated_path_is_not_guessed_at(tmp_path):
    root = package(tmp_path, 'scenes:\n  thing:\n    type: assy\n    path: "{{ param_name }}.assy"\n')
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_ASSEMBLY


def test_a_scene_of_type_world_says_nothing_about_an_assy_file(tmp_path):
    root = package(tmp_path, "scenes:\n  thing:\n    type: world\n")
    assert client_lint.detect_flavor(str(root / "thing.assy")) == assy_lint.FLAVOR_ASSEMBLY


def test_the_caller_may_say_outright(tmp_path):
    """'pc lint --file --schema scene' overrides the detection."""
    root = package(tmp_path, "assemblies:\n  thing:\n    type: assy\n")
    report = client_lint.check_file(str(root / "thing.assy"), flavor=assy_lint.FLAVOR_SCENE)
    assert report.flavor == assy_lint.FLAVOR_SCENE
    assert report.failed


def test_a_file_kind_nothing_checks_is_reported_as_unchecked(tmp_path):
    report = client_lint.check_file(str(tmp_path / "notes.txt"))
    assert not report.checked
    assert report.diagnostics == []


#
# ... and the package walk's exact answer
#


def scene_package(tmp_path, config):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "partcad.yaml").write_text(config)
    (root / "thing.assy").write_text(CONNECTED)
    return root


@pytest.mark.parametrize(
    "config, expected",
    [
        ("scenes:\n  thing:\n    type: assy\n", [assy_lint.SCENE_NO_HOW]),
        ("assemblies:\n  thing:\n    type: assy\n", []),
    ],
)
def test_the_package_walk_checks_each_file_as_what_its_package_declares(tmp_path, config, expected):
    root = scene_package(tmp_path, config)
    ctx = pc.Context(str(root))
    project = ctx.get_project("//")

    check_run = AssySchemaLinting("AssySchema")
    targets = check_run.get_targets(ctx, project)
    assert [os.path.basename(target) for target in targets] == ["thing.assy"]

    report = asyncio.run(check_run.validate(ctx, project, targets[0]))
    assert [message.split(": ", 1)[1] for _, message in report.messages] == expected


def test_the_flavor_is_part_of_what_a_cached_finding_is_keyed_on(tmp_path):
    """Moving a declaration changes the schema without touching the file."""
    root = scene_package(tmp_path, "scenes:\n  thing:\n    type: assy\n")
    ctx = pc.Context(str(root))
    project = ctx.get_project("//")

    check_run = AssySchemaLinting("AssySchema")
    target = check_run.get_targets(ctx, project)[0]
    as_scene = check_run.get_hash(project.name, target).get()

    (root / "partcad.yaml").write_text("assemblies:\n  thing:\n    type: assy\n")
    project = pc.Context(str(root)).get_project("//")
    check_run.get_targets(pc.Context(str(root)), project)
    as_assembly = check_run.get_hash(project.name, target).get()

    assert as_scene != as_assembly
