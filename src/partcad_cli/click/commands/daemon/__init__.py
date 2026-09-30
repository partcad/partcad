#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class DaemonCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "daemon")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".daemon"


@click.command(cls=DaemonCommands, help="Manage the PartCAD background daemon")
def cli() -> None:
    pass
