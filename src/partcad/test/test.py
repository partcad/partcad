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

from .. import code_version
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

# What one object's report is collecting while a check works out its verdict for
# it: (test, shape, notes), where 'notes' is a list of (level, text) the check
# said -- 'error' for 'failed()', 'warning' for 'warned()', 'info', 'skipped',
# 'not-applicable', and 'passed' for what a pass said about itself -- and of
# ('artifact', dict) for what it left behind to be looked at. Set by
# 'partcad.test.report', which is what the IDE's Test tab is drawn from; a
# check run any other way is collected by nobody. Like '_reasons', it notes only
# what the check says about that shape, not about the objects it tests on the
# way.
_report: contextvars.ContextVar = contextvars.ContextVar("partcad.test.report", default=None)


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

    # The wrappers this test runs in a sandbox to reach its verdict, by the name
    # 'wrapper.get()' takes. The version each reports is part of the verdict's
    # key, so raising it has every verdict it reached reached again (see
    # 'code_version'); 'tests/partcad/unit/test_code_version.py' holds every
    # test that runs one to naming it.
    WRAPPERS: tuple[str, ...] = ()

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
            # Prepared before the key below is read, because what the shape is
            # keyed on is not all known until then: an assembly's key takes in
            # the keys of what it links to, a compound's the key of the assembly
            # it flattens, a part's the file a 'fileFrom' or a plugin fetches -
            # all of it added by 'prepare_async()', which used to run only once
            # 'test()' built the shape. By then the key had been read, so the
            # verdict was remembered under one that covered none of it: every
            # assembly a package-wide 'pc test' reached logged "Hash update after
            # being used", and a check answered without building the shape kept
            # its pass after a part the assembly links to had changed.
            #
            # Waiting, because every check of this shape asks at once, and only
            # the first of them prepares it; the rest would otherwise read the
            # key while that is still under way. And 'get_cacheable()' is asked
            # again once it is done: preparing can find that the shape cannot be
            # cached at all, because something it links to is not.
            try:
                await shape.prepare_async(wait=True)
            except Exception:  # pylint: disable=broad-except
                # Not this method's to report: 'test()' builds the shape, meets
                # the same failure and says so in the check's own words. What it
                # does mean is that there is no key to remember a verdict under.
                is_cacheable = False
            else:
                is_cacheable = shape.get_cacheable()
        if is_cacheable:
            # The manufacturability tests depend on `manufacturable`, which is
            # not part of shape.hash; fold it into the cache key so that flipping
            # the flag invalidates any previously cached result.
            manufacturable = int(bool(getattr(shape, "is_manufacturable", True)))
            suffix = await self.cache_key_suffix(ctx, shape)
            cache_key = f"test.{self.name}.manufacturable={manufacturable}{suffix}"
            versions = code_version.wrappers_key(self.WRAPPERS)
            if versions is not None:
                cache_key += ".code=" + versions
            cached_results = await ctx.cache_tests.read_data_async(shape.hash, [cache_key])
            cached_bytes = cached_results.get(cache_key, [])
            if cached_bytes and len(cached_bytes) != 0:
                return await self._replay_async(ctx, shape, bytes(cached_bytes))

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
            # The artifacts are kept whole, and first: each is a few names, and
            # a verdict read back without them has lost what it pointed at.
            artifacts = [reason for reason in reasons if isinstance(reason, dict)][:16]
            said = [reason[:1024] for reason in reasons if isinstance(reason, str)][:16]
            payload = json.dumps(artifacts + said).encode("utf-8")
        return bytes([result]) + payload

    async def _replay_async(self, ctx, shape, cached: bytes) -> bool:
        """A stored verdict, read back and said again, with what it left behind."""
        result = bool(cached[0])
        if result == self.TEST_PASSED:
            if len(cached) != 1:
                return self.failed(shape, "Invalid cached data")
            return result
        entries = []
        if len(cached) > 1:
            try:
                entries = list(json.loads(cached[1:].decode("utf-8")))
            except Exception:  # pylint: disable=broad-except
                # Not ours to interpret: the verdict still stands, and the
                # sentence below says less than it could rather than nothing.
                entries = []
        reasons = [str(entry) for entry in entries if not isinstance(entry, dict)]
        if not reasons:
            # An entry written before reasons were kept, or a failure that
            # said nothing in the check's own name.
            self.failed(shape, "Failed test result loaded from cache")
        for reason in reasons:
            self.failed(shape, "%s (remembered from an earlier run; 'pc --cache-bypass test' checks again)", reason)
        for entry in entries:
            artifact = entry.get("artifact") if isinstance(entry, dict) else None
            if isinstance(artifact, dict) and await self.restore_artifact_async(ctx, shape, artifact):
                self.artifact(shape, artifact)
        return result

    async def restore_artifact_async(self, ctx, shape, artifact: dict) -> bool:
        """Make an artifact a cached verdict names showable again, in this context.

        What a check leaves behind is usually an object it made rather than one
        a package declares (see 'artifact()'), so a verdict read back in a
        context that has never run the check names something that is not there
        yet. A check that leaves such things behind puts them back here, and
        says whether it could: an artifact that cannot be shown is not offered.
        """
        return True

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
        self._note(shape, "info", message)

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
        self._note(shape, "warning", message)
        return self.TEST_PASSED

    def failed(self, shape, *args) -> bool:
        """This methods works like logging.error() but prepends the message with the test name and the shape name.

        What it says is also kept with the verdict being worked out, when this
        check is working one out for this shape (see 'test_cached()'), so that
        a failure read back from the cache can say it again.
        """
        message = self._log_message_prepare(*args)
        pc_logging.error(f"Test failed: {shape.project_name}:{shape.name}: {self.name}{message}")
        self._note(shape, "error", message)
        collecting = _reasons.get()
        if collecting is not None and collecting[0] is self and collecting[1] is shape and message:
            # Without the ": " '_log_message_prepare' puts in front of it.
            collecting[2].append(message[2:])
        return self.TEST_FAILED

    def passed(self, shape, *args) -> bool:
        """This methods works like logging.error() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test passed: {shape.project_name}:{shape.name}: {self.name}{message}")
        self._note(shape, "passed", message)
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
        self._note(shape, "skipped", message)
        return self.TEST_PASSED

    def not_applicable(self, shape, *args) -> bool:
        """Nothing to ask of this object: a pass that says why it is one.

        Logged at DEBUG, as it always was -- a check that does not apply is the
        usual case and says nothing a reader of the run needs -- and noted for a
        report (see 'partcad.test.report'), which shows it as "not applicable"
        rather than as a pass the object did nothing to earn.
        """
        if args and args[0] is None:
            # 'inapplicable()' had no reason to give: say nothing rather than "None".
            args = ()
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test: {shape.project_name}:{shape.name}: {self.name}: Not applicable{message}")
        self._note(shape, "not-applicable", message)
        return self.TEST_PASSED

    def inapplicable(self, shape):
        """Why this check has nothing to ask of 'shape', or None when it applies.

        Answered from what the object *is* and what it declares, without
        building or measuring anything and without the cache: what a report
        asks before deciding whether to run the check at all, so that a check
        that does not apply is shown as such even where an earlier run left a
        pass for it in the cache. A check whose 'test()' begins by asking the
        same question asks it here, so that the two cannot disagree.
        """
        return None

    def artifact(self, shape, artifact: dict) -> None:
        """Leave something behind for whoever reads the verdict to look at.

        An object PartCAD can show -- {'kind', 'package', 'name', 'title',
        'desc'} -- such as the assembly the interference check puts together of
        two parts that overlap and what they share (see 'test/interference.py').
        Noted for a report, and kept with a failure in the cache like what it
        said, so that a verdict read back from there still has it.
        """
        self._note(shape, "artifact", artifact)
        collecting = _reasons.get()
        if collecting is not None and collecting[0] is self and collecting[1] is shape:
            collecting[2].append({"artifact": artifact})

    def _note(self, shape, level: str, message) -> None:
        """Hand what was said to the report collecting for this check and this shape, if one is."""
        collecting = _report.get()
        if collecting is None or collecting[0] is not self or collecting[1] is not shape:
            return
        if isinstance(message, str):
            # Without the ": " '_log_message_prepare' puts in front of it.
            message = message[2:] if message.startswith(": ") else message
        collecting[2].append((level, message))
