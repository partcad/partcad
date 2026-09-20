#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ....service import run


@click.command(help="Dump the PC_* environment variables of the PartCAD daemon")
@click.pass_obj
def cli(cli_ctx) -> None:
    """The `PC_*` variables the daemon process is running with.

    The daemon-side counterpart of `pc system status env`, and the one report
    that cannot be reconstructed from this side at all: the daemon inherited the
    environment of whatever started it, which may have been another shell,
    another window, or a previous day. Variables whose names say they
    authenticate are scrubbed there, in the daemon, so the value never reaches
    the wire.
    """
    run(cli_ctx, "daemon.status.env", span_name="daemon status env")
