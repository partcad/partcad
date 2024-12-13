import os
import rich_click as click
from partcad_cli.click.loader import Loader
from click.testing import CliRunner

# from partcad_cli.click.commands.list.assemblies import cli as list_assemblies


class ListCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "list")


@click.command(cls=ListCommands, help="List components")
# @click.option("-a", "--all", is_flag=True, help="List all available parts, assemblies and scenes")
# @click.pass_obj
def cli():  # ctx, all
    pass
    # if all:
    #     runner = CliRunner()
    #     runner.invoke(list_assemblies, ["--recursive", "--used_by", "some_assembly", "some_package"])
