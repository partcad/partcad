#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""How the cache's tiers are read and written: promotion, remembered misses, write-behind.

The remote tiers here are fakes - a dictionary behind the real I/O thread (see
partcad.cache_io) - so that a test can hold a write on the wire, make a tier
unreachable, or count what it was asked, without a server. What the real
memcached and S3 clients do over a socket is in test_cache_backends.py.
"""

import asyncio
import collections
import os
import subprocess
import sys
import textwrap
import threading

import pytest
from cache_config import CacheUserConfig

import partcad
from partcad import cache_backend, cache_io
from partcad.cache import Cache
from partcad.cache_hash import CacheHash

# A protocol bug here is far more likely to hang than to fail: fail instead.
pytestmark = pytest.mark.timeout(60)

PAYLOAD = b"\x28\xb5\x2f\xfd" + bytes(range(256)) * 4


class FakeRemote(cache_backend.RemoteCacheBackend):
    """A remote tier with nothing remote about it: a dictionary, and a gate its writes wait at.

    Two of them with the same label are one tier, the way two contexts' tiers
    pointed at one server are.
    """

    name = "fake"

    def __init__(self, label: str = "fake", min_entry_size: int = 0, max_entry_size: int = 0) -> None:
        super().__init__(None, "shapes", min_entry_size=min_entry_size, max_entry_size=max_entry_size)
        self.label = label
        self.storage = {}
        # What it was asked, request by request, and what it was sent, in order.
        self.reads = []
        self.checks = []
        self.sent = []
        self.opened = 0
        self.closed = 0
        # Open unless a test closes it: a write waits here before it lands.
        self.gate = threading.Event()
        self.gate.set()
        self.unreachable = False
        self._sending = collections.Counter()
        self.overlapped = False

    @property
    def client_key(self) -> tuple:
        return ("fake", self.label)

    @property
    def location(self) -> tuple:
        return ("fake", self.label)

    async def _open(self):
        self.opened += 1
        return self

    async def _close(self, client) -> None:
        self.closed += 1

    async def _read_async(self, names):
        async with self.connected():
            self.reads.append(list(names))
            if self.unreachable:
                raise ConnectionRefusedError("nobody there")
            return {name: self.storage[name] for name in names if name in self.storage}

    async def _contains_async(self, names):
        async with self.connected():
            self.checks.append(list(names))
            if self.unreachable:
                raise ConnectionRefusedError("nobody there")
            return {name: bool(self.storage.get(name)) for name in names}

    async def _write_async(self, items):
        async with self.connected():
            for name in items:
                self._sending[name] += 1
                self.overlapped = self.overlapped or self._sending[name] > 1
            try:
                while not self.gate.is_set():
                    await asyncio.sleep(0.005)
                for name, value in items.items():
                    self.storage[name] = value
                    self.sent.append((name, value))
            finally:
                for name in items:
                    self._sending[name] -= 1
        return {name: True for name in items}


def _hash(data: str = "geometry") -> CacheHash:
    cache_hash = CacheHash("pkg:widget", cache=True)
    cache_hash.add_string(data)
    return cache_hash


def _name(key: str, data: str = "geometry") -> str:
    return "%s.%s" % (_hash(data).get(), key)


def _cache(tmp_path, *remotes, files: bool = True, **config) -> Cache:
    """A cache of the files tier (unless 'files' is False) with 'remotes' behind it."""
    cache = Cache("shapes", CacheUserConfig(tmp_path, cache=files, **config))
    cache.backends = cache.backends + list(remotes)
    return cache


def _read(cache, keys, data="geometry"):
    return asyncio.run(cache.read_data_async(_hash(data), keys))


def _write(cache, items, data="geometry"):
    return asyncio.run(cache.write_data_async(_hash(data), items))


def _io_threads():
    return [thread for thread in threading.enumerate() if thread.name == cache_io.THREAD_NAME]


# ---------------------------------------------------------------- promotion --


def test_a_hit_in_a_far_tier_is_copied_into_the_nearer_ones(tmp_path):
    """Without it, an entry only S3 holds is downloaded by every process, every time."""
    near, far = FakeRemote("near"), FakeRemote("far")
    cache = _cache(tmp_path, near, far)
    files = cache.backends[0]
    far.storage[_name("part")] = PAYLOAD

    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    cache_io.flush()

    assert (files.cache_dir / _name("part")).read_bytes() == PAYLOAD
    # With the sidecar the files tier keeps beside every entry it writes.
    assert (files.cache_dir / _name("name")).read_bytes() == b"pkg:widget"
    assert near.storage == {_name("part"): PAYLOAD}

    # And the next read stops at the nearest tier, as if the entry were built here.
    near.reads.clear()
    far.reads.clear()
    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    assert near.reads == [] and far.reads == []


def test_a_hit_is_copied_only_into_the_tiers_that_missed_it(tmp_path):
    near, far = FakeRemote("near"), FakeRemote("far")
    cache = _cache(tmp_path, near, far)
    near.storage[_name("part")] = PAYLOAD

    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    cache_io.flush()

    assert far.storage == {}
    assert far.reads == []


def test_promotion_keeps_to_each_tiers_size_window(tmp_path):
    """A tier that would not take the entry from a write does not get it from a read either."""
    near, far = FakeRemote("near", max_entry_size=len(PAYLOAD) - 1), FakeRemote("far")
    cache = _cache(tmp_path, near, far, cache_max_entry_size=len(PAYLOAD) - 1)
    far.storage[_name("part")] = PAYLOAD

    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    cache_io.flush()

    assert near.storage == {}
    assert list(cache.backends[0].cache_dir.iterdir()) == []


def test_promotion_writes_no_tier_that_is_switched_off(tmp_path):
    far = FakeRemote("far")
    cache = _cache(tmp_path, far, files=False)
    far.storage[_name("part")] = PAYLOAD

    assert _read(cache, ["part"]) == {"part": PAYLOAD}

    assert not (tmp_path / "cache").exists()


def test_an_empty_entry_is_not_worth_copying(tmp_path):
    """It is a miss to every reader of it (see cache_shape.read_async)."""
    far = FakeRemote("far")
    cache = _cache(tmp_path, far)
    far.storage[_name("part")] = b""

    _read(cache, ["part"])

    assert list(cache.backends[0].cache_dir.iterdir()) == []


# ------------------------------------------------------------ known misses --


def test_a_miss_is_remembered_and_the_tier_is_not_asked_again(tmp_path):
    far = FakeRemote()
    cache = _cache(tmp_path, far)

    for _ in range(3):
        assert _read(cache, ["part", "cmps"]) == {"part": None, "cmps": None}

    assert far.reads == [[_name("part"), _name("cmps")]]


def test_a_local_hit_does_not_send_its_components_to_the_network_every_time(tmp_path):
    """The case this is for: a part found in the files tier, read with the 'cmps' it never had."""
    far = FakeRemote()
    cache = _cache(tmp_path, far)
    _write(cache, {"part": PAYLOAD})
    cache_io.flush()

    for _ in range(3):
        assert _read(cache, ["part", "cmps"]) == {"part": PAYLOAD, "cmps": None}

    assert far.reads == [[_name("cmps")]]


def test_an_existence_check_and_a_read_share_what_was_learnt(tmp_path):
    far = FakeRemote()
    cache = _cache(tmp_path, far)

    _read(cache, ["part"])
    assert asyncio.run(cache.contains_data_async(_hash(), ["part", "cmps"])) == {"part": False, "cmps": False}
    _read(cache, ["cmps"])

    assert far.reads == [[_name("part")]]
    assert far.checks == [[_name("cmps")]]


def test_a_miss_is_believed_for_a_while_and_then_asked_again(tmp_path, monkeypatch):
    """Another machine may write the entry into a tier they share, and a daemon lives for hours."""
    clock = [1000.0]
    monkeypatch.setattr(cache_io, "_now", lambda: clock[0])
    far = FakeRemote()
    cache = _cache(tmp_path, far)

    assert _read(cache, ["part"]) == {"part": None}
    # Somebody else builds it and publishes it.
    far.storage[_name("part")] = PAYLOAD

    clock[0] += cache_io.KNOWN_MISS_TTL - 1
    assert _read(cache, ["part"]) == {"part": None}
    assert len(far.reads) == 1

    clock[0] += 2
    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    assert len(far.reads) == 2


def test_this_processs_own_write_clears_a_remembered_miss(tmp_path):
    """A write is never followed by a miss of what it wrote - in any context of this process."""
    far = FakeRemote()
    cache = _cache(tmp_path / "one", far, files=False)
    other = _cache(tmp_path / "two", FakeRemote(), files=False)
    other.backends[0].storage = far.storage

    assert _read(cache, ["part"]) == {"part": None}
    assert _read(other, ["part"]) == {"part": None}

    _write(cache, {"part": PAYLOAD})
    cache_io.flush()

    # Landed, so it is the tier that answers now, for both of them.
    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    assert _read(other, ["part"]) == {"part": PAYLOAD}
    assert far.reads[-1] == [_name("part")]


def test_a_lookup_overtaken_by_a_write_is_not_remembered():
    """Its "not here" may describe the tier from before the write landed."""
    misses = cache_io._KnownMisses()

    misses.begin(["key"])
    misses.forget("key")
    misses.end(["key"], {"key"})
    assert not misses.known("key")

    # Once nothing about it is on the wire any more, a miss is a miss again.
    misses.begin(["key"])
    misses.end(["key"], {"key"})
    assert misses.known("key")


def test_only_so_many_misses_are_remembered():
    misses = cache_io._KnownMisses(limit=2)
    for key in ("a", "b", "c"):
        misses.begin([key])
        misses.end([key], {key})

    assert [misses.known(key) for key in ("a", "b", "c")] == [False, True, True]


def test_a_tier_that_could_not_be_asked_has_said_nothing(tmp_path):
    """A refused connection is not a miss: the entry may well be there, and is asked for again."""
    far = FakeRemote()
    far.unreachable = True
    cache = _cache(tmp_path, far)

    for _ in range(2):
        assert _read(cache, ["part"]) == {"part": None}
        assert asyncio.run(cache.contains_data_async(_hash(), ["cmps"])) == {"cmps": False}

    assert len(far.reads) == 2
    assert len(far.checks) == 2


# -------------------------------------------------------------- write-behind --


def test_a_remote_write_does_not_wait_for_the_tier(tmp_path):
    """The shape's lock is held across its cache write, so a PUT there stalls everyone waiting for it."""
    far = FakeRemote()
    far.gate.clear()
    cache = _cache(tmp_path, far)

    # Returns while the send is held at the gate.
    assert _write(cache, {"part": PAYLOAD}) == {"part": True}

    # The files tier is written before the write returns, for every process here.
    assert (cache.backends[0].cache_dir / _name("part")).read_bytes() == PAYLOAD
    assert far.storage == {}

    far.gate.set()
    assert cache_io.flush(timeout=30)
    assert far.storage == {_name("part"): PAYLOAD}


