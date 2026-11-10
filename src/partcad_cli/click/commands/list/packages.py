#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...exclude import exclude_option, exclude_params
from ...service import run

"""List Packages command.

Without recursion it shows the sub-packages of PACKAGE (the current package by
default): the folders and dependencies directly below it, every one, so that the
tree can be walked down a level at a time - a distributor's categories, the
public index's sections. With recursion it shows every package below PACKAGE
that has something in it: a sketch, a part, an assembly or a scene, whether the
package lists them or finds them with its own search. With --all it shows the
complete subtree: PACKAGE and every package below it, whether or not it holds
anything, sorted by name.
"""


@click.command(
    help=(
        "List the sub-packages of PACKAGE (the current package by default), or with -r every package below it "
        "that has something in it. PACKAGE may end in '...' to mean the latter"
    ),
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Every package below PACKAGE with something in it, rather than its sub-packages (or '<package>...')",
)
@click.option(
    "-a",
    "--all",
    "complete",
    is_flag=True,
    help="The complete subtree: PACKAGE and every package below it, empty ones included (implies -r)",
)
@exclude_option
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx, recursive: bool, complete: bool, exclude, package: str):
    params = {"package": package, "recursive": recursive, **exclude_params(exclude)}
    if complete:
        params["all"] = True
    run(cli_ctx, "list.packages", params, needs_context=True)
