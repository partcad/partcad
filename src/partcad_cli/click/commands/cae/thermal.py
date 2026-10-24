#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...analysis import analysis_command, analysis_options


@click.command(help="Run a heat transfer analysis of a part and report its findings")
@analysis_options
@click.argument("object", type=str, required=True)  # The part to analyse
@click.pass_obj
def cli(cli_ctx, package, implementation, output_dir, as_json, params, object):
    """Ask the configured solver how hot the part gets, heated and cooled as it is.

    The part says where it is held at a temperature, heated and cooled in its
    own `thermal:` section; everything else about the run is
    `analysis_command`, shared with `pc cae fea`.
    """
    analysis_command(cli_ctx, "thermal", package, implementation, output_dir, as_json, params, object)
