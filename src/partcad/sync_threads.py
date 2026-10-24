#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-02-09
#
# Licensed under Apache License, Version 2.0.
#
"""The two thread pools PartCAD's own work runs on, and why they cannot deadlock.

A part or a sketch is built on the *constrained* pool ('run_async'), which is
sized by 'threadsMax'; an assembly is instantiated on the *unconstrained* one
('run_detached'), because it computes nothing itself and only waits for what it
is made of. A thread of either pool is a **slot**, and whoever runs on one holds
it until the work it was handed returns.

Objects are built from other objects -- an alias from its source, an extrusion
from its sketch, a compound from an assembly -- and that is where pools of
threads deadlock: the outer object holds a slot while it waits for the inner one
to be built, and if the inner one needs a slot of its own, then as many outer
objects at once as the pool has slots wait for slots that none of them will give
back. That is how 'threadsMax: 2' stopped 'pc render -r' for good, and pools of
four and of seven stopped the same way with four and seven such objects at once.

Two rules make that impossible, whatever the size of either pool.

**Work started on a slot runs on that slot.** A coroutine handed to the pools by
a thread that already holds a slot is simply awaited where it is, in the event
loop that is already running there: it is a further step of the work that holds
the slot, not a new arrival. A synchronous function cannot be called on that
thread -- it may well run an event loop of its own, which a thread already
running one cannot -- so it runs on a thread that is not counted against either
pool, which the slot holder waits for in its place. Only work started from
outside the pools, which is every top-level object a command asks for, waits for
a slot; and that is what still fans out over the whole pool. So nothing that
holds a slot ever waits for another slot, and nesting is as deep as it likes.
This is the rule 'concurrency.ReentrantGate' applies to tests and linting.

**A slot holder waiting for a lock gives its slot back while the lock's holder
is not making progress on a slot of its own.** A shape is locked while it is
built ('Shape.locked()'), and the lock can be held by a thread that holds no
slot and is waiting for the pool: the event loop a command runs on holds an
assembly's lock while the assembly's children are built, and a part's while it
asks for the part from inside that lock ('get_solidity_async' does). Waiting for
such a lock while keeping the slot is the same deadlock as before, one step
removed -- the work the holder waits for may be queued behind the very threads
that wait for the holder. So while it waits, such a slot does not count against
its pool, and the pool admits the next piece of work in its place
('PoolAwareRLock'). A holder that does hold a slot, and is not itself waiting
like this, needs nothing from the pool to finish, so waiting for it costs only
the slot it is held on. A shape that another caller is preparing is waited for
the same way ('waiting', used by 'partcad.preparation'), since a preparation
can take such a lock. The commonest case does not arise at all: a part or a
sketch that a command asks for goes to the pool before its lock is taken, so the
thread holding it while it is built is the thread building it (see
'Shape.get_wrapped').

Neither pool is a strict limit, and neither was before; a slot given back lets
a pool run over its size for as long as the wait lasts. The strict limit is the
number of sandbox processes ('sandbox_lock.process_slots'), and it is the one
that decides how much of the machine a render takes.
"""

import asyncio
import collections
import concurrent.futures
import os
import sys
import threading
import time

from opentelemetry import context as otel_context

from .user_config import cpu_cores, user_config

# What the thread a piece of work runs on is doing it for, or None on a thread
# that holds no slot. A thread-local rather than a context variable: what holds
# a slot is the thread, and every task of the event loop running on it shares
# that one thread. A context variable would also follow work onto threads that
# hold nothing -- 'asyncio.to_thread' copies the context it is called from.
_local = threading.local()

# The same, for every thread running pool work right now, keyed by the thread's
# identity: whoever waits for a lock reads the holder's entry here (see
# 'PoolAwareRLock'). A plain dictionary, whose single reads and writes the
# interpreter keeps atomic, because it is read from threads other than the one
# that writes it.
_slots = {}

