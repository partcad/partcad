#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ide`: putting an object in front of a person.

Two ways, and they differ in where the window is. `pc ide view` shows an object in
the PartCAD Viewer -- the IDE's own window, fed by the daemon that builds the
shape. `pc ide open` opens a file in a third-party application on the machine of
whoever ran the command, waits for it to close, and brings back what was edited
in it. Neither one produces anything a package keeps: that is `export`,
`render` and the rest.
"""

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class IdeCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "ide")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".ide"


@click.command(cls=IdeCommands, help="Show an object: in the PartCAD Viewer, or in another application")
def cli() -> None:
    pass


def deprecated_alias(command: click.Command, old: str, replacement: str) -> click.Command:
    """``command`` under its old name: hidden from help, saying on stderr what it is called now.

    Kept because something other than a person types these. A VS Code extension
    older than the rename runs `pc open --json` and reads stdout -- which is why
    the note goes to stderr, where it leaves that JSON alone.
    """

    def callback(**kwargs):
        click.echo("'%s' is deprecated: use '%s'." % (old, replacement), err=True)
        return click.get_current_context().invoke(command, **kwargs)

    return type(command)(
        name=command.name,
        params=command.params,
        callback=callback,
        help="Deprecated: '%s'." % replacement,
        hidden=True,
        deprecated=False,
    )
