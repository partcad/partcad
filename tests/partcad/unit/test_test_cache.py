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

    async def prepare_async(self, wait=False):
        pass

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
        assert asyncio.run(check._replay_async(None, shape, bytes([False]))) is Test.TEST_FAILED
        assert asyncio.run(check._replay_async(None, shape, bytes([True]))) is Test.TEST_PASSED
    assert "Failed test result loaded from cache" in caplog.text


def test_a_reason_that_will_not_decode_still_leaves_the_verdict(caplog):
    import logging

    check = _FailTest()
    with caplog.at_level(logging.ERROR):
        assert (
            asyncio.run(check._replay_async(None, _FakeShape(True), bytes([False]) + b"\xff not json"))
            is Test.TEST_FAILED
        )
    assert "Failed test result loaded from cache" in caplog.text


def test_a_pathological_reason_is_bounded():
    entry = Test._record(Test.TEST_FAILED, ["x" * 200000])
    assert len(entry) < 4096


# --------------------------------------------------------------------------- #
# A remembered failure keeps what it left behind                              #
# --------------------------------------------------------------------------- #


class _ArtifactTest(Test):
    """Fails, leaving one thing behind to look at; restores it only while 'restorable'."""

    def __init__(self):
        super().__init__("leaves")
        self.restorable = True
        self.restored = []

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        self.artifact(shape, {"kind": "assembly", "package": "pkg", "name": "bracket/overlap"})
        return self.failed(shape, "it overlaps")

    async def restore_artifact_async(self, ctx, shape, artifact):
        self.restored.append(artifact["name"])
        return self.restorable


def _collected(check, ctx, shape):
    """Run 'check' through its cache with a report collecting, as 'partcad.test.report' does."""
    from partcad.test.test import _report

    notes = []

    async def run():
        token = _report.set((check, shape, notes))
        try:
            return await check.test_cached([], ctx, shape)
        finally:
            _report.reset(token)

    return asyncio.run(run()), notes


def test_a_remembered_failure_keeps_what_it_left_behind():
    Test.MAX_CONCURRENT_TESTS = 8
    check = _ArtifactTest()
    ctx = _FakeCtx()
    ctx.cache_tests = _MemoryCache()
    shape = _FakeShape(True)

    first, notes = _collected(check, ctx, shape)
    assert first is Test.TEST_FAILED
    assert ("artifact", {"kind": "assembly", "package": "pkg", "name": "bracket/overlap"}) in notes

    # Read back: the reason is said again, and the artifact is put back first.
    again, notes = _collected(check, ctx, shape)
    assert again is Test.TEST_FAILED
    assert check.restored == ["bracket/overlap"]
    assert [level for level, _ in notes] == ["error", "artifact"]

    # One that can no longer be put back is not offered.
    check.restorable = False
    _, notes = _collected(check, ctx, shape)
    assert [level for level, _ in notes] == ["error"]


def test_the_artifacts_survive_a_failure_too_long_to_keep_whole():
    reasons = ["x" * 2048] * 100 + [{"artifact": {"name": "overlap"}}]
    recorded = Test._record(Test.TEST_FAILED, reasons)
    import json

    kept = json.loads(recorded[1:].decode("utf-8"))
    assert kept[0] == {"artifact": {"name": "overlap"}}
    assert all(len(reason) == 1024 for reason in kept[1:])


# --------------------------------------------------------------------------- #
# A verdict is keyed on everything the shape is made of                      #
# --------------------------------------------------------------------------- #

_PACKAGE = """
parts:
  cube:
    type: step
    path: cube.step
assemblies:
  assembly:
    type: assy
"""


def _package(tmp_path):
    (tmp_path / "partcad.yaml").write_text(_PACKAGE)
    (tmp_path / "assembly.assy").write_text("links:\n  - part: cube\n")
    # Only the bytes matter here: nothing is built, only keyed.
    (tmp_path / "cube.step").write_text("cube v1\n")
    return tmp_path


class _KeyedCache:
    """A verdict cache addressed the way the real one is: by what the hash says."""

    def __init__(self):
        self.entries = {}
        self.reads = []
        self.writes = []

    async def read_data_async(self, shape_hash, keys):
        key = shape_hash.get()
        self.reads.append(key)
        return {k: self.entries.get((key, k), []) for k in keys}

    async def write_data_async(self, shape_hash, data):
        key = shape_hash.get()
        self.writes.append(key)
        for k, value in data.items():
            self.entries[(key, k)] = value


