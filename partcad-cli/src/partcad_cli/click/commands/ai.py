import os
import rich_click as click
from partcad_cli.click.loader import Loader


class AiCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "ai")


@click.command(cls=AiCommands, help="- Import a package, add a part or assembly.")
def cli():
    pass
