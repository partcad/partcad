#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from .. import SystemCommands


class IssueCommands(SystemCommands):
    COMMANDS_FOLDER_PATH = os.path.join(SystemCommands.COMMANDS_FOLDER_PATH, "issue")
    COMMANDS_PACKAGE_NAME = SystemCommands.COMMANDS_PACKAGE_NAME + ".issue"


@click.command(cls=IssueCommands, help="PartCAD's own issues on GitHub, for an agent that hit a defect in PartCAD")
def cli() -> None:
    pass


def read(path):
    """The text of a file, or of standard input for '-'."""
    if path is None:
        return None
    if path == "-":
        return click.get_text_stream("stdin").read()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def emit(data) -> None:
    import json

    click.echo(json.dumps(data, indent=2, default=str))


def workspace(cli_ctx) -> str:
    return getattr(cli_ctx, "path", None) or os.getcwd()
