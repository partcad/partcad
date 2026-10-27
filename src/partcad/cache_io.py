#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The one thread the cache's remote tiers do their I/O on.

PartCAD drives its async work through many short event loops: every task the
pools run is an 'asyncio.run()' of its own (see 'sync_threads'), and every
synchronous accessor is one more. A network client belongs to the loop that
opened it, so a remote tier used to open a client for each loop that asked it
something and close it again when that loop's last request was over. A shape
is read in one pool task and written in another, so it cost at least two
client opens -- a TCP connect each, and against S3 a TLS handshake each, which
is tens of milliseconds apiece before a byte of the entry has moved.

So the remote tiers' clients belong to a loop that lives as long as the process,
on a thread of its own. Everything else hands that loop the request and waits
for the answer without blocking its own loop ('run_coroutine_threadsafe' on one
side, 'wrap_future' on the other). A client is opened the first time a tier
needs it, shared by every tier that reaches the same server, and closed once,
when the process exits or PartCAD is de-initialised ('shutdown').

Three more things live on that loop, because each is state about a remote tier
that every caller in the process has to agree on, and keeping it on the one
thread is what lets it do without locks:

* **Write-behind.** A remote write is queued here and the caller goes on; the
  write is sent from this loop. A shape's cache write is made while the shape's
  lock is held, so a PUT to S3 used to sit in front of everything waiting for
  that shape. The queue is bounded ('MAX_QUEUED_BYTES', 'MAX_QUEUED_ENTRIES'):
  a writer that finds it full waits for room, which is back-pressure rather
  than memory growing for as long as the network is slower than the builds.
  What is queued is sent before the process exits, within 'EXIT_TIMEOUT'. A
  write that fails is logged as it always was, and the entry is then simply not
  there -- as if the tier had evicted it, which a shared cache may do anyway.

* **Read-your-writes.** An entry that is queued, or on its way, is visible to
  every read and existence check in this process from the moment its write
  returned, because the queue holds its bytes anyway and a lookup here looks in
  the queue first. The files tier is not deferred at all (see 'cache.py'), so
  another process on this machine sees an entry as soon as this one does.

* **Known misses.** Most of what is asked of a remote tier is not there: a
  shape is read together with its components ('cmps') and its properties are
  read on their own ('-props'), and both are usually absent. Without a memo
  each of those costs a memcached round trip and an S3 GET answering 404 on
  every read -- even when the shape itself was a local hit. So what a tier
  answered "not here" for is remembered ('_KnownMisses'). See there for why it
  expires and why only a definite answer is remembered.
