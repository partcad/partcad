#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class GenerateCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "adhoc/generate")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".adhoc.generate"


@click.command(
    cls=GenerateCommands,
    help="Ad-hoc generate AI-powered features without creating packages.",
)
def cli() -> None:
    pass
