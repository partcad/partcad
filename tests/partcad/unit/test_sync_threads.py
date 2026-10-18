#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The thread pools PartCAD builds on, and the two rules that keep them from deadlocking.

An object built out of another one -- an alias, an extrusion of a sketch -- is
built on a slot of the constrained pool, and asks for the other one from there.
When that took a second slot, as many such objects at once as the pool had
threads each held one and waited for another, for good: 'threadsMax: 2' stopped
'pc render -r', and the pools of four and seven PartCAD actually runs with
stopped the same way with four and seven such objects at once. Every case here
uses a real 'ThreadPoolManager', most of them with one or two threads, which the
configuration never allows (see 'THREADS_MAX_MINIMUM') and which nothing about
the pools needs any more.

Like 'test_concurrency.py', every case is driven against a wall clock: a
regression does not make these slow, it makes them never return, so each one
runs under 'asyncio.wait_for()' and a timeout is the failure being looked for.
The module-wide 'timeout' mark is the backstop for a wait that blocks a thread
outright, which 'wait_for' cannot interrupt.
"""

import asyncio
import threading
import time

import pytest
from opentelemetry import context as otel_context

from partcad.sync_threads import PoolAwareRLock, ThreadPoolManager, current_slot

pytestmark = pytest.mark.timeout(120)

# Long enough for any of these to finish on a loaded machine many times over.
DEADLINE = 20


@pytest.fixture
def pools():
    """Make 'ThreadPoolManager's for one test, and stop them afterwards.

    With whatever was still queued cancelled: a regression leaves work waiting
    on work that will never run, and cancelling it is what lets those threads
    finish instead of outliving the test.
    """
    made = []

    def make(threads):
        manager = ThreadPoolManager(threads)
        made.append(manager)
        return manager

    yield make
    for manager in made:
        manager.constrained_executor.shutdown(wait=False, cancel_futures=True)
        manager.unconstrained_executor.shutdown(wait=False, cancel_futures=True)


def _run(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, timeout=DEADLINE))


# ---- work started on a slot runs on that slot -------------------------------


@pytest.mark.parametrize("threads", [1, 2, 4, 7])
def test_as_many_nested_objects_as_there_are_threads(pools, threads):
    """The deadlock itself: every slot held by an object waiting for its source.

    Each outer object takes a slot and, from it, asks the same pool for its
    source -- what 'PartFactoryAlias.instantiate' does through
    'source.get_wrapped()' -> 'Part.get_shape()' -> 'run_async'. The barrier
    makes sure every one of them holds its slot before any asks.
    """
    manager = pools(threads)
    everyone_holds_a_slot = threading.Barrier(threads, timeout=DEADLINE)

    async def source():
        return "source"

    async def alias():
        everyone_holds_a_slot.wait()
        return await manager.run_async(source)

    async def main():
        return await asyncio.gather(*(manager.run_async(alias) for _ in range(threads)))

    assert _run(main()) == ["source"] * threads


def test_nesting_is_as_deep_as_it_likes(pools):
    """An alias of an alias of an alias of a part, on one thread."""
    manager = pools(1)

    async def level(depth):
        if depth == 0:
            return "part"
        return await manager.run_async(level, depth - 1)

    assert _run(manager.run_async(level, 5)) == "part"


def test_nested_work_is_awaited_where_it_is(pools):
    """On the same thread, in the same loop, as part of the same task.

    The same task matters: 'Shape.locked()' is re-entrant per task, so a source
    asked for from inside a locked shape still holds what the caller held, and
    a nested coroutine is in the caller's trace rather than a stranger's.
    """
    manager = pools(1)

    async def where():
        return threading.get_ident(), asyncio.get_running_loop(), asyncio.current_task()

    async def outer():
        here = threading.get_ident(), asyncio.get_running_loop(), asyncio.current_task()
        return here, await manager.run_async(where)

    outside, inside = _run(manager.run_async(outer))
    assert outside == inside


def test_top_level_work_still_fans_out_over_the_whole_pool(pools):
    """What is asked for from outside the pools is what keeps the machine busy.

    Four pieces of work, four slots, and a barrier only all four together can
    pass: run one after another they would wait at it forever.
    """
    manager = pools(4)
    all_four = threading.Barrier(4, timeout=DEADLINE)

    async def work():
        all_four.wait()
        return threading.get_ident()

    async def main():
        return await asyncio.gather(*(manager.run_async(work) for _ in range(4)))

    assert len(set(_run(main()))) == 4


def test_top_level_work_waits_for_a_slot(pools):
    """And no more of it runs at once than there are slots."""
    manager = pools(2)
    lock = threading.Lock()
    running = 0
    peak = 0

    def work():
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1

    async def main():
        await asyncio.gather(*(manager.run(work) for _ in range(8)))

    _run(main())
    assert peak == 2


def test_nested_synchronous_work_takes_no_slot(pools):
    """A function cannot be called on the slot holder's thread: it may run a loop of its own.

    An assembly's synchronous 'instantiate' does exactly that, with
    'asyncio.run()', which refuses to start inside a running loop. So it runs on
    a thread of its own, without waiting for a slot -- on a pool of one, while
    the one slot is held by the work waiting for it.
    """
    manager = pools(1)

    async def leaf():
        return threading.get_ident()

    def synchronous():
        return threading.get_ident(), asyncio.run(leaf())

    async def outer():
        return threading.get_ident(), await manager.run(synchronous)

    holder, (helper, helper_loop_thread) = _run(manager.run_async(outer))
    assert helper != holder
    assert helper_loop_thread == helper


def test_nested_work_on_the_other_pool_does_not_wait_for_its_slots(pools):
    """Across the two pools too: a part asking for an assembly's instantiation.

    Every slot of the unconstrained pool is held by work that only finishes once
    the nested call below has, so a nested call that waited for one of them
    would wait for ever.
    """
    manager = pools(1)
    slots = manager.unconstrained_executor.size
    release = threading.Event()
    blockers_started = threading.Barrier(slots + 1, timeout=DEADLINE)

    def blocker():
        blockers_started.wait()
        assert release.wait(DEADLINE)

    def nested():
        return "instantiated"

    async def part():
        blockers_started.wait()
        answer = await manager.run_detached(nested)
        release.set()
        return answer

    async def main():
        results = await asyncio.gather(manager.run_async(part), *(manager.run_detached(blocker) for _ in range(slots)))
        return results[0]

    assert _run(main()) == "instantiated"


def test_complete_from_a_slot_does_not_wait_for_one(pools):
    """'complete()' blocks its caller; a caller holding a slot must not wait for another.

    This is how a synchronous accessor of a plugin-backed package fetches from
    inside a running loop ('ProjectExternalRepository._run_elsewhere').
    """
    manager = pools(1)
    slots = manager.unconstrained_executor.size
    release = threading.Event()
    blockers_started = threading.Barrier(slots + 1, timeout=DEADLINE)

    def blocker():
        blockers_started.wait()
        assert release.wait(DEADLINE)

    async def fetch():
        return "fetched"

    async def part():
        blockers_started.wait()
        answer = manager.complete(fetch())
        release.set()
        return answer

    async def main():
        results = await asyncio.gather(manager.run_async(part), *(manager.run_detached(blocker) for _ in range(slots)))
        return results[0]

    assert _run(main()) == "fetched"


def test_complete_from_outside_the_pools_still_runs_elsewhere(pools):
    """From a loop that holds no slot it is the unconstrained pool, as before."""
    manager = pools(1)

    async def where():
        return threading.get_ident(), current_slot() is not None

    async def main():
        return manager.complete(where())

    thread, on_a_slot = _run(main())
    assert thread != threading.get_ident()
    assert on_a_slot


# ---- what does not change ---------------------------------------------------


class Failure(Exception):
    pass


@pytest.mark.parametrize("nested", [False, True])
def test_an_exception_reaches_the_caller(pools, nested):
    manager = pools(1)
    raised = Failure("the build failed")

    async def failing():
        raise raised

    def failing_synchronously():
        raise raised

    async def outer():
        with pytest.raises(Failure) as coroutine_error:
            await manager.run_async(failing)
        with pytest.raises(Failure) as function_error:
            await manager.run(failing_synchronously)
        with pytest.raises(Failure) as detached_error:
            await manager.run_detached(failing_synchronously)
        return coroutine_error.value, function_error.value, detached_error.value

    caught = _run(manager.run_async(outer) if nested else outer())
    assert caught == (raised, raised, raised)


def test_a_failure_gives_its_slot_back(pools):
    manager = pools(1)

    def failing():
        raise Failure()

    async def main():
        for _ in range(3):
            with pytest.raises(Failure):
                await manager.run(failing)
        return await manager.run(lambda: "still running")

    assert _run(main()) == "still running"


def test_work_cancelled_while_it_waits_never_runs(pools):
    """And takes no slot: what is queued after it still gets one."""
    manager = pools(1)
    ran = []
    holding = threading.Event()
    release = threading.Event()

    def hold():
        holding.set()
        assert release.wait(DEADLINE)

    async def main():
        first = asyncio.ensure_future(manager.run(hold))
        await asyncio.get_running_loop().run_in_executor(None, holding.wait, DEADLINE)
        doomed = asyncio.ensure_future(manager.run(ran.append, "doomed"))
        await asyncio.sleep(0)
        doomed.cancel()
        release.set()
        await first
        with pytest.raises(asyncio.CancelledError):
            await doomed
        return await manager.run(lambda: "next")

    assert _run(main()) == "next"
    assert ran == []


def test_nested_work_is_cancelled_with_its_caller(pools):
    """Awaited in place, nested work is cancelled the way any awaited coroutine is.

    It used to run to the end on a thread of its own however its caller ended.
    """
    manager = pools(1)
    seen = []

    async def slow():
        try:
            await asyncio.sleep(DEADLINE)
        except asyncio.CancelledError:
            seen.append("cancelled")
            raise

    async def outer():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(manager.run_async(slow), timeout=0.05)
        return seen

    assert _run(manager.run_async(outer)) == ["cancelled"]


def test_the_trace_follows_the_work(pools):
    """What 'TracedThreadPoolExecutor' was for: the caller's tracing context, on the thread that does the work."""
    manager = pools(1)
    token = otel_context.attach(otel_context.set_value("partcad.test", "the caller's"))
    try:

        async def read():
            return otel_context.get_value("partcad.test")

        def read_synchronously():
            return otel_context.get_value("partcad.test")

        async def outer():
            return (
                await read(),
                await manager.run_async(read),
                await manager.run(read_synchronously),
                manager.complete(read()),
            )

        async def main():
            return await manager.run_async(outer), await manager.run(read_synchronously)

        nested, top_level = _run(main())
    finally:
        otel_context.detach(token)
    assert nested == ("the caller's",) * 4
    assert top_level == "the caller's"
    # And it is the asker's, not the thread's: asked for once the caller has
    # let go of it, on the same threads, the work does not see it.
    assert _run(manager.run(read_synchronously)) is None


