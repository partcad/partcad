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
