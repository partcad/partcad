#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Objects built out of other objects, on thread pools of one, two and four threads.

What 'threadsMax: 2' stopped for good, as the objects that stopped it rather
than as the pool alone (that is 'test_sync_threads.py'): an alias built from
its source, an alias of an alias, a sketch alias, a part built out of an
assembly, each asked for at the same time as the object it is built from --
through 'Shape.get_wrapped()', its lock, 'Part.get_shape()' and a real
'ThreadPoolManager'. The objects whose own geometry would take a sandbox to
build have it replaced by a function that returns an envelope at once;
everything between that and the caller is real.

Two ways this deadlocked, and both are here. An object holding a slot asked
the same pool for a slot to build its source on. And the loop a command runs
on, asking for the source itself, took the source's lock and held it while the
source's build waited in the pool's queue -- behind the objects waiting for that
lock. A part and eight aliases of it, asked for at once, stopped that way on
four threads, the least 'threadsMax' allows.
"""

import asyncio
import pathlib
import threading
import time

import pytest
import yaml

import partcad as pc
import partcad.assembly
import partcad.part
import partcad.sketch
import partcad.sync_threads
from partcad import shape_envelope
from partcad.assembly import Assembly
from partcad.part import Part
from partcad.shape import Shape
from partcad.sync_threads import ThreadPoolManager

pytestmark = pytest.mark.timeout(120)

DEADLINE = 20

BREP = pathlib.Path(__file__).parent / "data" / "brep" / "solid.brep"


@pytest.fixture
def pool(monkeypatch):
    """Build on a 'ThreadPoolManager' of the test's own, of the size it asks for."""
    made = []

    def install(threads):
        manager = ThreadPoolManager(threads)
        made.append(manager)
        for module in (partcad.sync_threads, partcad.part, partcad.sketch, partcad.assembly):
            monkeypatch.setattr(module, "threadpool_manager", manager)
        return manager

    yield install
    for manager in made:
        manager.constrained_executor.shutdown(wait=False, cancel_futures=True)
        manager.unconstrained_executor.shutdown(wait=False, cancel_futures=True)


def _envelope(name):
    return shape_envelope.make_shape(b"brep", name=name, label=name)


def _parts(spec, builds):
    """Parts named by 'spec', each built from the part it names, or from nothing.

    A part built from nothing takes a moment, as a real build does, so that the
    others have time to come asking; every build of one is counted in 'builds'.
    """
    parts = {name: Part("//pkg", {"name": name}) for name in spec}
    for name, source in spec.items():
        if source is None:

            async def build(obj, name=name):
                builds.append(name)
                time.sleep(0.05)
                return _envelope(name)

        else:

            async def build(obj, source=source):
                time.sleep(0.01)
                return await parts[source].get_wrapped(None)

        parts[name].instantiate = build
    return parts


def _get_all(objects, ctx=None):
    async def main():
        return await asyncio.gather(*(obj.get_wrapped(ctx) for obj in objects))

    return asyncio.run(asyncio.wait_for(main(), timeout=DEADLINE))


SOURCE_AND_EIGHT_ALIASES = {"source": None, **{"alias-%d" % i: "source" for i in range(8)}}


