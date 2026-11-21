#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class CommentCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "comment")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".comment"


@click.command(cls=CommentCommands, help="Read and write the comments on an object or on a package")
def cli() -> None:
    """The `pc comment` group: `pc comment list` reads the threads of comments, `pc comment add` writes one.

    A package and every object it declares may carry `comments:`, a list of
    threads, each an ordered list of comments (see `partcad_utils.comments`).
    Both are daemon work (`comment.list`, `comment.add`): the second writes a
    declaration the warm context then has to read again, as `pc add` does.
    """
