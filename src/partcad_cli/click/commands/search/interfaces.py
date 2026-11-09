import rich_click as click

from ...search_scope import recursive_option
from ...service import run


@click.command(help="Search interfaces by keyword")
@recursive_option
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