# How long a contended lock is waited for between attempts, and so how soon a
# waiter notices both that the lock was released and that its holder has
# started or stopped making progress. The same bounds 'sandbox_lock' polls with:
# a shape is held for as long as it takes to build, which is seconds, so the
# upper bound costs nothing, and the lower one keeps a lock that was released a
# moment after it was asked for from being waited for any longer than that.
_POLL_MIN = 0.002
_POLL_MAX = 0.05

# The most threads one pool may start, counting the ones that run work which
# holds no slot of its own (see 'SlotPool.submit_on') and the ones waiting with
# their slot given back. Neither of those may ever wait for a thread, or the
# deadlock this module exists to rule out comes back through the threads instead
# of the slots, so this is not a limit anything reaches: how many slots there
# are is 'SlotPool.size'. Threads are started when nothing idle can take the
# work, and kept for the life of the process, as 'ThreadPoolExecutor' keeps
# them -- so a pool has as many as it ever ran at once.
_THREADS_UNBOUNDED = sys.maxsize


class _Slot:
    """One slot of a pool, as held by the work admitted to it.

    Work started on a slot shares this object with the work that started it,
    whichever thread it runs on (see 'SlotPool.submit_on'), so giving the slot
    back is one thing however many of those threads are waiting at once.
    """

    __slots__ = ("pool", "_given_back")

    def __init__(self, pool: "SlotPool"):
        self.pool = pool
        # How many of the threads working on this slot are waiting with it
        # given back. Changed under the pool's lock.
        self._given_back = 0

    @property
    def given_back(self) -> bool:
        return self._given_back > 0

    def give_back(self):
        self.pool._give_back(self)

    def take_back(self):
        self.pool._take_back(self)


class _Work:
    """A call handed to a pool: what to run, the future it answers, its tracing context."""

    __slots__ = ("fn", "args", "kwargs", "future", "context", "slot", "admitted")

    def __init__(self, fn, args, kwargs, slot=None):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.future = concurrent.futures.Future()
        # Taken here, on the thread that asks, because that is whose trace the
        # work belongs to; the thread that eventually runs it has no idea.
        self.context = otel_context.get_current()
        # The slot it runs on: the one it was admitted to, or the one of
        # whoever asked for it (see 'SlotPool.submit_on').
        self.slot = slot
        # Whether it holds a slot of the pool it was handed to, and so has one
        # to release when it finishes.
        self.admitted = False


