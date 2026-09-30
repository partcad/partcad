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
import os
import shutil

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


def _key_of(ctx, kind, name):
    async def get():
        if kind == "assembly":
            return await ctx._get_assembly(":" + name).get_cache_key_async()
        return await (await ctx._get_part_async(":" + name)).get_cache_key_async()

    return asyncio.run(get())


def test_nothing_built_out_of_an_uncached_part_is_cached(package):
    """'cache: false' on a part has to reach what it is part of.

    Its content is in no key, so an assembly keyed on its own file would go on
    being served, the part inside it as it was, after the part changed.
    """
    config = (package / "partcad.yaml").read_text()
    (package / "partcad.yaml").write_text(config.replace("path: cube.step", "path: cube.step\n    cache: false"))
    ctx = pc.Context(str(package))

    assert _key_of(ctx, "part", "cube") is None
    assert _key_of(ctx, "assembly", "assembly") is None
    assert _key_of(ctx, "part", "merged") is None
    # ...and nothing else is dragged down with them.
    assert _key_of(ctx, "part", "other") is not None


def test_nothing_extruded_from_an_uncached_sketch_is_cached(package):
    config = (package / "partcad.yaml").read_text()
    (package / "partcad.yaml").write_text(config.replace("path: outline.dxf", "path: outline.dxf\n    cache: false"))
    ctx = pc.Context(str(package))

    assert _key_of(ctx, "part", "slab") is None


def _connected_keys(path):
    ctx = pc.Context(str(path))

    async def collect():
        assembly = ctx._get_assembly(":connect-interfaces")
        motor = await ctx._get_part_async(":example-motor")
        return await assembly.get_cache_key_async(), await motor.get_cache_key_async()

    return asyncio.run(collect())


def test_editing_an_interface_moves_the_key_of_an_assembly_connected_through_it(tmp_path):
    """Where a connected part goes is its interface's to say, not the part's.

    A part's key covers the names of the interfaces it implements; what a port
    of one of them is at is declared in the interface, and moving it moves the
    part within every assembly that connects through it.
    """
    package = tmp_path / "feature_interface"
    shutil.copytree(os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples", "feature_interface"), package)
    assembly, motor = _connected_keys(package)
    assert assembly is not None

    config = (package / "partcad.yaml").read_text()
    moved = "TL: [[-16.5, 15.5, 0.0], [0.0, 0.0, 1.0], 270.0] # top left"
    assert "TL: [[-15.5, 15.5, 0.0], [0.0, 0.0, 1.0], 270.0] # top left" in config
    (package / "partcad.yaml").write_text(
        config.replace("TL: [[-15.5, 15.5, 0.0], [0.0, 0.0, 1.0], 270.0] # top left", moved, 1)
    )

    moved_assembly, moved_motor = _connected_keys(package)
    assert moved_motor == motor
    assert moved_assembly != assembly
