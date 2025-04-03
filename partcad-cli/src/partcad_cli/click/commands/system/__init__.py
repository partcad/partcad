#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from ...loader import Loader


class SystemCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "system")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".system"


@click.command(cls=SystemCommands, help="PartCAD system commands")
def cli() -> None:
    pass
