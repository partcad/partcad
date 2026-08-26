#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class ConvertCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "adhoc/convert")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".adhoc.convert"


@click.command(cls=ConvertCommands, help="Ad-hoc convert parts or sketches to another format without updating their type.")
def cli() -> None:
    pass
