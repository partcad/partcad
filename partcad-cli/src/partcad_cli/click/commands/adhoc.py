import os
import rich_click as click
from partcad_cli.click.loader import Loader


class AdhocCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "adhoc")


@click.command(cls=AdhocCommands, help="???")
def cli() -> None:
    pass
