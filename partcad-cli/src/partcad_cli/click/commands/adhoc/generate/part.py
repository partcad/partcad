#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from pathlib import Path

import partcad as pc
from partcad.shape import PART_EXTENSION_MAPPING
from partcad.adhoc.generate import generate_cad_file
from ....cli_context import CliContext


@click.command(help="Ad-hoc generate CAD files using AI features.")
@click.option(
    "--desc",
    "desc",
    type=str,
    help="The part description used by LLMs.",
    required=True,
    show_envvar=True,
)
@click.option(
    "--ai",
    "provider",
    type=click.Choice(
        [
            "google",
            "openai",
        ]
    ),
    help="Generative AI provider.",
    required=True,
    show_envvar=True,
)
@click.option(
    "--kind",
    "kind",
    type=click.Choice(
        [
            "ai-cadquery",
            "ai-openscad",
        ]
    ),
    help="Type of the part",
    required=True,
)
@click.pass_obj
def cli(cli_ctx: CliContext, kind, provider, desc):
    """
    Generate a CAD file using specified provider and type.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        try:
            pc.logging.info(f"Generating ...")
            generate_cad_file(provider, kind, desc)
            pc.logging.info(f"Generation complete")
        except Exception as e:
            import traceback

            tb = traceback.print_exc()
            pc.logging.error(f"Error during generation: {tb}")
            raise click.Abort() from e
