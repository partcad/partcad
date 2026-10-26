#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Which task starts next, and whether one may start: admission by slots, rank and memory.

The memory is scripted rather than measured, and the monitor is driven by hand
('tick'), so that nothing here depends on the machine the tests run on.
"""

import asyncio
import threading
import time

import pytest

from partcad import admission, memory, sync_threads
from partcad.admission import CALL, LOAD, Admission, Rank, ranked

GB = 1024**3


class _Memory:
    """What the scripted machine holds, and what 'measure' reports of it."""

    def __init__(self, usage=0):
        self.usage = usage
        self.measured = 0

    def measure(self):
        self.measured += 1
        return memory.Footprint(own=self.usage, reusable=0, children=0, containers=0)


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _budgeted(count=4, usage=0, capacity=10 * GB, share=0.8, clock=None):
    """An admission with a budget of 'share' of 'capacity', and a scripted machine under it."""
    machine = _Memory(usage)
    slots = Admission(count, monitor=False, clock=clock)
    slots.set_budget(share, measure=machine.measure, capacity_of=lambda count_swap: capacity)
    return slots, machine


async def _take(slots, rank, label, order, kind=CALL, hold=0.0):
    with ranked(rank):
        async with slots.task_async(kind):
            order.append(label)
            if hold:
                await asyncio.sleep(hold)


# ---- rank -------------------------------------------------------------------


def test_the_best_ranked_waiter_gets_the_slot_that_frees():
    """Not whichever asked first: objects that started nothing yet go in declaration order."""
    slots = Admission(1, monitor=False)
    first, second = Rank("first"), Rank("second")
    order = []

    async def scenario():
        async with slots.slot_async():
            later = asyncio.create_task(_take(slots, second, "second", order))
            await asyncio.sleep(0.01)
            earlier = asyncio.create_task(_take(slots, first, "first", order))
            await asyncio.sleep(0.01)
            assert order == []
        await asyncio.wait_for(asyncio.gather(later, earlier), timeout=10)

    asyncio.run(scenario())
    assert order == ["first", "second"]


def test_what_is_started_is_finished_first():
    """An object that has started work goes before one declared earlier that has not."""
    slots = Admission(1, monitor=False)
    declared_first, started_first = Rank("declared first"), Rank("started first")
    order = []

    async def scenario():
        # 'started first' gets the only slot while nothing else asks for it.
        with ranked(started_first):
            async with slots.slot_async():
                waiting = asyncio.create_task(_take(slots, declared_first, "declared first", order))
                await asyncio.sleep(0.01)
                more = asyncio.create_task(_take(slots, started_first, "started first, again", order))
                await asyncio.sleep(0.01)
        await asyncio.wait_for(asyncio.gather(waiting, more), timeout=10)

    asyncio.run(scenario())
    assert order == ["started first, again", "declared first"]


def test_a_build_ranks_as_well_as_whoever_waits_for_it():
    """A brick built for a picture ranked last is wanted by the picture ranked first."""
    early, late = Rank("early"), Rank("late")
    build = Rank("brick", parent=late)
    assert build.key() > early.key()

    build.lend(early)
    assert build.key() == early.key()
    # And whatever the build itself started goes with it.
    assert Rank("a part of the brick", parent=build).key() == early.key()


def test_a_rank_is_started_when_its_first_task_is():
    slots = Admission(1, monitor=False)
    parent = Rank("object")
    child = Rank("its brick", parent=parent)
    with ranked(child):
        assert slots._try_acquire()
    assert child.started is not None
    assert parent.started == child.started


def test_the_rank_goes_with_work_to_a_pool_thread():
    """Beside the tracing context: work handed to a pool is still the asking thread's."""
    rank = Rank("object")

    async def inside():
        return admission.current(), threading.get_ident()

    async def outside():
        with ranked(rank):
            return await sync_threads.threadpool_manager.run_async(inside)

    seen, thread = asyncio.run(outside())
    assert seen is rank
    assert thread != threading.get_ident()


# ---- slots and loads --------------------------------------------------------


def test_a_load_takes_no_process_slot():
    """Every slot busy, and an object can still be read into memory."""
    slots = Admission(1, monitor=False)
    assert slots._try_acquire(CALL)
    assert not slots._try_acquire(CALL)
    assert slots._try_acquire(LOAD)
    slots._release(LOAD)
    slots._release(CALL)


def test_a_load_does_not_wait_behind_a_call_that_waits_for_a_slot():
    """A better-ranked call held back by the slots does not hold back a load: it needs none."""
    slots = Admission(1, monitor=False)
    order = []

    async def scenario():
        async with slots.slot_async():
            call = asyncio.create_task(_take(slots, Rank("better"), "call", order))
            await asyncio.sleep(0.01)
            await asyncio.wait_for(_take(slots, Rank("worse"), "load", order, kind=LOAD), timeout=10)
        await asyncio.wait_for(call, timeout=10)

    asyncio.run(scenario())
    assert order == ["load", "call"]


