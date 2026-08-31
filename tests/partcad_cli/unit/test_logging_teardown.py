#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The CLI takes its log renderer back off, however the command ended.

`pc` installs a renderer for the `partcad` logger while the group callback runs
-- the ANSI terminal one, or a plain handler under `--no-ansi` -- and that
renderer holds the stream it was handed at that moment. Installing a second one
is a no-op while the first is still installed, so a renderer left behind by one
command is the renderer the *next* command in the same process writes through:
into a stream nobody reads any more. What that looks like is a command that
printed nothing at all.

A user runs one command per process, which hides it completely. This suite is
where many commands share a process, and it is what noticed: a `pc open` that
failed left the plain handler attached, and the very next `pc system status`
reported an empty page -- on every platform and every interpreter, because
nothing about it is environmental.

The teardown therefore cannot live only on the path a command returns by. The
command below fails through click's own error handling rather than by raising
something of PartCAD's own, because that is the path with the least of PartCAD
on it: if the renderer comes off there, it comes off anywhere.
"""

import logging
from collections.abc import Iterator

from click.testing import CliRunner

import partcad_utils.logging_ansi_terminal as logging_ansi_terminal
import partcad_utils.logging_remote_client as logging_remote_client
from partcad_cli.click.command import cli
from partcad_utils import logging as pc_logging

# A package that is not there, asked for a file type that does not exist: two
# reasons to fail, neither of which needs a daemon, a network or a CAD runtime.
FAILING_COMMAND = ["render", "-t", "no-such-format", "nothing"]


def _handlers() -> set:
    """What is on the `partcad` logger right now.

    A set, and read rather than assumed empty: the suite runs under pytest,
    which attaches capture handlers of its own. What is asserted below is that
    the CLI leaves this exactly as it found it, whatever "it" happens to be.
    """
    return set(logging.getLogger("partcad").handlers)


def _fail(click_runner: CliRunner, tmp_path, *before):
    """Run the failing command, and confirm it failed with a renderer live.

    The `ERROR:partcad:` prefix is the plain renderer's own format, so finding
    it in what the runner captured is what says a renderer was installed *and*
    bound to this invocation. Without that, the assertions that follow would
    hold for the empty reason that nothing was ever installed at all.
    """
    result = click_runner.invoke(cli, [*before, "-p", str(tmp_path), *FAILING_COMMAND])
    assert result.exit_code != 0, result.output
    return result


def test_a_failing_command_detaches_the_plain_renderer(click_runner: Iterator[CliRunner], tmp_path) -> None:
    before = _handlers()
    result = _fail(click_runner, tmp_path, "--no-ansi")
    assert "ERROR:partcad:" in result.output

    assert logging_remote_client._plain_handler is None
    assert _handlers() == before


def test_a_failing_command_detaches_the_ansi_renderer(click_runner: Iterator[CliRunner], tmp_path) -> None:
    """The default renderer, which has more to put back than a handler.

    `logging_ansi_terminal.init()` takes the logger's handlers off and keeps
    them, and runs a listener thread of its own, so leaving that behind mislays
    the handlers as well as the thread.
    """
    before = _handlers()
    _fail(click_runner, tmp_path)

    assert logging_ansi_terminal.listener is None
    assert logging_ansi_terminal.queue_handler is None
    assert _handlers() == before


def test_a_failing_command_does_not_silence_the_next_one(click_runner: Iterator[CliRunner], tmp_path) -> None:
    """The symptom itself, stated as the two commands that showed it.

    `pc system status` writes its whole report through the `partcad` logger, so
    it is the command a mislaid renderer empties completely.
    """
    _fail(click_runner, tmp_path, "--no-ansi")
    # The command that follows is a second process in the field, and starts with
    # nothing recorded against it. Only the renderer was ever meant to outlive
    # the command that installed it, and only for as long as that command ran.
    pc_logging.reset_errors()

    result = click_runner.invoke(cli, ["--no-ansi", "system", "status"])
    assert result.exit_code == 0, result.output
    assert "PartCAD version:" in result.output, result.output
