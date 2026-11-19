#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc comment add` and `pc comment list`: what each asks the daemon, and what the list prints."""

import json
import os

from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_cli.click.commands.comment import add
from partcad_cli.click.commands.comment import list as list_command


def _calls(monkeypatch, module, answer=None):
    calls = []

    def run(cli_ctx, method, params, needs_context=False):
        calls.append((method, params, needs_context))
        return answer

    monkeypatch.setattr(module, "run", run)
    return calls


def test_a_comment_is_signed_with_git_and_sent_to_the_daemon(monkeypatch, tmp_path):
    calls = _calls(monkeypatch, add)
    monkeypatch.setattr(add.pc_comments, "author", lambda directory=None: "Ada Lovelace")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        ["--no-ansi", "comment", "add", "bracket", "-m", "Too *thin*.", "--ref", "face:12", "--attach", "a.jpg"],
    )
    assert result.exit_code == 0, result.output
    ((method, params, needs_context),) = calls
    assert (method, needs_context) == ("comment.add", True)
    assert params["object"] == "bracket"
    assert params["name"] == "Ada Lovelace"
    assert params["text"] == "Too *thin*."
    assert params["ref"] == "face:12"
    assert params["thread"] is None
    # Absolute, as 'pc add' sends a file: the daemon writes it relative to the package.
    assert params["attachments"] == [os.path.join(str(tmp_path), "a.jpg")]
    assert "kind" not in params


def test_a_reply_names_its_thread_and_a_kind_flag_says_what_the_object_is(monkeypatch):
    calls = _calls(monkeypatch, add)
    result = CliRunner().invoke(
        cli, ["--no-ansi", "comment", "add", "--kind", "color", "red", "-m", "ok", "--reply", "2", "--author", "Ada"]
    )
    assert result.exit_code == 0, result.output
    ((_, params, _),) = calls
    assert (params["thread"], params["kind"], params["name"]) == (2, "color", "Ada")
    assert params["attachments"] is None


def test_without_an_object_the_comment_is_on_the_package(monkeypatch):
    calls = _calls(monkeypatch, add)
    result = CliRunner().invoke(cli, ["--no-ansi", "comment", "add", "-m", "Release notes", "--author", "Ada"])
    assert result.exit_code == 0, result.output
    ((_, params, _),) = calls
    assert "object" not in params


def test_nobody_to_sign_it_with_is_refused_before_anything_is_asked(monkeypatch):
    calls = _calls(monkeypatch, add)
    monkeypatch.setattr(add.pc_comments, "author", lambda directory=None: None)
    result = CliRunner().invoke(cli, ["--no-ansi", "comment", "add", "bracket", "-m", "x"])
    assert result.exit_code == 2
    assert "git config" in result.output
    assert calls == []


def test_the_threads_are_listed_with_the_index_a_reply_names(monkeypatch):
    answer = {
        "objects": {
            "//p:bracket": {
                "object": "//p:bracket",
                "kind": "part",
                "threads": [
                    {
                        "index": 0,
                        "ref": "face:12",
                        "about": "face 12",
                        "comments": [
                            {
                                "name": "Ada",
                                "date": "2026-11-19 14:31:01 UTC",
                                "text": "Too thin.\nReally.",
                                "attachments": ["photos/crack.jpg"],
                            }
                        ],
                    }
                ],
            }
        }
    }
    calls = _calls(monkeypatch, list_command, answer)
    result = CliRunner().invoke(cli, ["--no-ansi", "comment", "list", "-a", "bracket"])
    assert result.exit_code == 0, result.output
    ((method, params, _),) = calls
    assert (method, params["object"], params["kind"]) == ("comment.list", "bracket", "assembly")
    assert "//p:bracket (part): 1 thread(s)" in result.output
    assert "[0] on face 12" in result.output
    assert "Ada, 2026-11-19 14:31:01 UTC:" in result.output
    assert "      Really." in result.output
    assert "Attached: photos/crack.jpg" in result.output

    result = CliRunner().invoke(cli, ["--no-ansi", "comment", "list", "--json", "bracket"])
    assert json.loads(result.output) == answer
