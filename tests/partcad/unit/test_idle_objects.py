#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The geometry kept in memory between uses, and what goes first when memory is wanted back."""

import asyncio
import gc

from cache_config import CacheUserConfig

from partcad import idle_objects
from partcad.cache_shape import ShapeCache
from partcad.idle_objects import LARGE, SMALL, TRANSIENT, IdleObjects, in_use
from partcad.shape import Shape

BREP = b"CASCADE Topology V3, (c) Open Cascade\n\nLocations 0\n"


class _Holder:
    """Anything that keeps an envelope the way a shape does."""

    def __init__(self, envelope=None):
        self._wrapped = envelope if envelope is not None else {"brep": b"x"}


def _kept(registry, kind, size=10):
    holder = _Holder()
    registry.keep(holder, holder._wrapped, size, kind)
    return holder


# ---- in use ----------------------------------------------------------------------


def test_an_envelope_nobody_else_holds_is_idle():
    assert not in_use(_Holder())


def test_an_envelope_somebody_holds_is_in_use():
    holder = _Holder()
    tree = holder._wrapped
    assert in_use(holder)
    del tree
    assert not in_use(holder)


def test_an_envelope_placed_in_a_bigger_tree_is_in_use():
    holder = _Holder()
    parent = {"assembly": [holder._wrapped]}
    assert in_use(holder)
    parent.clear()
    assert not in_use(holder)


def test_an_envelope_a_waiting_coroutine_holds_is_in_use():
    """A render waiting for a sandbox with the tree in hand is using it."""
    holder = _Holder()

    async def render(tree, started, release):
        started.set()
        await release.wait()
        return tree

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(render(holder._wrapped, started, release))
        await started.wait()
        assert in_use(holder)
        release.set()
        await task

    asyncio.run(scenario())
    gc.collect()
    assert not in_use(holder)


# ---- what goes first ---------------------------------------------------------------


def test_large_objects_go_before_small_ones_and_the_least_recently_used_first():
    registry = IdleObjects()
    small = _kept(registry, SMALL, 10)
    old_large = _kept(registry, LARGE, 100)
    new_large = _kept(registry, LARGE, 100)

    assert registry.free(50) == 100
    assert old_large._wrapped is None
    assert new_large._wrapped is not None
    assert small._wrapped is not None

    assert registry.free(150) == 110
    assert new_large._wrapped is None
    assert small._wrapped is None


def test_using_an_object_makes_it_the_last_of_its_list_to_go():
    registry = IdleObjects()
    first = _kept(registry, LARGE, 100)
    second = _kept(registry, LARGE, 100)
    registry.touch(first)

    registry.free(1)
    assert second._wrapped is None
    assert first._wrapped is not None


def test_an_object_in_use_is_never_freed():
    registry = IdleObjects()
    used = _kept(registry, LARGE, 100)
    idle = _kept(registry, SMALL, 10)
    tree = used._wrapped

    assert registry.free(1000) == 10
    assert used._wrapped is tree
    assert idle._wrapped is None
    # And it is still on its list, to be freed once nothing uses it.
    del tree
    assert registry.free(1000) == 100


def test_a_transient_object_goes_as_soon_as_nothing_uses_it():
    """Over 1 MB with a disk tier holding it: kept for its users, not for later."""
    registry = IdleObjects()
    transient = _kept(registry, TRANSIENT, 5_000_000)
    large = _kept(registry, LARGE, 100_000_000)
    tree = transient._wrapped

    assert registry.sweep() == 0
    assert transient._wrapped is tree
    del tree
    assert registry.sweep() == 5_000_000
    assert transient._wrapped is None
    # A sweep frees nothing else: the others are kept until memory is wanted.
    assert large._wrapped is not None


def test_freeing_takes_the_unused_transient_objects_whatever_was_asked_for():
    registry = IdleObjects()
    transient = _kept(registry, TRANSIENT, 5_000_000)
    large = _kept(registry, LARGE, 100)
    assert registry.free(1) == 5_000_000
    assert transient._wrapped is None
    assert large._wrapped is not None


def test_an_entry_whose_shape_keeps_something_else_now_is_dropped_and_frees_nothing():
    registry = IdleObjects()
    holder = _kept(registry, LARGE, 100)
    replacement = {"brep": b"y"}
    holder._wrapped = replacement

    assert registry.free(1000) == 0
    assert holder._wrapped is replacement
    assert registry.held()[LARGE]["objects"] == 0