@pytest.mark.parametrize(
    "threads, spec, order",
    [
        (1, {"source": None, "alias": "source"}, ["alias"]),
        (1, {"source": None, "a": "source", "b": "source"}, ["a", "b"]),
        (2, {"source": None, "a": "source", "b": "source"}, ["a", "b"]),
        (1, {"source": None, "alias": "source"}, ["alias", "source"]),
        (2, {"source": None, "a": "source", "b": "source"}, ["a", "b", "source"]),
        (1, {"source": None, "alias": "source", "alias-of-alias": "alias"}, ["alias-of-alias"]),
        (2, {"source": None, "alias": "source", "alias-of-alias": "alias"}, ["alias-of-alias", "alias", "source"]),
        (4, SOURCE_AND_EIGHT_ALIASES, ["alias-%d" % i for i in range(8)] + ["source"]),
        (4, SOURCE_AND_EIGHT_ALIASES, ["source"] + ["alias-%d" % i for i in range(8)]),
    ],
    ids=[
        "one alias, one thread",
        "two aliases, one thread",
        "two aliases, two threads",
        "an alias and its source, one thread",
        "two aliases and their source, two threads",
        "an alias of an alias, one thread",
        "an alias of an alias, the alias and the source, two threads",
        "eight aliases and then their source, four threads",
        "a source and then eight aliases of it, four threads",
    ],
)
def test_objects_built_from_objects_complete(pool, threads, spec, order):
    manager = pool(threads)
    builds = []
    parts = _parts(spec, builds)

    results = _get_all([parts[name] for name in order])

    assert all(shape_envelope.is_shape_envelope(result) for result in results)
    # Built once, however many objects asked for it at once.
    assert builds == ["source"]
    # And on no more threads than the pool has: an object waiting for a source
    # being built on a slot keeps its own, rather than letting another in to
    # wait beside it.
    assert len(manager.constrained_executor._threads._threads) <= threads


def test_the_loop_holding_the_source_s_lock_while_it_is_built(pool):
    """Some callers take a shape's lock first and ask for the shape inside it.

    'get_solidity_async' and 'get_bounding_box_async' do, so the loop holds the
    source's lock while the source is built -- and the aliases, each on a slot,
    wait for that lock. They give their slots back while they wait, or the build
    the loop is waiting for has none to run on.
    """
    pool(1)
    builds = []
    parts = _parts({"source": None, "a": "source", "b": "source"}, builds)
    source = parts["source"]

    async def solidity_like():
        # After the aliases have their slots, and long enough for them to reach
        # the source's lock while this holds it.
        await asyncio.sleep(0.005)
        async with source.locked():
            await asyncio.sleep(0.03)
            return await source.get_wrapped(None)

    async def main():
        return await asyncio.gather(parts["a"].get_wrapped(None), parts["b"].get_wrapped(None), solidity_like())

    results = asyncio.run(asyncio.wait_for(main(), timeout=DEADLINE))

    assert all(shape_envelope.is_shape_envelope(result) for result in results)
    assert builds == ["source"]


def test_a_part_built_out_of_an_assembly_the_loop_is_building(pool):
    """A compound of an assembly, asked for beside the assembly itself, on one thread.

    An assembly builds itself on the loop that asks for it, holding its lock
    while its children are built on the pool, so that they are spread over the
    pool. The compound, on the one slot, waits for that lock; the assembly's
    child waits for a slot. The compound gives its slot back, or neither ever
    finishes -- and the loop, which used to block on the compound's thread lock
    once it got round to it, would not even notice.
    """
    pool(1)
    assembly = Assembly("//pkg", {"name": "assembly"})
    child = Part("//pkg", {"name": "child"})
    compound = Part("//pkg", {"name": "compound"})

    async def build_child(obj):
        time.sleep(0.02)
        return _envelope("child")

    def instantiate_assembly(obj):
        time.sleep(0.02)
        obj.add(child, "child")

    async def build_compound(obj):
        return await assembly.get_wrapped(None)

    child.instantiate = build_child
    assembly.instantiate = instantiate_assembly
    compound.instantiate = build_compound

    async def main():
        async def the_assembly():
            # Once the compound has the one slot.
            await asyncio.sleep(0.01)
            return await assembly.get_wrapped(None)

        return await asyncio.gather(compound.get_wrapped(None), the_assembly())

    built_compound, built_assembly = asyncio.run(asyncio.wait_for(main(), timeout=DEADLINE))

    assert built_compound is not None and built_assembly is not None
    assert [node["label"] for node in built_assembly[shape_envelope.KEY_ASSEMBLY]] == ["child"]


