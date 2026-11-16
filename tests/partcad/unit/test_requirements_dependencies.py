#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'has_dependencies' and 'has_private_dependencies': what an object is built from ('partcad.object_dependencies').

Against a workspace of two packages, '//' and '//lib' below it: '//lib' is a
package other than the object's own and is not under '//pub', so it is a private
dependency. '//pub' itself cannot be reached here, so what makes a package
public is pinned on its name.
"""

import asyncio
import textwrap

import pytest

import partcad as pc
from partcad import object_dependencies, requirements

PACKAGE = """
parts:
  own:
    type: basic
    cuboid: 10
    requirements:
      has_dependencies: false
      has_private_dependencies: false
  borrowed:
    type: enrich
    source: lib:block
  required-to-be-alone:
    type: basic
    cuboid: 10
    requirements:
      has_dependencies: true
assemblies:
  kit:
    type: assy
    requirements:
      has_dependencies: true
      has_private_dependencies: false
"""

KIT = """
links:
  - part: own
  - part: lib:block
    location: [[20, 0, 0], [0, 0, 1], 0]
"""

LIB = """
parts:
  block:
    type: basic
    cuboid: 5
"""


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    path = tmp_path_factory.mktemp("dependencies")
    (path / "partcad.yaml").write_text(textwrap.dedent(PACKAGE))
    (path / "kit.assy").write_text(textwrap.dedent(KIT))
    (path / "lib").mkdir()
    (path / "lib" / "partcad.yaml").write_text(textwrap.dedent(LIB))
    return pc.Context(str(path))


def _checks(ctx, shape) -> dict:
    report = asyncio.run(requirements.check_async(ctx, shape))
    return {check.name: (check.passed, check.detail) for check in report.checks if check.section == requirements.HAS}


@pytest.mark.parametrize(
    "package, public",
    [("//pub", True), ("//pub/std/metric", True), ("//publish", False), ("//lib", False), ("//", False)],
)
def test_public_is_pub_and_what_is_under_it(package, public):
    assert object_dependencies.is_public(package) is public


def test_builtin_is_part_of_partcad_and_no_dependency():
    found = object_dependencies.Dependencies("//")
    found.add("//builtin/color", "colour //builtin/color:rgba")
    found.add("//", "itself")
    assert found.packages == {}


def test_an_object_of_its_own_package_alone_draws_on_nothing(ctx):
    checks = _checks(ctx, ctx.get_part(":own"))
    assert checks == {
        "has_dependencies": (True, "it draws on no other package"),
        "has_private_dependencies": (True, "it draws on no package outside //pub"),
    }


def test_required_to_draw_on_another_and_does_not(ctx):
    passed, detail = _checks(ctx, ctx.get_part(":required-to-be-alone"))["has_dependencies"]
    assert passed is False
    assert detail == "it draws on no other package"


def test_an_assembly_draws_on_every_package_a_part_in_it_is_from(ctx):
    checks = _checks(ctx, ctx.get_assembly(":kit"))
    assert checks["has_dependencies"] == (True, "it draws on //lib: part //lib:block (in //:kit)")
    passed, detail = checks["has_private_dependencies"]
    assert passed is False
    assert detail.startswith("it is required not to draw on a package outside //pub, and does: //lib")


def test_a_reference_draws_on_the_package_of_what_it_is_of(ctx):
    found = asyncio.run(object_dependencies.collect_async(ctx, ctx.get_part(":borrowed")))
    assert list(found.packages) == ["//lib"]
    assert list(found.private) == ["//lib"]
    assert found.unknown == []


def test_both_are_read_as_yes_or_no_requirements():
    declaration = requirements.parse({"has_dependencies": True, "has_private_dependencies": False})
    assert [(has.name, has.required) for has in declaration.has] == [
        ("has_dependencies", True),
        ("has_private_dependencies", False),
    ]
    assert not declaration.problems
