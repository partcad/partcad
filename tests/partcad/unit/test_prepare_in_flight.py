#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A shape's key is read once its preparation is over, whoever began it.

'Shape.prepare_async()' raises its flag as a preparation *begins*, and anyone
else who asked meanwhile used to return on it and read the key: a parent
assembly keying itself on a part it links to, 'pc install', a build reading the
cache. What the preparation hashes in - the file a 'fileFrom' or a plugin
fetches, the keys of what an assembly links to - was not in the hash yet, and a
hash adds its files when it is first read, so the shape kept that key, file
left out, for as long as the process lived.

A key reader now waits for the preparation. Two waits could never end, and
these hold them to not starting: a cycle of preparations, and a thread that
holds a shape's lock waiting for a preparation on another thread - which that
lock may be what stops. Each test that could hang has a timeout of its own.
"""

import asyncio
import logging
import threading

import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad import shape as pc_shape
from partcad.actions.package.install import install_async
from partcad.cache_hash import CacheHash
from partcad.cache_shape import ShapeCache
from partcad.shape import Shape

# How long anything here may take before it is taken to have hung, in seconds.
HANG = 20.0

_PACKAGE = """
parts:
  cube:
    type: step
    path: cube.step
assemblies:
  assembly:
    type: assy
"""


@pytest.fixture
def package(tmp_path):
    (tmp_path / "partcad.yaml").write_text(_PACKAGE)
    (tmp_path / "assembly.assy").write_text("links:\n  - part: cube\n")
    # Only the bytes matter here: nothing is built, only keyed.
    (tmp_path / "cube.step").write_text("cube v1\n")
    return tmp_path


def _keys(path):
    """The part's and the assembly's keys, from a context of their own: what they should be."""
    ctx = pc.Context(str(path))

    async def collect():
        part = await (await ctx._get_part_async(":cube")).get_cache_key_async()
        assembly = await ctx._get_assembly(":assembly").get_cache_key_async()
        return part, assembly

    return asyncio.run(collect())


def _being_fetched(path, ctx, delay=0.1, begun=None):
    """The part, its file not there until a preparation that takes 'delay' seconds has fetched it.

    What a 'fileFrom' or a repository plugin does. 'begun', a threading.Event,
    is set once the preparation is under way.
    """
    part = ctx.get_part(":cube")
    assert part is not None
    content = (path / "cube.step").read_text()
    (path / "cube.step").unlink()

    async def fetch(shape):
        if begun is not None:
            begun.set()
        await asyncio.sleep(delay)
        (path / "cube.step").write_text(content)

    part._prepare = fetch
    return part


def test_a_key_read_while_the_part_is_being_fetched_has_the_file_in_it(package, caplog):
    """Every reader gets the key of the fetched file, and so does the assembly linking the part."""
    part_key, assembly_key = _keys(package)
    ctx = pc.Context(str(package))
    part = _being_fetched(package, ctx)

    async def main():
        preparation = asyncio.create_task(part.prepare_async())
        await asyncio.sleep(0)
        keys = await asyncio.gather(
            part.get_cache_key_async(),
            part.get_cache_key_async(),
            ctx._get_assembly(":assembly").get_cache_key_async(),
        )
        await preparation
        return keys

    with caplog.at_level(logging.WARNING):
        keys = asyncio.run(asyncio.wait_for(main(), HANG))

    assert keys == [part_key, part_key, assembly_key]
    assert "Hash update after being used" not in caplog.text


def test_pc_install_keys_an_assembly_on_the_part_it_is_fetching_at_the_same_time(package):
    """'pc install' prepares a package's objects concurrently, the part and the assembly linking it together."""
    part_key, assembly_key = _keys(package)
    ctx = pc.Context(str(package))
    part = _being_fetched(package, ctx)

    stats = asyncio.run(asyncio.wait_for(install_async(ctx, [ctx.get_current_project_path()]), HANG))

    assert stats["failed"] == 0 and stats["part"] == 1 and stats["assembly"] == 1
    assert asyncio.run(part.get_cache_key_async()) == part_key
    assert asyncio.run(ctx._get_assembly(":assembly").get_cache_key_async()) == assembly_key


#
# Cycles of preparations
#

_CYCLE = """
assemblies:
  x:
    type: assy
  y:
    type: assy
"""


@pytest.fixture
def cycle(tmp_path):
    """Two assemblies that link each other: a broken package, which must still not hang anything."""
    (tmp_path / "partcad.yaml").write_text(_CYCLE)
    (tmp_path / "x.assy").write_text("links:\n  - assembly: y\n")
    (tmp_path / "y.assy").write_text("links:\n  - assembly: x\n")
    ctx = pc.Context(str(tmp_path))
    return ctx, ctx._get_assembly(":x"), ctx._get_assembly(":y")


def _slowed(shape, delay=0.05):
    """Make 'shape''s preparation hand its loop back before it does anything, so that two can interleave."""
    hook = shape._prepare

    async def slow(target):
        await asyncio.sleep(delay)
        await hook(target)

    shape._prepare = slow


def test_a_shape_that_links_back_to_itself_has_no_key_and_does_not_hang(cycle):
    _ctx, x, y = cycle

    key = asyncio.run(asyncio.wait_for(x.get_cache_key_async(), HANG))

    # Keyed on itself is keyed on nothing: neither of the two can be cached.
    assert key is None
    assert asyncio.run(asyncio.wait_for(y.get_cache_key_async(), HANG)) is None


