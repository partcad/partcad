#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc update`.

The command does two things that used to be one, and the order matters: PartCAD
itself is updated first, so a package that needs a newer PartCAD gets one. What
these pin down is the contract between the two halves -- which of them runs, in
which order, and which failures are allowed to stop the other.
"""

from collections.abc import Iterator

import partcad_cli.click.commands.update as update_command
import pytest
from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_service_json_rpc import selfupdate


@pytest.fixture
def recorder(monkeypatch):
    """Record what the command does, without letting it reach a daemon or a network.

    Both halves are stubbed: `selfupdate` (which would talk to GitHub/PyPI and
    write to the installation) and `service.run` (which would start a daemon).
    """

    class Recorder:
        def __init__(self):
            self.events = []
            self.update_result = {"updated": False, "current": "0.7.158", "latest": "0.7.158", "reason": None}
            self.check_result = {
                "kind": "standalone",
                "current": "0.7.158",
                "latest": "0.7.159",
                "pinned": None,
                "update_available": True,
                "reason": None,
            }
            self.update_error = None

        def fake_update(self, to_version=None, log=None, **kwargs):
            self.events.append(("selfupdate", to_version))
            if self.update_error:
                raise self.update_error
            return self.update_result

        def fake_check(self, to_version=None, **kwargs):
            self.events.append(("check", to_version))
            if self.update_error:
                raise self.update_error
            return self.check_result

        def fake_run(self, cli_ctx, method, params=None, span_name=None, needs_context=False):
            self.events.append(("daemon", method))
            return {}

    rec = Recorder()
    monkeypatch.setattr(selfupdate, "update", rec.fake_update)
    monkeypatch.setattr(selfupdate, "check", rec.fake_check)
    monkeypatch.setattr(update_command, "run", rec.fake_run)
    return rec


def _invoke(click_runner, *args):
    return click_runner.invoke(cli, ["--no-ansi", "update", *args])


def test_update_updates_partcad_before_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner)
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None), ("daemon", "update")]


def test_partcad_only_skips_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--partcad-only")
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None)]


def test_packages_only_skips_the_version_check(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--packages-only")
    assert result.exit_code == 0
    assert recorder.events == [("daemon", "update")]


def test_check_reports_without_installing_or_updating_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--check")
    assert result.exit_code == 0
    assert recorder.events == [("check", None)]
    assert "0.7.159 is available" in result.output


def test_check_says_so_when_up_to_date(click_runner: Iterator[CliRunner], recorder) -> None:
    recorder.check_result = {**recorder.check_result, "latest": "0.7.158", "update_available": False}
    result = _invoke(click_runner, "--check")
    assert "PartCAD 0.7.158 is up to date." in result.output


def test_to_version_is_passed_through(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--partcad-only", "--to-version", "0.7.100")
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", "0.7.100")]


def test_partcad_only_and_packages_only_are_mutually_exclusive(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--partcad-only", "--packages-only")
    assert result.exit_code == 2
    assert recorder.events == []


def test_packages_only_rejects_the_self_update_options(click_runner: Iterator[CliRunner], recorder) -> None:
    result = _invoke(click_runner, "--packages-only", "--check")
    assert result.exit_code == 2
    assert recorder.events == []


def test_a_failed_self_update_still_updates_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    """A source checkout, or an unreachable index, must not break `pc update`."""
    recorder.update_error = selfupdate.SelfUpdateError("PartCAD runs from a source checkout")
    result = _invoke(click_runner)
    assert result.exit_code == 0
    assert recorder.events == [("selfupdate", None), ("daemon", "update")]
    assert "was not updated" in result.output


def test_a_failed_self_update_is_fatal_when_it_was_the_whole_request(
    click_runner: Iterator[CliRunner], recorder
) -> None:
    recorder.update_error = selfupdate.SelfUpdateError("could not reach https://pypi.org")
    result = _invoke(click_runner, "--partcad-only")
    assert result.exit_code == 1
    assert "could not reach" in result.output


def test_offline_skips_the_version_check_but_not_the_packages(click_runner: Iterator[CliRunner], recorder) -> None:
    """`--offline` promises nothing is fetched, and a release lookup is a fetch."""
    result = click_runner.invoke(cli, ["--no-ansi", "--offline", "update"])
    assert result.exit_code == 0
    assert recorder.events == [("daemon", "update")]
    assert "Offline mode" in result.output
