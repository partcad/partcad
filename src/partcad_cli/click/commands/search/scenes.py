#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ...service import run


@click.command(help="Search scenes by keyword")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help="Package to search the scenes in, defaults to '//'(the root package)",
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter scenes using the specified keyword",
    type=str,
    required=True,
)
@click.pass_obj
def cli(cli_ctx, recursive: bool, package: str, keyword: str) -> None:
    run(
        cli_ctx,
        "search.objects",
        {"kind": "scenes", "package": package, "recursive": recursive, "keyword": keyword},
        needs_context=True,
    )
