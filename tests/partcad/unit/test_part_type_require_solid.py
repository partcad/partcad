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
import os
import shutil

import pytest
import yaml

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


def _key(directory, require_solid=False, marks=0):
    """The cache key of a ':skin' part, in a package whose 'skin' type differs in 'requireSolid' and nothing else."""
    if not directory.exists():
        directory.mkdir()
        shutil.copy(os.path.join(os.path.dirname(PACKAGE), "face.py"), directory / "face.py")
        part_type = {"path": "face.py"}
        if require_solid:
            part_type["requireSolid"] = True
        (directory / "partcad.yaml").write_text(
            yaml.safe_dump({"partTypes": {"skin": part_type}, "parts": {"skin_part": {"type": ":skin"}}})
        )
    part = pc.Context(str(directory)).get_part(":skin_part")
    for _ in range(marks):
        part.key_on_required_solid()
    asyncio.run(part.prepare_async(wait=True))
    return part.hash.get()


def test_it_is_part_of_the_cache_key(tmp_path):
    """A part cached before its type said 'requireSolid' was accepted then, and must not be read back now.

    The verdict is reached as a part is built, and a cache hit is not built: so
    the declaration is in the key, and only the strict side adds to it.
    """
    lenient = _key(tmp_path / "lenient")
    assert lenient is not None
    assert _key(tmp_path / "lenient_again") == lenient
    assert _key(tmp_path / "strict", require_solid=True) != lenient


def test_it_is_added_to_the_key_once(tmp_path):
    """An assembly built twice hands back the parts it registered the first time, and marks them again."""
    package = tmp_path / "package"
    once = _key(package, marks=1)
    assert once != _key(package)
    assert _key(package, marks=2) == once
