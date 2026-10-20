#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One object's `pc test`, as the IDE's Test tab is drawn from it.

The subject is the package of 'test_requirements.py' ('data/requirements'): a
part, an assembly of two of them, a sketch and an interface. Nothing here builds
geometry: which checks apply is a question about what an object is and declares,
and what a check said is collected from checks written for the purpose.
"""

import asyncio

import pytest

import partcad as pc
from partcad.test import catalog, report
from partcad.test.test import Test

PACKAGE = "tests/partcad/unit/data/requirements/partcad.yaml"


@pytest.fixture
def ctx():
    return pc.Context(PACKAGE)


def _listed(ctx, shape):
    return {result.name: result for result in asyncio.run(report.run_async(ctx, shape, verify=False))}


def test_without_running_anything_every_check_is_listed_in_the_order_it_runs(ctx):
    results = asyncio.run(report.run_async(ctx, ctx.get_part("//:plate"), verify=False))
    assert [result.name for result in results] == catalog.registered()


def test_a_check_that_does_not_apply_says_why_before_anything_is_run(ctx):
    part = _listed(ctx, ctx.get_part("//:plate"))
    assert part["interference"].status == report.NOT_APPLICABLE
    assert part["interference"].findings == [
        {"level": "info", "text": "only an assembly or a scene has parts to overlap"}
    ]
    assert part["manufacturability-laser"].status == report.NOT_APPLICABLE
    # What applies is left to be run.
    for name in ("cad", "shell", "solidity", "requirements", "sim"):
        assert part[name].status is None, name

    assembly = _listed(ctx, ctx.get_assembly("//:pair"))
    assert assembly["interference"].status is None
    assert assembly["shell"].status == report.NOT_APPLICABLE
    assert assembly["shell"].findings[0]["text"].startswith("an assembly is checked through its parts")

    sketch = _listed(ctx, ctx.get_sketch("//:m3-boundary"))
    assert sketch["solidity"].findings[0]["text"] == "a sketch has no solid"
    assert sketch["fea"].findings[0]["text"] == "only a part is analysed"


def test_an_interface_is_listed_with_nothing_that_applies(ctx):
    results = asyncio.run(report.run_async(ctx, ctx.get_interface("//:m3-thru"), verify=False))
    assert {result.status for result in results} == {report.NOT_APPLICABLE}


def test_a_report_carries_the_entry_of_each_check(ctx):
    answer = report.to_dict(
        "//:plate", "part", asyncio.run(report.run_async(ctx, ctx.get_part("//:plate"), verify=False)), False
    )
    assert answer["verified"] is False
    first = answer["tests"][0]
    assert first["name"] == "cad"
    assert first["doc"]["title"] == catalog.TESTS["cad"].title
    assert first["status"] is None and first["findings"] == [] and first["artifacts"] == []


class _Saying(Test):
    """A check that says what it is told to, about the shape it is asked about and another."""

    def __init__(self, name, say):
        super().__init__(name)
        self.say = say

    async def test(self, tests_to_run, ctx, shape, test_ctx={}):
        test_ctx[self.NOT_CACHEABLE] = True
        # Said about another object on the way: not this verdict's.
        self.failed(_Other(), "about something else")
        return self.say(self, shape)


class _Other:
    project_name = "elsewhere"
    name = "other"


def _artifact(check, shape):
    check.artifact(shape, {"kind": "assembly", "package": "//", "name": "overlap"})
    return check.failed(shape, "they overlap")


def _raises(check, shape):
    raise RuntimeError("it broke")


def test_what_each_check_said_becomes_its_verdict_and_findings(ctx):
    Test.MAX_CONCURRENT_TESTS = 8
    checks = [
        _Saying("passes", lambda check, shape: check.passed(shape, "all three met")),
        _Saying("fails", lambda check, shape: check.failed(shape, "it is %s", "wrong")),
        _Saying("warns", lambda check, shape: check.warned(shape, "nobody makes it")),
        _Saying("skips", lambda check, shape: check.skipped(shape, "no solver here")),
        _Saying("finds-nothing", lambda check, shape: check.not_applicable(shape, "nothing to ask")),
        _Saying("leaves", _artifact),
        _Saying("breaks", _raises),
    ]
    results = {
        result.name: result
        for result in asyncio.run(report.run_async(ctx, ctx.get_part("//:plate"), tests=checks, verify=True))
    }
    assert {name: result.status for name, result in results.items()} == {
        "passes": report.PASSED,
        "fails": report.FAILED,
        "warns": report.WARNED,
        "skips": report.SKIPPED,
        "finds-nothing": report.NOT_APPLICABLE,
        "leaves": report.FAILED,
        "breaks": report.FAILED,
    }
    assert results["passes"].findings == [{"level": "info", "text": "all three met"}]
    assert results["fails"].findings == [{"level": "error", "text": "it is wrong"}]
    assert results["warns"].findings == [{"level": "warning", "text": "nobody makes it"}]
    assert results["skips"].findings == [{"level": "warning", "text": "no solver here"}]
    assert results["leaves"].artifacts == [{"kind": "assembly", "package": "//", "name": "overlap"}]
    assert results["breaks"].findings == [{"level": "error", "text": "the check could not be run: it broke"}]
    # Nothing said about the other object reached this object's report.
    assert not any("something else" in finding["text"] for result in results.values() for finding in result.findings)
