#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class OpsCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "ops")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".ops"


@click.command(
    cls=OpsCommands,
    help=(
        "Operations: what has become of an object since it was written -- the revisions of its package (rev) "
        "and what uses it (used-by)"
    ),
)
def cli() -> None:
    """The `pc ops` group: `rev` and `used-by`.

    The IDE's Operations tabs on the command line: `pc ops rev` is its
    Revisions tab and `pc ops used-by` its Used By tab, each asking the daemon
    what the tab asks it. `rev` is a group of its own so that what is done with
    a revision (`pc ops rev list|diff|uses|used-by`) has room to grow beside it.
    """
