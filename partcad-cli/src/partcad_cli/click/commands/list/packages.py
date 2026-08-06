#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run

"""List Packages command.

It shows the packages that have at least one sketch, part, or assembly.
The primary purpose of this interface is to feed user interfaces like IDEs with the list of packages that are worth
showing.
When no recursion in requested, it shows the current package if and only if it has any parts, sketches, or assemblies.
"""


@click.command(help="List imported packages")
@click.option("-r", "--recursive", is_flag=True, help="Recursively process all imported packages")
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx, recursive: bool, package: str):
    run(
        cli_ctx,
        "list.packages",
        {"package": package, "recursive": recursive},
        needs_context=True,
    )