# ---- a slot waiting for a lock ----------------------------------------------


def test_a_slot_gives_its_slot_back_while_the_loop_holds_the_lock(pools):
    """The loop a command runs on holds a lock, and waits for work still queued.

    The one slot is taken by work waiting for that lock. Unless it gives the slot
    back while it waits, the work the loop is waiting for never starts, and the
    loop never lets go of the lock.
    """
    manager = pools(1)
    lock = PoolAwareRLock()
    waiting = threading.Event()

    def waiter():
        waiting.set()
        with lock:
            return "waited"

    async def main():
        async with lock:
            first = asyncio.ensure_future(manager.run(waiter))
            await asyncio.get_running_loop().run_in_executor(None, waiting.wait, DEADLINE)
            built = await manager.run(lambda: "built")
        return built, await first

    assert _run(main()) == ("built", "waited")


def test_waiting_for_a_lock_held_on_a_working_slot_keeps_the_slot(pools):
    """A holder working on a slot needs nothing from the pool to finish.

    So the waiter keeps its slot, and the pool does not start a thread for
    something else to wait beside it: with two slots, the third piece of work
    starts only once one of the first two is done.
    """
    manager = pools(2)
    lock = PoolAwareRLock()
    held = threading.Event()
    order = []

    def holder():
        with lock:
            held.set()
            time.sleep(0.2)
            order.append("holder")

    def waiter():
        assert held.wait(DEADLINE)
        with lock:
            order.append("waiter")

    def third():
        order.append("third")

    async def main():
        await asyncio.gather(manager.run(holder), manager.run(waiter), manager.run(third))

    _run(main())
    assert order.index("third") > order.index("holder")
    assert len(manager.constrained_executor._threads._threads) == 2


