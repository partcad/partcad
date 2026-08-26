#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc system status` and `pc daemon status`, through the real CLI.

Written at the same level as test_version.py: invoke the command a user would
type and assert what they would read. Nothing is stubbed, so `pc daemon status`
exercises the whole path -- CLI, client, socket, daemon session, operation --
the way it does in the field.

The behave suite covers the rest of the command surface end to end; these two
are here because status is the report a user reaches for first when something
looks wrong, on either side of the daemon boundary.
"""

import logging
import re
from collections.abc import Iterator

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