def test_an_entry_whose_shape_is_gone_is_dropped():
    registry = IdleObjects()
    _kept(registry, SMALL, 10)
    gc.collect()
    assert registry.free(1000) == 0
    assert registry.held()[SMALL]["objects"] == 0


def test_held_says_how_much_each_list_holds():
    registry = IdleObjects()
    keep = [_kept(registry, LARGE, 100), _kept(registry, LARGE, 50), _kept(registry, SMALL, 5)]
    assert registry.held() == {
        TRANSIENT: {"objects": 0, "bytes": 0},
        LARGE: {"objects": 2, "bytes": 150},
        SMALL: {"objects": 1, "bytes": 5},
    }
    assert keep


# ---- what a shape keeps ------------------------------------------------------------


class _Ctx:
    def __init__(self, tmp_path, **config):
        self.user_config = CacheUserConfig(tmp_path, **config)
        self.cache_shapes = ShapeCache(user_config=self.user_config)


class _Part(Shape):
    """A part whose factory hands back an envelope of 'size' bytes, with no sandbox involved."""

    def __init__(self, name, size=100):
        super().__init__("pkg", {"name": name})
        self.name = name
        self.kind = "part"
        self.hash.add_string("geometry-%s" % name)
        self.size = size
        self.built = 0

    async def get_shape(self, ctx):
        self.built += 1
        return {"name": None, "label": None, "brep": BREP + b"x" * self.size}


def _kind_of(shape):
    with idle_objects.idle_objects._lock:
        return idle_objects.idle_objects._kind_of.get(id(shape))


def test_a_small_part_is_kept_on_the_small_list(tmp_path):
    ctx = _Ctx(tmp_path, cache_memory_double_cache_max_entry_size=1000)
    part = _Part("small", size=10)
    asyncio.run(part.get_wrapped(ctx))
    assert _kind_of(part) == SMALL


def test_a_large_part_on_disk_is_kept_only_while_used(tmp_path):
    """Its outputs share one copy while any of them runs, and nothing keeps it after."""
    ctx = _Ctx(tmp_path, cache_memory_double_cache_max_entry_size=1000)
    part = _Part("large", size=5000)
    tree = asyncio.run(part.get_wrapped(ctx))
    assert _kind_of(part) == TRANSIENT

    # A second user gets the same copy, not a second one read from disk.
    assert asyncio.run(part.get_wrapped(ctx)) is tree
    idle_objects.idle_objects.sweep()
    assert part._wrapped is tree

    del tree
    idle_objects.idle_objects.sweep()
    assert part._wrapped is None

    # And it comes back from the disk, not from being built again.
    again = asyncio.run(part.get_wrapped(ctx))
    assert again["brep"].endswith(b"x" * 5000)
    assert part.built == 1


def test_a_large_part_nothing_persistent_holds_is_kept_until_memory_is_wanted(tmp_path):
    ctx = _Ctx(tmp_path, cache=False, cache_memory_double_cache_max_entry_size=1000)
    part = _Part("unstored", size=5000)
    asyncio.run(part.get_wrapped(ctx))
    assert _kind_of(part) == LARGE

    idle_objects.idle_objects.sweep()
    assert part._wrapped is not None

    idle_objects.idle_objects.free(1)
    assert part._wrapped is None
    # Built again when asked for again: there is nothing else to get it from.
    asyncio.run(part.get_wrapped(ctx))
    assert part.built == 2
    idle_objects.idle_objects.forget(part)


def test_an_object_over_the_memory_limit_is_not_kept(tmp_path):
    """Built again on each use, as it always was, whether a disk tier holds it or not."""
    for ctx in (
        _Ctx(tmp_path / "unstored", cache=False, cache_memory_max_entry_size=1000),
        _Ctx(tmp_path / "stored", cache_memory_max_entry_size=1000),
    ):
        part = _Part("huge", size=5000)
        asyncio.run(part.get_wrapped(ctx))
        assert part._wrapped is None
        assert _kind_of(part) is None


def test_a_sweep_drops_the_entries_of_shapes_that_are_gone():
    registry = IdleObjects()
    _kept(registry, LARGE, 100)
    replaced = _kept(registry, SMALL, 10)
    replaced._wrapped = None
    alive = _kept(registry, LARGE, 100)
    gc.collect()

    assert registry.sweep() == 0
    assert registry.held()[LARGE] == {"objects": 1, "bytes": 100}
    assert registry.held()[SMALL] == {"objects": 0, "bytes": 0}
    assert alive._wrapped is not None
