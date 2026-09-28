#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A shape built out of others is keyed on what they contain, not only their names.

An extrusion names its sketch, a compound part its assembly, an ASSY assembly
the parts it links to - and the names were all their keys ever covered. Edit the
sketch, or a part inside the assembly, and every one of those kept its key and
went on being served from the entry built before the edit.
"""

import asyncio

import pytest

import partcad as pc

_CONFIG = """
sketches:
  outline:
    type: dxf
    path: outline.dxf
parts:
  cube:
    type: step
    path: cube.step
  other:
    type: step
    path: other.step
  slab:
    type: extrude
    sketch: outline
    depth: 1
  merged:
    type: compound
    source: assembly
assemblies:
  assembly:
    type: assy
"""


@pytest.fixture
def package(tmp_path):
    (tmp_path / "partcad.yaml").write_text(_CONFIG)
    (tmp_path / "assembly.assy").write_text("links:\n  - part: cube\n")
    # Only the bytes matter here: nothing is built, only keyed.
    (tmp_path / "cube.step").write_text("cube v1\n")
    (tmp_path / "other.step").write_text("other v1\n")
    (tmp_path / "outline.dxf").write_text("outline v1\n")
    return tmp_path


def _keys(path):
    """Every key, from a context of its own: the way a new command sees them."""
    ctx = pc.Context(str(path))

    async def collect():
        keys = {}
        for name in ("cube", "other", "slab", "merged"):
            keys[name] = await (await ctx._get_part_async(":" + name)).get_cache_key_async()
        keys["assembly"] = await ctx._get_assembly(":assembly").get_cache_key_async()
        return keys

    return asyncio.run(collect())


def _moved(before, after):
    return {name for name in before if before[name] != after[name]}


def test_editing_a_linked_part_moves_every_key_built_from_it(package):
    before = _keys(package)
    assert None not in before.values()

    (package / "cube.step").write_text("cube v2\n")

    assert _moved(before, _keys(package)) == {"cube", "assembly", "merged"}


def test_editing_a_sketch_moves_the_key_of_its_extrusion(package):
    before = _keys(package)

    (package / "outline.dxf").write_text("outline v2\n")

    assert _moved(before, _keys(package)) == {"slab"}


def test_editing_what_nothing_uses_moves_nothing_else(package):
    """Folding keys in must not cost a rebuild of objects that did not change."""
    before = _keys(package)

    (package / "other.step").write_text("other v2\n")

    assert _moved(before, _keys(package)) == {"other"}


def test_a_shape_keyed_on_its_whole_content_has_no_broken_dependencies(package):
    ctx = pc.Context(str(package))

    async def check():
        slab = await ctx._get_part_async(":slab")
        assembly = ctx._get_assembly(":assembly")
        await slab.get_cache_key_async()
        await assembly.get_cache_key_async()
        return slab.cache_dependencies_broken, assembly.cache_dependencies_broken

    assert asyncio.run(check()) == (False, False)


@pytest.mark.parametrize("edited", ["cube.step", "partcad.yaml"])
def test_a_warm_context_notices_a_file_it_read_was_edited(package, edited):
    """What the daemon asks before reusing a context it has kept warm."""
    ctx = pc.Context(str(package))
    asyncio.run(ctx._get_assembly(":assembly").get_cache_key_async())
    assert not ctx.sources_changed()

    with open(package / edited, "a") as f:
        f.write("\n# edited\n")

    assert ctx.sources_changed()
