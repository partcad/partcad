#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc system status` and `pc daemon status`, through the real CLI.

Written at the same level as test_version.py: invoke the command a user would
type and assert what they would read. Nothing is stubbed, so the `pc daemon
status` half exercises the whole path -- CLI, client, socket, daemon session,
operation -- the way it does in the field.

The behave suite covers the rest of the command surface end to end; these are
here because status is the report a user reaches for first when something looks
wrong, on either side of the daemon boundary -- and because the report now has
three halves (the internal data, the resolved configuration, the environment),
each of which exists in both places.
"""

import logging
import os
import re
from collections.abc import Iterator

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli

# Every line the report promises, on either side.
EXPECTED = [
    "PartCAD version:",
    "Internal data storage location:",
    "Total internal data storage size:",
    "Git cache size:",
    "Tar cache size:",
    "Sandbox environments size:",
    "Conda package cache size:",
]


def _assert_status_report(output: str) -> None:
    for needle in EXPECTED:
        assert needle in output, f"{needle!r} missing from:\n{output}"
    # Sizes are reported in megabytes, not raw bytes.
    assert re.search(r"Git cache size: \d+\.\d\dMB", output), output


def test_system_status_reports_the_local_state(click_runner: Iterator[CliRunner]) -> None:
    """`pc system status` describes the machine the CLI runs on."""
    result = click_runner.invoke(cli, ["--no-ansi", "system", "status"])
    logging.debug("result.output: %s", result.output)
    assert result.exit_code == 0
    _assert_status_report(result.output)


def test_daemon_status_reports_the_daemon_state(click_runner: Iterator[CliRunner]) -> None:
    """`pc daemon status` describes the daemon, over the full client/daemon path."""
    result = click_runner.invoke(cli, ["--no-ansi", "daemon", "status"])
    logging.debug("result.output: %s", result.output)
    assert result.exit_code == 0
    _assert_status_report(result.output)


# What each of the other two reports promises, on either side.
EXPECTED_CONFIG = [
    "Configuration file:",
    "internal_state_dir:",
    "python_sandbox:",
]


def _assert_config_report(output: str) -> None:
    """Assert the lines a `... status config` report owes, on either side."""
    for needle in EXPECTED_CONFIG:
        assert needle in output, f"{needle!r} missing from:\n{output}"


def test_bare_system_status_still_reports_the_internal_data(click_runner: Iterator[CliRunner]) -> None:
    """The command grew subcommands; it did not stop being a command.

    Every docs page and every script that runs `pc system status` runs it with
    no argument, so a group that answered with its own help would break all of
    them silently.
    """
    result = click_runner.invoke(cli, ["--no-ansi", "system", "status"])
    assert result.exit_code == 0
    _assert_status_report(result.output)


def test_system_status_config_reports_the_resolved_configuration(click_runner: Iterator[CliRunner]) -> None:
    """`pc system status config` describes the machine the CLI runs on."""
    result = click_runner.invoke(cli, ["--no-ansi", "system", "status", "config"])
    logging.debug("result.output: %s", result.output)
    assert result.exit_code == 0
    _assert_config_report(result.output)


def test_daemon_status_config_reports_the_daemons_configuration(click_runner: Iterator[CliRunner]) -> None:
    """The same report, over the full client/daemon path, for the other side."""
    result = click_runner.invoke(cli, ["--no-ansi", "daemon", "status", "config"])
    logging.debug("result.output: %s", result.output)
    assert result.exit_code == 0
    _assert_config_report(result.output)


def test_system_status_env_reports_the_partcad_environment(
    click_runner: Iterator[CliRunner], monkeypatch: pytest.MonkeyPatch
) -> None:
    """This process's own `PC_*` variables, with the credentials taken out."""
    monkeypatch.setenv("PC_TAGS", "status-test")
    monkeypatch.setenv("PC_REMOTE_SANDBOX_TOKEN", "s3cr3t-do-not-print")

    result = click_runner.invoke(cli, ["--no-ansi", "system", "status", "env"])
    logging.debug("result.output: %s", result.output)

    assert result.exit_code == 0
    assert "PC_TAGS=status-test" in result.output
    assert "PC_REMOTE_SANDBOX_TOKEN=<scrubbed>" in result.output
    assert "s3cr3t-do-not-print" not in result.output


def test_daemon_status_env_reports_the_environment_of_whatever_answered(
    click_runner: Iterator[CliRunner],
) -> None:
    """The environment of the process that served the request, whichever that is.

    What the command promises is not "an environment that differs from mine" --
    it is "the environment of the process doing the work". Which process that is
    depends on the platform, and so does the right assertion:

    * On POSIX the request goes to the shared per-workspace socket daemon, a
      detached process holding whatever environment started it. A variable set
      only here never reaches it, and that difference is the whole reason
      `pc daemon status env` exists.
    * On Windows `partcad_client.client.connect()` does not use the named-pipe
      daemon; it spawns a one-shot stdio service as a *child of this process*,
      which inherits this environment. The variable is then genuinely in the
      environment of the process that answered, so reporting it is correct
      rather than a leak.

    Asserting the POSIX half everywhere is what this test did first, and it
    failed on `Pytest (windows-2022, 3.14)` for exactly the second reason.
    """
    result = click_runner.invoke(
        cli,
        ["--no-ansi", "daemon", "status", "env"],
        env={"PC_STATUS_TEST_CLIENT_ONLY": "client"},
    )
    logging.debug("result.output: %s", result.output)

    assert result.exit_code == 0
    if os.name == "nt":
        assert "PC_STATUS_TEST_CLIENT_ONLY=client" in result.output
    else:
        assert "PC_STATUS_TEST_CLIENT_ONLY" not in result.output
