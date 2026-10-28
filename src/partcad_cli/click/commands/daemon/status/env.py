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
    that cannot be reconstructed from this side at all: the shared daemon -- a
    socket on POSIX, a named pipe on Windows -- inherited the environment of
    whatever started it, which may have been another shell, another window, or
    a previous day.

    Where no daemon can be had, `partcad_client.client.connect()` falls back to
    a one-shot stdio service spawned as a child of this process, and the answer
    is then this environment. That is still the environment of the process
    doing the work, which is what this command reports; it is simply not a
    *different* one. (Windows used to get that answer every time, before `pc`
    there used the daemon.)

    Variables whose names say they authenticate are scrubbed on the far side,
    before the log line is written, so the value never reaches the wire.
    """
    run(cli_ctx, "daemon.status.env", span_name="daemon status env")
