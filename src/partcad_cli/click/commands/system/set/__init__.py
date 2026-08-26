#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click


from .. import SystemCommands


class SetCommands(SystemCommands):
    COMMANDS_FOLDER_PATH = os.path.join(SystemCommands.COMMANDS_FOLDER_PATH, "set")
    COMMANDS_PACKAGE_NAME = SystemCommands.COMMANDS_PACKAGE_NAME + ".set"


@click.command(cls=SetCommands, help="Set system-wide settings")
def cli() -> None:
    pass
