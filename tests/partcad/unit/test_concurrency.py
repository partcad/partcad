#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The admission gate that 'pc test' and 'pc lint' run behind.

Every case here is written against a wall clock, because what is being tested is
that something completes at all. A regression does not make these slow, it makes
them never return -- so each one is driven through 'asyncio.wait_for()' and a
timeout is the failure.
"""

import asyncio

import pytest

from partcad.concurrency import ReentrantGate
from partcad.test.test import Test


def test_nested_admission_does_not_deadlock():
    """A gated call made from inside a gated call must pass straight through.

    Regression (the 'Examples (PartCAD)' hang on 'ubuntu-24.04-arm'): 'CamTest'
    runs the whole suite over every object an assembly is procured from, from
    inside the call the gate has already admitted. While the gate was a plain
    'asyncio.Semaphore', as many of those as the limit allowed would each hold a
    permit while waiting for one, and 'pc test -r' stopped for good -- taking the
    daemon's answer with it, so the CLI waited on a response that never came.
    """
    limit = 4
    gate = ReentrantGate("test.nested")

    async def leaf():
        return 1

    async def branch():
        # As many nested calls as the limit, from as many admitted callers.
        return sum(await asyncio.gather(*(gate.run(limit, leaf) for _ in range(limit))))

    async def main():
        return await asyncio.gather(*(gate.run(limit, branch) for _ in range(limit)))

    assert asyncio.run(asyncio.wait_for(main(), timeout=30)) == [limit] * limit


def test_admission_is_capped_for_unrelated_callers():
    """Nested calls are free; independent ones still queue behind the limit."""
    limit = 2
    gate = ReentrantGate("test.capped")
    live = 0
    peak = 0

    async def work():
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1

    async def main():
        await asyncio.gather(*(gate.run(limit, work) for _ in range(10)))

    asyncio.run(asyncio.wait_for(main(), timeout=30))
    assert peak == limit


def test_a_sibling_task_is_not_admitted_by_its_neighbour():
    """The admission a task inherits is its caller's, not any task's.

    'asyncio.Task' copies the context it is created in, which is what carries the
    admission into nested work. A task created outside an admitted call carries
    nothing, or the cap would evaporate the moment anything was admitted at all.
    """
    gate = ReentrantGate("test.sibling")
    order = []
    live = 0
    peak = 0

    async def slow(tag):
        nonlocal live, peak
        order.append(tag)
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.05)
        live -= 1

    async def main():
        first = asyncio.create_task(gate.run(1, slow, "first"))
        await asyncio.sleep(0)  # let 'first' take the only permit
        second = asyncio.create_task(gate.run(1, slow, "second"))
        await asyncio.gather(first, second)

    asyncio.run(asyncio.wait_for(main(), timeout=30))
    # The order alone proves nothing -- it comes out the same whether 'second'
    # waited or was waved straight through, because both append on entry. That
    # only one ran at a time is the claim.
    assert peak == 1
    assert order == ["first", "second"]


def test_each_loop_gets_its_own_semaphore():
    """A gate survives the loop it was first used on.

    The daemon runs one 'asyncio.run()' per request, so a semaphore kept for the
    process belongs to whichever request created it: 'asyncio.Semaphore' binds
    itself to the loop it first blocks on and refuses every later one.
    """
    gate = ReentrantGate("test.per_loop")

    async def contend():
        # Blocking on the semaphore is what binds it to a loop, so contend.
        await asyncio.gather(*(gate.run(1, asyncio.sleep, 0) for _ in range(4)))

    for _ in range(3):
        asyncio.run(asyncio.wait_for(contend(), timeout=30))


class _RecursiveTest(Test):
    """A stand-in for 'CamTest', which tests the objects an assembly is made of."""

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        children = shape.get("children", [])
        results = await asyncio.gather(
            *(t.test_cached(tests_to_run, ctx, child, test_ctx) for child in children for t in tests_to_run)
        )
        return self.TEST_PASSED if all(results) else self.TEST_FAILED


class _NoCacheShape(dict):
    hash = "hash"
    name = "shape"
    project_name = "pkg"

    def get_cacheable(self):
        return False


def test_recursive_test_cached_completes():
    """The real 'Test.test_cached' wrapper, nested the way 'CamTest' nests it."""
    Test.MAX_CONCURRENT_TESTS = 4
    suite = [_RecursiveTest("cam")]

    def assembly():
        return _NoCacheShape(children=[_NoCacheShape() for _ in range(4)])

    async def main():
        return await asyncio.gather(
            *(suite[0].test_cached(suite, None, assembly()) for _ in range(Test.MAX_CONCURRENT_TESTS))
        )

    results = asyncio.run(asyncio.wait_for(main(), timeout=60))
    assert results == [Test.TEST_PASSED] * Test.MAX_CONCURRENT_TESTS


@pytest.mark.parametrize("limit", [None, 0])
def test_an_unset_limit_still_admits(limit):
    """'MAX_CONCURRENT_TESTS' is None until 'partcad.test.all.tests()' sets it."""
    gate = ReentrantGate("test.unset")

    async def main():
        return await asyncio.gather(*(gate.run(limit, asyncio.sleep, 0) for _ in range(4)))

    asyncio.run(asyncio.wait_for(main(), timeout=30))
