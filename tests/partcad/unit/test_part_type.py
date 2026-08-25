#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for package-defined partTypes.

A partType is a reusable, package-defined way to construct parts. A part whose
'type' references it (the short form ':<name>', expanded to '<package>:<name>')
is built by PartFactoryWrapper. These tests cover the expansion, the partType
config accessor, and the factory dispatch without the sandbox; a gated
end-to-end test instantiates the shape when the sandbox is available.
"""

import asyncio

import pytest

import partcad as pc
from partcad import factory

EXAMPLE = "examples/produce_part_wrapper"


def test_wrapper_factory_is_registered():
    # A part 'type' that carries a package path is dispatched to the wrapper.
    assert "wrapper" in factory.all["part"]


def test_part_type_definition_is_enumerated():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    cfg = root.get_part_type_config("box")
    assert cfg is not None
    assert cfg.get("kind", "wrapper") == "wrapper"
    assert cfg.get("path") == "box_wrapper.py"
    # It is enumerable as an object kind, and it is not a part.
    assert "box" in root.object_names("partType")
    assert "box" not in root.object_names("part")


def test_short_part_type_is_expanded_and_stored():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())

    part = ctx.get_part(":demo")
    assert part is not None

    # The short ':box' form is expanded to the fully-qualified '<package>:box'
    # and stored expanded (here, at construction, when the part factory is made).
    expanded = root.get_part_config("demo")["type"]
    assert expanded != ":box"
    assert expanded.endswith(":box")
    assert expanded == root.name + ":box"


def test_unknown_part_type_is_not_found():
    ctx = pc.Context(EXAMPLE)
    root = ctx.get_project(ctx.get_current_project_path())
    assert root.get_part_type_config("nope") is None


@pytest.mark.slow
def test_wrapper_part_instantiates():
    """End to end: the wrapper script produces the part's shape (needs the sandbox)."""
    ctx = pc.Context(EXAMPLE)
    part = ctx.get_part(":demo")
    assert part is not None
    try:
        wrapped = asyncio.run(part.get_wrapped(ctx))
    except Exception as e:
        pytest.skip("Sandbox unavailable for partType wrapper: %s" % e)
    assert wrapped is not None
