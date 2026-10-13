#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

import contextvars
import copy
import json
from abc import ABC, abstractmethod

from .. import logging as pc_logging
from ..concurrency import ReentrantGate

# Shared by every Test, because MAX_CONCURRENT_TESTS is a cap on tests as a
# whole rather than on any one of them.
#
# Re-entrant, and it has to be: 'ManufacturabilityTest.test' runs the whole suite over every
# object the assembly under test is procured from, from inside the call this
# gate has already admitted. Counting those nested runs as new arrivals is what
# used to wedge 'pc test -r' for good -- with every permit held by a caller
# waiting for a permit, no test ever finished and the daemon stopped answering.
_gate = ReentrantGate("partcad.test.concurrency")


# What 'failed()' said while a verdict was being worked out, so that a failure
# read back from the cache can say it again. A context variable rather than an
# attribute: one Test instance checks every object concurrently, and each
# 'test_cached()' call is a task of its own, so the collector has to belong to
# the call. Holds (test, shape, messages); 'failed()' appends only for that test
# and that shape, because a check that tests other objects on the way -- an
# assembly's manufacturability testing its parts -- logs their failures too,
# and those are theirs to remember, under their own keys.
_reasons: contextvars.ContextVar = contextvars.ContextVar("partcad.test.reasons", default=None)

