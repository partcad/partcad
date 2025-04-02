#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click

from .. import SetCommands


class TelemetryCommands(SetCommands):
    COMMANDS_FOLDER_PATH = os.path.join(SetCommands.COMMANDS_FOLDER_PATH, "telemetry")
    COMMANDS_PACKAGE_NAME = SetCommands.COMMANDS_PACKAGE_NAME + ".telemetry"


@click.command(cls=TelemetryCommands, help="System-wide telemetry settings")
def cli() -> None:
    pass