class SlotPool(concurrent.futures.Executor):
    """A pool that runs at most 'size' pieces of work at once, on threads of its own.

    'ThreadPoolExecutor(size)' limits the number of threads, which is the wrong
    thing to limit here: work waiting on a slot it already holds has to run on a
    thread without waiting for one, and a slot that has been given back has to
    let the next piece of work in while its own thread is still alive. So the
    threads come from an executor that is not limited, and what is limited is how
    many pieces of work that were admitted -- 'submit' -- are running and have
    not given their slot back.
    """

    def __init__(self, size: int, thread_name_prefix: str):
        self.size = size
        self._threads = concurrent.futures.ThreadPoolExecutor(
            max_workers=_THREADS_UNBOUNDED, thread_name_prefix=thread_name_prefix
        )
        self._lock = threading.Lock()
        # Work waiting for a slot, first come first served.
        self._waiting = collections.deque()
        # How many slots are taken: work admitted and not finished, less the
        # slots that are given back right now.
        self._taken = 0

    def submit(self, fn, /, *args, **kwargs):
        """Run 'fn(*args, **kwargs)' on a slot of this pool, once one is free."""
        work = _Work(fn, args, kwargs)
        with self._lock:
            self._waiting.append(work)
        self._admit()
        return work.future

    def submit_on(self, slot: _Slot, fn, /, *args, **kwargs):
        """Run 'fn(*args, **kwargs)' now, on 'slot' -- the slot of whoever is asking.

        On a thread of this pool's, but on nobody's slot of this pool's: it is a
        step of the work that holds 'slot', which waits for it, so it takes no
        slot and waits for none.
        """
        work = _Work(fn, args, kwargs, slot=slot)
        # A future nobody else has seen cannot have been cancelled yet.
        work.future.set_running_or_notify_cancel()
        self._start(work)
        return work.future

    def shutdown(self, wait=True, *, cancel_futures=False):
        if cancel_futures:
            with self._lock:
                waiting = list(self._waiting)
                self._waiting.clear()
            for work in waiting:
                work.future.cancel()
        self._threads.shutdown(wait=wait, cancel_futures=cancel_futures)

    def _next_locked(self):
        """The next piece of waiting work, now holding a slot -- or None. Under the lock."""
        while self._waiting and self._taken < self.size:
            work = self._waiting.popleft()
            # Cancelled while it waited (the caller's task was), so it never
            # runs, and takes no slot.
            if not work.future.set_running_or_notify_cancel():
                continue
            self._taken += 1
            work.slot = _Slot(self)
            work.admitted = True
            return work
        return None

    def _admit(self):
        """Start whatever waiting work there are slots for now."""
        while True:
            with self._lock:
                work = self._next_locked()
            if work is None:
                return
            self._start(work)

    def _start(self, work: _Work):
        while work is not None:
            try:
                self._threads.submit(self._run, work)
                return
            except RuntimeError as e:
                # Shut down, or the interpreter is exiting: the work will not
                # run, and its caller is told so rather than left waiting.
                following = self._release(work)
                work.future.set_exception(e)
                work = following

    def _run(self, work: _Work):
        # And then whatever its slot is handed to next, on this same thread:
        # admitted anywhere else, it would be admitted while this thread is
        # still busy here, and the pool would start a thread for it every time.
        while work is not None:
            succeeded, outcome = self._execute(work)
            following = self._release(work)
            if succeeded:
                work.future.set_result(outcome)
            else:
                work.future.set_exception(outcome)
            work = following

    @staticmethod
    def _execute(work: _Work):
        ident = threading.get_ident()
        _slots[ident] = work.slot
        _local.slot = work.slot
        token = otel_context.attach(work.context)
        try:
            return True, work.fn(*work.args, **work.kwargs)
        except BaseException as e:
            return False, e
        finally:
            otel_context.detach(token)
            _local.slot = None
            _slots.pop(ident, None)

    def _release(self, work: _Work):
        """Free the slot 'work' held, and return what it goes to next, to run on this thread.

        Nothing for work that ran on its caller's slot: it took none of this
        pool's.
        """
        if not work.admitted:
            return None
        work.admitted = False
        with self._lock:
            self._taken -= 1
            following = self._next_locked()
        return following

    def _give_back(self, slot: _Slot):
        with self._lock:
            slot._given_back += 1
            if slot._given_back != 1:
                return
            self._taken -= 1
        self._admit()

    def _take_back(self, slot: _Slot):
        # Without waiting for it: the work coming back already holds whatever it
        # was waiting for, and making it wait again for a slot is how a slot
        # holder ends up waiting for a slot. The pool runs over its size until
        # enough of what it admitted in the meantime has finished.
        with self._lock:
            slot._given_back -= 1
            if slot._given_back == 0:
                self._taken += 1


def current_slot():
    """The slot the calling thread is working on, or None if it holds none."""
    return getattr(_local, "slot", None)


def _run_to_completion(coroutine, args):
    return asyncio.run(coroutine(*args))


