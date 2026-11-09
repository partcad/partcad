import rich_click as click

from ...search_scope import recursive_option
from ...service import run


@click.command(help="Search sketches by keyword")
@recursive_option
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help=(
        "Package to search the sketches in, defaults to '//'(the root package). "
        "'<package>...' searches that package and every package below it"
    ),
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter sketches using the specified keyword",
    type=str,
    required=True,
)
@click.pass_obj
def cli(cli_ctx, recursive: bool, package: str, keyword: str) -> None:
    run(
        cli_ctx,
        "search.objects",
        {"kind": "sketches", "package": package, "recursive": recursive, "keyword": keyword},
        needs_context=True,
    )
