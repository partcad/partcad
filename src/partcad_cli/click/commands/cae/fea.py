#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...analysis import analysis_command, analysis_options


@click.command(help="Run a finite element analysis of a part and report its findings")
@analysis_options
@click.argument("object", type=str, required=True)  # The part to analyse
@click.pass_obj
def cli(cli_ctx, package, implementation, output_dir, create_dirs, as_json, object):
    """Ask the configured solver how the part holds up under what it carries.

    The part says what holds it and what it carries in its own `fea:` section;
    everything else about the run is `analysis_command`, shared with `pc cae cfd`.
    """
    analysis_command(cli_ctx, "fea", package, implementation, output_dir, create_dirs, as_json, object)
