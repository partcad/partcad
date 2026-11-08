#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc system locale`: where the user is, as this machine's user configuration says it.

The country, language and currency PartCAD works with, the user's address, the
location a store's nearest shop is chosen by, whether PartCAD may ask this
machine's location service for that location, and what the user said they use
PartCAD for. All of it is the user's, in their own `~/.partcad/config.yaml`,
which is why every command here runs in this process and none asks the daemon:
a daemon can be on another machine, which is neither where the user is nor
where their file is (see "Command boundary" in src/partcad_cli/AGENTS.md).

The PartCAD IDE and the editor extension ask the same questions the first time
they start, and answer them by running these commands - `show --json` to know
whether they were asked already, `set` to write the answers, `locate` and
`settings` for the location service.
"""

import os

import rich_click as click

from .. import SystemCommands


class LocaleCommands(SystemCommands):
    COMMANDS_FOLDER_PATH = os.path.join(SystemCommands.COMMANDS_FOLDER_PATH, "locale")
    COMMANDS_PACKAGE_NAME = SystemCommands.COMMANDS_PACKAGE_NAME + ".locale"


@click.command(
    cls=LocaleCommands,
    help="Where you are: country, language, currency, address and location, for ordering and handling manufacturing",
)
def cli() -> None:
    pass
