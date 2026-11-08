#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One object's qualification, as a list of verdicts rather than as a log.

What the IDE's Qualification tabs are drawn from -- Basic, Topology and Other,
each the rows of its subtype: one line per check `pc qual test` runs, in the
order it runs them, each with its subtype, its verdict, what it said on the way
to it, what it left behind to be looked at (the geometry of a topology finding),
the report an external tool wrote (an 'other' check's), and what the check is
(see 'partcad.qual.catalog').

It runs the checks `pc qual test <object>` runs, the way it runs them -- the same
instances, through 'test_cached()', so the same cache -- and only listens.
Every check reports through 'Test.failed()', 'warned()', 'info()', 'skipped()'
and 'not_applicable()', and each of them hands what it says to the report
collecting for that check and that object (see 'test._report'). So nothing a
check says has to be said twice, and a check that says nothing new reports
nothing new; there is no second implementation of any verdict here.

A verdict here is one of five, where `pc qual test` has two:

- 'passed', and 'failed';
- 'warned': a finding on an object nobody is going to make ('Test.warned()'),
  which `pc qual test` reports and does not fail;
- 'skipped': the question could not be put on this machine ('Test.skipped()'),
  which `pc qual test` passes, out loud;
- 'not-applicable': the check has nothing to ask of this object. Decided by
  'Test.inapplicable()' before the check is run at all -- from what the object
  is and declares, without the cache, so that a pass an earlier run left there
  is not shown for a check that never applied -- or by the check itself, when
  it finds out only as it runs ('Test.not_applicable()').
"""

import asyncio
import typing

from . import config as qual_config
from . import registry
from .qualification import Test, _report

PASSED = "passed"
FAILED = "failed"
WARNED = "warned"
SKIPPED = "skipped"
NOT_APPLICABLE = "not-applicable"

# What each note a check makes becomes in a report: the levels a finding is
# shown at. A pass that says something about itself ("3 requirements met") is
# information like any other.
_LEVELS = {
    "error": "error",
    "warning": "warning",
    "skipped": "warning",
    "info": "info",
    "passed": "info",
    "not-applicable": "info",
}


class Result:
    """One check's verdict on one object, and what it said and left on the way."""

    def __init__(
        self,
        name: str,
        status: typing.Optional[str] = None,
        findings=None,
        artifacts=None,
        subtype: str = qual_config.BASIC,
        doc: typing.Optional[dict] = None,
        reports=None,
    ):
        self.name = name
        self.subtype = subtype
        self.doc = doc
        # What an 'other' check's tool reported, as it said it (see
        # 'Qualification.report()'): one per run, so usually one.
        self.reports = reports if reports is not None else []
        # None until the check has been run: a report asked for without running
        # anything lists the checks and leaves this unset.
        self.status = status
        self.findings = findings if findings is not None else []
        self.artifacts = artifacts if artifacts is not None else []

    @classmethod
    def of(cls, test: Test, verdict: bool, notes: list) -> "Result":
        """The result of a check that ran, from its verdict and what it said."""
        result = cls(test.name, subtype=test.SUBTYPE, doc=test.doc())
        levels = set()
        for level, said in notes:
            if level == "artifact":
                if said not in result.artifacts:
                    result.artifacts.append(said)
                continue
            if level == "report":
                if said not in result.reports:
                    result.reports.append(said)
                continue
            levels.add(level)
            if said:
                finding = {"level": _LEVELS.get(level, "info"), "text": said}
                if finding not in result.findings:
                    result.findings.append(finding)
        if not verdict:
            # Anything but a pass is a failure, as it is to `pc qual test`, which
            # takes 'all()' of the verdicts.
            result.status = FAILED
        elif "skipped" in levels:
            result.status = SKIPPED
        elif "warning" in levels:
            result.status = WARNED
        elif "not-applicable" in levels:
            result.status = NOT_APPLICABLE
        else:
            result.status = PASSED
        return result

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "subtype": self.subtype,
            "status": self.status,
            "findings": list(self.findings),
            "artifacts": list(self.artifacts),
            "reports": list(self.reports),
            "doc": self.doc,
        }


async def _run_one(test: Test, tests: list, ctx, shape, test_ctx: dict) -> Result:
    """Run one check through its cache, collecting what it says about 'shape'."""
    notes: list = []
    token = _report.set((test, shape, notes))
    try:
        verdict = await test.test_cached(tests, ctx, shape, test_ctx)
    except Exception as e:  # pylint: disable=broad-except
        # A check that broke has not passed: `pc qual test` reports the same object
        # as failed when one of its checks raises.
        notes.append(("error", "the check could not be run: %s" % e))
        verdict = Test.TEST_FAILED
    finally:
        _report.reset(token)
    return Result.of(test, verdict, notes)


def _is_testable(shape) -> bool:
    """Whether the checks are asked of 'shape' at all: a part, an assembly, a scene or a sketch.

    An interface is not a shape: `pc qual test -i` resolves its ports and asks none
    of these, so for one every check is listed as not applying to it.
    """
    from ..shape import Shape

    return isinstance(shape, Shape)


async def run_async(ctx, shape, tests: typing.Optional[list] = None, verify: bool = True, subtypes=None) -> list:
    """Every check `pc qual test <object>` runs on 'shape', and - when 'verify' - its verdict.

    'subtypes' limits it to the checks of those subtypes (all of them for
    none), and the checks plugins supply that the object declares are asked
    after the built-in ones, as a run of the command asks them.

    Without 'verify' nothing is run: the checks are listed, those that do not
    apply say why, and every other verdict is None. That costs a declaration
    read, which is what lets a client show the list before the slow ones are
    done.

    Asked about one object by name, as `pc qual test <object>` is ('Test.NAMED'), so
    a check that answers differently when walked to gives the answer a user
    asking about this object gets on the command line.
    """
    if tests is None:
        tests = registry.select(ctx.get_all_tests(), subtypes)
    builtin = list(tests)
    tests = registry.for_shape(builtin, shape, subtypes)
    results: list = [None] * len(tests)
    running = []
    testable = _is_testable(shape)
    for index, test in enumerate(tests):
        if not testable:
            reason = "an interface is tested by resolving its ports ('pc qual test -i'); this check is not asked of one"
        else:
            reason = test.inapplicable(shape)
        if reason is not None:
            results[index] = Result(
                test.name,
                NOT_APPLICABLE,
                [{"level": "info", "text": reason}],
                subtype=test.SUBTYPE,
                doc=test.doc(),
            )
        elif not verify:
            results[index] = Result(test.name, subtype=test.SUBTYPE, doc=test.doc())
        else:
            running.append(index)

    if running:
        test_ctx = {Test.NAMED: True}
        # Each check is handed the built-in list as what "the suite" is: a check
        # that runs the others over what the object is made of (manufacturability)
        # runs those, and not the checks this object declares for itself.
        done = await asyncio.gather(*[_run_one(tests[index], builtin, ctx, shape, test_ctx) for index in running])
        for index, result in zip(running, done):
            results[index] = result
    return results


def to_dict(object_name: str, kind: str, results: list, verified: bool, subtypes=None) -> dict:
    """A report as the JSON-RPC methods 'qual.report' and 'test.report' answer it."""
    return {
        "object": object_name,
        "kind": kind,
        "verified": verified,
        "subtypes": list(qual_config.subtypes_of(subtypes)),
        "tests": [result.to_dict() for result in results],
    }
