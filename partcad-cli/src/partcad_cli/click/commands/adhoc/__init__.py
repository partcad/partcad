#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class AdhocCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "adhoc")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".adhoc"


@click.command(
    cls=AdhocCommands, help="Ad-hoc commands for on-the-fly operations without requiring configuration or setup."
)
def cli() -> None:
    pass
