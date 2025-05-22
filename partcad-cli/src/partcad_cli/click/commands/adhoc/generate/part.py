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


@click.command(help="Ad-hoc generate CAD files using AI features. `desc` is the part description used by LLMs.")
@click.argument(
    "desc",
    type=str,
)
@click.option(
    "--ai",
    "provider",
    type=click.Choice(["google", "openai"]),
    default="google",
    show_default=True,
    help="Generative AI provider.",
    required=False,
    show_envvar=True,
)
@click.option(
    "--kind",
    "kind",
    type=click.Choice(["ai-cadquery", "ai-openscad"]),
    default="ai-cadquery",
    show_default=True,
    help="Type of the part.",
    required=False,
)
@click.option(
    "-p",
    "--path",
    show_envvar=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Directory to save the generated files. Defaults to the current working directory if not specified.",
)
@click.pass_obj
def cli(cli_ctx: CliContext, kind: str, provider: str, desc: str, path: str = None):
    """
    Generate a CAD file using specified provider and type.

    Arguments:
      desc    The part description used by LLMs.
    """
    with pc.telemetry.set_context(cli_ctx.otel_context):
        try:
            pc.logging.info(f"Generating ...")
            generate_cad_file(provider, kind, desc, path)
            pc.logging.info(f"Generation complete")
        except Exception as e:
            pc.logging.error(f"Error during generation: {e}")
            raise click.Abort() from e
