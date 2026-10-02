#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc daemon start` and `pc daemon stop`, on every platform.

Both commands used to answer Windows with a sentence instead of doing anything
-- `daemon start` printing "not available on Windows yet" on *stdout*, where the
endpoint goes, with a zero exit status. The VS Code extension reads that stdout
to find the daemon, so it connected to the sentence and the window was left with
no PartCAD in it at all.

The daemon exists on Windows (a named pipe, served by
`partcad_service_json_rpc.daemon`), so there is nothing here to branch on any
more. These tests hold that: whatever `os.name` says, the command hands the
question to `partcad_client` and prints what came back.
"""

import os

import pytest
from click.testing import CliRunner

from partcad_cli.click.commands.daemon import start as start_command
from partcad_cli.click.commands.daemon import stop as stop_command

ENDPOINTS = {
    "posix": "/home/me/.partcad/workspaces/0123456789abcdef/socket",
    "nt": "\\\\.\\pipe\\partcad-0123456789abcdef",
}


@pytest.mark.parametrize("os_name", ["posix", "nt"])
def test_start_prints_the_endpoint_it_was_given(monkeypatch, os_name):
    monkeypatch.setattr(os, "name", os_name)
    monkeypatch.setattr(start_command.client, "start_daemon", lambda **_: ENDPOINTS[os_name])

    result = CliRunner().invoke(start_command.cli, [])

    assert result.exit_code == 0
    # Exactly the endpoint and nothing else: whoever reads this connects to it.
    assert result.output.strip() == ENDPOINTS[os_name]


@pytest.mark.parametrize("os_name", ["posix", "nt"])
def test_stop_reports_whether_one_was_running(monkeypatch, os_name):
    monkeypatch.setattr(os, "name", os_name)

    monkeypatch.setattr(stop_command.daemon, "stop_daemon", lambda: True)
    stopped = CliRunner().invoke(stop_command.cli, [])
    assert stopped.exit_code == 0
    assert "PartCAD daemon stopped" in stopped.output

    monkeypatch.setattr(stop_command.daemon, "stop_daemon", lambda: False)
    idle = CliRunner().invoke(stop_command.cli, [])
    assert idle.exit_code == 0
    assert "No PartCAD daemon was running" in idle.output


def test_stop_all_stops_every_daemon_on_the_machine(monkeypatch):
    """What an uninstaller runs, so that nothing is executing out of the files
    it is about to remove."""
    monkeypatch.setattr(stop_command.daemon, "live_daemon_dirs", lambda: ["a", "b"])
    monkeypatch.setattr(stop_command.daemon, "stop_all_daemons", lambda: ["a", "b"])
    monkeypatch.setattr(stop_command.daemon, "stop_daemon", lambda: pytest.fail("--all is not this workspace's"))

    result = CliRunner().invoke(stop_command.cli, ["--all"])

    assert result.exit_code == 0
    assert "Stopped 2 of 2 PartCAD daemon(s)" in result.output


def test_stop_all_with_nothing_running_says_so(monkeypatch):
    monkeypatch.setattr(stop_command.daemon, "live_daemon_dirs", lambda: [])
    monkeypatch.setattr(stop_command.daemon, "stop_all_daemons", lambda: pytest.fail("there was nothing to stop"))

    result = CliRunner().invoke(stop_command.cli, ["--all"])

    assert result.exit_code == 0, result.output
    assert "No PartCAD daemon was running" in result.output


def test_stop_all_fails_when_a_daemon_will_not_go(monkeypatch):
    """The caller is about to delete what it runs from, so it has to know."""
    monkeypatch.setattr(stop_command.daemon, "live_daemon_dirs", lambda: ["a", "b"])
    monkeypatch.setattr(stop_command.daemon, "stop_all_daemons", lambda: ["a"])

    result = CliRunner().invoke(stop_command.cli, ["--all"])

    assert result.exit_code != 0
    assert "Stopped 1 of 2 PartCAD daemon(s)" in result.output
    assert "1 PartCAD daemon(s) did not stop" in result.output


def test_stop_all_does_not_count_a_daemon_it_was_not_asked_about(monkeypatch):
    """The helper takes its own snapshot: a daemon that started after this one
    and stopped must not stand in for one from this list that did not."""
    monkeypatch.setattr(stop_command.daemon, "live_daemon_dirs", lambda: ["a", "b"])
    monkeypatch.setattr(stop_command.daemon, "stop_all_daemons", lambda: ["a", "late"])

    result = CliRunner().invoke(stop_command.cli, ["--all"])

    assert result.exit_code != 0
    assert "Stopped 1 of 2 PartCAD daemon(s)" in result.output
