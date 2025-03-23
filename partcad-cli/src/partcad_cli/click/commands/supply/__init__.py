#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class SupplyCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "supply")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".supply"


@click.command(cls=SupplyCommands, help="Supply Chain commands")
def cli() -> None:
    pass
