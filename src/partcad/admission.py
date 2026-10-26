#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which task starts next, and whether one may start at all.

A **task** is one wrapper call -- a sandbox process, a call into an
implementation's container -- or one object the daemon reads into memory from a
cache tier. It is not a process (a container serves many calls) and not an
action (an action holds many tasks): it is the smallest piece of work that,
once started, runs to its end without waiting for any other. That last property
is what everything here rests on.

Two things decide whether a waiting task starts:

  * **A process slot**, for a call. 'threadsMax' of them (see
    'sandbox_lock.process_slot_count'), because a wrapper is a CAD interpreter of
    several hundred megabytes and it is processes, not threads, that fill a
    machine. A load takes none.

  * **The memory budget**, for either: a share of the machine's capacity
    ('memoryBudget', 0.8 by default, of RAM plus swap unless 'memoryBudgetSwap'
    says otherwise; see 'partcad.memory'). A task starts while what this
    process's work holds is under it. Nothing is anticipated: a task may -- will
    -- grow past what was free when it started, and the rest of the capacity is
    the room for that.

and one thing decides which: **rank**. The task whose work ranks best starts
first, among those that can use what is free. A rank is an object's place in
the run -- objects that have started work rank by when they started it, the
others by the order they were declared in -- so that what is started is
finished first. A shape being built ranks as well as the best of whoever waits
for it ('Rank.lend'), and the rank travels with the work across a thread hop
(see 'sync_threads._Work').

Nothing that has started is ever touched: no task is paused, stopped or made to
wait once it runs. The one lever is not starting new ones. And whenever nothing
is running at all, the best-ranked waiting task starts whatever the usage: every
running task ends, so a design bigger than the machine is slowed down to one
task at a time and then finishes or fails -- it never stops.

What that cannot see coming is tasks that start together and then grow
together: the four views of one model, ready at once when its tree is, each
grows by up to 2.5 GB after it starts. Where the budget leaves room for that,
nothing more is needed. Where it does not -- a machine with little memory for
the work, which `pc healthcheck` points out -- **pacing** can be turned on
('memoryPacing'): once the work holds that share of its budget, a task starts
only when the memory has stopped rising since the last one started (flat over
SETTLE seconds of measurements, the last start at least SETTLE seconds back).
It guesses nothing about any task either; it lets each one show what it takes
before the next. Below the share nothing waits, and when nothing runs the next
task starts as always, so it slows down only work that is already high.

While anything runs or waits, a monitor measures the memory a few times a
second. From 90% of the budget it asks for idle objects to be freed (see
'partcad.idle_objects'), and while tasks are held back by memory it says so in
the log, every thirty seconds -- which is also what keeps a client waiting for
the daemon from taking the silence for a stall.

