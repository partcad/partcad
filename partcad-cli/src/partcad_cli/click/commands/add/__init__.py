#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class AddCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "add")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".add"


@click.command(cls=AddCommands, help="Add a dependency, sketch, part, or assembly")
@click.option(
    "-P",
    "--package",
    help="Package to add the object to",
    type=str,
    default=".",
)
def cli(package: str) -> None:
    pass
