import rich_click as click
from click.testing import CliRunner

from partcad_cli.click.commands.search.assemblies import cli as search_assemblies
from partcad_cli.click.commands.search.interfaces import cli as search_interfaces
from partcad_cli.click.commands.search.packages import cli as search_packages
from partcad_cli.click.commands.search.parts import cli as search_parts
from partcad_cli.click.commands.search.scenes import cli as search_scenes
from partcad_cli.click.commands.search.sketches import cli as search_sketches

from ... import fast_only
from ...cli_context import CliContext
from ...search_scope import each_package_option, recursive_option


@click.command(help="Search all available parts, sketches, assemblies and scenes with the given keyword")
@recursive_option
@each_package_option
@fast_only.option()
@click.option(
    "-k",
    "--keyword",
    help="Search and filter objects using the specified keyword",
    type=str,
    required=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help=(
        "Package to search the objects in, defaults to '//'(the root package). "
        "'<package>...' searches that package and every package below it"
    ),
)
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, each_package: bool, fast_only: bool, package: str, keyword: str) -> None:
    """Search all available parts, assemblies and scenes with the given keyword, recursively unless told not to."""
    options = []
    runner = CliRunner()

    # Forwarded either way: each search is recursive unless told otherwise.
    options.append("--recursive" if recursive else "--no-recursive")
    if package:
        options.extend(["--package", package])
    if keyword:
        options.extend(["--keyword", keyword])
    # Only the searches that find assemblies take it: nothing else declares a
    # timeout, so nothing else has anything to leave out.
    assembly_options = (["--fast-only"] if fast_only else []) + options
    # Only the searches of shapes take it: a catalog searches for those.
    shape_options = ["--each-package"] if each_package else []

    catch_exceptions = False

    runner.invoke(search_packages, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(search_sketches, shape_options + options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(search_interfaces, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(search_parts, shape_options + options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(search_assemblies, shape_options + assembly_options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(search_scenes, shape_options + assembly_options, catch_exceptions=catch_exceptions, obj=cli_ctx)
