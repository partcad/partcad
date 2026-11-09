import rich_click as click

from ...search_scope import each_package_option, recursive_option
from ...service import run


@click.command(help="Search sketches by keyword")
@recursive_option
@each_package_option
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
def cli(cli_ctx, recursive: bool, each_package: bool, package: str, keyword: str) -> None:
    run(
        cli_ctx,
        "search.objects",
        {
            "kind": "sketches",
            "package": package,
            "recursive": recursive,
            "each_package": each_package,
            "keyword": keyword,
        },
        needs_context=True,
    )
