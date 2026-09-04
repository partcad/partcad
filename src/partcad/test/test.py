#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from abc import ABC, abstractmethod
import copy

from .. import logging as pc_logging
from ..concurrency import ReentrantGate

# Shared by every Test, because MAX_CONCURRENT_TESTS is a cap on tests as a
# whole rather than on any one of them.
#
# Re-entrant, and it has to be: 'CamTest.test' runs the whole suite over every
# object the assembly under test is procured from, from inside the call this
# gate has already admitted. Counting those nested runs as new arrivals is what
# used to wedge 'pc test -r' for good -- with every permit held by a caller
# waiting for a permit, no test ever finished and the daemon stopped answering.
_gate = ReentrantGate("partcad.test.concurrency")


def semaphore_wrapper(f):
    async def wrapper(*args, **kwargs):
        return await _gate.run(Test.MAX_CONCURRENT_TESTS, f, *args, **kwargs)

    return wrapper


class Test(ABC):
    # TODO(clairbee): move the constants to the global scope
    # TODO(clairbee): add the concept of a "skipped" test (introduce the enum type TestResult or find existing python types)
    TEST_FAILED = False
    TEST_PASSED = True
    MAX_CONCURRENT_TESTS = None

    def __init__(self, name: str) -> None:
        self.name = name

    def cache_key_suffix(self, ctx, shape) -> str:
        """What this test's result depends on beyond 'shape.hash', as text.

        A shape's hash covers what the shape is built from, and a test may read
        more than that. Whatever it reads has to reach the cache key, or the
        answer to a question the user has just changed comes back from the run
        before the change.

        Empty for a test whose answer is a property of the shape alone; see
        'CamTest.cache_key_suffix()' for the one that is not.
        """
        return ""

    @semaphore_wrapper
    async def test_cached(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        is_cacheable = shape.get_cacheable()
        if is_cacheable:
            # The manufacturability tests depend on `manufacturable`, which is
            # not part of shape.hash; fold it into the cache key so that flipping
            # the flag invalidates any previously cached result.
            manufacturable = int(bool(getattr(shape, "is_manufacturable", True)))
            cache_key = f"test.{self.name}.manufacturable={manufacturable}{self.cache_key_suffix(ctx, shape)}"
            cached_results = await ctx.cache_tests.read_data_async(shape.hash, [cache_key])
            cached_bytes = cached_results.get(cache_key, [])
            if cached_bytes and len(cached_bytes) != 0:
                if len(cached_bytes) != 1:
                    # TODO(clairbee): use this space to persist the failure error message in the cache, be mindful of the special treatment 1 byte objects get in the cache
                    # raise ValueError(f"Invalid cache data for test {self.name} in shape {shape.name}")
                    return self.failed(shape, "Invalid cached data")
                result = bool(cached_bytes[0])
                if result == self.TEST_FAILED:
                    # TODO(clairbee): persist the failure error message in the cache, be mindful of the special treatment 1 byte objects get in the cache
                    self.failed(shape, "Failed test result loaded from cache")
                return result

        result = await self.test(tests_to_run, ctx, shape, test_ctx)

        if is_cacheable:
            # Only cache passed test results?
            # if result == self.TEST_PASSED:
            await ctx.cache_tests.write_data_async(shape.hash, {cache_key: bytes([result])})
        return result

    @abstractmethod
    async def test(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        raise NotImplementedError("This method should be overridden")

    async def test_log_wrapper(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        test_ctx = copy.copy(test_ctx)
        test_ctx["log_wrapper"] = True
        action_name = (
            shape.project_name
            if "action_prefix" not in test_ctx
            else f"{test_ctx['action_prefix']}:{shape.project_name}"
        )
        with pc_logging.Action("Test", action_name, shape.name, self.name):
            return await self.test_cached(tests_to_run, ctx, shape, test_ctx)

    def _log_message_prepare(self, *args) -> str:
        if args:
            message = args[0] % args[1:] if args[1:] else args[0]
            message = f": {message}"
        else:
            message = ""
        return message

    def debug(self, shape, *args) -> None:
        """This methods works like logging.debug() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test: {shape.project_name}:{shape.name}: {self.name}{message}")

    def failed(self, shape, *args) -> bool:
        """This methods works like logging.error() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.error(f"Test failed: {shape.project_name}:{shape.name}: {self.name}{message}")
        return self.TEST_FAILED

    def passed(self, shape, *args) -> bool:
        """This methods works like logging.error() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test passed: {shape.project_name}:{shape.name}: {self.name}{message}")
        return self.TEST_PASSED
