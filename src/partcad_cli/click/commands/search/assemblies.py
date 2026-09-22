import rich_click as click

from ...service import run


@click.command(help="Search assemblies by keyword")
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
        "Package to search the assemblies in, defaults to '//'(the root package). "
        "'<package>...' searches that package and every package below it"
    ),
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter assemblies using the specified keyword",
    type=str,
)
@click.option(
    "-i",
    "--interface",
    "interface",
    type=str,
    help=(
        "Search for the assemblies that implement this interface, or anything derived from it. "
        "A bare name is the one this package declares; '//package:name' is any other"
    ),
    show_envvar=True,
)
@click.pass_obj
def cli(cli_ctx, recursive: bool, package: str, keyword: str, interface: str) -> None:
    if not keyword and not interface:
        raise click.UsageError("Nothing to search for: pass --keyword, --interface, or both")
    run(
        cli_ctx,
        "search.objects",
        {"kind": "assemblies", "package": package, "recursive": recursive, "keyword": keyword, "interface": interface},
        needs_context=True,
    )
