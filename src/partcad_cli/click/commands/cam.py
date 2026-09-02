#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from ..service import run


@click.command(help="Produce the manufacturing instructions for a part")
@click.option(
    "-t",
    "--format",
    "format",
    help="The kind of instructions to produce, when the package declares more than one",
    type=str,
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the part from",
    type=str,
)
@click.option(
    "-e",
    "--options-package",
    help="Package to read the 'cam:' configuration from, in addition to the part's own package",
    type=str,
)
@click.option(
    "-O",
    "--output-dir",
    help="Put the copy in this directory instead of the current one",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
)
@click.option(
    "-o",
    "--output",
    "output_name",
    help="Name the copy this instead of what the package calls it",
    type=str,
)
@click.option(
    "--visual",
    help="Produce the plugin's 3D model of what the instructions do, instead of the instructions",
    is_flag=True,
)
@click.option(
    "-f",
    "--force",
    help="Produce the package's copy again even though it is already there",
    is_flag=True,
)
@click.option(
    "--ignore-manufacturability",
    help="Produce the instructions for a part that is not declared manufacturable",
    is_flag=True,
)
@click.option(
    "-p",
    "--param",
    "params",
    type=str,
    multiple=True,
    metavar="<name>=<value>",
    help="Assign a value to the parameter",
    show_envvar=True,
)
@click.argument("object", type=str, required=True)
@click.pass_obj
def cli(
    cli_ctx,
    format,
    package,
    options_package,
    output_dir,
    output_name,
    visual,
    force,
    ignore_manufacturability,
    params,
    object,
) -> None:
    """Write what a machine needs to make this part.

    The package keeps its own copy of the file, written once and reused
    afterwards, and this puts a copy of it where the command was run - which is
    the file to feed to a machine. See 'partcad.actions.cam'.
    """
    run(
        cli_ctx,
        "cam",
        {
            "object": object,
            "package": package,
            "format": format,
            "options_package": options_package,
            # Resolved here: the daemon runs somewhere else, and both of these
            # name a place in the user's own working directory.
            "output_dir": os.path.abspath(output_dir) if output_dir else os.getcwd(),
            "output_name": output_name,
            "visual": visual,
            "force": force,
            "ignore_manufacturability": ignore_manufacturability,
            "params": list(params),
        },
        span_name="cam",
        needs_context=True,
    )
