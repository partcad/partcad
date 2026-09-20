#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from partcad_utils import logging as pc_logging
from partcad_utils import telemetry as pc_telemetry
from partcad_utils.config_report import ENV_PREFIX, environment


@click.command(help="Dump the PC_* environment variables of this process")
@click.pass_obj
def cli(cli_ctx) -> None:
    """The `PC_*` variables this `pc` process was started with.

    Not the same report as `config` beside it, and that is the point: the
    configuration says what an option resolved to, this says what the
    environment asked for. They disagree whenever a command-line option won, a
    variable was misspelled, or a value was rejected -- which is most of the
    cases where somebody runs either of them.

    Values that authenticate this process to something else are scrubbed; the
    names are still listed, because "is it set" is what a report needs to say
    about a credential. See `partcad_utils.config_report`.
    """
    with pc_telemetry.set_context(cli_ctx.otel_context):
        with pc_logging.Process("StatusEnv", "global"):
            reported = list(environment())
            if not reported:
                pc_logging.info("No %s* environment variables are set" % ENV_PREFIX)
            for name, value in reported:
                pc_logging.info("%s=%s" % (name, value))
