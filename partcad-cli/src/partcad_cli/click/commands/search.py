import os
import rich_click as click
from partcad_cli.click.loader import Loader


class SearchCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "search")


@click.command(cls=SearchCommands, help="Search parts, sketches or assemblies")
def cli() -> None:
    pass
