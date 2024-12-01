import os
import rich_click as click
from partcad_cli.click.loader import Loader


class AddCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "add")


@click.command(cls=AddCommands, help="- Import a package, add a part or assembly.")
def cli():
    pass
