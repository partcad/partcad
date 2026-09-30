#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Two different objects must not share a cache entry.

A shape's hash is seeded with nothing that identifies the shape itself (see
Shape.__init__), so everything that tells two of them apart has to be added by
the factory that builds them. Where it is not, the cache hands whichever of
them asks first the geometry of another -- silently, and only once the cache is
warm, which is why it survived being rendered.
"""

import asyncio

import pytest

import partcad as pc


@pytest.fixture
def ctx():
    return pc.Context("examples")


def _keys(ctx, package, names):
    async def collect():
        return [await ctx.get_part("%s:%s" % (package, name)).get_cache_key_async() for name in names]

    return asyncio.run(collect())


def test_extruded_parts_of_one_package_are_cached_apart(ctx):
    """'cylinder' and 'clock' are both an extrusion 1mm deep of another sketch."""
    keys = _keys(ctx, "//pub/examples/partcad/produce_part_extrude", ["cylinder", "clock", "dxf"])
    assert None not in keys
    assert len(set(keys)) == len(keys), "extruded parts share a cache entry: %s" % keys


def test_swept_parts_of_one_package_are_cached_apart(ctx):
    keys = _keys(ctx, "//pub/examples/partcad/produce_part_sweep", ["pipe", "clock", "dxf"])
    assert None not in keys
    assert len(set(keys)) == len(keys), "swept parts share a cache entry: %s" % keys