class _Context:
    """A package's context, with a verdict cache that outlives it.

    A fresh context per run is what a new command is: nothing about the
    shapes is in memory, and what was remembered is only what the cache holds.
    """

    def __init__(self, path, cache):
        import partcad as pc

        self.ctx = pc.Context(str(path))
        self.ctx.cache_tests = cache

    def assembly(self):
        return self.ctx._get_assembly(":assembly")


class _DeclarationCheck(Test):
    """A check answered from the declaration, which never builds the shape."""

    def __init__(self):
        super().__init__("declared")
        self.runs = 0

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        self.runs += 1
        return self.passed(shape)


class _BuildingCheck(Test):
    """A check that builds the shape, which prepares it before anything else (see 'Shape.get_wrapped')."""

    def __init__(self):
        super().__init__("built")

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        await shape.prepare_async()
        return self.passed(shape)


def test_a_verdict_is_not_kept_once_a_part_the_assembly_links_to_changes(tmp_path):
    """The key a verdict is remembered under covers what the assembly links to.

    It used to be read before the assembly was prepared, and an assembly's
    preparation is what adds the keys of its links to its own. So a check that
    reached its verdict without building the assembly - and so without
    preparing it - remembered it under a key that left the parts out, and kept
    handing back the pass after one of them had changed.
    """
    Test.MAX_CONCURRENT_TESTS = 8
    package = _package(tmp_path)
    cache = _KeyedCache()
    check = _DeclarationCheck()

    def run():
        context = _Context(package, cache)
        assert asyncio.run(check.test_cached([], context.ctx, context.assembly())) is Test.TEST_PASSED

    run()
    assert check.runs == 1
    # Asked again about the same assembly, it is remembered ...
    run()
    assert check.runs == 1
    # ... and asked once the part it links to has changed, it is checked again.
    (package / "cube.step").write_text("cube v2\n")
    run()
    assert check.runs == 2
    assert len(set(cache.writes)) == 2


def test_a_verdict_is_read_and_written_under_one_complete_key(tmp_path, caplog):
    """Nothing is added to the hash after the verdict's key has been read from it.

    Every assembly a package-wide 'pc test' reached used to log "Hash update
    after being used": the key was read, then the check built the assembly,
    and building it prepared it - adding the keys of its links to a hash that
    had already been used.
    """
    import logging

    Test.MAX_CONCURRENT_TESTS = 8
    package = _package(tmp_path)
    cache = _KeyedCache()
    context = _Context(package, cache)
    assembly = context.assembly()

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(_BuildingCheck().test_cached([], context.ctx, assembly)) is Test.TEST_PASSED

    assert "Hash update after being used" not in caplog.text
    assert cache.reads == cache.writes
    # And that one key is the assembly's own, as anything else asking for it gets it.
    assert cache.reads == [asyncio.run(_Context(package, _KeyedCache()).assembly().get_cache_key_async())]


def test_every_check_waits_for_the_preparation_the_first_one_began(tmp_path, caplog):
    """The checks of one shape all ask at once, and only the first prepares it.

    The rest used to return on the flag that preparation raises as it begins,
    and read the key while it was under way - for a part whose file is fetched,
    before the file had arrived. A hash adds its files when it is first read,
    so the shape went on being keyed on the file's absence for as long as the
    process lived, and so was every verdict about it.
    """
    import logging

    Test.MAX_CONCURRENT_TESTS = 8
    package = _package(tmp_path)
    fresh = _Context(package, _KeyedCache())
    fetched = asyncio.run(fresh.ctx.get_part(":cube").get_cache_key_async())
    expected = asyncio.run(fresh.assembly().get_cache_key_async())
    cache = _KeyedCache()
    context = _Context(package, cache)
    part = context.ctx.get_part(":cube")
    assert part is not None

    # What a 'fileFrom' does: the file is not there until the preparation has
    # fetched it, and fetching it takes a while.
    content = (package / "cube.step").read_text()
    (package / "cube.step").unlink()

    async def fetch(shape):
        await asyncio.sleep(0.05)
        (package / "cube.step").write_text(content)

    part._prepare = fetch
    checks = [_DeclarationCheck() for _ in range(4)]

    async def run_all():
        return await asyncio.gather(*(check.test_cached([], context.ctx, part) for check in checks))

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(run_all()) == [Test.TEST_PASSED] * len(checks)

    assert "Hash update after being used" not in caplog.text
    assert cache.reads == [fetched] * len(checks)
    # The assembly linking it is keyed on what was fetched, too.
    assert asyncio.run(context.assembly().get_cache_key_async()) == expected
