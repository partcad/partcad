#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc open`.

The command is a thin wrapper over `partcad_client.external`, and what is pinned
here is the wrapping: the options it hands over, and the two ways it reports
back. The JSON shape matters most -- the VS Code extension's "Open in..." menu
reads it, and on a failure the message it carries is the whole answer (which X
server to install, or how to let PartCAD use a container), so it has to survive
a non-zero exit rather than be replaced by one.

Which side of the command boundary this command is on is checked by
`test_command_boundary.py`; nothing here starts an application or a container.
"""

import json
from collections.abc import Iterator

import pytest
from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_client import external


@pytest.fixture
def opened(monkeypatch):
    """Record the call `pc open` makes, and answer it however a test wants."""

    class Recorder:
        def __init__(self):
            self.calls = []
            self.error = None
            self.result = external.OpenResult(
                tool="freecad",
                method="native",
                path="/w/cube.step",
                command=["/usr/bin/freecad", "/w/cube.step"],
                detail="FreeCAD is installed on this machine.",
            )

        def open_file(self, path, tool="freecad", use_docker=False, image=None, log=None):
            self.calls.append({"path": path, "tool": tool, "use_docker": use_docker, "image": image, "log": log})
            if self.error:
                raise self.error
            return self.result

    recorder = Recorder()
    monkeypatch.setattr(external, "open_file", recorder.open_file)
    return recorder


def _invoke(click_runner, *args):
    return click_runner.invoke(cli, ["--no-ansi", "open", *args])


def test_the_options_reach_the_opener(click_runner: Iterator[CliRunner], opened) -> None:
    result = _invoke(
        click_runner, "--with", "freecad", "--use-docker", "--docker-image", "freecad/freecad:weekly", "x.step"
    )
    assert result.exit_code == 0, result.output
    assert opened.calls == [
        {
            "path": "x.step",
            "tool": "freecad",
            "use_docker": True,
            "image": "freecad/freecad:weekly",
            "log": opened.calls[0]["log"],
        }
    ]


def test_freecad_is_the_default_application(click_runner: Iterator[CliRunner], opened) -> None:
    _invoke(click_runner, "x.step")
    assert opened.calls[0]["tool"] == "freecad"
    assert opened.calls[0]["use_docker"] is False


def test_what_happened_is_reported(click_runner: Iterator[CliRunner], opened) -> None:
    result = _invoke(click_runner, "x.step")
    assert "FreeCAD is installed on this machine." in result.output


def test_json_reports_what_happened_in_full(click_runner: Iterator[CliRunner], opened) -> None:
    result = _invoke(click_runner, "--json", "x.step")
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "ok": True,
        "tool": "freecad",
        "method": "native",
        "path": "/w/cube.step",
        "command": ["/usr/bin/freecad", "/w/cube.step"],
        "detail": "FreeCAD is installed on this machine.",
    }


def test_json_stays_silent_about_progress(click_runner: Iterator[CliRunner], opened) -> None:
    # The caller parses stdout; progress lines would be in the way of the one
    # thing it is there to read.
    _invoke(click_runner, "--json", "x.step")
    assert opened.calls[0]["log"] is None


def test_a_failure_is_an_error_with_the_reason(click_runner: Iterator[CliRunner], opened) -> None:
    opened.error = external.ExternalToolError("FreeCAD was not found on this machine.")
    result = _invoke(click_runner, "x.step")
    assert result.exit_code != 0
    assert "FreeCAD was not found" in result.output


def test_a_failure_keeps_its_message_under_json(click_runner: Iterator[CliRunner], opened) -> None:
    opened.error = external.ExternalToolError("Install XQuartz (https://www.xquartz.org/)")
    result = _invoke(click_runner, "--json", "x.step")
    assert result.exit_code == 1
    reported = json.loads(result.output)
    assert reported["ok"] is False
    assert "XQuartz" in reported["error"]
