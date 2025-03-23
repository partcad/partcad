#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class SearchCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "search")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".search"


@click.command(cls=SearchCommands, help="Search parts, sketches or assemblies")
def cli() -> None:
    pass
