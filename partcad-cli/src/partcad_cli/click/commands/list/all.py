import rich_click as click
from click.testing import CliRunner

from partcad_cli.click.commands.list.assemblies import cli as list_assemblies
from partcad_cli.click.commands.list.interfaces import cli as list_interfaces
from partcad_cli.click.commands.list.mates import cli as list_mates
from partcad_cli.click.commands.list.packages import cli as list_packages
from partcad_cli.click.commands.list.parts import cli as list_parts
from partcad_cli.click.commands.list.sketches import cli as list_sketches


@click.option(
    "-u",
    "used_by",
    help="Only process objects used by the given assembly or scene.",
    type=str,
    required=False,
)
@click.option(
    "-r",
    "recursive",
    is_flag=True,
    help="Recursively process all imported packages",
)
@click.argument("package", type=str, required=False)
@click.command(help="List all available parts, assemblies and scenes")
def cli(used_by, recursive) -> None:
    """List all available parts, assemblies and scenes recursively."""
    runner = CliRunner()
    options = []

    if recursive:
        options.append("--recursive")
    if used_by:
        options.append("--used_by")

    runner.invoke(list_assemblies, options)
    runner.invoke(list_interfaces, options)
    runner.invoke(list_mates, options)
    runner.invoke(list_packages, options)
    runner.invoke(list_parts, options)
    runner.invoke(list_sketches, options)
