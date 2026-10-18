#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A verdict reached while an object is held to being made is not the object's own.

'ManufacturabilityTest' runs every check over what a manufacturable assembly is
procured from, and over a part's stock, with 'force_manufacturing' set: whatever
those objects say about themselves, they have to be had. A part that says
'manufacturable: false' then answers the same question two ways - "not
applicable" when it is tested on its own, "cannot be purchased or manufactured"
when the assembly tests it - and both answers used to be remembered under one
key. Whichever a package-wide 'pc test' reached first answered for both, so the
assembly could pass on its part's own "not applicable", or the part fail its
own run with the assembly's failure. These hold the two apart in either order.
"""

import asyncio

import partcad as pc
from partcad.test.manufacturability import ManufacturabilityTest
from partcad.test.test import Test

# Spelt as 'ManufacturabilityTest' sets it on what it tests.
FORCE = "force_manufacturing"
FORCED = {FORCE: True}


class _Cache:
    """A verdict cache that remembers, addressed the way the real one is."""

    def __init__(self):
        self.entries = {}

    @staticmethod
    def _hash(shape_hash):
        return shape_hash if isinstance(shape_hash, str) else shape_hash.get()

    async def read_data_async(self, shape_hash, keys):
        return {k: self.entries.get((self._hash(shape_hash), k), []) for k in keys}

    async def write_data_async(self, shape_hash, data):
        for k, value in data.items():
            self.entries[(self._hash(shape_hash), k)] = value


class _Ctx:
    def __init__(self):
        self.cache_tests = _Cache()


class _Shape:
    def __init__(self, manufacturable):
        self.hash = "geometry"
        self.is_manufacturable = manufacturable
        self.name = "bolt"
        self.project_name = "//pkg"
        self.config = {}

    async def prepare_async(self, wait=False):
        pass

    def get_cacheable(self):
        return True


class _Held(Test):
    """'ManufacturabilityTest''s rule, and nothing else: nothing to ask unless it is to be made."""

    def __init__(self):
        super().__init__("held")
        self.runs = 0

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        self.runs += 1
        if not shape.is_manufacturable and FORCE not in test_ctx:
            return self.not_applicable(shape, "it says it is not manufacturable")
        return self.failed(shape, "Cannot be purchased or manufactured")


def _verdict(check, ctx, shape, test_ctx):
    Test.MAX_CONCURRENT_TESTS = 8
    return asyncio.run(check.test_cached([check], ctx, shape, test_ctx))


def test_the_key_is_the_one_the_manufacturability_check_sets():
    assert Test.FORCE_MANUFACTURING == FORCE


def test_a_forced_failure_is_not_hidden_by_the_pass_cached_first():
    check, ctx, shape = _Held(), _Ctx(), _Shape(manufacturable=False)

    assert _verdict(check, ctx, shape, {}) is Test.TEST_PASSED
    assert _verdict(check, ctx, shape, FORCED) is Test.TEST_FAILED
    assert check.runs == 2


def test_an_unforced_pass_is_not_hidden_by_the_failure_cached_first():
    check, ctx, shape = _Held(), _Ctx(), _Shape(manufacturable=False)

    assert _verdict(check, ctx, shape, FORCED) is Test.TEST_FAILED
    assert _verdict(check, ctx, shape, {}) is Test.TEST_PASSED
    assert check.runs == 2


def test_each_is_still_remembered_under_its_own_key():
    check, ctx, shape = _Held(), _Ctx(), _Shape(manufacturable=False)

    for _ in range(2):
        assert _verdict(check, ctx, shape, {}) is Test.TEST_PASSED
        assert _verdict(check, ctx, shape, FORCED) is Test.TEST_FAILED
    assert check.runs == 2


def test_an_object_that_is_to_be_made_answers_once_for_both():
    """Forcing changes nothing there, so an assembly's walk reads what the package's own run left."""
    check, ctx, shape = _Held(), _Ctx(), _Shape(manufacturable=True)

    assert _verdict(check, ctx, shape, {}) is Test.TEST_FAILED
    assert _verdict(check, ctx, shape, FORCED) is Test.TEST_FAILED
    assert check.runs == 1


def test_a_verdict_a_forced_run_left_under_the_shared_key_is_not_read_back():
    """What a cache filled before the keys were told apart holds: a forced failure under the plain key."""
    check, ctx, shape = _Held(), _Ctx(), _Shape(manufacturable=False)
    ctx.cache_tests.entries[("geometry", "test.held.manufacturable=0")] = Test._record(Test.TEST_FAILED, ["old"])

    assert _verdict(check, ctx, shape, {}) is Test.TEST_PASSED
    assert check.runs == 1


#
# The check itself, on a part that says it is not to be made
#

_PACKAGE = """
parts:
  bolt:
    type: step
    path: bolt.step
    manufacturable: false
"""


def _bolt(tmp_path):
    (tmp_path / "partcad.yaml").write_text(_PACKAGE)
    # Only the bytes matter: the check reads the declaration and builds nothing.
    (tmp_path / "bolt.step").write_text("bolt\n")
    ctx = pc.Context(str(tmp_path))
    ctx.cache_tests = _Cache()
    part = ctx.get_part(":bolt")
    assert part is not None and not part.is_manufacturable
    return ctx, part


def _errors(caplog):
    import logging

    return [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]


def test_the_manufacturability_check_fails_a_forced_run_after_its_own_pass(tmp_path, caplog):
    ctx, part = _bolt(tmp_path)
    check = ManufacturabilityTest()

    assert _verdict(check, ctx, part, {}) is Test.TEST_PASSED
    caplog.clear()
    assert _verdict(check, ctx, part, FORCED) is Test.TEST_FAILED
    assert any("Cannot be purchased or manufactured" in message for message in _errors(caplog))
    # Not the remembered verdict of the run before: this one was worked out.
    assert not any("remembered from an earlier run" in message for message in _errors(caplog))


def test_the_manufacturability_check_passes_its_own_run_after_a_forced_failure(tmp_path, caplog):
    ctx, part = _bolt(tmp_path)
    check = ManufacturabilityTest()

    assert _verdict(check, ctx, part, FORCED) is Test.TEST_FAILED
    caplog.clear()
    assert _verdict(check, ctx, part, {}) is Test.TEST_PASSED
    assert _errors(caplog) == []