def test_an_alias_does_not_wait_for_its_built_source_s_lock(pool):
    """A built source is read without its lock, which may be held for something else.

    Whoever holds a shape's lock may be writing that shape's files -- a render
    holds it for as long as the sandbox takes. An alias has no reason to wait
    for that once the geometry it needs is there.
    """
    pool(1)
    builds = []
    parts = _parts({"source": None, "alias": "source"}, builds)
    _get_all([parts["source"]])

    held = threading.Event()
    release = threading.Event()

    def hold_the_source():
        async def hold():
            async with parts["source"].locked():
                held.set()
                await asyncio.get_running_loop().run_in_executor(None, release.wait, DEADLINE)

        asyncio.run(hold())

    holder = threading.Thread(target=hold_the_source)
    holder.start()
    try:
        assert held.wait(DEADLINE)
        results = _get_all([parts["alias"]])
    finally:
        release.set()
        holder.join()

    assert shape_envelope.is_shape_envelope(results[0])
    assert builds == ["source"]


def test_a_part_asked_for_by_a_command_is_built_on_the_pool_with_its_lock(pool):
    """The lock is taken where the shape is built, not by the loop that asked.

    That is what lets an alias waiting for the lock wait for a thread that is
    building, rather than for a loop that is waiting for the pool.
    """
    pool(1)
    seen = {}
    part = Part("//pkg", {"name": "part"})

    async def build(obj):
        seen["builder"] = threading.get_ident()
        seen["holder"] = obj.lock._owner
        return _envelope("part")

    part.instantiate = build
    _get_all([part])

    assert seen["holder"] == seen["builder"] != threading.get_ident()


# ---- the same, through a real package --------------------------------------


PACKAGE = {
    "parts": {
        # 'cache: false', which the references take on, so that nothing here
        # reads or writes the shape cache: what is under test is the build.
        "base": {"type": "brep", "path": "solid.brep", "cache": False},
        "alias": {"type": "alias", "source": ":base"},
        "another-alias": {"type": "alias", "source": ":base"},
        "alias-of-alias": {"type": "alias", "source": ":alias"},
        "alias-of-alias-of-alias": {"type": "alias", "source": ":alias-of-alias"},
    },
    "sketches": {
        "outline": {"type": "basic", "circle": 2.0, "cache": False},
        "outline-alias": {"type": "alias", "source": ":outline"},
        "outline-alias-of-alias": {"type": "alias", "source": ":outline-alias"},
    },
}


@pytest.fixture
def package(tmp_path, monkeypatch):
    """A package of references, with the two objects at the bottom built without a sandbox.

    The aliases, the context they look their sources up in, the factories, the
    locks and the pool are PartCAD's own; only what 'base' and 'outline' would
    run a sandbox to produce is replaced, and so is the sandbox every part is
    validated in on its way out.
    """
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    (tmp_path / "solid.brep").write_bytes(BREP.read_bytes())
    ctx = pc.Context(str(tmp_path))

    async def as_it_came(self, ctx, envelope):
        return envelope

    monkeypatch.setattr(Shape, "_validated_part", as_it_came)

    builds = []
    for obj in (ctx._get_part(":base"), ctx._get_sketch(":outline")):

        async def build(shape, name=obj.name):
            builds.append(name)
            time.sleep(0.05)
            return _envelope(name)

        obj.instantiate = build
    return ctx, builds


@pytest.mark.parametrize("threads", [1, 2])
def test_a_package_of_references_builds_on_a_tiny_pool(pool, package, threads):
    """Every reference and every source at once, the references asked for first."""
    pool(threads)
    ctx, builds = package
    objects = [ctx._get_part(":" + name) for name in reversed(list(PACKAGE["parts"]))]
    objects += [ctx._get_sketch(":" + name) for name in reversed(list(PACKAGE["sketches"]))]
    assert all(obj is not None for obj in objects)

    results = _get_all(objects, ctx)

    assert all(shape_envelope.is_shape_envelope(result) for result in results)
    assert sorted(builds) == ["base", "outline"]
