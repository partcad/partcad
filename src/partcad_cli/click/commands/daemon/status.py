#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run


@click.command(help="Display the state of internal data used by the PartCAD daemon")
@click.pass_obj
def cli(cli_ctx) -> None:
    """The daemon-side counterpart of `pc system status`.

    Reports the daemon's own version and internal state directory, which are the
    client's only for as long as the two share a machine.
    """
    run(cli_ctx, "daemon.status", span_name="daemon status")
