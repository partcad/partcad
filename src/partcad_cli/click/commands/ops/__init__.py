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
        "Operations of a package or of one object of it: its revisions (rev), what it depends on (deps), what "
        "uses it (used-by), and what a change reaches (impact), at any state of its repository -- a revision, "
        "STAGED or WORKTREE"
    ),
)
def cli() -> None:
    """The `pc ops` group: `summary`, `rev`, `deps`, `used-by` and `impact`.

    The IDE's Operations tabs on the command line, each asking the daemon what
    the tab asks it (`ops.*`; see `partcad_utils.ops_views`, which says which
    kinds of subject each applies to). The subject is the only argument of
    every reading command: an object, or a package -- `-P`'s, this one, or one
    written as a package path.
    """
