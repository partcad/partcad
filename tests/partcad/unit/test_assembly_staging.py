#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The first phase of building an assembly: what has to be built before it.

An assembly is built out of other assemblies, and each of those can take
minutes. So a daemon asked for one looks before it builds: it reads what the
assembly places and asks which of those are not cached yet, which is what its
client then builds one request at a time (see 'partcad_utils.staging').

What is under test here is the reading, and it reads a declaration rather than
geometry: the fixture package's parts are never built, so none of this needs a
CAD sandbox.
"""

import asyncio

import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad.cache_shape import ShapeCache

DATA = "tests/partcad/unit/data/assembly_staging"

# The package is the root of this workspace, so its own name is '//'. An
# instance placed with parameter values of its own is registered - and so has to
# be asked for - under a name carrying them.
UNIT = ("//", "unit")
UNIT_WIDE = ("//", "unit;gap=4.0")


def names(assemblies):
    return [(item.project_name, item.name) for item in assemblies]


def uncached(ctx, assembly):
    return names(asyncio.run(assembly.get_uncached_subassemblies_async(ctx)))


@pytest.fixture
def ctx(tmp_path):
    """The fixture package, with a shape cache of this test's own.

    The cache decides what the first phase reports, so it must not be the one
    the machine running the tests has been filling: an entry left there by
    something else would make this answer "nothing to build" for a reason that
    has nothing to do with the code under test.
    """
    context = pc.Context(DATA)
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "state"))
    return context


def test_the_assemblies_an_assembly_places_are_the_ones_it_links_to(ctx):
    top = ctx._get_assembly(":top")
    assert top is not None

    # Every link naming an assembly, in the order the file names them, the one
    # inside the container node included -- that node is assembled here, but
    # what it places is placed all the same.
    assert names(asyncio.run(top.get_subassemblies_async())) == [UNIT, UNIT, UNIT_WIDE, UNIT]


def test_an_assembly_placed_several_times_is_one_thing_to_build(ctx):
    top = ctx._get_assembly(":top")

    # Three links to one instance, and a second instance of the same assembly:
    # two things to build, not four.
    assert uncached(ctx, top) == [UNIT, UNIT_WIDE]


def test_what_is_reported_is_what_a_client_can_ask_for_by_name(ctx):
    """The package and the name are the request that builds it."""
    top = ctx._get_assembly(":top")
    pending = asyncio.run(top.get_uncached_subassemblies_async(ctx))

    for item in pending:
        assert ctx._get_assembly("%s:%s" % (item.project_name, item.name)) is item


def test_an_assembly_built_out_of_parts_alone_has_nothing_to_build_first(ctx):
    """Parts are not staged: a part is built out of its own files."""
    unit = ctx._get_assembly(":unit")

    assert uncached(ctx, unit) == []


def test_an_assembly_already_in_memory_is_not_reported(ctx):
    top = ctx._get_assembly(":top")
    for sub in asyncio.run(top.get_subassemblies_async()):
        sub._wrapped = {"assembly": []}

    assert uncached(ctx, top) == []


def test_a_cached_assembly_is_not_reported(ctx):
    """What the cache holds costs nothing to use, so it is not work to do."""
    top = ctx._get_assembly(":top")
    pending = asyncio.run(top.get_uncached_subassemblies_async(ctx))
    assert pending, "the fixture is meant to have something to build"

    # Written as a build would leave it, and read back as an existence check
    # rather than as geometry -- which is the whole reason a large assembly can
    # be asked about at all.
    asyncio.run(ctx.cache_shapes.write_data_async(pending[0].hash, {"assembly": b"\x28\xb5\x2f\xfdcached"}))

    assert uncached(ctx, top) == names(pending[1:])


def test_an_alias_is_built_by_building_what_it_points_at(ctx):
    """An alias holds no geometry of its own; the source is what has to be built."""
    alias = ctx._get_assembly(":top_alias")
    assert alias is not None

    assert names(asyncio.run(alias.get_subassemblies_async())) == [("//", "top")]


def test_an_assembly_nobody_declared_places_nothing_of_its_own(ctx):
    """One put together in Python has no declaration to read links out of."""
    assembly = pc.Assembly({"name": "hand-made"})

    assert asyncio.run(assembly.get_subassemblies_async()) == []
