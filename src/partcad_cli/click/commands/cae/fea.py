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
    analysis_command(cli_ctx, "fea", package, implementation, output_dir, create_dirs, as_json, object)