# How much of what a failure said is kept with it. A reason is a sentence or a
# short report; this is a bound on a pathological one, not a budget.
_MAX_REASONS_BYTES = 64 * 1024


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

    # A key a test may set on its 'test_ctx' to say "this verdict is about the
    # machine, not about the shape -- do not remember it".
    #
    # The cache key is built from what the *question* is: the shape's hash, and
    # whatever 'cache_key_suffix()' adds. Nothing in it describes the machine the
    # answer was reached on, and it could not: a test cannot know what its
    # implementation needs installed. So a verdict that turned on something
    # external -- a solver that is not here -- would otherwise be cached under a
    # key that installing the solver does not change, and the pass would survive
    # the reason for it going away. See 'CaeTest.test()', which is the one test
    # that can reach that state.
    NOT_CACHEABLE = "not_cacheable"

    # A key the caller sets on 'test_ctx' to say the object was asked about on
    # its own, by name -- 'pc test <object>' -- rather than reached by walking a
    # package or a tree of them. Most checks give the same verdict either way;
    # one that does not reads this (see 'SimTest', where a claim with no
    # condition to check is a skip in a walk and a failure when asked about).
    # A verdict that turns on it must not be cached, since the cache key does
    # not carry it.
    NAMED = "named"

    def __init__(self, name: str) -> None:
        self.name = name

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What this test's result depends on beyond 'shape.hash', as text.

        A shape's hash covers what the shape is built from, and a test may read
        more than that. Whatever it reads has to reach the cache key, or the
        answer to a question the user has just changed comes back from the run
        before the change.

        Empty for a test whose answer is a property of the shape alone; see
        'ManufacturabilityTest.cache_key_suffix()' for the one that is not.

        Asynchronous because what a test reads is not always text in the
        declaration in front of it: a verdict about *another* object depends on
        that object's own cache key, and a shape has no correct key until the
        files it is built from are on disk (see 'Shape.get_cache_key_async').
        See 'ManufacturabilitySheetMetalTest.cache_key_suffix()', which is the
        one that does.
        """
        return ""

    @semaphore_wrapper
    async def test_cached(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        # Copied, because 'test()' may set 'NOT_CACHEABLE' on it below and the
        # default argument is a single dict shared by every call that omits one.
        test_ctx = dict(test_ctx)

        is_cacheable = shape.get_cacheable()
        if is_cacheable:
            # The manufacturability tests depend on `manufacturable`, which is
            # not part of shape.hash; fold it into the cache key so that flipping
            # the flag invalidates any previously cached result.
            manufacturable = int(bool(getattr(shape, "is_manufacturable", True)))
            suffix = await self.cache_key_suffix(ctx, shape)
            cache_key = f"test.{self.name}.manufacturable={manufacturable}{suffix}"
            cached_results = await ctx.cache_tests.read_data_async(shape.hash, [cache_key])
            cached_bytes = cached_results.get(cache_key, [])
            if cached_bytes and len(cached_bytes) != 0:
                return self._replay(shape, bytes(cached_bytes))

        token = _reasons.set((self, shape, []))
        try:
            result = await self.test(tests_to_run, ctx, shape, test_ctx)
            reasons = _reasons.get()[2]
        finally:
            _reasons.reset(token)

        if is_cacheable and not test_ctx.get(self.NOT_CACHEABLE):
            await ctx.cache_tests.write_data_async(shape.hash, {cache_key: self._record(result, reasons)})
        return result

    @classmethod
    def _record(cls, result: bool, reasons: list) -> bytes:
        """A verdict as it is stored: one byte, and for a failure the reasons after it.

        The first byte is the verdict and is all a pass is, which is every entry
        this cache held before reasons were kept -- so an old entry reads back
        exactly as it always did. A failure carries what 'failed()' said while
        it was reached, as JSON, so that reading it back can say *why* rather
        than only that it failed: a cached failure used to print "Failed test
        result loaded from cache", which is the one thing its reader already
        knew. Test entries are outside every tier's size window (see
        'cache_backend.SIZED_KEYS'), so the longer entry is stored like the
        short one.
        """
        if result == cls.TEST_PASSED or not reasons:
            return bytes([result])
        payload = json.dumps(reasons).encode("utf-8")
        if len(payload) > _MAX_REASONS_BYTES:
            payload = json.dumps([reason[:1024] for reason in reasons[:16]]).encode("utf-8")
        return bytes([result]) + payload

    def _replay(self, shape, cached: bytes) -> bool:
        """A stored verdict, read back and said again."""
        result = bool(cached[0])
        if result == self.TEST_PASSED:
            if len(cached) != 1:
                return self.failed(shape, "Invalid cached data")
            return result
        reasons = []
        if len(cached) > 1:
            try:
                reasons = [str(reason) for reason in json.loads(cached[1:].decode("utf-8"))]
            except Exception:  # pylint: disable=broad-except
                # Not ours to interpret: the verdict still stands, and the
                # sentence below says less than it could rather than nothing.
                reasons = []
        if not reasons:
            # An entry written before reasons were kept, or a failure that
            # said nothing in the check's own name.
            self.failed(shape, "Failed test result loaded from cache")
        for reason in reasons:
            self.failed(shape, "%s (remembered from an earlier run; 'pc --cache-bypass test' checks again)", reason)
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

    def info(self, shape, *args) -> None:
        """Like logging.info(), prefixed with the test name and the shape name.

        For what a reader of the result has to know in order to read it: a
        check that could only be applied to part of what it was given says so
        here, so that a pass is not mistaken for a clean bill of health.
        """
        message = self._log_message_prepare(*args)
        pc_logging.info(f"Test: {shape.project_name}:{shape.name}: {self.name}{message}")

    def warned(self, shape, *args) -> bool:
        """What the check found, on an object nobody is going to make.

        A finding, reported, that does not fail the run. An object that says
        'manufacturable: false' is a record of something - an import kept as it
        arrived, a model of a part somebody else makes - and holding it to what
        a thing being built is held to would mean either editing it until the
        checks are happy, which destroys the record, or turning the checks off,
        which loses the finding. Said out loud and not fatal keeps both.
        """
        message = self._log_message_prepare(*args)
        pc_logging.warning(f"Test: {shape.project_name}:{shape.name}: {self.name}{message}")
        return self.TEST_PASSED

    def failed(self, shape, *args) -> bool:
        """This methods works like logging.error() but prepends the message with the test name and the shape name.

        What it says is also kept with the verdict being worked out, when this
        check is working one out for this shape (see 'test_cached()'), so that
        a failure read back from the cache can say it again.
        """
        message = self._log_message_prepare(*args)
        pc_logging.error(f"Test failed: {shape.project_name}:{shape.name}: {self.name}{message}")
        collecting = _reasons.get()
        if collecting is not None and collecting[0] is self and collecting[1] is shape and message:
            # Without the ": " '_log_message_prepare' puts in front of it.
            collecting[2].append(message[2:])
        return self.TEST_FAILED

    def passed(self, shape, *args) -> bool:
        """This methods works like logging.error() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test passed: {shape.project_name}:{shape.name}: {self.name}{message}")
        return self.TEST_PASSED

    def skipped(self, shape, *args) -> bool:
        """Not asked here, and saying so out loud.

        There is no third verdict to return -- see the TODO above -- so this is
        a pass, and the whole of what distinguishes it is the line it writes.
        That line is a `WARNING` rather than an `INFO` on purpose: a skip is a
        question nobody answered, and the run it happens in reports success. A
        reader scrolling past `INFO` would be told a package passed on a machine
        where a third of it never ran.

        It is not an `ERROR`, though, and the difference is whether anything
        could have been asked. A `WARNING` says the machine is not equipped;
        `failed()` says the implementation was equipped and did not deliver. Only
        the second is a bug in something, and only the second stops the command.

        The caller sets `NOT_CACHEABLE` alongside this for the same reason it
        does around a failure: what makes it a skip is a property of the machine,
        and nothing that changes it changes the cache key.
        """
        message = self._log_message_prepare(*args)
        pc_logging.warning(f"Test skipped: {shape.project_name}:{shape.name}: {self.name}{message}")
        return self.TEST_PASSED
