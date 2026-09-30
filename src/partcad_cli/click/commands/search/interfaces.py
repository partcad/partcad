import rich_click as click

from ...service import run


@click.command(help="Search interfaces by keyword")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively search in all imported packages (older spelling of '<package>...')",
    show_envvar=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help=(
        "Package to search the interfaces in, defaults to '//'(the root package). "
        "'<package>...' searches that package and every package below it"
    ),
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter interfaces using the specified keyword",
    type=str,
    required=True,
)
@click.pass_obj
def cli(cli_ctx, recursive: bool, package: str, keyword: str) -> None:
    run(
        cli_ctx,
        "search.objects",
        {"kind": "interfaces", "package": package, "recursive": recursive, "keyword": keyword},
        needs_context=True,
    )
