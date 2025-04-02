#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class ConvertCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "convert")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".convert"


@click.command(cls=ConvertCommands, help="Convert parts or sketches to another format and update their type.")
@click.option(
    "-P",
    "--package",
    help="Package to add the object to",
    type=str,
    default=".",
)
def cli(package: str) -> None:
    pass
