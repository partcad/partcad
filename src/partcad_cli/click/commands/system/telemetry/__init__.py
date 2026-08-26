#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os
import rich_click as click


from .. import SystemCommands


class TelemetryCommands(SystemCommands):
    COMMANDS_FOLDER_PATH = os.path.join(SystemCommands.COMMANDS_FOLDER_PATH, "telemetry")
    COMMANDS_PACKAGE_NAME = SystemCommands.COMMANDS_PACKAGE_NAME + ".telemetry"


@click.command(cls=TelemetryCommands, help="Telemetry commands")
def cli() -> None:
    pass