The state is a count under a mutex rather than a semaphore, as the process slots
always were: the ceiling moves while slots are held ('resize'), and tasks are
asked for from many threads and many event loops at once (a part is built on a
worker thread with a loop of its own), so nothing here may belong to one loop or
block the loop it is asked from.
"""

import asyncio
import collections
import contextlib
import contextvars
import itertools
import threading
import time
from typing import Callable, List, Optional

from . import logging as pc_logging
from . import memory

# The two kinds of task.
CALL = "call"  # a wrapper call: takes a process slot
LOAD = "load"  # an object read into this process from a cache tier: takes none

# Idle objects are freed from this fraction of the budget on, so that they go
# before new starts stop.
FREE_AT = 0.9

# How often the monitor measures while anything runs or waits.
INTERVAL = 0.5

# How often a waiter checks for itself whatever it was told. Grants wake waiters
# directly; this is the backstop that makes a lost wake-up a delay, not a hang.
RECHECK = 1.0

# How long tasks are held back by memory before the log says so, and how often
# it says so again while they are.
HELD_NOTICE = 5.0
HEARTBEAT = 30.0

# How often at most the log says that a task was started over the budget
# because nothing else was running.
OVER_NOTICE = 60.0

# How often at most the garbage collector is run and the allocators trimmed to
# find out whether the daemon is really over the mark. A collection stops every
# thread for as long as it takes.
RELEASE_EVERY = 5.0

# How often the daemon's log is told where memory and the tasks stand.
TRACE = 5.0

# How many rounds of freeing one measurement may lead to.
FREE_ROUNDS = 8

# How long a measured capacity is trusted. A cgroup's limit can be changed under
# a running process, and reading it costs a few file reads.
CAPACITY_SECONDS = 60.0

# With pacing on: how long the memory has to have stopped rising before the next
# task starts, and the least time between two starts.
SETTLE = 5.0

# A rise smaller than this share of the budget is not one: it is what two
# measurements in a row differ by while nothing grows.
RISE = 0.01


class Rank:
    """Where a piece of work stands in the queue.

    An object's rank is when its first task started, or, before that, its place
    in the order objects were created -- which is declaration order for the
    objects of a package. 'parent' is the rank of the work this is part of, and
    'lend' raises a rank to that of a task waiting for it; the rank a task waits
    with is the best of all of these.
    """

    _counter = itertools.count()
    __slots__ = ("seq", "started", "parent", "lent", "name")

    def __init__(self, name: str = None, parent: "Rank" = None):
        self.seq = next(Rank._counter)
        self.started = None
        self.parent = parent
        self.lent = []
        self.name = name

    def _own(self):
        if self.started is not None:
            return (0, self.started, self.seq)
        return (1, self.seq, 0)

    def key(self):
        """The best of this rank, its parents' and what was lent to any of them."""
        best = None
        seen = set()
        pending = [self]
        while pending:
            rank = pending.pop()
            if id(rank) in seen:
                continue
            seen.add(id(rank))
            own = rank._own()
            if best is None or own < best:
                best = own
            if rank.parent is not None:
                pending.append(rank.parent)
            pending.extend(rank.lent)
        return best

    def lend(self, other: Optional["Rank"]) -> None:
        """Rank as well as 'other' from now on: it is waiting for what this rank's work makes."""
        if other is None or other is self:
            return
        for lent in self.lent:
            if lent is other:
                return
        self.lent.append(other)

    def mark_started(self, now: float) -> None:
        rank = self
        while rank is not None:
            if rank.started is None:
                rank.started = now
            rank = rank.parent


_rank = contextvars.ContextVar("partcad_admission_rank", default=None)


def current() -> Optional[Rank]:
    """The rank of the work this code is doing, or None for work nobody ranked."""
    return _rank.get()


@contextlib.contextmanager
def ranked(rank: Optional[Rank]):
    """Do the work inside with 'rank', and tasks started from it, wherever they run."""
    token = _rank.set(rank)
    try:
        yield rank
    finally:
        _rank.reset(token)


class _Waiter:
    __slots__ = ("kind", "rank", "seq", "since", "granted", "event", "loop", "future")

    _counter = itertools.count()

    def __init__(self, kind: str, rank: Optional[Rank], since: float, loop=None):
        self.kind = kind
        # A task nobody ranked ranks like an object nobody has started yet,
        # created when it asked: behind what has started, in the order it came.
        self.rank = rank if rank is not None else Rank()
        self.seq = next(_Waiter._counter)
        self.since = since
        self.granted = False
        self.loop = loop
        self.event = threading.Event() if loop is None else None
        self.future = loop.create_future() if loop is not None else None

    def order(self):
        return (self.rank.key(), self.seq)


def _resolve(future) -> None:
    if not future.done():
        future.set_result(None)