def test_two_preparations_waiting_for_each_other_do_not_hang(cycle):
    """X's preparation waits for Y, which is being prepared by another task that needs X: refused, not waited."""
    _ctx, x, y = cycle
    _slowed(x)
    _slowed(y)

    async def both():
        return await asyncio.gather(x.get_cache_key_async(), y.get_cache_key_async())

    assert asyncio.run(asyncio.wait_for(both(), HANG)) == [None, None]


#
# A shape's lock
#


def test_a_thread_holding_a_shape_s_lock_does_not_wait_for_another_thread_s_preparation(package):
    """The wait that would deadlock: the preparer's thread is stopped by the very lock the reader holds.

    Thread A prepares the part, and while that is under way, a second task on
    A's loop asks for the assembly's lock, which thread B holds - so A, and the
    preparation with it, stops until B lets go. B, holding the lock, asks for
    the part's key. Waiting for the preparation there would never end. It is
    not waited for: B gets no key, lets go of the lock, A finishes the
    preparation, and the key is then the fetched file's - not the key of a file
    that was not there yet.
    """
    part_key, _assembly_key = _keys(package)
    ctx = pc.Context(str(package))
    begun, held = threading.Event(), threading.Event()
    part = _being_fetched(package, ctx, delay=0.5, begun=begun)
    assembly = ctx._get_assembly(":assembly")
    seen = {}

    def preparer():
        async def stopped_by_the_lock():
            while not held.is_set():
                await asyncio.sleep(0.01)
            with assembly.lock:
                pass

        async def main():
            await asyncio.gather(part.prepare_async(), stopped_by_the_lock())

        asyncio.run(main())

    def reader():
        assert begun.wait(HANG)
        with assembly.lock:
            held.set()
            try:
                seen["key"] = asyncio.run(asyncio.wait_for(part.get_cache_key_async(), HANG))
            except asyncio.TimeoutError:
                seen["key"] = "waited for a preparation that the lock it holds had stopped"

    threads = [threading.Thread(target=preparer, daemon=True), threading.Thread(target=reader, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(HANG)
    assert not any(thread.is_alive() for thread in threads), "the two threads deadlocked"

    assert seen["key"] is None
    assert asyncio.run(part.get_cache_key_async()) == part_key


def test_a_task_holding_a_shape_s_lock_waits_for_a_preparation_on_its_own_thread(package):
    """How an assembly's children are built: on the thread that holds the assembly's lock, which can wait."""
    part_key, _assembly_key = _keys(package)
    ctx = pc.Context(str(package))
    part = _being_fetched(package, ctx)
    assembly = ctx._get_assembly(":assembly")

    async def main():
        preparation = asyncio.create_task(part.prepare_async())
        await asyncio.sleep(0)
        async with assembly.locked():
            key = await part.get_cache_key_async()
        await preparation
        return key

    assert asyncio.run(asyncio.wait_for(main(), HANG)) == part_key


#
# Building
#

BREP = b"CASCADE Topology V3, (c) Open Cascade\n\nLocations 0\n"


class _Ctx:
    def __init__(self, tmp_path):
        self.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path))


class _Part(Shape):
    """A part whose factory hands back an envelope, with no sandbox involved."""

    def __init__(self):
        super().__init__("pkg", {"name": "bracket"})
        self.name = "bracket"
        self.kind = "part"
        self.hash.add_string("geometry")

    async def get_shape(self, ctx):
        return {"name": None, "label": None, "brep": BREP}


def test_a_build_begun_while_another_task_prepares_the_shape_is_cached_under_the_whole_key(tmp_path, caplog):
    """'get_wrapped()' prepares before it takes the shape's lock, and waits there for a preparation under way."""
    part = _Part()

    async def adds(shape):
        await asyncio.sleep(0.1)
        # What a preparation adds to the key: a linked object's key, say.
        shape.hash.add_string("what the preparation adds")

    part._prepare = adds
    expected = CacheHash("pkg:bracket", cache=True)
    expected.add_string("geometry")
    expected.add_string("what the preparation adds")

    async def main():
        preparation = asyncio.create_task(part.prepare_async())
        await asyncio.sleep(0)
        await part.get_wrapped(_Ctx(tmp_path))
        await preparation

    with caplog.at_level(logging.WARNING):
        asyncio.run(asyncio.wait_for(main(), HANG))

    assert "Hash update after being used" not in caplog.text
    assert part.hash.get() == expected.get()
    assert (tmp_path / "cache" / "shapes" / ("%s.part" % expected.get())).exists()


def test_the_wait_is_bounded(package, monkeypatch, caplog):
    """A preparation that never finishes costs the reader the bound, and the key: not the run."""
    monkeypatch.setattr(pc_shape, "_PREPARE_WAIT_MAX", 0.2)
    ctx = pc.Context(str(package))
    part = _being_fetched(package, ctx, delay=HANG * 10)

    async def main():
        preparation = asyncio.create_task(part.prepare_async())
        await asyncio.sleep(0)
        try:
            return await part.get_cache_key_async()
        finally:
            preparation.cancel()

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(asyncio.wait_for(main(), HANG)) is None
    assert "going on without its cache key" in caplog.text
