#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A qualification test a plugin supplies, run through 'wrappers/wrapper_qual.py' (see 'partcad.qual.plugin').

The plugin is a package's own: a 'qual:' section declaring one 'other' test, a
script that counts, and parts that declare it -- one it passes, one it fails, and
the mistakes a declaration can make.
"""

import asyncio
import os
import shutil

import pytest

import partcad as pc
from partcad.qual import report

BOX = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples", "produce_part_brep", "box.brep")

PACKAGE = """
qual:
  tally:
    desc: Counts, and says whether the count is three
    path: tally.py
    subtype: other
    expected: 3
parts:
  right:
    type: brep
    path: box.brep
    qual:
      other:
        count:
          path: :tally
  wrong:
    type: brep
    path: box.brep
    qual:
      other:
        count:
          path: :tally
          expected: 2
  misplaced:
    type: brep
    path: box.brep
    qual:
      basic:
        count:
          path: :tally
  missing:
    type: brep
    path: box.brep
    qual:
      other:
        count:
          path: :nothing
  plain:
    type: brep
    path: box.brep
"""

SCRIPT = """
import os

def process(path, request):
    with open(os.path.join(path, "seen.txt"), "w") as stream:
        stream.write(request["subject"])
    ok = request["expected"] == 3
    return {
        "success": True,
        "passed": ok,
        "findings": [{"level": "info" if ok else "error", "text": "counted %s" % request["expected"]}],
        "report": {
            "title": "Tally",
            "verdict": "GO" if ok else "NO-GO",
            "rows": [{"severity": "info", "subject": request["subject"], "kind": request["subject_kind"]}],
        },
    }
"""


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "tally.py").write_text(SCRIPT)
    shutil.copy(BOX, tmp_path / "box.brep")
    config = pc.UserConfig()
    config.cache_bypass = True
    return pc.Context(str(tmp_path), user_config=config)


def _other(ctx, name, subtypes=("other",)):
    part = ctx.get_part("//:%s" % name)
    return {result.name: result for result in asyncio.run(report.run_async(ctx, part, subtypes=list(subtypes)))}


def test_a_declared_test_is_run_by_its_plugin_and_its_report_handed_on(ctx):
    count = _other(ctx, "right")["count"]
    assert (count.subtype, count.status) == ("other", report.PASSED)
    (handed,) = count.reports
    assert handed["title"] == "Tally" and handed["verdict"] == "GO"
    assert handed["rows"] == [
        {"severity": "info", "subject": "%s:right" % ctx.get_part("//:right").project_name, "kind": "part"}
    ]
    assert count.doc["applies"].startswith("the object that declares it")


def test_what_the_object_declares_overrides_the_plugins_default(ctx):
    count = _other(ctx, "wrong")["count"]
    assert count.status == report.FAILED
    assert {"level": "error", "text": "counted 2"} in count.findings
    assert count.reports[0]["verdict"] == "NO-GO"


def test_a_test_declared_under_another_subtype_than_its_plugin_supplies_fails_saying_where(ctx):
    count = _other(ctx, "misplaced", ("basic",))["count"]
    assert count.status == report.FAILED
    assert "declare it under 'qual: other:'" in count.findings[0]["text"]


def test_a_plugin_nobody_declares_fails_saying_what_there_is(ctx):
    count = _other(ctx, "missing")["count"]
    assert count.status == report.FAILED
    assert "declares no qualification plugin 'nothing'" in count.findings[0]["text"]
    assert "It declares: tally" in count.findings[0]["text"]


def test_an_object_that_declares_nothing_has_no_other_tests(ctx):
    assert _other(ctx, "plain") == {}


def test_a_package_walk_asks_each_object_what_it_declares(ctx):
    project = ctx.get_project("//")
    assert asyncio.run(project.test_async(ctx, subtypes=["other"], prefix="count")) is False
