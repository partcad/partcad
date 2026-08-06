#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run


@click.command(help="List available providers")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.argument("package", type=str, required=False, default=".")  # help="Package to retrieve the object from"
@click.pass_obj
def cli(cli_ctx, recursive: bool, package: str) -> None:
    run(
        cli_ctx,
        "list.providers",
        {"package": package, "recursive": recursive},
        needs_context=True,
    )
