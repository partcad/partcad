#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class RevisionsCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "revisions")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".revisions"


@click.command(
    cls=RevisionsCommands,
    help=(
        "The revisions of a package in its git repository: list them, show what changed in an object (or the "
        "package) since one of them, and what the package used and was used by at one"
    ),
)
def cli() -> None:
    """The `pc revisions` group: `list`, `diff`, `uses` and `used-by`.

    The IDE's Operations > Revisions tab on the command line, asking the daemon
    what the tab asks it (`revisions.list`, `revisions.compare`,
    `revisions.uses`, `revisions.used_by`). A revision is loaded into the
    daemon's context as `<package>@<sha>` and stays there, as it does for the tab
    (see "A package at a revision" in docs/source/config_package.rst).
    """
