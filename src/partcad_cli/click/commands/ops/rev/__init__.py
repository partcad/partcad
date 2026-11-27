#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from .. import OpsCommands


class RevCommands(OpsCommands):
    COMMANDS_FOLDER_PATH = os.path.join(OpsCommands.COMMANDS_FOLDER_PATH, "rev")
    COMMANDS_PACKAGE_NAME = OpsCommands.COMMANDS_PACKAGE_NAME + ".rev"


@click.command(
    cls=RevCommands,
    help=(
        "The revisions of a package or an object in its git repository: list them, compare two states, say what "
        "is staged, stage it, and make a new revision of it"
    ),
)
def cli() -> None:
    """The `pc ops rev` group: `list`, `diff`, `status`, `stage` and `new`.

    The IDE's Operations > Revisions tab on the command line (`ops.rev.*`). A
    state is a revision -- a commit id, a tag, a branch, `HEAD~1` -- or
    `STAGED` (the git index) or `WORKTREE` (the files on disk); a revision is
    loaded into the daemon's context as `<package>@<sha>` and stays there, as it
    does for the tab (see "A package at a revision" in
    docs/source/config_package.rst).
    """