class ThreadPoolManager:
    def __init__(self, threads_max: int):
        # How many slots the constrained pool has. A configured 'threadsMax' is
        # at least THREADS_MAX_MINIMUM by the time it gets here ('UserConfig'
        # raises it), for the reasons given there; nothing about this pool
        # needs it to be, because nothing waits on it while holding a slot of
        # it (see the top of this module).
        if threads_max is not None:
            cpu_count = threads_max
        else:
            cpu_count = cpu_cores()
            if cpu_count < 8:
                # Seven on a machine with fewer than eight cores. This used to be
                # here so that PartCAD would not deadlock itself on a small
                # machine -- nested objects each held a slot while waiting for
                # another -- and that can no longer happen at any size. It stays
                # because the pool should not be smaller than the number of
                # sandbox processes PartCAD runs when nothing says otherwise --
                # one per core, and at least four (see 'default_threads_max') --
                # since what a slot of this pool spends most of its time on is
                # waiting for one of those: with fewer slots than processes,
                # some of the processes would never be used. Seven is not less
                # than that on any machine with fewer than eight cores.
                cpu_count = 7
            else:
                # Leave one core for the asyncio event loop and stuff
                cpu_count -= 1

        # Calculate thread counts
        constrained = cpu_count
        unconstrained = 2 + cpu_count * 2

        # Windows thread limit adjustment
        if os.name == "nt":
            constrained = min(constrained, 61)
            unconstrained = min(unconstrained, 61)

        # Create executors
        self.constrained_executor = SlotPool(constrained, "partcad-executor-")
        self.unconstrained_executor = SlotPool(unconstrained, "partcad-executor-others-")

    async def run(self, method, *args):
        """Run 'method(*args)' on the constrained pool.

        On a slot of it; or, from a thread that holds a slot already, at once on
        a thread that takes none (see the top of this module).
        """
        return await asyncio.wrap_future(self._submit(self.constrained_executor, method, *args))

    async def run_detached(self, method, *args):
        """Run 'method(*args)' on the unconstrained pool, the way 'run' does on the other."""
        return await asyncio.wrap_future(self._submit(self.unconstrained_executor, method, *args))

    async def run_async(self, coroutine, *args):
        """Await 'coroutine(*args)' on a slot of the constrained pool, in a loop of its own.

        Or right here, from a thread that holds a slot of either pool already.
        """
        if current_slot() is not None:
            # On a slot already, of either pool: this is more of the work that
            # holds it, so it is awaited here, in the loop already running,
            # rather than handed to a thread that would have to wait for a slot
            # -- see the top of this module. In the same task, too, so that
            # whatever the caller holds ('Shape.locked()' is re-entrant per
            # task) is still held, and the trace it is part of is the caller's.
            return await coroutine(*args)
        return await self.run(_run_to_completion, coroutine, args)

    async def run_async_detached(self, coroutine, *args):
        """'run_async', on the unconstrained pool."""
        if current_slot() is not None:
            return await coroutine(*args)
        return await self.run_detached(_run_to_completion, coroutine, args)

    def complete(self, coroutine):
        """Run 'coroutine' to completion on another thread and wait for it.

        For synchronous code that is running inside an event loop, where
        'asyncio.run()' refuses to start a second one. The waiting blocks the
        calling thread, so a caller holding a slot is not made to wait for
        another one to do it on.
        """
        return self._submit(self.unconstrained_executor, asyncio.run, coroutine).result()

    @staticmethod
    def _submit(pool: SlotPool, method, *args):
        slot = current_slot()
        if slot is None:
            return pool.submit(method, *args)
        return pool.submit_on(slot, method, *args)

    def shutdown(self, wait=True, *, cancel_futures=False):
        """Stop both pools. For a manager of a test's own, which the process outlives."""
        self.constrained_executor.shutdown(wait=wait, cancel_futures=cancel_futures)
        self.unconstrained_executor.shutdown(wait=wait, cancel_futures=cancel_futures)


