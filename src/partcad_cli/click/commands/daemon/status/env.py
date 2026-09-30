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

    The daemon-side counterpart of `pc system status env`. On POSIX it is the
    one report that cannot be reconstructed from this side at all: the shared
    socket daemon inherited the environment of whatever started it, which may
    have been another shell, another window, or a previous day.

    On Windows it answers the same question and usually gets the same answer as
    `pc system status env`, because `partcad_client.client.connect()` does not
    use the named-pipe daemon -- it spawns a one-shot stdio service as a child
    of this process, which inherits this environment. That is the environment of
    the process doing the work, which is what this command reports; it is simply
    not a *different* one there.

    Variables whose names say they authenticate are scrubbed on the far side,
    before the log line is written, so the value never reaches the wire.
    """
    run(cli_ctx, "daemon.status.env", span_name="daemon status env")