"""

import asyncio
import collections
import concurrent.futures
import contextvars
import os
import threading
import time

from opentelemetry import context as otel_context

from . import logging as pc_logging

# How much may be queued for the remote tiers at once, in bytes and in entries.
# A shape's entry is already held in memory by the shape that produced it, so
# what the bound limits is how far the queue can keep payloads alive past the
# memory tier's own decisions -- and how much is lost if the process is killed
# rather than stopped. An entry bigger than the whole bound is still taken, once
# the queue is empty, or it could never be written at all.
MAX_QUEUED_BYTES = 64 << 20
MAX_QUEUED_ENTRIES = 1024

# How many queued writes are sent at once. S3 takes one object per request and
# memcached one item per 'set', so this is what keeps a burst of builds from
# being written one round trip at a time; botocore pools ten connections, and
# the memcached client is opened with as many (see 'cache_backend_memcache').
MAX_CONCURRENT_WRITES = 8

# How long "not here" is believed, in seconds. A key names what produced the
# entry, not when, so a miss that has gone stale can only cost work and never
# serve the wrong bytes: somebody else wrote the entry in the meantime, and this
# process builds what it could have fetched -- and writes it, which clears the
# miss. Long enough to cover the many reads one command makes of the same
# entries (each output of an object, every property lookup), short enough that a
# daemon serving for hours picks up what a CI fleet published a minute ago.
KNOWN_MISS_TTL = 60.0
# And how many are remembered, the oldest forgotten first: a key and a deadline
# each, so this is a few megabytes at most for a daemon that has seen a lot.
KNOWN_MISS_MAX = 1 << 16

# What the thread is called, which is how a test tells that none is left behind.
THREAD_NAME = "partcad-cache-io"

# How long the process waits, when it exits or PartCAD is de-initialised, for
# what is queued to be sent. Below the 30 s 'pc daemon stop' waits for a daemon
# to be gone ('partcad_client.daemon.STOP_TIMEOUT'), so that a tier that has
# stopped answering costs the writes it holds and not an upgrade that gives up.
EXIT_TIMEOUT = 20.0
# And for the clients to close after that.
CLOSE_TIMEOUT = 5.0


class Unavailable(RuntimeError):
    """The I/O thread cannot be had, because the process is exiting."""


def _now() -> float:
    """The clock a remembered miss expires by."""
    return time.monotonic()


class _KnownMisses:
    """The entries remote tiers recently answered "not here" for. Used on the I/O loop only.

    Keyed by '(location, name)', where the location says which tier and which
    namespace in it (see 'RemoteCacheBackend.location'), so every cache of every
    context in this process shares what each of them learnt about a tier.

    Three rules keep it from hiding an entry that is there:

    * **It expires** ('KNOWN_MISS_TTL'). Another process or another machine may
      write the entry at any moment, through a tier they share, and a warm
      daemon lives for hours. A stale miss costs a build, never a wrong answer
      (see the TTL), and it is bounded in time.
    * **This process's own write clears it** ('forget'), at the moment the write
      is queued, so a write is never followed by a miss of what it wrote. That
      includes a lookup that was already on the wire when the write was queued:
      its "not here" may describe the tier from before the write landed, so it
      is not remembered either.
    * **Only a definite answer is remembered.** A tier that could not be asked
      -- refused, timed out, answered an error -- has said nothing about the
      entry, and a lookup of it is tried again next time (see
      'CacheBackend._read_guarded').

    The files tier has none of this. A miss there is a failed open(), which is
    cheaper than remembering it, and other processes on this machine write that
    directory all the time.
    """

    def __init__(self, limit: int = None) -> None:
        self.limit = KNOWN_MISS_MAX if limit is None else limit
        # key -> when the miss stops being believed (see '_now').
        self._deadlines = collections.OrderedDict()
        # key -> how many lookups of it are on the wire right now.
        self._looking = {}
        # The keys among those that this process wrote while they were.
        self._written = set()

    def known(self, key) -> bool:
        deadline = self._deadlines.get(key)
        if deadline is None:
            return False
        if deadline <= _now():
            del self._deadlines[key]
            return False
        return True

    def begin(self, keys) -> None:
        """Lookups of 'keys' are going out."""
        for key in keys:
            self._looking[key] = self._looking.get(key, 0) + 1

    def end(self, keys, missing) -> None:
        """The lookups of 'keys' are over, and the tier said it does not have 'missing'."""
        deadline = _now() + KNOWN_MISS_TTL
        for key in keys:
            if key in missing and key not in self._written:
                self._deadlines[key] = deadline
                self._deadlines.move_to_end(key)
            count = self._looking[key] - 1
            if count:
                self._looking[key] = count
            else:
                del self._looking[key]
                self._written.discard(key)
        while len(self._deadlines) > self.limit:
            self._deadlines.popitem(last=False)

    def forget(self, key) -> None:
        """This process wrote 'key': whatever a tier said about it before is out of date."""
        self._deadlines.pop(key, None)
        if key in self._looking:
            self._written.add(key)


class _Entry:
    """One queued write: the tier it is for, the name, and the bytes."""

    __slots__ = ("backend", "name", "value")

    def __init__(self, backend, name: str, value: bytes) -> None:
        self.backend = backend
        self.name = name
        self.value = value


class _WriteBehind:
    """The remote tiers' writes, queued and sent from the I/O loop. Used on that loop only.

    Every write of an entry replaces the one queued before it, and one entry is
    never sent twice at once, so what a tier ends up holding is the last thing
    this process wrote to it, as it would have been had every write been
    awaited in turn.
    """

    def __init__(self, misses: _KnownMisses) -> None:
        self.misses = misses
        # (location, name) -> _Entry, for everything written and not landed yet:
        # queued, or being sent. What a lookup in this process looks in first.
        self.pending = {}
        # The keys waiting to be sent, each at most once, oldest first.
        self._queue = collections.deque()
        self._queued = set()
        # key -> a future that is done when the send of it under way is over.
        self._sending = {}
        self._bytes = 0
        self._running = 0
        self._workers = set()
        # Notified whenever an entry lands (or fails to), which is what both a
        # writer waiting for room and a flush wait for. Made on the I/O loop.
        self._changed = asyncio.Condition()

    def _has_room(self, key, size: int) -> bool:
        replaced = self.pending.get(key)
        held = self._bytes - (len(replaced.value) if replaced is not None else 0)
        count = len(self.pending) - (1 if replaced is not None else 0)
        if count == 0:
            return True
        return held + size <= MAX_QUEUED_BYTES and count < MAX_QUEUED_ENTRIES

    async def put(self, backend, items: dict) -> dict:
        """Queue 'items' for 'backend', waiting for room first if the queue is full."""
        taken = {}
        async with self._changed:
            for name, value in items.items():
                if not isinstance(value, bytes):
                    # Held past the caller's return, so it must not change under us.
                    value = bytes(value)
                key = (backend.location, name)
                await self._changed.wait_for(lambda: self._has_room(key, len(value)))
                replaced = self.pending.get(key)
                if replaced is not None:
                    self._bytes -= len(replaced.value)
                self.pending[key] = _Entry(backend, name, value)
                self._bytes += len(value)
                self.misses.forget(key)
                if key not in self._queued:
                    self._queued.add(key)
                    self._queue.append(key)
                taken[name] = True
                self._start()
        return taken

    def _start(self) -> None:
        loop = asyncio.get_running_loop()
        # A worker that is sending takes nothing from the queue until it is
        # done, so it is the idle ones that have to cover what is waiting.
        while self._running < MAX_CONCURRENT_WRITES and self._running - len(self._sending) < len(self._queue):
            self._running += 1
            # In a context of its own rather than a copy of the writer's: a
            # worker sends whatever is queued next, so the trace of the write
            # that happened to start it is not the trace of what it sends.
            task = contextvars.Context().run(loop.create_task, self._work())
            self._workers.add(task)
            task.add_done_callback(self._workers.discard)

    async def _work(self) -> None:
        try:
            while self._queue:
                key = self._queue.popleft()
                self._queued.discard(key)
                # An earlier write of the same entry still on the wire lands
                # first: sent side by side, the older could arrive last.
                while key in self._sending:
                    await asyncio.wait({self._sending[key]})
                entry = self.pending.get(key)
                if entry is None:
                    continue
                done = asyncio.get_running_loop().create_future()
                self._sending[key] = done
                try:
                    # Failures are contained and logged there, exactly as an
                    # awaited write's were.
                    await entry.backend._write_guarded({entry.name: entry.value})
                finally:
                    del self._sending[key]
                    done.set_result(None)
                    if self.pending.get(key) is entry:
                        del self.pending[key]
                        self._bytes -= len(entry.value)
                    async with self._changed:
                        self._changed.notify_all()
        finally:
            # With no await between the empty queue and this, so that a write
            # queued after it sees the worker gone and starts another.
            self._running -= 1

    def queued(self, location=None) -> int:
        return sum(1 for key in self.pending if location is None or key[0] == location)

    async def flush(self, location=None) -> None:
        """Wait until everything written so far (to the tier at 'location', or anywhere) has landed."""
        async with self._changed:
            await self._changed.wait_for(lambda: self.queued(location) == 0)

    def cancel(self) -> None:
        for task in list(self._workers):
            task.cancel()


class _Loop:
    """The I/O thread, its event loop, and what lives on it."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        # client key -> (client, the coroutine function that closes it).
        self._clients = {}
        self._opening = {}
        self.misses = _KnownMisses()
        self.writes = None
        # A daemon thread, because the interpreter waits for every other kind
        # before it runs what would stop this one; 'shutdown' is what ends it.
        self.thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        try:
            self.thread.start()
        except BaseException:
            self.loop.close()
            raise
        # The asyncio primitives are made on the loop that uses them.
        self.submit(self._setup()).result()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        # Which I/O loop this thread is, for whatever runs on it: '_current'
        # stops saying so the moment 'shutdown' begins, and the writes it then
        # waits for still have to reach their clients.
        _local.io = self
        try:
            self.loop.run_forever()
        finally:
            try:
                # Whatever is still waiting here - a writer waiting for room, a
                # lookup the clients closed under - ends now, and its caller is
                # told the tier is not there (see '_call') rather than left
                # waiting for a loop that has stopped.
                tasks = asyncio.all_tasks(self.loop)
                for task in tasks:
                    task.cancel()
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.run_until_complete(self.loop.shutdown_default_executor())
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("cache: I/O loop did not shut down cleanly: %s" % e)
            finally:
                self.loop.close()

    async def _setup(self) -> None:
        self.writes = _WriteBehind(self.misses)

    def submit(self, coroutine) -> concurrent.futures.Future:
        try:
            return asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        except RuntimeError as e:
            # The loop is closed: 'shutdown' got there first.
            coroutine.close()
            raise Unavailable(str(e))

    async def client(self, backend):
        """The client 'backend' reaches its server through, opened on first use."""
        key = backend.client_key
        known = self._clients.get(key)
        if known is None:
            lock = self._opening.setdefault(key, asyncio.Lock())
            async with lock:
                known = self._clients.get(key)
                if known is None:
                    known = self._clients[key] = (await backend._open(), backend._close)
        return known[0]

    async def close_clients(self) -> None:
        clients, self._clients = self._clients, {}
        for client, close in clients.values():
            try:
                await close(client)
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("cache: failed to close a client: %s" % e)

    async def read(self, backend, names: list) -> dict:
        found = {}
        ask = []
        for name in names:
            key = (backend.location, name)
            entry = self.writes.pending.get(key)
            if entry is not None:
                found[name] = entry.value
            elif not self.misses.known(key):
                ask.append(name)
        if ask:
            keys = [(backend.location, name) for name in ask]
            self.misses.begin(keys)
            stored = None
            try:
                stored = await backend._read_guarded(ask)
            finally:
                # Absent from the answer is "not here"; present as None is "could
                # not find out", and so is a lookup that never finished. Neither
                # of those is remembered.
                missing = () if stored is None else {key for key, name in zip(keys, ask) if name not in stored}
                self.misses.end(keys, missing)
            for name in ask:
                data = stored.get(name)
                if data is not None:
                    found[name] = data
        return found

    async def contains(self, backend, names: list) -> dict:
        held = {}
        ask = []
        for name in names:
            key = (backend.location, name)
            entry = self.writes.pending.get(key)
            if entry is not None:
                held[name] = bool(entry.value)
            elif self.misses.known(key):
                held[name] = False
            else:
                ask.append(name)
        if ask:
            keys = [(backend.location, name) for name in ask]
            self.misses.begin(keys)
            answer = None
            try:
                answer = await backend._contains_guarded(ask)
            finally:
                # False is "not here"; None, or nothing, is "could not find out".
                missing = () if answer is None else {key for key, name in zip(keys, ask) if answer.get(name) is False}
                self.misses.end(keys, missing)
            for name in ask:
                held[name] = bool(answer.get(name))
        return held

    def stop(self, timeout: float) -> None:
        """Send what is queued, close the clients, and end the thread. From any other thread."""
        try:
            try:
                self.submit(self.writes.flush()).result(timeout)
            except concurrent.futures.TimeoutError:
                left = self.submit(_count(self.writes)).result(CLOSE_TIMEOUT)
                pc_logging.warning(
                    "cache: %d write(s) to a remote cache tier did not finish within %ds and were dropped"
                    % (left, timeout)
                )
            self.loop.call_soon_threadsafe(self.writes.cancel)
            self.submit(self.close_clients()).result(CLOSE_TIMEOUT)
        except (Unavailable, concurrent.futures.TimeoutError) as e:
            pc_logging.debug("cache: the I/O thread did not stop cleanly: %s" % e)
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("cache: the I/O thread did not stop cleanly: %s" % e)
        finally:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                pass
            self.thread.join(CLOSE_TIMEOUT)