def test_a_queued_write_is_visible_to_this_process(tmp_path):
    """Read-your-writes, for an entry only a remote tier holds (the files tier is off here)."""
    far = FakeRemote()
    far.gate.clear()
    cache = _cache(tmp_path / "one", far, files=False)
    # Another context's cache, whose tier is another object for the same server.
    other = _cache(tmp_path / "two", FakeRemote(), files=False)

    _write(cache, {"part": PAYLOAD})

    assert _read(cache, ["part"]) == {"part": PAYLOAD}
    assert _read(other, ["part"]) == {"part": PAYLOAD}
    assert asyncio.run(other.contains_data_async(_hash(), ["part"])) == {"part": True}
    # Answered from the queue: the tier was not asked.
    assert far.reads == [] and far.checks == []

    far.gate.set()
    cache_io.flush()
    assert far.storage == {_name("part"): PAYLOAD}


def test_writes_of_one_entry_land_in_the_order_they_were_made(tmp_path):
    """The last write wins, as it would have had each been awaited; none is sent beside another."""
    far = FakeRemote()
    far.gate.clear()
    cache = _cache(tmp_path, far, files=False)
    versions = [b"v1" + PAYLOAD, b"v2" + PAYLOAD, b"v3" + PAYLOAD]

    for value in versions:
        _write(cache, {"part": value})
        # What a read sees is what was written last.
        assert _read(cache, ["part"]) == {"part": value}

    far.gate.set()
    cache_io.flush()

    assert far.storage == {_name("part"): versions[-1]}
    sent = [value for _, value in far.sent]
    assert sent[-1] == versions[-1]
    assert sent == sorted(sent, key=versions.index)
    assert not far.overlapped


