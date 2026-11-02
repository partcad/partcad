#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A 'partType' that declares 'requireSolid', built for real.

The rule itself is 'test_part_validation.py's, with the sandbox stubbed. Here a
package declares a type with it and the same script without it, and the parts
are built in a sandbox the way any partType's are: the wrapper judges the live
shape ('wrapper_common.solid_problems') and the core acts on what it found. So
what is tested is that the declaration reaches the part, not a check of its own.
"""

import asyncio
import logging

import pytest

import partcad as pc

PACKAGE = "tests/partcad/unit/data/require_solid/partcad.yaml"


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(PACKAGE)


def _build(ctx, name):
    part = ctx.get_part(name)
    return part, asyncio.run(part.get_wrapped(ctx))


def test_without_it_a_part_that_is_not_a_solid_is_built_and_reported(ctx, caplog):
    with caplog.at_level(logging.WARNING):
        part, envelope = _build(ctx, ":lenient")
    assert envelope is not None
    assert part.errors == []
    assert "is not a solid: it holds no solid" in caplog.text


def test_with_it_the_same_part_fails_and_says_why(ctx):
    part, envelope = _build(ctx, ":strict")
    assert envelope is None
    assert part.solid_required
    assert any(
        "is not a solid: it holds no solid; it has faces that belong to no solid" in error for error in part.errors
    ), part.errors


def test_with_it_a_part_that_is_a_solid_is_built(ctx):
    part, envelope = _build(ctx, ":whole")
    assert envelope is not None, part.errors
    assert part.errors == []
