#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class ReqAddCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "req", "add")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".req.add"


@click.command(
    cls=ReqAddCommands,
    help="Add a requirement to an object, in its package's partcad.yaml: one command per kind of requirement",
)
def cli() -> None:
    pass
