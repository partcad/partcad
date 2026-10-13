#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

from partcad.test.test import Test


class _FakeCache:
    def __init__(self):
        self.reads = []

    async def read_data_async(self, shape_hash, keys):
        self.reads.append((shape_hash, tuple(keys)))
        return {k: [] for k in keys}  # always a cache miss

    async def write_data_async(self, shape_hash, data):
        pass


class _FakeCtx:
    def __init__(self):
        self.cache_tests = _FakeCache()


class _FakeShape:
    def __init__(self, manufacturable):
        self.hash = "identical-geometry-hash"
        self.is_manufacturable = manufacturable
        self.name = "part"
        self.project_name = "pkg"

    def get_cacheable(self):
        return True


class _PassTest(Test):
    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        return self.TEST_PASSED


def _cache_read_identity(manufacturable):
    Test.MAX_CONCURRENT_TESTS = 8
    # No semaphore to reset between the two asyncio.run() calls below: the gate
    # in 'partcad.concurrency' keeps one per loop, which is what a daemon
    # serving a second command needs too.
    ctx = _FakeCtx()
    asyncio.run(_PassTest("cam").test_cached([], ctx, _FakeShape(manufacturable)))
    # The (shape_hash, (cache_key,)) the test looked up in the cache.
    return ctx.cache_tests.reads[0]


def test_test_cache_key_depends_on_manufacturable():
    """Two shapes with identical geometry but different `manufacturable` must not
    share a test-result cache entry.

    Regression: the cache was keyed on shape.hash alone, so a cam failure cached
    while manufacturable=True was still returned after flipping to False.
    """
    ident_true = _cache_read_identity(True)
    ident_false = _cache_read_identity(False)
    # Same geometry hash on both ...
    assert ident_true[0] == ident_false[0]
    # ... but different cache identity, because the key encodes manufacturable.
    assert ident_true != ident_false


# --------------------------------------------------------------------------- #
# A remembered failure says why                                               #
# --------------------------------------------------------------------------- #


class _MemoryCache:
    """A verdict cache that remembers, for the two-run tests below."""

    def __init__(self):
        self.entries = {}

    async def read_data_async(self, shape_hash, keys):
        return {k: self.entries.get((shape_hash, k), []) for k in keys}

    async def write_data_async(self, shape_hash, data):
        for key, value in data.items():
            self.entries[(shape_hash, key)] = value


class _FailTest(Test):
    """Fails with two reasons, and fails another object on the way."""

    def __init__(self):
        super().__init__("thing")
        self.runs = 0

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        self.runs += 1
        # A check that tests other objects on the way logs their failures too;
        # those are theirs, not this verdict's.
        self.failed(_FakeShape(True), "a part it is made from is broken")
        self.failed(shape, "first reason")
        return self.failed(shape, "second reason\n\twith a second line")


def _run_twice(check, caplog):
    import logging

    Test.MAX_CONCURRENT_TESTS = 8
    ctx = _FakeCtx()
    ctx.cache_tests = _MemoryCache()
    shape = _FakeShape(True)
    shape.name = "bracket"
    assert asyncio.run(check.test_cached([], ctx, shape)) is Test.TEST_FAILED
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(check.test_cached([], ctx, shape)) is Test.TEST_FAILED
    return ctx, [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]


def test_a_remembered_failure_says_why(caplog):
    """It used to say only "Failed test result loaded from cache", which the reader already knew."""
    check = _FailTest()
    _ctx, messages = _run_twice(check, caplog)

    assert check.runs == 1
    assert len(messages) == 2
    assert "first reason" in messages[0]
    assert "second reason\n\twith a second line" in messages[1]
    assert all("pkg:bracket: thing" in message for message in messages)
    assert all("remembered from an earlier run" in message for message in messages)
    # What it logged about the other object is not this verdict's to repeat.
    assert not any("a part it is made from" in message for message in messages)


def test_a_pass_is_still_one_byte():
    """Every entry this cache held before reasons were kept is a pass or a bare failure."""
    assert Test._record(Test.TEST_PASSED, ["ignored"]) == bytes([True])
    assert Test._record(Test.TEST_FAILED, []) == bytes([False])


def test_an_entry_from_before_reasons_were_kept_reads_as_it_always_did(caplog):
    import logging

    check = _FailTest()
    shape = _FakeShape(True)
    with caplog.at_level(logging.ERROR):
        assert check._replay(shape, bytes([False])) is Test.TEST_FAILED
        assert check._replay(shape, bytes([True])) is Test.TEST_PASSED
    assert "Failed test result loaded from cache" in caplog.text


def test_a_reason_that_will_not_decode_still_leaves_the_verdict(caplog):
    import logging

    check = _FailTest()
    with caplog.at_level(logging.ERROR):
        assert check._replay(_FakeShape(True), bytes([False]) + b"\xff not json") is Test.TEST_FAILED
    assert "Failed test result loaded from cache" in caplog.text


def test_a_pathological_reason_is_bounded():
    entry = Test._record(Test.TEST_FAILED, ["x" * 200000])
    assert len(entry) < 4096
