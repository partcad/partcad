#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ... import fast_only
from ...service import run


@click.command(
    help="List available scenes. PACKAGE may end in '...' to reach every package below it",
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages (older spelling of '<package>...')",
    show_envvar=True,
)
@fast_only.option()
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx, recursive: bool, fast_only: bool, package: str) -> None:
    run(
        cli_ctx,
        "list.objects",
        {"kind": "scenes", "package": package, "recursive": recursive, "fast_only": fast_only},
        needs_context=True,
    )
