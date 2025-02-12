import os
import rich_click as click
from partcad_cli.click.loader import Loader


class ImportCommands(Loader):
    COMMANDS_FOLDER = os.path.join(Loader.COMMANDS_FOLDER, "import")


@click.command(cls=ImportCommands, help="Import a dependency, sketch, part, or assembly")
def cli() -> None:
    pass
