#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc revisions list|diff|uses|used-by' and 'pc used-by': what reaches the daemon, and what is printed.

What the daemon answers is pinned beside 'partcad.revisions' and 'partcad.usage'
and in 'tests/partcad_service_json_rpc/test_operations_tab.py'; what is pinned
here is the commands: the method each asks, what an OBJECT left out means (the
package), and how each answer is printed -- a diff as the daemon wrote it, with
'--exit-code' saying whether anything changed.
"""

import importlib
import json

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer

    def run(self, cli_ctx, method, params, needs_context=False, **kwargs):
        self.calls.append((method, params, needs_context))
        return self.answer


def _record(monkeypatch, module, answer):
    recorder = _Recorder(answer)
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands." + module), "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", *args])


HISTORY = {
    "package": "//",
    "published": True,
    "head": "b" * 40,
    "revisions": [
        {"sha": "b" * 40, "short": "b" * 8, "summary": "second", "author": "Tester", "time": 1_700_000_100},
        {"sha": "a" * 40, "short": "a" * 8, "summary": "first", "author": "Tester", "time": 1_700_000_000},
    ],
}

UNIFIED = "--- //@aaaaaaaa:cube\n+++ //:cube\n@@ -1,2 +1,2 @@\n cube:\n-  cuboid: 10\n+  cuboid: 30\n"


def test_both_are_commands_of_their_own():
    result = _invoke("--help")

    assert "revisions" in result.output
    assert "used-by" in result.output


def test_list_with_no_object_is_of_the_package(monkeypatch):
    recorder = _record(monkeypatch, "revisions.list", HISTORY)

    result = _invoke("revisions", "list")

    assert result.exit_code == 0, result.output
    ((method, params, needs_context),) = recorder.calls
    assert method == "revisions.list"
    assert needs_context
    assert params == {"package": ".", "kind": "package"}
    lines = result.output.splitlines()
    assert lines[0].startswith("* bbbbbbbb") and lines[0].endswith("second")
    assert lines[1].startswith("  aaaaaaaa") and lines[1].endswith("first")


def test_list_of_an_object_says_its_kind_when_a_flag_does(monkeypatch):
    recorder = _record(monkeypatch, "revisions.list", HISTORY)

    _invoke("revisions", "list", "-a", "-P", "//pkg", "frame")

    assert recorder.calls[0][1] == {"package": "//pkg", "object": "frame", "kind": "assembly"}


def test_a_package_not_published_says_so(monkeypatch):
    _record(monkeypatch, "revisions.list", {"package": "//", "published": False, "head": None, "revisions": []})

    result = _invoke("revisions", "list")

    assert "not published yet" in result.output


def test_diff_prints_the_unified_diff_the_daemon_wrote(monkeypatch):
    recorder = _record(monkeypatch, "revisions.diff", {"same": False, "unified": UNIFIED, "rows": []})

    result = _invoke("revisions", "diff", "-U", "1", "v1", "cube")

    assert result.exit_code == 0, result.output
    ((method, params, _),) = recorder.calls
    assert method == "revisions.compare"
    assert params == {"package": "", "object": "cube", "revision": "v1", "lines": 1}
    assert result.output == UNIFIED


def test_diff_with_no_object_is_of_the_package(monkeypatch):
    recorder = _record(monkeypatch, "revisions.diff", {"same": True, "unified": "", "rows": []})

    result = _invoke("revisions", "diff", "v1")

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][1]["kind"] == "package"
    assert result.output == ""


@pytest.mark.parametrize("same, code", [(True, 0), (False, 1)])
def test_diff_exit_code_says_whether_anything_changed(monkeypatch, same, code):
    _record(monkeypatch, "revisions.diff", {"same": same, "unified": "" if same else UNIFIED, "rows": []})

    result = _invoke("revisions", "diff", "--exit-code", "v1", "cube")

    assert result.exit_code == code


def test_diff_json_is_the_daemon_s_answer(monkeypatch):
    answer = {"same": False, "unified": UNIFIED, "rows": [{"tag": "equal"}]}
    _record(monkeypatch, "revisions.diff", answer)

    result = _invoke("revisions", "diff", "--json", "v1", "cube")

    assert json.loads(result.output) == answer


def test_uses_lists_each_dependency_at_its_commit(monkeypatch):
    recorder = _record(
        monkeypatch,
        "revisions.uses",
        {
            "package": "//",
            "revision": "a" * 40,
            "dependencies": [
                {"name": "std", "short": "f00dfeed", "versioned": "//std@" + "f" * 40, "package": "//@x/std"},
            ],
        },
    )

    result = _invoke("revisions", "uses", "v1")

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][0] == "revisions.uses"
    assert recorder.calls[0][1] == {"package": ".", "object": None, "revision": "v1"}
    assert result.output.split() == ["std", "f00dfeed", "//std@" + "f" * 40]


def test_revisions_used_by_is_a_command_of_two_words(monkeypatch):
    recorder = _record(
        monkeypatch,
        "revisions.used_by",
        {"package": "//", "revision": "a" * 40, "objects": [{"object": "//x:pair", "kind": "assembly", "count": 2}]},
    )

    result = _invoke("revisions", "used-by", "v1")

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][0] == "revisions.used_by"
    assert result.output.split() == ["2", "assembly", "//x:pair"]


def test_used_by_an_object_and_loading_the_workspace_first(monkeypatch):
    recorder = _record(monkeypatch, "used_by", {"object": "//:cube", "objects": []})

    result = _invoke("used-by", "--load", "cube")

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][0] == "usage.used_by"
    assert recorder.calls[0][1] == {"package": "", "object": "cube", "load": True}
    assert "Nothing PartCAD has loaded uses //:cube" in result.output


def test_a_kind_flag_needs_an_object():
    result = _invoke("used-by", "-a")

    assert result.exit_code != 0
