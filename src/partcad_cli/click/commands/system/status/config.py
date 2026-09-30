#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_utils import logging as pc_logging
from partcad_utils import telemetry as pc_telemetry
from partcad_utils.config_report import resolved_options
from partcad_utils.user_config import UserConfig
from partcad_utils.user_config import user_config as pc_user_config


@click.command(help="Dump the effective configuration of this installation")
@click.pass_obj
def cli(cli_ctx) -> None:
    """What this machine's configuration resolved to, all layers applied.

    The same object `pc config` prints, reported here so that it sits beside
    `pc daemon status config` -- the daemon has a configuration of its own,
    resolved from its own environment when something first started it, and
    "which of the two am I looking at" is the question this pair exists to
    answer. `command.py` has already laid the command line over the file and the
    `PC_*` environment by the time a command body runs, so this is the effective
    configuration and not a layer of it.

    Read through `partcad_utils`, which is where the configuration and the report
    actually live; `partcad` re-exports both under its own namespace, and going
    through the re-export would only be a longer way to reach the same objects.
    """
    with pc_telemetry.set_context(cli_ctx.otel_context):
        with pc_logging.Process("StatusConfig", "global"):
            config_path = UserConfig.get_config_path()
            if not os.path.exists(config_path):
                config_path += " (absent)"
            pc_logging.info("Configuration file: %s" % config_path)
            for key, value in resolved_options(pc_user_config):
                pc_logging.info("%s: %s" % (key, value))
