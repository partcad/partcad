#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req`: what each command asks the daemon, and how a value typed on the command line is read.

The daemon's side -- what is written, and what is refused -- is pinned in
'tests/partcad_service_json_rpc/test_requirements_rpc.py'. Here the daemon is
not reached: the request is caught where it would leave.
"""

import io
import re

import pytest
import yaml
from click.testing import CliRunner

from partcad_cli.click import service
from partcad_cli.click.command import cli
from partcad_cli.click.commands.qual import add as qual_add
from partcad_cli.click.commands.qual import test as qual_test
from partcad_cli.click.commands.req import list as req_list


def _calls(monkeypatch, module=service, answer=None):
    calls = []

    def run(cli_ctx, method, params, needs_context=False):
        calls.append((method, params))
        return answer

    monkeypatch.setattr(module, "run", run)
    return calls


def _invoke(*args, stdin=None):
    return CliRunner().invoke(cli, ["--no-ansi", "req", *args], input=stdin)


def _words(output: str) -> str:
    """What rich-click drew in a box, as words."""
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).replace("│", " ").split())


@pytest.mark.parametrize(
    "args, requirement, name, value",
    [
        (["feature", "bracket", "mount", "Takes an M3 screw"], "feature", "mount", "Takes an M3 screw"),
        (["port", "bracket", "top"], "port", "top", None),
        (
            ["port", "bracket", "top", "--direction", "0", "0", "-1", "--angle", "90", "--boundary", "m3"],
            "port",
            "top",
            {"direction": [0, 0, -1], "angle": 90, "sketch": "m3"},
        ),
        (
            ["port", "bracket", "top", "--position", "null", "null", ">=5"],
            "port",
            "top",
            {"position": [None, None, ">=5"]},
        ),
        (["interface", "bracket", "mount"], "interface", "mount", None),
        (["physics", "bracket", "mass", "--value", ">0,<=0.05"], "physics", "mass", ">0,<=0.05"),
        # Each word is one value, whatever it starts with: no YAML quoting is needed on the command line.
        (["physics", "bracket", "mass", "--value", ">5"], "physics", "mass", ">5"),
        (["physics", "bracket", "mass", "--value", "!0"], "physics", "mass", "!0"),
        (["physics", "bracket", "mass", "--value", "0.25"], "physics", "mass", 0.25),
        (
            ["physics", "bracket", "centerOfMass", "--vector", "null", "null", "<5"],
            "physics",
            "centerOfMass",
            [None, None, "<5"],
        ),
        (
            ["match", "bracket", ":old", "--weight", "5", "--volume", "10%"],
            "match",
            ":old",
            {"volume": "10%", "mass": 5},
        ),
        (["has", "bracket", "material"], "has", "material", True),
        (["has", "bracket", "private_dependencies", "--not"], "has", "private_dependencies", False),
    ],
)
def test_add_says_the_requirement_from_the_command_line_alone(monkeypatch, args, requirement, name, value):
    calls = _calls(monkeypatch)
    result = _invoke("add", *args)
    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "requirements.add"
    assert (params["requirement"], params["name"], params["value"]) == (requirement, name, value)
    assert params["object"] == "bracket"
    assert params["replace"] is False


def test_options_may_come_anywhere_after_the_kind(monkeypatch):
    calls = _calls(monkeypatch)
    result = _invoke("add", "port", "--replace", "bracket", "-a", "top", "--direction", "0", "0", "-1")
    assert result.exit_code == 0, result.output
    ((_, params),) = calls
    assert (params["replace"], params["kind"], params["value"]) == (True, "assembly", {"direction": [0, 0, -1]})


def test_instances_are_named_one_option_each(monkeypatch):
    calls = _calls(monkeypatch)
    result = _invoke("add", "interface", "bracket", "mount", "--instance", "left", "--instance", "right")
    assert result.exit_code == 0, result.output
    ((_, params),) = calls
    assert params["instances"] == ["left", "right"]


def test_stdin_is_read_as_yaml_with_yamls_own_quoting(monkeypatch):
    calls = _calls(monkeypatch)
    result = _invoke("add", "physics", "bracket", "centerOfMass", "--stdin", stdin="[null, null, '>5']\n")
    assert result.exit_code == 0, result.output
    ((_, params),) = calls
    assert params["value"] == [None, None, ">5"]


def test_stdin_is_read_as_json_when_asked(monkeypatch):
    calls = _calls(monkeypatch)
    result = _invoke("add", "match", "bracket", ":old", "--stdin", "--json", stdin='{"mass": 5}')
    assert result.exit_code == 0, result.output
    ((_, params),) = calls
    assert params["value"] == {"mass": 5}


def test_stdin_that_yaml_cannot_read_says_how_to_quote(monkeypatch):
    calls = _calls(monkeypatch)
    result = _invoke("add", "physics", "bracket", "mass", "--stdin", stdin=">0\n")
    assert result.exit_code == 2
    assert "quote it" in _words(result.output)
    assert calls == []


def test_stdin_and_options_that_say_the_same_are_refused(monkeypatch):
    calls = _calls(monkeypatch)
    result = _invoke("add", "physics", "bracket", "mass", "--value", "1", "--stdin", stdin="1")
    assert result.exit_code == 2
    assert "use one" in _words(result.output)
    assert calls == []


@pytest.mark.parametrize(
    "args, requirement, extra",
    [
        (["feature", "bracket", "mount", "--with-references"], "feature", {"with_references": True}),
        (["interface", "bracket", "mount", "--instance", "left"], "interface", {"instances": ["left"]}),
        (["match", "bracket", ":old", "--weight"], "match", {"amounts": ["mass"]}),
        (["has", "bracket", "material"], "has", {}),
    ],
)
def test_remove_and_rm_ask_the_same(monkeypatch, args, requirement, extra):
    for verb in ("remove", "rm"):
        calls = _calls(monkeypatch)
        result = _invoke(verb, *args)
        assert result.exit_code == 0, result.output
        ((method, params),) = calls
        assert method == "requirements.remove"
        assert params["requirement"] == requirement
        assert {key: params[key] for key in extra} == extra


ANSWER = {
    "object": "//pkg:bracket",
    "kind": "part",
    "section": {"physics": {"mass": ">0"}, "has_material": True, "features": {"mount": "M3"}},
    "declared": {"physics": {"mass": ">0"}, "has_material": True, "features": {"mount": "M3"}},
    "requirements": [
        {"section": "physics", "name": "mass", "requirement": ">0", "passed": True, "detail": "1 kg"},
        {"section": "has", "name": "has_material", "requirement": "true", "passed": False, "detail": "none"},
    ],
}


def test_list_prints_yaml_that_reads_back(monkeypatch):
    calls = _calls(monkeypatch, req_list, ANSWER)
    result = _invoke("list", "bracket")
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "requirements.check"
    printed = yaml.safe_load(io.StringIO(result.output))
    assert printed == {"object": "//pkg:bracket", "kind": "part", "requirements": ANSWER["declared"]}
    # A comparison is quoted, so the text can be handed back to '--stdin'.
    assert "mass: '>0'" in result.output


def test_list_yaml_is_the_default_and_json_is_asked_for(monkeypatch):
    _calls(monkeypatch, req_list, ANSWER)
    assert _invoke("list", "bracket", "--yaml").output == _invoke("list", "bracket").output
    import json

    printed = json.loads(_invoke("list", "bracket", "--json").output)
    assert printed["requirements"] == ANSWER["declared"]


def test_list_of_some_kinds_with_their_verdicts(monkeypatch):
    calls = _calls(monkeypatch, req_list, ANSWER)
    result = _invoke("list", "bracket", "--kind", "has", "--verify")
    assert result.exit_code == 0, result.output
    assert calls[0][1]["verify"] is True
    printed = yaml.safe_load(result.output)
    assert printed["requirements"] == {"has_material": True}
    assert [check["name"] for check in printed["checks"]] == ["has_material"]


def test_test_is_qual_test_of_the_requirements_alone(monkeypatch):
    calls = _calls(monkeypatch, qual_test)
    result = _invoke("test", "-a", "bracket", "-p", "width=5")
    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "qual.run"
    assert (params["subtypes"], params["filter"], params["object"], params["assembly"]) == (
        ["basic"],
        "requirements",
        "bracket",
        True,
    )


def test_test_takes_none_of_the_options_that_choose_the_tests(monkeypatch):
    _calls(monkeypatch, qual_test)
    for option in ("--topology", "--simulation", "--filter", "--json"):
        assert _invoke("test", option, "bracket").exit_code == 2, option


def test_qual_add_refuses_nothing_itself_and_says_replace(monkeypatch):
    calls = _calls(monkeypatch, qual_add)
    result = CliRunner().invoke(
        cli, ["--no-ansi", "qual", "add", "--topology", "--replace", "--set", "limit=>5", "b", "t"]
    )
    assert result.exit_code == 0, result.output
    ((_, params),) = calls
    assert params["replace"] is True
    # '>5' typed on the command line is the text, not an empty folded block.
    assert params["entry"] == {"limit": ">5"}
