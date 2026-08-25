#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from .. import DaemonCommands


class SetCommands(DaemonCommands):
    COMMANDS_FOLDER_PATH = os.path.join(DaemonCommands.COMMANDS_FOLDER_PATH, "set")
    COMMANDS_PACKAGE_NAME = DaemonCommands.COMMANDS_PACKAGE_NAME + ".set"


@click.command(cls=SetCommands, help="Set settings on the PartCAD daemon")
def cli() -> None:
    pass