def test_a_slot_waiting_behind_a_waiting_slot_gives_it_back(pools):
    """The holder is on a slot, but waits for the loop: the waiter behind it has to give way too.

    One slot. The first piece of work takes it, takes 'inner', and waits for
    'outer', which the loop holds -- so it gives the slot back, and the second
    is let in. The second waits for 'inner', whose holder is on a slot but is
    not working on it; keeping its own slot would leave none for the work the
    loop is waiting for.
    """
    manager = pools(1)
    outer = PoolAwareRLock()
    inner = PoolAwareRLock()
    inner_held = threading.Event()
    both_waiting = threading.Event()

    def holds_inner_waits_for_outer():
        with inner:
            inner_held.set()
            with outer:
                return "first"

    def waits_for_inner():
        assert inner_held.wait(DEADLINE)
        both_waiting.set()
        with inner:
            return "second"

    async def main():
        async with outer:
            first = asyncio.ensure_future(manager.run(holds_inner_waits_for_outer))
            second = asyncio.ensure_future(manager.run(waits_for_inner))
            await asyncio.get_running_loop().run_in_executor(None, both_waiting.wait, DEADLINE)
            # Both slots are taken by work waiting, one way or another, for
            # this loop -- which waits for work that has not started.
            built = await manager.run(lambda: "built")
        return built, await first, await second

    assert _run(main()) == ("built", "first", "second")


