#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc ops': summary, rev list|diff|status|stage|new, deps list|add|remove|update, used-by, impact.

What the daemon answers is pinned beside 'partcad.changes', 'partcad.revisions',
'partcad.working_copy', 'partcad.usage' and 'partcad.impact', and in
'tests/partcad_service_json_rpc'; what is pinned here is the commands: the
method each asks and with what, what an OBJECT left out -- or written as a
package path -- means, how the states are said, how each answer is printed, and
what 'pc ops rev new' asks before it agrees to something. 'pc add dep' and
'pc update' are the old names of two of them.
"""

import importlib
import json

import pytest
from click.testing import CliRunner

from partcad_cli.click import service
from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self, answers):
        self.calls = []
        self.answers = list(answers)

    def run(self, cli_ctx, method, params, needs_context=False, **kwargs):
        self.calls.append((method, dict(params), needs_context))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _record(monkeypatch, module, *answers):
    """Every daemon call the command 'module' makes, answered with 'answers' in turn (the last one again and again)."""
    recorder = _Recorder(answers or [None])
    monkeypatch.setattr(service, "run", recorder.run)
    loaded = importlib.import_module("partcad_cli.click.commands." + module)
    if hasattr(loaded, "run"):
        monkeypatch.setattr(loaded, "run", recorder.run)
    return recorder


def _invoke(*args, input=None):
    return CliRunner().invoke(cli, ["--no-ansi", *args], input=input)


HISTORY = {
    "package": "//",
    "published": True,
    "head": "b" * 40,
    "more": False,
    "revisions": [
        {"sha": "b" * 40, "short": "b" * 8, "summary": "second", "author": "Tester", "time": 1_700_000_100},
        {
            "sha": "a" * 40,
            "short": "a" * 8,
            "summary": "first",
            "author": "Tester",
            "time": 1_700_000_000,
            "in": ["sub"],
        },
    ],
}

UNIFIED = "--- //@aaaaaaaa:cube\n+++ //@WORKTREE:cube\n@@ -1,2 +1,2 @@\n cube:\n-  cuboid: 10\n+  cuboid: 30\n"

STATUS = {
    "package": "//",
    "object": None,
    "branch": "main",
    "head": "b" * 40,
    "index": "c" * 40,
    "staged": [{"kind": "part", "name": "bracket", "object": "//:bracket", "how": ["declaration"]}],
    "unstaged": [{"kind": "part", "name": "gusset", "object": "//:gusset", "how": ["added"]}],
    "files": [{"path": "README.md", "sections": ["unstaged"]}],
    "own_files": None,
    "partial": [],
    "others_staged": [],
    "elsewhere": [{"directory": "motors", "package": "//motors", "staged": 2, "unstaged": 0}],
    "advice": "Stage the changes to // that are not staged yet -- :gusset (added) -- for a new revision.",
}


# ---- the tree ----------------------------------------------------------------


def test_the_operations_commands_are_under_ops():
    for command in (
        ["ops"],
        ["ops", "summary"],
        ["ops", "rev"],
        ["ops", "rev", "status"],
        ["ops", "rev", "stage"],
        ["ops", "rev", "new"],
        ["ops", "deps"],
        ["ops", "deps", "add"],
        ["ops", "used-by"],
        ["ops", "impact"],
    ):
        assert _invoke(*command, "--help").exit_code == 0, command
    # Gone before they shipped: 'pc revisions', 'pc used-by', 'pc ops rev uses' and 'pc ops rev used-by'.
    for command in (["revisions"], ["used-by"], ["ops", "rev", "uses"], ["ops", "rev", "used-by"]):
        assert _invoke(*command, "--help").exit_code != 0, command


def test_the_old_names_that_shipped_are_kept_but_not_listed():
    import click

    assert _invoke("add", "dep", "--help").exit_code == 0
    assert _invoke("update", "--help").exit_code == 0
    context = click.Context(cli)
    assert cli.get_command(context, "update").hidden
    assert cli.get_command(context, "add").get_command(context, "dep").hidden


# ---- rev list ----------------------------------------------------------------


def test_list_with_no_object_is_of_the_package(monkeypatch):
    recorder = _record(monkeypatch, "ops.rev.list", HISTORY)

    result = _invoke("ops", "rev", "list")

    assert result.exit_code == 0, result.output
    ((method, params, needs_context),) = recorder.calls
    assert method == "ops.rev.list"
    assert needs_context
    assert params == {"package": ".", "kind": "package", "limit": 100, "params": []}
    lines = result.output.splitlines()
    assert lines[0].startswith("* bbbbbbbb") and lines[0].endswith("second")
    assert lines[1].startswith("  aaaaaaaa") and lines[1].endswith("first  (in sub)")


def test_a_subject_written_as_a_package_path_is_that_package(monkeypatch):
    recorder = _record(monkeypatch, "ops.rev.list", HISTORY)

    result = _invoke("ops", "rev", "list", "//lib", "--limit", "5", "--after", "a" * 40)

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][1] == {"package": "//lib", "kind": "package", "limit": 5, "after": "a" * 40, "params": []}


def test_list_of_an_object_says_its_kind_when_a_flag_does_and_how_each_revision_changed_it(monkeypatch):
    answer = {**HISTORY, "revisions": [{**HISTORY["revisions"][0], "how": ["declaration", "source"]}], "more": True}
    recorder = _record(monkeypatch, "ops.rev.list", answer)

    result = _invoke("ops", "rev", "list", "-a", "frame")

    assert recorder.calls[0][1]["kind"] == "assembly" and recorder.calls[0][1]["object"] == "frame"
    assert "(declaration, source)" in result.output
    assert "--after " + "b" * 40 in result.output


def test_a_package_not_published_says_so(monkeypatch):
    _record(monkeypatch, "ops.rev.list", {"package": "//", "published": False, "revisions": []})

    assert "not published yet" in _invoke("ops", "rev", "list").output


# ---- rev diff ------------------------------------------------------------------


@pytest.mark.parametrize(
    "options, states",
    [
        ([], {}),
        (["--staged"], {"from": "HEAD", "to": "STAGED"}),
        (["--unstaged"], {"from": "STAGED", "to": "WORKTREE"}),
        (["--since", "v1"], {"from": "v1", "to": "WORKTREE"}),
        (["--from", "v1", "--to", "STAGED"], {"from": "v1", "to": "STAGED"}),
    ],
)
def test_diff_says_the_states_it_compares(monkeypatch, options, states):
    recorder = _record(monkeypatch, "ops.rev.diff", {"same": False, "unified": UNIFIED})

    result = _invoke("ops", "rev", "diff", *options, "cube")

    assert result.exit_code == 0, result.output
    params = recorder.calls[0][1]
    assert {key: params[key] for key in ("from", "to") if key in params} == states
    assert result.output == UNIFIED


def test_diff_refuses_the_states_said_twice():
    assert _invoke("ops", "rev", "diff", "--staged", "--unstaged").exit_code == 2
    assert _invoke("ops", "rev", "diff", "--staged", "--from", "v1").exit_code == 2


def test_diff_of_a_package_lists_what_changed_in_it_first(monkeypatch):
    answer = {
        "same": False,
        "unified": "",
        "changes": {
            "objects": [{"kind": "part", "name": "cube", "how": ["source"]}],
            "files": [{"path": "README.md", "how": "modified"}],
            "package_changed": True,
        },
    }
    recorder = _record(monkeypatch, "ops.rev.diff", answer)

    result = _invoke("ops", "rev", "diff")

    assert recorder.calls[0][1]["kind"] == "package"
    assert "Objects:" in result.output and ":cube" in result.output and "README.md" in result.output
    assert "The package's own declaration changed" in result.output


@pytest.mark.parametrize("same, code", [(True, 0), (False, 1)])
def test_diff_exit_code_says_whether_anything_changed(monkeypatch, same, code):
    _record(monkeypatch, "ops.rev.diff", {"same": same, "unified": "" if same else UNIFIED})

    assert _invoke("ops", "rev", "diff", "--exit-code", "cube").exit_code == code


def test_diff_json_is_the_daemon_s_answer(monkeypatch):
    answer = {"same": False, "unified": UNIFIED, "rows": []}
    _record(monkeypatch, "ops.rev.diff", answer)

    assert json.loads(_invoke("ops", "rev", "diff", "--json", "cube").output) == answer


# ---- rev status, stage and new ---------------------------------------------------


def test_status_says_what_is_staged_what_is_not_and_what_to_tell_an_agent(monkeypatch):
    recorder = _record(monkeypatch, "ops.rev.status", STATUS)

    result = _invoke("ops", "rev", "status")

    assert recorder.calls[0][0] == "ops.rev.status"
    output = result.output
    assert output.index("Staged") < output.index(":bracket") < output.index("Not staged") < output.index(":gusset")
    assert "README.md" in output and "//motors" in output
    assert "pc ops rev stage" in output and STATUS["advice"] in output


def test_stage_says_what_it_staged(monkeypatch):
    recorder = _record(
        monkeypatch,
        "ops.rev.stage",
        {"staged": ["bracket.py", "partcad.yaml (the declaration of bracket)"], "notes": []},
    )

    result = _invoke("ops", "rev", "stage", "bracket")

    assert recorder.calls[0][0] == "ops.rev.stage" and recorder.calls[0][1]["object"] == "bracket"
    assert "Staged: bracket.py, partcad.yaml (the declaration of bracket)" in result.output


def test_new_sends_the_message_and_the_author_git_on_this_machine_names(monkeypatch):
    import partcad_utils.git_identity as git_identity

    monkeypatch.setattr(git_identity, "identity", lambda directory=None: {"name": "Ann", "email": "ann@example.com"})
    recorder = _record(
        monkeypatch,
        "ops.rev.new",
        {"short": "c" * 8, "summary": "Bracket", "checks": [{"passed": True, "summary": "lint passed"}]},
    )

    result = _invoke("ops", "rev", "new", "-m", "Bracket", "bracket")

    assert result.exit_code == 0, result.output
    params = recorder.calls[0][1]
    assert params["message"] == "Bracket" and params["author"] == {"name": "Ann", "email": "ann@example.com"}
    assert params["include_others"] is False and params["yes"] is False and params["skip_checks"] is False
    assert "passed  lint passed" in result.output and "cccccccc  Bracket" in result.output


def test_new_refused_with_nobody_to_ask_says_why_and_fails(monkeypatch):
    refusal = service.Refusal(
        "Also staged, and would be in this revision: //motors", {"code": "others-staged", "status": STATUS}
    )
    _record(monkeypatch, "ops.rev.new", refusal)

    result = _invoke("ops", "rev", "new", "-m", "Bracket")

    assert result.exit_code == 2
    assert "Also staged" in result.output


def test_new_agreed_to_up_front_is_sent_as_agreed(monkeypatch):
    recorder = _record(monkeypatch, "ops.rev.new", {"short": "c" * 8, "summary": "Bracket", "checks": []})

    _invoke("ops", "rev", "new", "-m", "Bracket", "--include-others", "--yes", "--skip-checks")

    params = recorder.calls[0][1]
    assert params["include_others"] is True and params["yes"] is True and params["skip_checks"] is True


def test_new_asks_on_a_terminal_and_sends_again_once_agreed(monkeypatch):
    refusal = service.Refusal("Changes of // are not staged", {"code": "warnings", "status": STATUS})
    recorder = _record(monkeypatch, "ops.rev.new", refusal, {"short": "c" * 8, "summary": "Bracket", "checks": []})
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands.ops.rev.new"), "_interactive", lambda: True)

    result = _invoke("ops", "rev", "new", "-m", "Bracket", input="y\n")

    assert result.exit_code == 0, result.output
    assert [call[1]["yes"] for call in recorder.calls] == [False, True]


# ---- deps ------------------------------------------------------------------------


def test_deps_of_a_package_list_what_it_declares_uses_and_holds(monkeypatch):
    answer = {
        "package": "//",
        "object": None,
        "declared": [
            {"name": "std", "type": "git", "short": "f00dfeed", "location": "https://x/std.git", "track": "main"}
        ],
        "undeclared": [{"package": "//pub/std/metric", "users": [{"name": "frame", "count": 12}]}],
        "subpackages": [{"name": "motors", "package": "//motors"}],
    }
    recorder = _record(monkeypatch, "ops.deps.list", answer)

    result = _invoke("ops", "deps", "list")

    assert recorder.calls[0][1]["kind"] == "package"
    assert "std" in result.output and "f00dfeed" in result.output and "(tracks main)" in result.output
    assert "//pub/std/metric  (by :frame)" in result.output and "//motors" in result.output


def test_deps_of_an_object_list_what_it_names_and_how(monkeypatch):
    answer = {
        "package": "//",
        "object": "//:frame",
        "dependencies": [{"object": "//std:bolt", "kind": "part", "how": ["placed"], "count": 4, "short": "f00dfeed"}],
    }
    _record(monkeypatch, "ops.deps.list", answer)

    assert _invoke("ops", "deps", "list", "frame").output.split() == ["4", "part", "//std:bolt", "placed", "f00dfeed"]


def test_deps_add_remove_and_update_ask_the_daemon(monkeypatch):
    recorder = _record(monkeypatch, "ops.deps.add", {"package": "//", "added": True})
    _invoke("ops", "deps", "add", "std", "https://x/std.git", "--track", "main")
    assert recorder.calls[0][:2] == (
        "ops.deps.add",
        {"package": ".", "name": "std", "location": "https://x/std.git", "track": "main"},
    )

    recorder = _record(monkeypatch, "ops.deps.remove", {"package": "//", "removed": True, "users": ["//:frame"]})
    result = _invoke("ops", "deps", "remove", "std")
    assert recorder.calls[0][:2] == ("ops.deps.remove", {"package": ".", "name": "std"})
    assert "Still used by: //:frame" in result.output

    recorder = _record(monkeypatch, "ops.deps.update", {"count": 3})
    _invoke("ops", "deps", "update", "std", "-P", "//lib")
    assert recorder.calls[0][:2] == ("ops.deps.update", {"package": "//lib", "names": ["std"]})
    _invoke("ops", "deps", "update", "--all")
    assert recorder.calls[1][1] == {"all": True}
    assert _invoke("ops", "deps", "update", "--all", "std").exit_code == 2


def test_the_old_names_say_the_new_ones_and_do_what_they_do(monkeypatch):
    recorder = _record(monkeypatch, "add.dep", {"package": "//", "added": True})
    result = _invoke("add", "dep", "std", "../std")
    assert recorder.calls[0][0] == "ops.deps.add" and recorder.calls[0][1]["location"] == "../std"
    assert "'pc add dep' is 'pc ops deps add' now" in result.output

    recorder = _record(monkeypatch, "update", {"count": 7})
    result = _invoke("update")
    assert recorder.calls[0][:2] == ("ops.deps.update", {"all": True})
    assert "Successfully updated 7 packages" in result.output


# ---- used-by and impact ----------------------------------------------------------------


def test_used_by_an_object_and_loading_the_workspace_first(monkeypatch):
    recorder = _record(monkeypatch, "ops.used_by", {"object": "//:cube", "objects": []})

    result = _invoke("ops", "used-by", "--load", "cube")

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][0] == "ops.used_by"
    assert recorder.calls[0][1] == {"package": "", "object": "cube", "load": True, "params": []}
    assert "Nothing PartCAD has loaded uses //:cube" in result.output


def test_used_by_a_package_lists_the_packages_that_depend_on_it(monkeypatch):
    answer = {
        "package": "//lib",
        "object": None,
        "packages": [{"package": "//app", "type": "git", "short": "a" * 8, "behind": 4}],
        "objects": [{"object": "//app:frame", "kind": "assembly", "count": 2, "how": ["placed"]}],
    }
    _record(monkeypatch, "ops.used_by", answer)

    output = _invoke("ops", "used-by", "//lib").output

    assert "//app" in output and "(4 revisions behind)" in output
    assert "2  assembly   //app:frame" in output


def test_a_kind_flag_needs_an_object():
    assert _invoke("ops", "used-by", "-a").exit_code != 0


IMPACT = {
    "package": "//lib",
    "object": None,
    "from": "HEAD",
    "to": "WORKTREE",
    "changed": [{"object": "//lib:bolt"}],
    "affects": [
        {
            "kind": "part",
            "object": "//lib:bolt",
            "reached": "changed",
            "via": [],
            "findings": [{"severity": "breaking", "summary": "parameter 'length' removed; //app:long passes it"}],
        },
        {
            "kind": "part",
            "object": "//app:long",
            "reached": "via",
            "via": ["//lib:bolt"],
            "findings": [{"severity": "verify", "summary": "its requirements and tests need running again"}],
        },
    ],
    "affected_by": [],
    "pins": [],
    "pinned": [{"package": "//robot", "short": "7b1c0d22", "behind": 12}],
    "summary": {"breaking": 1, "changed": 0, "verify": 1, "info": 0},
}


def test_impact_sends_the_states_and_what_to_run_and_prints_the_findings(monkeypatch):
    recorder = _record(monkeypatch, "ops.impact", IMPACT)

    result = _invoke("ops", "impact", "--staged", "--measure", "--load", "//lib")

    params = recorder.calls[0][1]
    assert params == {
        "package": "//lib",
        "kind": "package",
        "from": "HEAD",
        "to": "STAGED",
        "measure": True,
        "test": False,
        "load": True,
    }
    output = result.output
    assert "1 breaking, 1 verify" in output
    assert "via //lib:bolt" in output and "parameter 'length' removed" in output
    assert "//robot" in output and "(12 revisions behind)" in output
    assert "--load looks at the whole workspace" not in output


@pytest.mark.parametrize("breaking, code", [(0, 0), (1, 1)])
def test_impact_exit_code_says_whether_anything_breaks(monkeypatch, breaking, code):
    _record(monkeypatch, "ops.impact", {**IMPACT, "summary": {**IMPACT["summary"], "breaking": breaking}})

    assert _invoke("ops", "impact", "--exit-code").exit_code == code


def test_summary_lists_the_views_the_subject_has(monkeypatch):
    answer = {
        "subject": {"package": "//", "object": "//:frame", "kind": "assembly"},
        "views": [
            {"id": "revisions", "label": "Revisions", "commands": [{"command": "pc ops rev list"}]},
            {"id": "usedby", "label": "Used By", "commands": [{"command": "pc ops used-by"}]},
        ],
        "summary": {
            "revisions": {"count": 3, "more": False},
            "status": {"staged": 1, "unstaged": 0},
            "usedBy": {"objects": 2},
        },
    }
    recorder = _record(monkeypatch, "ops.summary", answer)

    output = _invoke("ops", "summary", "frame").output

    assert recorder.calls[0][:2] == ("ops.views", {"package": "", "object": "frame", "summary": True})
    assert "//:frame (assembly)" in output and "3 revisions; 1 staged, 0 not staged" in output
    assert "2 objects" in output and "pc ops rev list" in output


@pytest.mark.parametrize(
    "module, method, command",
    [
        ("ops.rev.list", "ops.rev.list", ["ops", "rev", "list"]),
        ("ops.rev.diff", "ops.rev.diff", ["ops", "rev", "diff"]),
        ("ops.deps.list", "ops.deps.list", ["ops", "deps", "list"]),
        ("ops.used_by", "ops.used_by", ["ops", "used-by"]),
        ("copy", "copy.object", ["copy"]),
    ],
)
def test_every_command_naming_an_object_takes_its_parameter_values(monkeypatch, module, method, command):
    """'-p' as every command that names an object takes it (see 'test_param_option.py')."""
    recorder = _record(monkeypatch, module, {"same": True, "unified": "", "objects": [], "dependencies": []})
    extra = ["big"] if command == ["copy"] else []

    result = _invoke(*command, "bolt", *extra, "-p", "length=10", "--param", "include=UP,DOWN")

    assert result.exit_code != 2, result.output
    ((called, params, _),) = recorder.calls
    assert called == method
    assert params["object"] == "bolt"
    assert params["params"] == ["length=10", "include=UP,DOWN"]
