import os
import rich_click as click
from partcad_cli.click.loader import Loader


class ListCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "list")


@click.command(cls=ListCommands, help="- List components")
def cli():
    pass
