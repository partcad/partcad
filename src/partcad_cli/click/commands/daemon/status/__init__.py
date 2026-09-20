#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ....service import run
from .. import DaemonCommands


class StatusCommands(DaemonCommands):
    """The subcommands of `pc daemon status`, one per `pc system status` counterpart.

    Each answers, for the daemon serving this workspace, the question its
    `pc system ...` twin answers for the machine the CLI runs on. The two
    coincide while the daemon is local; they will not once it can be remote,
    which is why both halves exist.
    """

    COMMANDS_FOLDER_PATH = os.path.join(DaemonCommands.COMMANDS_FOLDER_PATH, "status")
    COMMANDS_PACKAGE_NAME = DaemonCommands.COMMANDS_PACKAGE_NAME + ".status"


# Bare `pc daemon status` keeps reporting what it always reported; see the same
# comment in the `pc system status` group.
@click.command(
    cls=StatusCommands,
    invoke_without_command=True,
    no_args_is_help=False,
    help="Display the state of internal data used by the PartCAD daemon",
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """The daemon-side counterpart of `pc system status`.

    Reports the daemon's own version and internal state directory, which are the
    client's only for as long as the two share a machine.
    """
    if ctx.invoked_subcommand is not None:
        return
    run(ctx.obj, "daemon.status", span_name="daemon status")