async def _count(writes: _WriteBehind) -> int:
    return writes.queued()


# The I/O loop the calling thread runs, on the I/O thread; nothing elsewhere.
_local = threading.local()

# The I/O thread, once something has needed it, and the lock that makes sure
# only one is started. Replaced by a fresh one after 'shutdown', so that the next
# use - the next test, the next 'activate' of the daemon - starts again.
_lock = threading.Lock()
_current = None
# Set once the process has begun to exit: nothing may start a thread then, and
# what still asks is answered as if the remote tiers were not there.
_exiting = False
_hooked = False


def _get() -> _Loop:
    global _current, _hooked
    current = _current
    if current is not None:
        return current
    with _lock:
        if _current is None:
            if _exiting:
                raise Unavailable("the process is exiting")
            if not _hooked:
                _hook_exit()
                _hooked = True
            try:
                _current = _Loop()
            except RuntimeError as e:
                # "can't create new thread at interpreter shutdown"
                raise Unavailable(str(e))
        return _current


def _hook_exit() -> None:
    """Have the queue sent when the process exits.

    Through 'threading._register_atexit' where it exists, which runs before the
    interpreter waits for its threads and before 'concurrent.futures' refuses
    new work -- the S3 client resolves host names on the loop's default
    executor, so a flush from a plain 'atexit' handler, which runs after both,
    could not open a connection it did not have already.
    """
    register = getattr(threading, "_register_atexit", None)
    if register is not None:
        try:
            register(_at_exit)
            return
        except RuntimeError:
            pass
    import atexit

    atexit.register(_at_exit)


