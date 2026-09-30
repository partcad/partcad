#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ....service import run


@click.command(help="Dump the effective configuration of the PartCAD daemon")
@click.pass_obj
def cli(cli_ctx) -> None:
    """What the daemon's own configuration resolved to.

    The daemon-side counterpart of `pc system status config`, and the pair is
    worth having precisely because the two answers differ. A daemon is warm and
    shared per workspace, so its configuration is whatever its environment held
    when something first started it -- possibly days ago, possibly from a VS
    Code window. A command's own configuration travels with every
    `context.create` and is what the *work* is done under (see "Whose user
    configuration the daemon works under" in `src/partcad_cli/AGENTS.md`); this
    reports the other one, which is what the daemon falls back on for a client
    that sends none.

    Like `pc daemon status`, this reaches the daemon serving this workspace,
    starting one if none is answering yet -- there is no reading the
    configuration of a process that does not exist.
    """
    run(cli_ctx, "daemon.status.config", span_name="daemon status config")
