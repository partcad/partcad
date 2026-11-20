#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click

from partcad_cli.click.loader import Loader


class ReqCommands(Loader):
    COMMANDS_FOLDER_PATH = os.path.join(Loader.COMMANDS_FOLDER_PATH, "req")
    COMMANDS_PACKAGE_NAME = Loader.COMMANDS_PACKAGE_NAME + ".req"

    # Another name a command answers to, and is not listed under.
    ALIASES = {"rm": "remove"}

    def get_command(self, ctx, name: str) -> click.Command:
        return super().get_command(ctx, self.ALIASES.get(name, name))


@click.command(
    cls=ReqCommands,
    help=(
        "What an object is required to be ('requirements:'): list it, add a requirement, remove one ('rm'), "
        "and test the model against it"
    ),
)
def cli() -> None:
    """The `pc req` group: `list`, `add <kind>`, `remove <kind>` (or `rm`), and `test`.

    A requirement is one of six kinds -- a feature, a port, an interface, a
    physical property, a match with another object, and a yes-or-no `has_`
    requirement -- and `add` and `remove` take the kind as a command of its own,
    since each is written differently (see 'partcad.requirements_edit'). All of
    it is daemon work: `requirements.check`, `requirements.add`,
    `requirements.remove`, and for `test`, `qual.run`.
    """