class PoolAwareRLock:
    """A re-entrant lock that work on the pools can wait for without deadlocking them.

    'threading.RLock' -- re-entrant for the thread holding it -- with two
    differences, which a shape's lock needs because it is held across 'await's
    and waited for from several threads at once, some of them event loops and
    some of them holding a slot:

    * ``async with`` takes it **without blocking the event loop**. It tries,
      and on failure awaits a poll of the same try, as 'sandbox_lock' does. A
      loop that blocked waiting for it could not run the task beside it, and
      that task may be what the holder is waiting for.

    * a thread holding a slot that waits for it **gives the slot back** for as
      long as the holder is not making progress on a slot of its own: a holder
      with no slot at all, or one whose slot is given back because it is itself
      waiting like this. The holder may be waiting for work the pool has not
      started, and the slots of the threads waiting for the holder are exactly
      what that work needs (see the top of this module). A holder that is
      working on a slot needs nothing from the pool to finish, and giving a slot
      back for one of those would only start another thread to wait beside it.
      Re-checked every time it polls, since holders come and go.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # The thread holding it, and how many times it has: written only by
        # that thread, while it holds it, and read by the threads waiting.
        self._owner = None
        self._depth = 0

    def _try(self, timeout=None) -> bool:
        if timeout is None:
            acquired = self._lock.acquire(blocking=False)
        else:
            acquired = self._lock.acquire(timeout=timeout)
        if acquired:
            self._owner = threading.get_ident()
            self._depth += 1
        return acquired

    def _waiting(self):
        # Whoever holds it, or None when it is free -- or about to be, which
        # the next try will tell.
        return waiting(lambda: self._owner)

    def acquire(self, blocking=True, timeout=-1) -> bool:
        if self._try():
            return True
        if not blocking:
            return False
        deadline = None if timeout is None or timeout < 0 else time.monotonic() + timeout
        with self._waiting() as waiting:
            while True:
                waiting.update()
                wait = _POLL_MAX if deadline is None else max(0.0, min(_POLL_MAX, deadline - time.monotonic()))
                if self._try(wait):
                    return True
                if deadline is not None and time.monotonic() >= deadline:
                    return False

    def release(self):
        if self._owner != threading.get_ident():
            raise RuntimeError("cannot release un-acquired lock")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
        self._lock.release()

    async def acquire_async(self):
        if self._try():
            return
        delay = _POLL_MIN
        with self._waiting() as waiting:
            while True:
                waiting.update()
                await asyncio.sleep(delay)
                if self._try():
                    return
                delay = min(delay * 2, _POLL_MAX)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    async def __aenter__(self):
        await self.acquire_async()
        return self

    async def __aexit__(self, *exc):
        self.release()


def needs_the_pool(thread) -> bool:
    """Whether 'thread' may be waiting for one of the pools, rather than working on a slot of its own.

    A thread that holds no slot may be waiting for the pool's queue -- the event
    loop a command runs on does. A thread whose slot is given back is itself
    waiting like that, at one remove. None, for nobody, needs nothing.
    """
    if thread is None:
        return False
    slot = _slots.get(thread)
    return slot is None or slot.given_back


def waiting(holder):
    """A wait by the calling thread for something 'holder()' names the thread of.

    Call 'update()' on it each time the wait is looked at again: a thread
    holding a slot gives it back for as long as the thread it waits for
    'needs_the_pool()', and takes it back when that stops, or when the wait
    ends. Nothing for a thread that holds no slot. 'PoolAwareRLock' waits this
    way, and so does a shape waiting for another caller's preparation of it
    ('partcad.preparation'): both are waits a slot must not spend holding the
    slot when what it waits for is waiting for the pool.
    """
    return _Waiting(holder)


class _Waiting:
    def __init__(self, holder):
        self.holder = holder
        self.slot = current_slot()
        self.giving_back = False

    def update(self):
        if self.slot is None:
            return
        if needs_the_pool(self.holder()):
            if not self.giving_back:
                self.giving_back = True
                self.slot.give_back()
        elif self.giving_back:
            self.giving_back = False
            self.slot.take_back()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.giving_back:
            self.giving_back = False
            self.slot.take_back()


threadpool_manager = ThreadPoolManager(user_config.threads_max)
