#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from partcad_cli.click.loader import Loader


class RenderCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "adhoc/render")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".adhoc.render"


@click.command(
    cls=RenderCommands,
    help="Ad-hoc render parts or sketches to a 2D image without adding them to a package.",
)
def cli() -> None:
    pass