def test_without_a_budget_memory_is_not_asked_about():
    slots = Admission(2, monitor=False)
    assert slots.budget is None
    assert slots._try_acquire()
    assert slots._try_acquire()
    assert not slots._try_acquire()
    assert slots._try_acquire(LOAD)


# ---- memory ------------------------------------------------------------------


def test_nothing_new_starts_over_the_budget_while_something_runs():
    slots, machine = _budgeted(usage=7 * GB)
    assert slots._try_acquire()
    machine.usage = 9 * GB  # over 8 GB, the budget
    slots.tick()

    assert not slots._try_acquire(CALL)
    assert not slots._try_acquire(LOAD)
    # And what runs is left to run.
    assert slots.snapshot()["running"] == 1


def test_starts_resume_when_usage_falls_under_the_budget():
    slots, machine = _budgeted(usage=9 * GB)
    assert slots._try_acquire()
    slots.tick()
    order = []

    async def scenario():
        waiter = asyncio.create_task(_take(slots, Rank("next"), "next", order))
        await asyncio.sleep(0.05)
        assert order == []
        machine.usage = 5 * GB
        slots.tick()
        await asyncio.wait_for(waiter, timeout=10)

    asyncio.run(scenario())
    assert order == ["next"]


def test_with_nothing_running_the_best_ranked_task_starts_whatever_the_usage(monkeypatch):
    """Throttled to one at a time, never to a stop."""
    warned = []
    monkeypatch.setattr(admission.pc_logging, "warning", lambda message: warned.append(message))
    slots, machine = _budgeted(usage=20 * GB)
    slots.tick()
    order = []

    # Declared in this order, so ranked in it too.
    better_rank, worse_rank = Rank("better"), Rank("worse")

    async def scenario():
        async with slots.slot_async():
            order.append("first")
            # Over the budget with one task running: the next waits.
            later = asyncio.create_task(_take(slots, worse_rank, "worse", order))
            better = asyncio.create_task(_take(slots, better_rank, "better", order, hold=0.05))
            await asyncio.sleep(0.05)
            assert order == ["first"]
        # The one running ended: the best-ranked waiter starts, and only it.
        await asyncio.sleep(0.02)
        assert order == ["first", "better"]
        await asyncio.wait_for(asyncio.gather(later, better), timeout=10)

    asyncio.run(scenario())
    # 'later' asked before 'better' did, but ranks after it.
    assert order == ["first", "better", "worse"]
    assert warned and "over its memory budget" in warned[0]


def test_an_unmeasured_start_is_not_held_back():
    """The burst at the start of a run is accepted: nothing is anticipated."""
    slots, machine = _budgeted(count=3, usage=20 * GB)
    assert all(slots._try_acquire() for _ in range(3))
    assert machine.measured == 0


def test_a_moment_with_nothing_running_is_not_the_start_of_a_run():
    """Regression: the monitor forgot its measurement whenever nothing ran, if only between two objects.

    The next waiters then found memory unmeasured, which is how a run starts,
    and all of them started at once over the budget.
    """
    machine = _Memory(usage=9 * GB)
    slots = Admission(4)
    slots.set_budget(0.8, measure=machine.measure, capacity_of=lambda count_swap: 10 * GB)
    try:
        with slots.slot():
            deadline = time.monotonic() + 10
            while slots.snapshot()["usage"] is None and time.monotonic() < deadline:
                time.sleep(0.01)
        # Long enough for the monitor to find nothing to do.
        time.sleep(admission.INTERVAL * 2)

        assert slots._try_acquire()
        assert not slots._try_acquire()
        slots._release()
    finally:
        slots.set_budget(0)


def test_a_share_of_zero_turns_the_budget_off():
    slots, machine = _budgeted(usage=20 * GB)
    slots.tick()
    assert slots._try_acquire()
    assert not slots._try_acquire()
    slots.set_budget(0)
    assert slots.budget is None
    assert slots._try_acquire()


def test_the_budget_is_the_share_of_the_capacity():
    slots, _ = _budgeted(capacity=10 * GB, share=0.5)
    assert slots.budget.limit == 5 * GB


def test_a_cancelled_wait_for_memory_leaves_nothing_behind():
    slots, machine = _budgeted(count=1, usage=20 * GB)
    assert slots._try_acquire(LOAD)
    slots.tick()

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_take(slots, Rank("given up"), "never", []), timeout=0.05)

    asyncio.run(scenario())
    assert slots.snapshot()["waiting"] == 0
    slots._release(LOAD)
    machine.usage = 0
    slots.tick()
    assert slots._try_acquire()
    assert not slots._try_acquire()


# ---- freeing ------------------------------------------------------------------


