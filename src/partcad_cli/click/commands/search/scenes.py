#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ... import fast_only
from ...service import run


@click.command(help="Search scenes by keyword")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively search in all imported packages (older spelling of '<package>...')",
    show_envvar=True,
)
@fast_only.option()
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help=(
        "Package to search the scenes in, defaults to '//'(the root package). "
        "'<package>...' searches that package and every package below it"
    ),
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter scenes using the specified keyword",
    type=str,
    required=True,
)
@click.pass_obj
def cli(cli_ctx, recursive: bool, fast_only: bool, package: str, keyword: str) -> None:
    run(
        cli_ctx,
        "search.objects",
        {"kind": "scenes", "package": package, "recursive": recursive, "fast_only": fast_only, "keyword": keyword},
        needs_context=True,
    )
