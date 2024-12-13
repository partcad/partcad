import os
import rich_click as click
from partcad_cli.click.loader import Loader
from click.testing import CliRunner

from partcad_cli.click.commands.list.assemblies import cli as list_assemblies
from partcad_cli.click.commands.list.interfaces import cli as list_interfaces
from partcad_cli.click.commands.list.mates import cli as list_mates
from partcad_cli.click.commands.list.packages import cli as list_packages
from partcad_cli.click.commands.list.parts import cli as list_parts
from partcad_cli.click.commands.list.sketches import cli as list_sketches


@click.command(help="List all available parts, assemblies and scenes")
# TODO: @alexanderilyin: Add all the same options
def cli():
    runner = CliRunner()
    runner.invoke(list_assemblies, ["--recursive"])
    runner.invoke(list_interfaces, ["--recursive"])
    runner.invoke(list_mates, ["--recursive"])
    runner.invoke(list_packages, ["--recursive"])
    runner.invoke(list_parts, ["--recursive"])
    runner.invoke(list_sketches, ["--recursive"])
