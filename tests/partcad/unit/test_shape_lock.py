#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The lock a shape holds over itself, and over the files it produces.

`Shape.locked()` answers one question for two things that used to be treated as
separate: instantiating a shape, and writing a file derived from it. They are the
same question because the *path* is derived from the shape -- `<part>.<format>`
beside the package -- so two concurrent runs over one shape resolve to one path
and step on each other there.

Like `test_concurrency.py` beside it, every case here is driven through
`asyncio.wait_for()`: a regression in a lock does not make a test slow, it makes
it never return, and a timeout is the failure being looked for.
"""

import asyncio
import threading

import pytest

from partcad.shape import Shape


def _shape():
    """A shape with nothing in it: only the locking machinery is under test."""
    return Shape("//test", {"name": "part"})


def test_a_shape_admits_one_holder_at_a_time():
    """The plain case: two tasks over one shape do not overlap."""

    async def scenario():
        shape = _shape()
        order = []

        async def hold(name):
            async with shape.locked():
                order.append(("enter", name))
                # Without the lock the sleep is where the other task gets in.
                await asyncio.sleep(0.01)
                order.append(("leave", name))

        await asyncio.gather(*(hold(n) for n in range(4)))
        return order

    order = asyncio.run(asyncio.wait_for(scenario(), timeout=10))
    # Every "enter" is followed by its own "leave" and nobody else's.
    pairs = [(order[i], order[i + 1]) for i in range(0, len(order), 2)]
    assert all(a[0] == "enter" and b == ("leave", a[1]) for a, b in pairs), order


def test_the_lock_is_re_entrant_within_one_task():
    """The operations nest, so a second acquisition must pass straight through.

    `analyze_async` holds this across clearing the path, running the
    implementation and verifying the file; inside that it calls `get_wrapped`
    and `_run_implementation_async`, each of which takes the same lock in its own
    right. `threading.RLock` allows that already; an `asyncio.Lock` does not, and
    the second acquisition would wait for a release only the waiting task can
    perform. That is a hang, not a slowdown -- hence the timeout.
    """

    async def scenario():
        shape = _shape()
        async with shape.locked():
            async with shape.locked():
                async with shape.locked():
                    return "reached"

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=10)) == "reached"


def test_a_second_task_still_waits():
    """Re-entrancy is for the holder, not for everybody: it is still a lock."""

    async def scenario():
        shape = _shape()
        seen = []

        async def holder():
            async with shape.locked():
                seen.append("held")
                await asyncio.sleep(0.05)
                seen.append("released")

        async def latecomer():
            await asyncio.sleep(0.01)
            async with shape.locked():
                seen.append("second")

        await asyncio.gather(holder(), latecomer())
        return seen

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=10)) == ["held", "released", "second"]


def test_an_exception_releases_the_lock():
    """A run that raised must not leave the shape locked for the process."""

    async def scenario():
        shape = _shape()
        with pytest.raises(RuntimeError):
            async with shape.locked():
                raise RuntimeError("the implementation failed")
        async with shape.locked():
            return "reacquired"

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=10)) == "reacquired"


def test_two_runs_do_not_take_each_other_s_model():
    """The defect this exists for, as the sequence that produced it.

    `analyze_async` clears the output path, asks the implementation to write it,
    and then reads the file's existence as the answer to "did this run produce a
    model". Two concurrent runs resolve to the *same* path, so unheld, the
    second one's `os.remove` lands between the first one's write and the first
    one's check -- and a run that succeeded reports that it produced nothing, or
    hands back the other run's file.
    """

    async def scenario():
        shape = _shape()
        on_disk = set()
        lost = []

        async def analyse(n):
            async with shape.locked():
                on_disk.discard("model")  # os.remove(final_filepath)
                await asyncio.sleep(0.01)
                on_disk.add("model")  # the implementation writes it
                await asyncio.sleep(0.01)
                if "model" not in on_disk:  # the existence check
                    lost.append(n)

        await asyncio.gather(*(analyse(n) for n in range(5)))
        return lost

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=10)) == []


def test_each_thread_locks_on_its_own_loop():
    """PartCAD runs an `asyncio.run()` per worker thread, and a lock bound to one
    loop cannot be awaited under another. The shape must still be exclusive.
    """
    shape = _shape()
    order = []
    barrier = threading.Lock()

    def worker(name):
        async def scenario():
            async with shape.locked():
                with barrier:
                    order.append(("enter", name))
                await asyncio.sleep(0.01)
                with barrier:
                    order.append(("leave", name))

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a thread never finished: the lock did not release"
    # `threading.RLock` is what serializes across threads; each thread's own
    # `asyncio.Lock` belongs to the loop it was created under.
    pairs = [(order[i], order[i + 1]) for i in range(0, len(order), 2)]
    assert all(a[0] == "enter" and b == ("leave", a[1]) for a, b in pairs), order
