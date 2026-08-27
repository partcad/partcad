#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the sandbox environment lock and the process budget promise.

These are what let a render run more than one wrapper at a time, so what is
worth pinning down is both halves of that: that wrappers reading one
environment do run together, and that an install into it still gets the
environment to itself.
"""

import asyncio

import pytest

from partcad.sandbox_lock import EnvironmentLock, ProcessSlots
from partcad import sandbox_lock


def _lock(tmp_path, name="env"):
    return EnvironmentLock(str(tmp_path / (name + ".lock")))


def test_get_returns_one_lock_per_path(tmp_path):
    """Two objects over one lock file would each believe they held it.

    filelock counts recursive acquires per object, so the second would take the
    file lock while the first still holds it and release it out from under it.
    """
    path = str(tmp_path / "env.lock")
    assert sandbox_lock.get(path) is sandbox_lock.get(path)
    assert sandbox_lock.get(path) is not sandbox_lock.get(str(tmp_path / "other.lock"))


def test_readers_share_the_environment(tmp_path):
    lock = _lock(tmp_path)
    with lock.acquire(write=False):
        with lock.acquire(write=False):
            with lock.acquire(write=False):
                pass


def test_a_writer_excludes_a_reader(tmp_path):
    lock = _lock(tmp_path)
    with lock.acquire(write=True):
        assert not lock._try_acquire(write=False)
        assert not lock._try_acquire(write=True)


def test_a_reader_excludes_a_writer(tmp_path):
    lock = _lock(tmp_path)
    with lock.acquire(write=False):
        assert not lock._try_acquire(write=True)


def test_the_environment_is_free_again_afterwards(tmp_path):
    lock = _lock(tmp_path)
    with lock.acquire(write=True):
        pass
    with lock.acquire(write=False):
        pass
    assert lock._try_acquire(write=True)
    lock._release(write=True)


def test_a_reader_waiting_defers_to_a_writer_waiting(tmp_path):
    """Otherwise a stream of wrappers starves the install one of them needs."""
    lock = _lock(tmp_path)
    with lock.acquire(write=False):
        lock._writers_waiting += 1
        try:
            assert not lock._try_acquire(write=False)
        finally:
            lock._writers_waiting -= 1


def test_another_process_is_kept_out_of_an_install(tmp_path):
    """Two installs into one environment are what actually leave it broken.

    A second EnvironmentLock over the same file stands in for a second PartCAD:
    filelock opens a descriptor of its own, and an flock over that conflicts
    with this one exactly as another process's would.
    """
    path = str(tmp_path / "env.lock")
    mine, theirs = EnvironmentLock(path), EnvironmentLock(path)
    with mine.acquire(write=True):
        assert not theirs._try_acquire(write=True)
    assert theirs._try_acquire(write=True)
    theirs._release(write=True)


def test_another_process_reading_is_not_kept_out(tmp_path):
    """Deliberate: reader against reader needs no exclusion at all.

    Paying for it with the one exclusive lock file there is would mean a busy
    render in one workspace stopping every other PartCAD process on the machine
    for as long as it runs. What that gives up is stated in sandbox_lock.
    """
    path = str(tmp_path / "env.lock")
    mine, theirs = EnvironmentLock(path), EnvironmentLock(path)
    with mine.acquire(write=False):
        assert theirs._try_acquire(write=False)
        theirs._release(write=False)


def test_a_reader_does_not_block_the_loop_a_writer_runs_on(tmp_path):
    """The reason waiting polls instead of blocking.

    A part is instantiated on a worker thread with an event loop of its own, so
    the same lock is taken from several loops -- but two tasks of one loop take
    it too, and a task that blocked its thread waiting for the task beside it to
    release would never see it released.
    """
    lock = _lock(tmp_path)
    order = []

    async def writer():
        async with lock.acquire_async(write=True):
            order.append("write-in")
            await asyncio.sleep(0.05)
            order.append("write-out")

    async def reader():
        await asyncio.sleep(0.01)
        async with lock.acquire_async(write=False):
            order.append("read")

    async def both():
        await asyncio.wait_for(asyncio.gather(writer(), reader()), timeout=10)

    asyncio.run(both())
    assert order == ["write-in", "write-out", "read"]


def test_readers_on_one_loop_do_not_wait_for_each_other(tmp_path):
    lock = _lock(tmp_path)

    async def reader(started, release):
        async with lock.acquire_async(write=False):
            started.set()
            await release.wait()

    async def both():
        release = asyncio.Event()
        first_started, second_started = asyncio.Event(), asyncio.Event()
        tasks = [
            asyncio.create_task(reader(first_started, release)),
            asyncio.create_task(reader(second_started, release)),
        ]
        await asyncio.wait_for(asyncio.gather(first_started.wait(), second_started.wait()), timeout=10)
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(both())


def test_process_slots_are_a_ceiling():
    slots = ProcessSlots(2)
    with slots.slot(), slots.slot():
        assert not slots._semaphore.acquire(blocking=False)
    with slots.slot():
        pass


def test_process_slots_wait_rather_than_fail():
    slots = ProcessSlots(1)
    running, peak = 0, 0

    async def work():
        nonlocal running, peak
        async with slots.slot_async():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    async def all_of_them():
        await asyncio.wait_for(asyncio.gather(*[work() for _ in range(5)]), timeout=10)

    asyncio.run(all_of_them())
    assert peak == 1


def test_a_cancelled_wait_leaves_nothing_behind():
    """A slot nobody got must not be released, or the ceiling drifts upwards."""
    slots = ProcessSlots(1)

    async def hold(started):
        async with slots.slot_async():
            started.set()
            await asyncio.sleep(0.2)

    async def scenario():
        started = asyncio.Event()
        holder = asyncio.create_task(hold(started))
        await started.wait()

        async def waiter():
            async with slots.slot_async():
                pass

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(waiter(), timeout=0.02)
        await holder

    asyncio.run(scenario())
    # One holder released one slot: exactly one is free, not two.
    assert slots._semaphore.acquire(blocking=False)
    assert not slots._semaphore.acquire(blocking=False)