class Admission:
    """The process slots and the memory budget, and who gets them next.

    'count' is how many calls may run at once. The budget is off until
    'set_budget' turns it on; without one this is exactly the process slots
    PartCAD always had, waking waiters in rank order. 'monitor=False' leaves the
    measuring to whoever calls 'tick()', which is what the tests do.
    """

    def __init__(self, count: int, budget: Optional[memory.Budget] = None, monitor: bool = True, clock=None):
        self._mutex = threading.Lock()
        self._poke = threading.Condition(self._mutex)
        self._count = count
        self._calls = 0
        self._running = 0
        self._waiting: List[_Waiter] = []
        self._budget = budget
        self._budget_at = 0.0
        self._footprint: Optional[memory.Footprint] = None
        self._clock = clock or time.monotonic
        self._monitor_enabled = monitor
        self._monitor = None
        self._pressure: List[Callable[[int], int]] = []
        self._rounds: List[Callable[[], object]] = []
        self._held_since = None
        self._last_heartbeat = None
        self._last_over_notice = None
        self._last_release = None
        self._last_trace = None
        self._pacing = 0.0
        # (when, usage) of the measurements of the last SETTLE seconds.
        self._history = collections.deque()
        self._last_start = None

    # ---- the configuration ---------------------------------------------------

    @property
    def count(self) -> int:
        return self._count

    @property
    def _in_use(self) -> int:
        """How many process slots are held: what the process slots called it."""
        return self._calls

    def resize(self, count: int) -> None:
        with self._mutex:
            if count == self._count:
                return
            was, self._count = self._count, count
            self._dispatch_locked()
        # Debug, and only on a change: a daemon serving clients configured
        # differently moves this on every request, and what it is at is a
        # question for its log, not for the user's terminal.
        pc_logging.debug("Sandbox processes at once: %d (was %d)" % (count, was))

    def set_budget(self, share: Optional[float], count_swap: bool = True, measure=None, capacity_of=None) -> None:
        """Aim this process's work at 'share' of the machine; None or 0 turns the budget off."""
        if not share or share <= 0:
            with self._mutex:
                self._budget = None
                self._footprint = None
                self._dispatch_locked()
                # So that the monitor sees there is nothing left to watch.
                self._poke.notify_all()
            return
        share = min(float(share), 1.0)
        with self._mutex:
            budget = self._budget
            if (
                budget is not None
                and budget.share == share
                and budget.count_swap == count_swap
                and measure is None
                and capacity_of is None
                and self._clock() - self._budget_at < CAPACITY_SECONDS
            ):
                return
        memory.configure_allocator()
        budget = memory.Budget(share, count_swap, measure=measure, capacity_of=capacity_of)
        # Read outside the mutex: a few files on Linux, a system call elsewhere.
        capacity = budget.capacity
        pc_logging.debug(
            "Memory budget: %s, %d%% of %s%s"
            % (memory.size(budget.limit), round(share * 100), memory.size(capacity), " with swap" if count_swap else "")
        )
        with self._mutex:
            self._budget = budget
            self._budget_at = self._clock()
            self._dispatch_locked()
            self._watch_locked()

    @property
    def budget(self) -> Optional[memory.Budget]:
        return self._budget

    def set_pacing(self, share: Optional[float]) -> None:
        """Pace starts once the work holds 'share' of its budget; None or 0 never paces.

        Pacing needs the budget: without one there is nothing to be a share of,
        and starts are as the process slots have them.
        """
        share = min(float(share), 1.0) if share and share > 0 else 0.0
        with self._mutex:
            if share == self._pacing:
                return
            self._pacing = share
            self._dispatch_locked()
        pc_logging.debug("Memory pacing: %s" % ("from %d%% of the budget" % round(share * 100) if share else "off"))

    @property
    def pacing(self) -> float:
        return self._pacing

    def on_pressure(self, free: Callable[[int], int]) -> None:
        """Ask 'free(excess)' to free idle memory when usage reaches the freeing mark.

        It returns what it believes it freed; what counts is the usage measured
        afterwards.
        """
        with self._mutex:
            if free not in self._pressure:
                self._pressure.append(free)

    def on_round(self, call: Callable[[], object]) -> None:
        """Have 'call()' made at the start of every round of the monitor, before it measures."""
        with self._mutex:
            if call not in self._rounds:
                self._rounds.append(call)

    # ---- tasks ---------------------------------------------------------------

    @contextlib.contextmanager
    def task(self, kind: str = CALL):
        """Run the body as one task of 'kind', once admitted. For synchronous callers."""
        waiter = self._enqueue(kind)
        try:
            while not waiter.granted:
                if waiter.event.wait(RECHECK):
                    break
                self._redispatch()
        except BaseException:
            self._abandon(waiter)
            raise
        try:
            yield
        finally:
            self._finish(kind)

    @contextlib.asynccontextmanager
    async def task_async(self, kind: str = CALL):
        """Run the body as one task of 'kind', once admitted, without blocking the loop."""
        waiter = self._enqueue(kind, loop=asyncio.get_running_loop())
        try:
            while not waiter.granted:
                done, _ = await asyncio.wait({waiter.future}, timeout=RECHECK)
                if done:
                    break
                self._redispatch()
        except BaseException:
            self._abandon(waiter)
            raise
        try:
            yield
        finally:
            self._finish(kind)

    def slot(self):
        """A process slot for one wrapper call (see 'task')."""
        return self.task(CALL)

    def slot_async(self):
        """A process slot for one wrapper call (see 'task_async')."""
        return self.task_async(CALL)

    def load(self):
        """Admission for one object read into memory (see 'task')."""
        return self.task(LOAD)

    def load_async(self):
        """Admission for one object read into memory (see 'task_async')."""
        return self.task_async(LOAD)

    def _try_acquire(self, kind: str = CALL) -> bool:
        """Start a task of 'kind' now if it can be started now; never wait."""
        waiter = _Waiter(kind, current(), self._clock())
        # Nothing to wake: whether it got one is the answer, here and now.
        waiter.event = None
        with self._mutex:
            self._waiting.append(waiter)
            self._dispatch_locked()
            if not waiter.granted:
                self._waiting.remove(waiter)
            return waiter.granted

    def _release(self, kind: str = CALL) -> None:
        self._finish(kind)

    # ---- the state -----------------------------------------------------------

    def snapshot(self) -> dict:
        """What is running and waiting, and the memory as last measured."""
        with self._mutex:
            footprint = self._footprint
            budget = self._budget
            return {
                "slots": self._count,
                "calls": self._calls,
                "running": self._running,
                "waiting": len(self._waiting),
                "usage": footprint.usage if footprint is not None else None,
                "budget": budget.limit if budget is not None else None,
                "pacing": self._pacing,
            }

    def tick(self) -> None:
        """Measure, free what idle memory is wanted back, and start whoever may start."""
        budget = self._budget
        if budget is None:
            self._redispatch()
            return
        with self._mutex:
            rounds = list(self._rounds)
        for call in rounds:
            try:
                call()
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("A round of the memory monitor failed: %s" % e)
        now = self._clock()
        footprint = self._measure(budget)
        if footprint is not None:
            footprint = self._free_if_wanted(budget, footprint, now)
        with self._mutex:
            if footprint is not None and self._budget is budget:
                self._footprint = footprint
                self._remember_locked(now, footprint.usage)
            self._dispatch_locked()
            notice = self._held_notice_locked(now)
            trace = self._trace_locked(now)
        if notice:
            pc_logging.info(notice)
        if trace:
            pc_logging.debug(trace)

    def _trace_locked(self, now: float) -> Optional[str]:
        """Where things stand, for the daemon's log, every TRACE seconds while anything runs."""
        if self._footprint is None or (self._last_trace is not None and now - self._last_trace < TRACE):
            return None
        self._last_trace = now
        return "Memory: %s of a %s budget; %d task(s) running (%d of %d process slots), %d waiting" % (
            self._footprint.describe(),
            memory.size(self._budget.limit),
            self._running,
            self._calls,
            self._count,
            len(self._waiting),
        )

    def _measure(self, budget: memory.Budget) -> Optional[memory.Footprint]:
        try:
            return budget.measure()
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("Memory could not be measured: %s" % e)
            return None

    def _free_if_wanted(self, budget, footprint, now):
        mark = budget.limit * FREE_AT
        if footprint.usage < mark:
            return footprint
        with self._mutex:
            pressure = list(self._pressure)
        for _ in range(FREE_ROUNDS):
            excess = int(footprint.usage - mark)
            freed = 0
            for free in pressure:
                try:
                    freed += free(excess - freed) or 0
                except Exception as e:  # pylint: disable=broad-except
                    pc_logging.debug("Freeing idle objects failed: %s" % e)
                if freed >= excess:
                    break
            if not freed and self._last_release is not None and now - self._last_release < RELEASE_EVERY:
                return footprint
            self._last_release = now
            memory.release()
            measured = self._measure(budget)
            if measured is None:
                return footprint
            footprint = measured
            if footprint.usage < mark or not freed:
                return footprint
        return footprint

    def _remember_locked(self, now: float, usage: int) -> None:
        """Keep a measurement for as long as pacing looks back."""
        self._history.append((now, usage))
        while self._history and now - self._history[0][0] > SETTLE:
            self._history.popleft()

    def _held_notice_locked(self, now: float) -> Optional[str]:
        held = self._held_locked(now)
        if not held:
            self._held_since = None
            self._last_heartbeat = None
            return None
        if self._held_since is None:
            self._held_since = now
            return None
        if now - self._held_since < HELD_NOTICE:
            return None
        if self._last_heartbeat is not None and now - self._last_heartbeat < HEARTBEAT:
            return None
        self._last_heartbeat = now
        if self._over_locked():
            return (
                "%d task(s) wait for memory to start: PartCAD's work holds %s of its %s budget, %d task(s) running"
                % (
                    held,
                    memory.size(self._footprint.usage),
                    memory.size(self._budget.limit),
                    self._running,
                )
            )
        return (
            "%d task(s) wait for memory to stop rising before they start (memoryPacing): PartCAD's work holds %s of"
            " its %s budget, %d task(s) running"
            % (
                held,
                memory.size(self._footprint.usage),
                memory.size(self._budget.limit),
                self._running,
            )
        )

    def _held_locked(self, now: float) -> int:
        """How many waiting tasks memory, and nothing else, is holding back."""
        if not self._waiting or not self._running:
            return 0
        if not (self._over_locked() or self._settling_locked(now)):
            return 0
        return sum(1 for w in self._waiting if w.kind != CALL or self._calls < self._count)

    # ---- the granting --------------------------------------------------------

    def _over_locked(self) -> bool:
        budget, footprint = self._budget, self._footprint
        if budget is None or footprint is None:
            # Not measured yet, which is the start of a run: whatever starts
            # now starts while usage is near nothing, and that burst is
            # accepted rather than paced (nothing is anticipated).
            return False
        return footprint.usage >= budget.limit

    def _settling_locked(self, now: float) -> bool:
        """Whether pacing holds the next start back: the work is high and its memory still rising.

        Only from the pacing share of the budget on. There, the next task
        starts once the last start is SETTLE seconds back and the memory has
        not risen over the measurements of the last SETTLE seconds -- which
        after a start means the task that started has stopped growing, or the
        work as a whole is shrinking.
        """
        budget, footprint = self._budget, self._footprint
        if not self._pacing or budget is None or footprint is None:
            return False
        if footprint.usage < self._pacing * budget.limit:
            return False
        if self._last_start is not None and now - self._last_start < SETTLE:
            return True
        lowest = min((usage for when, usage in self._history if now - when <= SETTLE), default=footprint.usage)
        return footprint.usage - lowest > budget.limit * RISE

    def _dispatch_locked(self) -> None:
        if not self._waiting:
            return
        over = self._over_locked()
        now = self._clock()
        for waiter in sorted(self._waiting, key=_Waiter.order):
            # Held back by memory only while something runs: when nothing
            # does, the best-ranked task starts whatever the memory.
            if self._running > 0 and (over or self._settling_locked(now)):
                break
            if waiter.kind == CALL and self._calls >= self._count:
                continue
            if over:
                self._over_notice_locked(waiter)
            self._grant_locked(waiter)

    def _over_notice_locked(self, waiter) -> None:
        now = self._clock()
        if self._last_over_notice is not None and now - self._last_over_notice < OVER_NOTICE:
            return
        self._last_over_notice = now
        pc_logging.warning(
            "Starting a task with PartCAD's work over its memory budget (%s of %s), since nothing else is running"
            % (memory.size(self._footprint.usage), memory.size(self._budget.limit))
        )

    def _grant_locked(self, waiter: _Waiter) -> None:
        self._waiting.remove(waiter)
        waiter.granted = True
        self._running += 1
        if waiter.kind == CALL:
            self._calls += 1
        self._last_start = self._clock()
        waiter.rank.mark_started(self._last_start)
        if waiter.event is not None:
            waiter.event.set()
        elif waiter.future is not None:
            try:
                waiter.loop.call_soon_threadsafe(_resolve, waiter.future)
            except RuntimeError:
                # Its loop is closed, so nobody is waiting any more: the task
                # it was granted is given straight back.
                self._finish_locked(waiter.kind)

    def _finish_locked(self, kind: str) -> None:
        self._running -= 1
        if kind == CALL:
            self._calls -= 1

    def _enqueue(self, kind: str, loop=None) -> _Waiter:
        waiter = _Waiter(kind, current(), self._clock(), loop=loop)
        with self._mutex:
            self._waiting.append(waiter)
            self._dispatch_locked()
            self._watch_locked()
        return waiter

    def _abandon(self, waiter: _Waiter) -> None:
        """A waiter that stopped waiting: take it off the queue, or give back what it was granted."""
        with self._mutex:
            if waiter in self._waiting:
                self._waiting.remove(waiter)
                return
            if waiter.granted:
                self._finish_locked(waiter.kind)
                self._dispatch_locked()

    def _finish(self, kind: str) -> None:
        with self._mutex:
            self._finish_locked(kind)
            self._dispatch_locked()

    def _redispatch(self) -> None:
        with self._mutex:
            self._dispatch_locked()

    # ---- the monitor ---------------------------------------------------------

    def _watch_locked(self) -> None:
        """Have the monitor running while there is a budget and anything runs or waits."""
        if not self._monitor_enabled or self._budget is None:
            return
        if self._monitor is not None and self._monitor.is_alive():
            self._poke.notify_all()
            return
        self._monitor = threading.Thread(target=self._watch, name="partcad-admission", daemon=True)
        self._monitor.start()

    def _watch(self) -> None:
        while True:
            with self._mutex:
                # Idle, keeping the last measurement: work that arrives finds
                # it, and this wakes to measure again. Dropping it made the
                # moment between one object's tasks and the next look like
                # the start of a run, whose unmeasured burst is accepted, and
                # every waiter started at once.
                while self._budget is not None and not (self._waiting or self._running):
                    self._poke.wait()
                if self._budget is None:
                    self._monitor = None
                    return
            try:
                self.tick()
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("The memory monitor failed a round: %s" % e)
            # A round every INTERVAL, however often it is poked meanwhile: a
            # poke is for waking it from idle, and every start and finish
            # dispatches for itself.
            due = time.monotonic() + INTERVAL
            with self._mutex:
                while self._budget is not None:
                    remaining = due - time.monotonic()
                    if remaining <= 0:
                        break
                    self._poke.wait(remaining)