def test_waiting_for_a_lock_does_not_stop_the_loop():
    """The task beside the waiting one keeps running; it may be what the holder waits for."""
    lock = PoolAwareRLock()
    held = threading.Event()
    release = threading.Event()

    def hold():
        with lock:
            held.set()
            release.wait(DEADLINE)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(DEADLINE)
    ticks = []

    async def main():
        async def ticker():
            while not release.is_set():
                ticks.append(1)
                if len(ticks) == 5:
                    release.set()
                await asyncio.sleep(0.005)

        ticking = asyncio.ensure_future(ticker())
        async with lock:
            pass
        await ticking

    try:
        _run(main())
    finally:
        release.set()
        holder.join()
    assert len(ticks) >= 5


def test_the_lock_is_re_entrant_for_the_thread_holding_it():
    lock = PoolAwareRLock()

    async def main():
        async with lock:
            with lock:
                async with lock:
                    return "reached"

    assert _run(main()) == "reached"
    # And it was let go of as many times as it was taken.
    assert lock.acquire(blocking=False)
    lock.release()


def test_the_lock_excludes_other_threads():
    lock = PoolAwareRLock()
    got = []

    def try_it(**kwargs):
        acquired = lock.acquire(**kwargs)
        got.append(acquired)
        if acquired:
            lock.release()

    with lock:
        other = threading.Thread(target=try_it, kwargs={"timeout": 0.05})
        other.start()
        other.join()
    other = threading.Thread(target=try_it, kwargs={"blocking": False})
    other.start()
    other.join()
    assert got == [False, True]


def test_only_the_holder_may_release_the_lock():
    lock = PoolAwareRLock()
    with pytest.raises(RuntimeError):
        lock.release()
    with lock:
        errors = []

        def release_elsewhere():
            try:
                lock.release()
            except RuntimeError as e:
                errors.append(e)

        other = threading.Thread(target=release_elsewhere)
        other.start()
        other.join()
        assert len(errors) == 1
