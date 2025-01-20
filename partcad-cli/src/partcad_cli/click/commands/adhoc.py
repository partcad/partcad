import os
import rich_click as click
from partcad_cli.click.loader import Loader


class AdhocCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "adhoc")


@click.command(cls=AdhocCommands, help="Run ad-hoc commands for on-the-fly operations without requiring a full configuration or setup.")
def cli() -> None:
    pass
