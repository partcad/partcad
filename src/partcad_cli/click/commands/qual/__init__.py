#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class QualCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "qual")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".qual"


@click.command(cls=QualCommands, help="Qualify an object: run its qualification tests, or declare one")
def cli() -> None:
    """The `pc qual` group: `pc qual test` runs the qualification tests, `pc qual add` declares one.

    A qualification test is of one of four subtypes -- basic, topology,
    simulation and other (see `partcad.qual`) -- and `pc qual test` runs all of
    them unless told which. `pc qual test` and `pc qual test --simulation` are the older spellings of
    `pc qual test` and `pc qual test --simulation`, and still work.
    """
