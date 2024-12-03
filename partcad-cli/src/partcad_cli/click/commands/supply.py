import os
import rich_click as click
from partcad_cli.click.loader import Loader


class SupplyCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "supply")


@click.command(cls=SupplyCommands, help="- Supplier related commands")
def cli():
    pass
