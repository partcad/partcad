#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How a part that only exists once an assembly is built gets built.

A URDF link or a STEP component is not declared in 'partcad.yaml' - the
assembly's own source file declares it - so resolving one has to instantiate
that assembly first, and instantiating is asynchronous.

That crosses the sync/async boundary, and it used to be crossed with a
'threading.Thread(...).start(); .join()', to borrow an event loop that
'asyncio.run()' could not create on a thread that already had one. What these
pin down is that it is crossed the way the rest of the codebase crosses it -
an '_async' implementation with a synchronous wrapper - because the thread cost
three things at once:

* 'join()' blocked the caller's event loop for the whole build;
* the thread was invisible to 'threads_max' and to the traced executors in
  'ThreadPoolManager', which is where every other thread in the core comes from;
* moving the work off the calling thread threw away the ownership of
  'Assembly.lock', an RLock chosen to be re-entrant precisely so that a nested
  resolution -- an assembly resolving one of the parts it itself produces --
  passes through instead of blocking on a lock the waiting thread holds.
"""

import asyncio
import threading

import pytest

from partcad.project import Project


class _FakeAssembly:
    """An assembly that records how its instantiation was reached."""

    def __init__(self):
        self.children = []
        self.threads = []
        self.loops = []

    async def do_instantiate(self):
        self.threads.append(threading.current_thread().name)
        self.loops.append(id(asyncio.get_running_loop()))
        self.children.append("link")


class _SlowAssembly(_FakeAssembly):
    def __init__(self, delay=0.05):
        super().__init__()
        self.delay = delay

    async def do_instantiate(self):
        await asyncio.sleep(self.delay)
        await super().do_instantiate()


def _bare_project(assembly, owner="robot"):
    """A Project with only what the materialization path reads.

    __init__ wants a configuration, a directory and a context, none of which have
    anything to say about which thread the build happens on.
    """
    prj = Project.__new__(Project)
    prj.name = "//pkg"
    prj.parts = {}
    prj._object_configs = {"assembly": {owner: {"type": "urdf"}}}
    prj._derived_parts_lock = threading.Lock()
    prj._derived_parts_attempted = set()
    prj.get_assembly = lambda name, *args, **kwargs: assembly
    return prj


# ---- the cheap path ----------------------------------------------------------


def test_a_declared_part_builds_nothing():
    """The common case must not cost an event loop, let alone a thread."""
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)
    prj.parts = {"widget": object()}

    prj._materialize_derived_part("widget")

    assert assembly.threads == []


def test_a_name_no_assembly_produces_builds_nothing():
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    prj._materialize_derived_part("brackets/left")

    assert assembly.threads == []


def test_each_owner_is_claimed_once():
    """A build that produced nothing must not be repeated on every lookup."""
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    prj._materialize_derived_part("robot/base")
    assembly.children.clear()  # as an empty URDF would leave it
    prj._materialize_derived_part("robot/wheel")

    assert len(assembly.threads) == 1


# ---- the thread the build runs on --------------------------------------------


def test_the_sync_path_builds_on_the_calling_thread():
    """The heart of it. A thread hop is what lost 'Assembly.lock' ownership."""
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    prj._materialize_derived_part("robot/base")

    assert assembly.threads == [threading.current_thread().name]


def test_the_async_path_builds_on_the_callers_thread_and_loop():
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)
    seen = {}

    async def main():
        seen["thread"] = threading.current_thread().name
        seen["loop"] = id(asyncio.get_running_loop())
        await prj._materialize_derived_part_async("robot/base")

    asyncio.run(main())

    assert assembly.threads == [seen["thread"]]
    assert assembly.loops == [seen["loop"]], "the build must be awaited on the caller's own loop"


def test_the_async_path_does_not_block_the_callers_loop():
    """What 'thread.join()' did, and what a 75 minute silent CI hang looks like.

    The old code blocked the calling thread until the build finished. When the
    caller was a coroutine -- 'ProviderCart.add_object' is one -- that thread was
    an event loop, so every other task on it stopped, including whatever would
    have logged progress.
    """
    assembly = _SlowAssembly()
    prj = _bare_project(assembly)
    ticks = []

    async def main():
        async def ticker():
            while True:
                await asyncio.sleep(0.005)
                ticks.append(1)

        task = asyncio.create_task(ticker())
        await prj._materialize_derived_part_async("robot/base")
        task.cancel()

    asyncio.run(main())

    assert ticks, "the loop made no progress while the assembly was being built"


# ---- what a coroutine reaching the synchronous accessor gets ------------------


def test_the_sync_accessor_refuses_a_running_loop_by_name():
    """Loudly, and naming the way out.

    Borrowing a thread to get a clean loop is what this replaces, so the one
    thing it must not do is quietly find another way to block the caller's loop.
    """
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    async def main():
        with pytest.raises(RuntimeError, match="get_part_async"):
            prj._materialize_derived_part("robot/base")

    asyncio.run(main())

    assert assembly.threads == []


def test_a_build_that_fails_is_reported_not_raised():
    """A part that cannot be built is a missing part, not an exception."""

    class Broken(_FakeAssembly):
        async def do_instantiate(self):
            raise Exception("the URDF is unreadable")

    prj = _bare_project(Broken())

    prj._materialize_derived_part("robot/base")  # must not raise

    async def main():
        await prj._materialize_derived_part_async("robot/base")

    prj._derived_parts_attempted.clear()
    asyncio.run(main())  # must not raise either
