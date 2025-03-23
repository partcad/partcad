import rich_click as click
from click.testing import CliRunner

from partcad.context import Context
from partcad_cli.click.commands.search.assemblies import cli as search_assemblies
from partcad_cli.click.commands.search.interfaces import cli as search_interfaces
from partcad_cli.click.commands.search.packages import cli as search_packages
from partcad_cli.click.commands.search.parts import cli as search_parts
from partcad_cli.click.commands.search.sketches import cli as search_sketches


@click.command(help="Search all available parts, sketches, and assemblies with the given keyword")
@click.option(
    "-u",
    "--used_by",
    help="Only process objects used by the given assembly or scene.",
    type=str,
    required=False,
    show_envvar=True,
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter objects using the specified keyword",
    type=str,
    required=True,
)
@click.argument("package", type=str, required=False, default=".")
@click.pass_obj
def cli(ctx: Context, used_by: str, recursive: bool, package: str, keyword: str) -> None:
    """Search all available parts, assemblies and scenes recursively with the given keyword."""
    runner = CliRunner()
    options = []

    if recursive:
        options.append("--recursive")
    if used_by:
        options.append("--used_by")
    if package:
        options.append(package)
    if keyword:
        options.extend(["--keyword", keyword])

    catch_exceptions = False

    runner.invoke(search_packages, options, catch_exceptions=catch_exceptions, obj=ctx)
    runner.invoke(search_sketches, options, catch_exceptions=catch_exceptions, obj=ctx)
    runner.invoke(search_interfaces, options, catch_exceptions=catch_exceptions, obj=ctx)
    runner.invoke(search_parts, options, catch_exceptions=catch_exceptions, obj=ctx)
    runner.invoke(search_assemblies, options, catch_exceptions=catch_exceptions, obj=ctx)
