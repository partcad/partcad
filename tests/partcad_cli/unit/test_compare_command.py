#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc compare <reference> <current>': what reaches the daemon, and the exit code.

The comparison is the daemon's ('compare.objects'); what stays in the client is
the order the two objects are sent in, the options as the daemon reads them,
the JSON on stdout when it is asked for, and failing when the report says
something it was held to does not hold.
"""

import json

from click.testing import CliRunner

import partcad_cli.click.commands.compare as compare_command
from partcad_cli.click.command import cli


class _Daemon:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def run(self, cli_ctx, method, params, needs_context=False, **kwargs):
        self.calls.append((method, params, needs_context))
        return self.answer


def _invoke(monkeypatch, answer, *args):
    daemon = _Daemon(answer)
    monkeypatch.setattr(compare_command, "run", daemon.run)
    result = CliRunner().invoke(cli, ["--no-ansi", "compare", *args])
    return daemon, result


def test_the_reference_comes_first_and_every_option_reaches_the_daemon(monkeypatch):
    """'pc compare A B' sends A as the reference and B as the current object, every option as the daemon reads it."""
    daemon, result = _invoke(
        monkeypatch,
        {"passed": True},
        "-P",
        "//pkg",
        "--surface-distance",
        "0.5",
        "--displacement",
        "--max-volume-difference",
        "5",
        "--max-displacement-difference",
        "1",
        "--max-mass-difference",
        "2.5",
        "--worst",
        "3",
        "bracket-v1",
        "bracket-v2",
    )
    assert result.exit_code == 0, result.output
    ((method, params, needs_context),) = daemon.calls
    assert method == "compare.objects"
    assert needs_context is True
    assert params == {
        "package": "//pkg",
        "object": "bracket-v1",
        "current": "bracket-v2",
        "surface_distance": 0.5,
        "displacement": True,
        "max_volume_difference": 5.0,
        "max_displacement_difference": 1.0,
        "max_mass_difference": 2.5,
        "worst": 3,
        "json": False,
    }


def test_nothing_asked_is_sent_as_nothing(monkeypatch):
    """Options left out are sent as None, '--displacement' as not asked, and '--worst' as its default."""
    daemon, result = _invoke(monkeypatch, {"passed": None}, "a", "b")
    assert result.exit_code == 0, result.output
    ((_, params, _),) = daemon.calls
    assert params["surface_distance"] is None
    assert params["displacement"] is False
    assert params["max_volume_difference"] is None
    assert params["max_displacement_difference"] is None
    assert params["max_mass_difference"] is None
    assert params["worst"] == 10


def test_json_is_the_report_on_stdout(monkeypatch):
    """'--json' asks the daemon not to print, and prints its answer here."""
    answer = {"passed": None, "volume": {"percent": 5.0}}
    daemon, result = _invoke(monkeypatch, answer, "--json", "a", "b")
    assert result.exit_code == 0, result.output
    assert daemon.calls[0][1]["json"] is True
    assert json.loads(result.stdout) == answer


def test_a_comparison_that_does_not_hold_fails_after_it_is_printed(monkeypatch):
    """A comparison that does not hold exits 1, after its JSON is on stdout."""
    answer = {"passed": False}
    _, result = _invoke(monkeypatch, answer, "--json", "--max-mass-difference", "1", "a", "b")
    assert result.exit_code == 1
    assert json.loads(result.stdout.split("\n}\n")[0] + "\n}") == answer
    assert "b does not hold to a" in result.output


def test_a_spacing_of_nothing_is_refused_before_anything_is_sent(monkeypatch):
    """A '--surface-distance' of 0 is a usage error, and nothing reaches the daemon."""
    daemon, result = _invoke(monkeypatch, {"passed": None}, "--surface-distance", "0", "a", "b")
    assert result.exit_code == 2
    assert daemon.calls == []


def test_two_objects_are_needed(monkeypatch):
    """One object is a usage error, and nothing reaches the daemon."""
    daemon, result = _invoke(monkeypatch, {"passed": None}, "a")
    assert result.exit_code == 2
    assert daemon.calls == []