def _at_exit() -> None:
    global _exiting
    _exiting = True
    shutdown()


def _after_fork_in_child() -> None:
    # The thread is not in the child, and its lock may have been held by some
    # other thread of the parent at the moment of the fork.
    global _lock, _current
    _lock = threading.Lock()
    _current = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


def running() -> bool:
    """Whether the I/O thread has been started (and not shut down since)."""
    return _current is not None


async def _call(method, *args):
    """'method(*args)' of the I/O loop, awaited from whatever loop the caller is on."""
    here = getattr(_local, "io", None)
    if here is not None:
        return await method(here, *args)
    io = _get()
    context = otel_context.get_current()

    async def traced():
        # The caller's trace, which the thread of the loop knows nothing about.
        token = otel_context.attach(context)
        try:
            return await method(io, *args)
        except asyncio.CancelledError:
            # Cancelled on the I/O loop's side: it stopped (see '_Loop._run').
            # Handed back as cancellation, the caller's own task would read it
            # as its own cancellation and stop a build over a cache lookup. A
            # caller that did cancel has its answer already, and this one goes
            # nowhere.
            raise Unavailable("the cache's I/O thread stopped")
        finally:
            otel_context.detach(token)

    return await asyncio.wrap_future(io.submit(traced()))


async def read(backend, names: list) -> dict:
    """The entries of 'names' that 'backend' holds, queued writes included."""
    return await _call(_Loop.read, backend, names)


