#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from abc import ABC, abstractmethod
import copy
import asyncio

from .. import logging as pc_logging

def semaphore_wrapper(f):
    async def wrapper(*args, **kwargs):
        if Test.semaphore is None:
            Test.semaphore = asyncio.Semaphore(Test.MAX_CONCURRENT_TESTS)
        async with Test.semaphore:
            return await f(*args, **kwargs)
    return wrapper

class Test(ABC):
    # TODO(clairbee): move the constants to the global scope
    # TODO(clairbee): add the concept of a "skipped" test (introduce the enum type TestResult or find existing python types)
    TEST_FAILED = False
    TEST_PASSED = True
    MAX_CONCURRENT_TESTS = None

    semaphore = None

    def __init__(self, name: str) -> None:
        self.name = name

    @semaphore_wrapper
    async def test_cached(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        is_cacheable = shape.get_cacheable()
        if is_cacheable:
            cache_key = f"test.{self.name}"
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
