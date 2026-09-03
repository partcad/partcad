#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Capping how much of one kind of work runs at once, without deadlocking on it.

PartCAD gates its tests and its linting checks so that a recursive run does not
start every check on every object of every package at once. The gate has to hold
two properties that a bare :class:`asyncio.Semaphore` does not, and losing either
one stops the event loop for good rather than slowing it down.

**It is re-entrant.** A check may run the other checks itself: ``CamTest.test``
walks everything an assembly is procured from and runs the whole suite over each
of those objects, and it does that from inside the very call the gate has already
admitted. A plain semaphore counts that nested call as a new arrival, so once as
many callers as the limit are each waiting on a nested call, every permit is held
by somebody waiting for a permit and nothing ever completes. Nested work is
charged to the permit its caller already holds instead.

**It is per event loop.** ``asyncio.Semaphore`` is not thread-safe and binds
itself to the loop it first blocks on, while PartCAD runs an ``asyncio.run()``
per worker thread (``ThreadPoolManager.run_async``) and the JSON-RPC daemon runs
one per request. A single process-wide semaphore is therefore shared between
loops that cannot see each other's waiters -- and, in a daemon, outlives the loop
it was bound to, so the second command of a session is refused by a primitive
belonging to the first command's closed loop.
"""

import asyncio
import contextvars
import os
import threading
import weakref


def default_limit() -> int:
    """How many operations to admit when nothing has said."""
    return max(os.cpu_count() or 1, 8)


class ReentrantGate:
    """An admission limit that nested work passes straight through.

    One instance per kind of work: the limits are unrelated, and so is the
    question of whether a caller is already inside one.
    """

    def __init__(self, name: str):
        # Whether the calling task is already inside this gate. A ContextVar
        # rather than an attribute because the answer is per task: an
        # asyncio.Task copies the context it is created in, so the tasks a check
        # spawns inherit the admission of the check that spawned them, while a
        # task started elsewhere on the same loop does not.
        self._admitted = contextvars.ContextVar(name, default=False)
        # Keyed weakly on the loop, so a loop that has been run and discarded
        # takes its semaphore with it instead of leaving one behind for every
        # request the daemon has ever served.
        self._semaphores: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
        # A plain lock around that mapping, because the loops reaching it are on
        # different threads and 'WeakKeyDictionary' is not thread-safe. It is
        # never held across an await -- only for the lookup.
        self._lock = threading.Lock()

    def _semaphore(self, limit) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._lock:
            semaphore = self._semaphores.get(loop)
            if semaphore is None:
                semaphore = asyncio.Semaphore(limit if limit else default_limit())
                self._semaphores[loop] = semaphore
            return semaphore

    async def run(self, limit, func, *args, **kwargs):
        """Await ``func(*args, **kwargs)``, admitting at most ``limit`` at once.

        A caller already admitted by this gate is not counted again -- it is the
        same unit of work, further in.
        """
        if self._admitted.get():
            return await func(*args, **kwargs)

        async with self._semaphore(limit):
            token = self._admitted.set(True)
            try:
                return await func(*args, **kwargs)
            finally:
                self._admitted.reset(token)