def test_idle_memory_is_asked_back_from_ninety_percent_of_the_budget(monkeypatch):
    monkeypatch.setattr(admission.memory, "release", lambda: None)
    slots, machine = _budgeted(usage=int(7.6 * GB))  # 95% of 8 GB
    asked = []

    def free(excess):
        asked.append(excess)
        machine.usage = 6 * GB
        return excess

    slots.on_pressure(free)
    slots.tick()

    # From 7.6 GB to the mark, 90% of 8 GB.
    assert asked == [int(7.6 * GB - 0.9 * 8 * GB)]
    assert slots.snapshot()["usage"] == 6 * GB


def test_under_the_mark_nothing_is_asked_back(monkeypatch):
    monkeypatch.setattr(admission.memory, "release", lambda: None)
    slots, machine = _budgeted(usage=7 * GB)  # 87.5% of 8 GB
    asked = []
    slots.on_pressure(lambda excess: asked.append(excess) or 0)
    slots.tick()
    assert asked == []


def test_freeing_is_asked_again_while_it_helps_and_not_once_it_does_not(monkeypatch):
    """Measured after every round: a recorded size is only a guess at what freeing returns."""
    released = []
    monkeypatch.setattr(admission.memory, "release", lambda: released.append(True))
    clock = _Clock()
    slots, machine = _budgeted(usage=9 * GB, clock=clock)
    asked = []

    def free(excess):
        asked.append(excess)
        if len(asked) < 3:
            machine.usage -= GB // 4
            return GB // 4
        return 0

    slots.on_pressure(free)
    slots.tick()

    # Asked a third time, which freed nothing: that ends it.
    assert len(asked) == 3
    assert len(released) == 2

    # Asked again on the next round, but the garbage is not collected again
    # straight away when there was nothing to free: a collection stops every
    # thread for as long as it takes.
    slots.tick()
    assert len(asked) == 4
    assert len(released) == 2

    # Only once a while has passed.
    clock.now += admission.RELEASE_EVERY
    slots.tick()
    assert len(asked) == 5
    assert len(released) == 3


def test_a_round_starts_with_what_was_asked_to_be_done_on_every_round():
    slots, machine = _budgeted()
    calls = []
    slots.on_round(lambda: calls.append(machine.measured))
    slots.tick()
    slots.tick()
    # Before each measurement, so that what it let go of is measured.
    assert calls == [0, 1]


# ---- telling the user ---------------------------------------------------------


def test_held_tasks_are_reported_after_a_while_and_then_every_thirty_seconds(monkeypatch):
    said = []
    monkeypatch.setattr(admission.pc_logging, "info", lambda message: said.append(message))
    clock = _Clock()
    slots, machine = _budgeted(usage=9 * GB, clock=clock)
    assert slots._try_acquire()
    slots.tick()

    async def scenario():
        waiter = asyncio.create_task(_take(slots, Rank("held"), "held", []))
        await asyncio.sleep(0.01)
        for at in (0, 4, 6, 20, 35, 36, 66):
            clock.now = 1000.0 + at
            slots.tick()
        waiter.cancel()

    asyncio.run(scenario())
    assert len(said) == 3
    assert "1 task(s) wait for memory" in said[0]
    assert "8.0 GB budget" in said[0]


def test_a_task_waiting_for_a_slot_is_not_said_to_wait_for_memory(monkeypatch):
    said = []
    monkeypatch.setattr(admission.pc_logging, "info", lambda message: said.append(message))
    clock = _Clock()
    slots, machine = _budgeted(count=1, usage=9 * GB, clock=clock)
    assert slots._try_acquire()
    slots.tick()

    async def scenario():
        waiter = asyncio.create_task(_take(slots, Rank("held"), "held", []))
        await asyncio.sleep(0.01)
        for at in (0, 10, 40):
            clock.now = 1000.0 + at
            slots.tick()
        waiter.cancel()

    asyncio.run(scenario())
    assert said == []


# ---- the process's own -----------------------------------------------------------


class _Config:
    def __init__(self, threads_max=None, **budget):
        self.threads_max = threads_max
        for key, value in budget.items():
            setattr(self, key, value)


def test_follow_takes_the_budget_a_request_carries(monkeypatch):
    from partcad import sandbox_lock

    slots = Admission(4, monitor=False)
    monkeypatch.setattr(sandbox_lock, "process_slots", slots)

    sandbox_lock.follow(_Config(memory_budget=0.5, memory_budget_swap=False))
    assert slots.budget.share == 0.5
    assert slots.budget.count_swap is False

    sandbox_lock.follow(_Config(memory_budget=0))
    assert slots.budget is None


def test_a_configuration_that_says_nothing_gets_the_defaults():
    from partcad import sandbox_lock

    assert sandbox_lock.memory_budget(_Config()) == (0.8, True)