def test_a_full_queue_makes_the_writer_wait(tmp_path, monkeypatch):
    """Back-pressure, rather than memory growing for as long as the network is slower than the builds."""
    monkeypatch.setattr(cache_io, "MAX_QUEUED_ENTRIES", 2)
    far = FakeRemote()
    far.gate.clear()
    cache = _cache(tmp_path, far, files=False)

    _write(cache, {"part": PAYLOAD}, data="one")
    _write(cache, {"part": PAYLOAD}, data="two")
    third = threading.Thread(target=_write, args=(cache, {"part": PAYLOAD}), kwargs={"data": "three"})
    third.start()
    third.join(0.5)

    assert third.is_alive()
    assert len(cache_io._current.writes.pending) == 2

    far.gate.set()
    third.join(30)
    cache_io.flush()
    assert not third.is_alive()
    assert len(far.storage) == 3


def test_an_entry_bigger_than_the_whole_queue_is_still_written(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_io, "MAX_QUEUED_BYTES", 16)
    far = FakeRemote()
    cache = _cache(tmp_path, far, files=False)

    assert _write(cache, {"part": PAYLOAD}) == {"part": True}
    cache_io.flush()

    assert far.storage == {_name("part"): PAYLOAD}


def test_a_failed_send_is_logged_and_the_entry_is_then_not_there(tmp_path, monkeypatch):
    class Refusing(FakeRemote):
        async def _write_async(self, items):
            raise ConnectionRefusedError("nobody there")

    logged = []
    monkeypatch.setattr(cache_backend.pc_logging, "debug", logged.append)
    far = Refusing()
    cache = _cache(tmp_path, far, files=False)

    assert _write(cache, {"part": PAYLOAD}) == {"part": True}
    cache_io.flush()

    assert any("write failed" in line for line in logged)
    assert _read(cache, ["part"]) == {"part": None}


