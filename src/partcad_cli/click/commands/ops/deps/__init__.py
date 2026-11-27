#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from .. import OpsCommands


class DepsCommands(OpsCommands):
    COMMANDS_FOLDER_PATH = os.path.join(OpsCommands.COMMANDS_FOLDER_PATH, "deps")
    COMMANDS_PACKAGE_NAME = OpsCommands.COMMANDS_PACKAGE_NAME + ".deps"


@click.command(
    cls=DepsCommands,
    help=(
        "What a package depends on -- list, add, remove and update its dependencies -- or what an object names "
        "and places"
    ),
)
def cli() -> None:
    """The `pc ops deps` group: `list`, `add`, `remove` and `update`.

    The IDE's Operations > Dependencies tab on the command line (`ops.deps.*`).
    `add` is what `pc add dep` was and `update` what `pc update` was; both old
    names still work.
    """
