#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Concurrency control over the sandboxes that wrappers run in.

Two things are shared by everything that runs a wrapper, and both used to be
guarded by a single mutex per runtime, held across the whole subprocess:

  * A sandbox *environment* -- a conda prefix or a v-env. Every wrapper that
    runs in it reads its package set; every install into it rewrites that set.
    Readers do not conflict with each other, only with an install, so this is a
    readers/writer lock rather than a mutex. It is keyed on the environment's
    path, which is what a wrapper actually runs out of. The v-env lock it
    replaces was keyed on the session, which gave two packages sharing the base
    environment two different locks over the same files, and gave the same
    environment two names depending on who asked for it.

  * The machine. A wrapper is a full CAD interpreter, several hundred megabytes
    of it, so it is the number of concurrent *processes* and not the number of
    threads that decides whether a render keeps the box busy or swaps it to
    death. 'process_slots' is that budget. It was previously implicit: the
    runtime mutex allowed exactly one.

Both are held across 'await's, and both are taken from more than one event loop
at a time -- a part is instantiated on a worker thread that runs a loop of its
own (see sync_threads). So neither can be an asyncio primitive, which belongs
to one loop, and neither may block the loop it is taken from: a task that
blocks its own loop waiting for a lock that another task on that same loop is
about to release deadlocks outright. The asynchronous acquires therefore await
a poll of a non-blocking try, which is what lets one implementation serve every
loop without a thread per waiter.
"""

import asyncio
import contextlib
import os
import threading
import time

from filelock import FileLock, Timeout

from .user_config import user_config

# How long a contended acquire waits between attempts. Contention only happens
# around an install, which takes seconds, so the upper bound costs nothing and
# the lower bound keeps an uncontended-but-just-missed acquire prompt.
_POLL_MIN = 0.002
_POLL_MAX = 0.1


class EnvironmentLock:
    """A readers/writer lock over one sandbox environment.

    Readers run wrappers out of the environment; writers install into it or
    create it. Readers share it, a writer excludes everyone.

    Within this process that is the whole story. Across processes only the
    writers are held apart, by the file lock below - which is what the
    per-environment lock file has always been for: two pip installs into one
    prefix are what actually leaves an environment broken. A wrapper reading an
    environment that another process is installing into is not covered, and was
    not covered before either for anything running out of the runtime's own
    environment, since installs into it took one lock file and runs out of it
    took another.

    Closing that gap needs a lock file a reader can hold in *shared* mode.
    Holding this exclusive one for reading would do it, but it would also mean
    a busy render in one workspace stopping every other PartCAD process on the
    machine for as long as it runs, reader against reader included - a worse
    bargain than the gap. filelock's SQLite-backed ReadWriteLock is what to
    reach for when its floor can be raised.

    Only one instance may exist per lock file, which is what 'get()' is for:
    filelock counts recursive acquires per object, so two objects over one path
    would each believe they hold it.
    """

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        # thread_local=False: what holds this is a group of readers or one
        # writer, neither of which is a thread.
        self._file_lock = FileLock(lock_path, thread_local=False)
        self._mutex = threading.Lock()
        self._readers = 0
        self._writer = False
        # Readers defer to a writer that is already waiting, so that a steady
        # stream of wrappers cannot starve the install one of them is waiting
        # for. Safe against the deadlock a bounded thread pool would introduce
        # here because waiters poll rather than occupy anything.
        self._writers_waiting = 0

    def _try_acquire(self, write: bool) -> bool:
        with self._mutex:
            if write:
                if self._writer or self._readers:
                    return False
                try:
                    self._file_lock.acquire(blocking=False)
                except Timeout:
                    # Another process is installing into this environment.
                    return False
                self._writer = True
            else:
                if self._writer or self._writers_waiting:
                    return False
                self._readers += 1
            return True

    def _release(self, write: bool) -> None:
        with self._mutex:
            if write:
                self._writer = False
                self._file_lock.release()
            else:
                self._readers -= 1

    def _wait_sync(self, write: bool) -> None:
        if self._try_acquire(write):
            return
        if write:
            with self._mutex:
                self._writers_waiting += 1
        try:
            delay = _POLL_MIN
            while not self._try_acquire(write):
                time.sleep(delay)
                delay = min(delay * 2, _POLL_MAX)
        finally:
            if write:
                with self._mutex:
                    self._writers_waiting -= 1

    async def _wait_async(self, write: bool) -> None:
        if self._try_acquire(write):
            return
        if write:
            with self._mutex:
                self._writers_waiting += 1
        try:
            delay = _POLL_MIN
            while not self._try_acquire(write):
                await asyncio.sleep(delay)
                delay = min(delay * 2, _POLL_MAX)
        finally:
            if write:
                with self._mutex:
                    self._writers_waiting -= 1

    @contextlib.contextmanager
    def acquire(self, write: bool = False):
        self._wait_sync(write)
        try:
            yield
        finally:
            self._release(write)

    @contextlib.asynccontextmanager
    async def acquire_async(self, write: bool = False):
        await self._wait_async(write)
        try:
            yield
        finally:
            self._release(write)


_environment_locks: dict[str, EnvironmentLock] = {}
_environment_locks_lock = threading.Lock()


def get(lock_path: str) -> EnvironmentLock:
    """The one lock over the environment this lock file stands for."""
    with _environment_locks_lock:
        if lock_path not in _environment_locks:
            _environment_locks[lock_path] = EnvironmentLock(lock_path)
        return _environment_locks[lock_path]


# conda serializes poorly against itself whatever it is installing -- the
# package cache and the solver's own state are shared by every prefix -- so what
# this stands for is conda, not any one environment. Named here rather than in
# the runtimes so that the Python and the JavaScript conda sandboxes cannot
# drift into naming two files and believing they share one.
CONDA_LOCK_NAME = ".conda.lock"


def conda(internal_state_dir: str) -> EnvironmentLock:
    """The one lock over conda itself, whatever is being provisioned with it.

    Always taken for writing: everything conda is asked to do here creates or
    installs into a prefix, so there is no reader half to share.

    A lock over conda has to be one object, and used to be one per runtime: the
    Python 3.11 sandbox, the Python 3.13 sandbox and the Node.js sandbox each
    built a FileLock of their own over this path. Across processes that still
    worked, and across threads it worked by accident -- the second thread waited
    on the file. Two of them on one event loop did not: a render holds this lock
    across an 'await' while conda runs, so the next task to reach it was the
    same thread asking for a lock it already held through another object, which
    filelock refuses outright ("Deadlock: ... already held by a different
    FileLock instance in this thread"). Refusing was the kind thing to do; the
    alternative was hanging.

    So the fix is not to talk filelock out of noticing -- 'is_singleton=True'
    would hand the second task the lock, which is the one outcome worse than
    either -- but to make the lock what it always claimed to be: one object,
    shared, with the waiting done by EnvironmentLock rather than by the file.
    """
    return get(os.path.join(internal_state_dir, CONDA_LOCK_NAME))


class ProcessSlots:
    """How many sandbox interpreters may run at once.

    A wrapper is a process, not a thread, and a CAD one at that: the ceiling
    that matters is the machine's, not the thread pool's. Without this a
    recursive render would fan out over every package, every shape and every
    file type at once and ask the machine for hundreds of OpenCASCADE
    interpreters.

    Taken *inside* whatever environment lock the caller holds and released
    before that lock is, so the two can never wait on each other: a slot holder
    is always running, never waiting for a lock.
    """

    def __init__(self, count: int):
        self.count = count
        self._semaphore = threading.BoundedSemaphore(count)

    @contextlib.contextmanager
    def slot(self):
        if not self._semaphore.acquire(blocking=False):
            delay = _POLL_MIN
            while not self._semaphore.acquire(blocking=False):
                time.sleep(delay)
                delay = min(delay * 2, _POLL_MAX)
        try:
            yield
        finally:
            self._semaphore.release()

    @contextlib.asynccontextmanager
    async def slot_async(self):
        if not self._semaphore.acquire(blocking=False):
            delay = _POLL_MIN
            while not self._semaphore.acquire(blocking=False):
                await asyncio.sleep(delay)
                delay = min(delay * 2, _POLL_MAX)
        try:
            yield
        finally:
            self._semaphore.release()


def _process_slot_count() -> int:
    """One interpreter per core, or whatever 'threadsMax' says instead.

    'threadsMax' is the user's statement of how much of the machine PartCAD may
    have; it named threads because threads were all there was to name.
    """
    if user_config.threads_max is not None:
        return max(1, user_config.threads_max)
    return max(2, os.cpu_count() or 1)


process_slots = ProcessSlots(_process_slot_count())