# --------------------------------------------------------- the thread itself --


def test_one_client_for_every_loop_closed_once_at_shutdown(tmp_path):
    """Every pool task is an 'asyncio.run()' of its own; the client outlives them all."""
    far = FakeRemote()
    cache = _cache(tmp_path, far, files=False)

    for index in range(5):
        _write(cache, {"part": PAYLOAD}, data=str(index))
        _read(cache, ["part"], data=str(index))
    cache_io.flush()
    assert far.opened == 1
    assert far.closed == 0

    cache_io.shutdown()

    assert far.closed == 1
    assert not cache_io.running()
    assert _io_threads() == []


def test_shutdown_sends_what_is_queued_first(tmp_path):
    far = FakeRemote()
    far.gate.clear()
    cache = _cache(tmp_path, far, files=False)
    for index in range(5):
        _write(cache, {"part": PAYLOAD}, data=str(index))
    assert far.storage == {}

    opener = threading.Timer(0.2, far.gate.set)
    opener.start()
    try:
        cache_io.shutdown()
    finally:
        opener.cancel()

    assert len(far.storage) == 5
    assert _io_threads() == []


def test_shutdown_gives_up_on_a_tier_that_does_not_answer(tmp_path, monkeypatch):
    """And says how much it dropped, rather than holding the process up for good."""
    warnings = []
    monkeypatch.setattr(cache_io.pc_logging, "warning", warnings.append)
    far = FakeRemote()
    far.gate.clear()
    cache = _cache(tmp_path, far, files=False)
    _write(cache, {"part": PAYLOAD})

    cache_io.shutdown(timeout=0.2)

    assert far.storage == {}
    assert len(warnings) == 1 and "1 write(s)" in warnings[0]
    assert _io_threads() == []


def test_the_thread_starts_again_after_a_shutdown(tmp_path):
    """The next test, or the daemon's next 'activate', after 'partcad.fini()'."""
    far = FakeRemote()
    cache = _cache(tmp_path, far, files=False)
    _write(cache, {"part": PAYLOAD}, data="before")
    partcad.fini()
    assert not cache_io.running()

    _write(cache, {"part": PAYLOAD}, data="after")
    cache_io.flush()

    assert cache_io.running()
    assert len(far.storage) == 2
    assert far.opened == 2 and far.closed == 1


def test_nothing_is_started_once_the_process_is_exiting(tmp_path, monkeypatch):
    """What still asks then is answered as if the remote tiers were not there."""
    monkeypatch.setattr(cache_io, "_exiting", False)
    cache_io._at_exit()
    far = FakeRemote()
    far.storage[_name("part")] = PAYLOAD
    cache = _cache(tmp_path, far, files=False)

    assert _write(cache, {"cmps": PAYLOAD}) == {}
    assert _read(cache, ["part"]) == {"part": None}
    assert not cache_io.running()
    assert _io_threads() == []


def test_a_process_that_exits_sends_what_it_queued(tmp_path):
    """Nobody flushes here: the interpreter's own exit does, through the hook cache_io installs."""
    landed = tmp_path / "landed"
    script = textwrap.dedent("""
        import asyncio, sys, time
        from partcad import cache_backend
        from partcad.cache import Cache
        from partcad.cache_hash import CacheHash

        class Slow(cache_backend.RemoteCacheBackend):
            name = "slow"
            client_key = location = ("slow",)

            async def _open(self):
                return None

            async def _write_async(self, items):
                async with self.connected():
                    await asyncio.sleep(0.5)
                with open(sys.argv[1], "wb") as f:
                    f.write(b"".join(items.values()))
                return {name: True for name in items}

        cache = Cache("shapes", None)
        cache.backends = [Slow(None, "shapes")]
        cache_hash = CacheHash("pkg:widget", cache=True)
        cache_hash.add_string("geometry")
        assert asyncio.run(cache.write_data_async(cache_hash, {"part": b"payload"})) == {"part": True}
        """)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.dirname(os.path.dirname(partcad.__file__))] + [p for p in [env.get("PYTHONPATH")] if p]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(landed)], env=env, capture_output=True, text=True, timeout=50
    )

    assert completed.returncode == 0, completed.stderr
    assert landed.read_bytes() == b"payload"
