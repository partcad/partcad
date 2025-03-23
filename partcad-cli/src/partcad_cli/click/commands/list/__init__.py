#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class ListCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "list")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".list"


@click.command(cls=ListCommands, help="List components")
def cli() -> None:
    pass