async def contains(backend, names: list) -> dict:
    """Which of 'names' 'backend' holds, queued writes included."""
    return await _call(_Loop.contains, backend, names)


async def write(backend, items: dict) -> dict:
    """Queue 'items' for 'backend', and say which were taken: every one, once it is queued."""
    return await _call(lambda io, *args: io.writes.put(*args), backend, items)


async def client(backend):
    """The client of 'backend', for its own I/O. Only ever awaited on the I/O loop."""
    io = getattr(_local, "io", None)
    if io is None:
        raise RuntimeError("a remote cache tier's client is used on the cache's I/O thread only")
    return await io.client(backend)


async def flush_async(location=None) -> None:
    """Wait until what this process has written so far has landed, for one tier or all."""
    if _current is None:
        return
    try:
        await _call(lambda io, where: io.writes.flush(where), location)
    except Unavailable:
        pass


def flush(timeout: float = None) -> bool:
    """'flush_async' for synchronous code. False if 'timeout' passed first."""
    io = _current
    if io is None:
        return True
    try:
        io.submit(io.writes.flush()).result(timeout)
        return True
    except concurrent.futures.TimeoutError:
        return False
    except Unavailable:
        return True


def shutdown(timeout: float = EXIT_TIMEOUT) -> None:
    """Send what is queued, close every client, and stop the thread.

    Called when the process exits and when PartCAD is de-initialised
    ('partcad.fini()', which the daemon does before it reloads PartCAD's
    modules). Nothing to do if no remote tier was ever used. The next use
    starts a new thread, except once the process is exiting.
    """
    global _current
    with _lock:
        io, _current = _current, None
    if io is not None:
        io.stop(timeout)
