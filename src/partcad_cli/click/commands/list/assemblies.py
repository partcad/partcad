#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ... import fast_only
from ...exclude import exclude_option, exclude_params
from ...service import run


@click.command(
    help="List available assemblies. PACKAGE may end in '...' to reach every package below it",
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages (older spelling of '<package>...')",
    show_envvar=True,
)
@fast_only.option()
@exclude_option
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx, recursive: bool, fast_only: bool, exclude, package: str) -> None:
    run(
        cli_ctx,
        "list.objects",
        {
            "kind": "assemblies",
            "package": package,
            "recursive": recursive,
            "fast_only": fast_only,
            **exclude_params(exclude),
        },
        needs_context=True,
    )
