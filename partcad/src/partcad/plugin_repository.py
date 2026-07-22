#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .plugin_request_repository_caps import PluginRequestRepositoryCaps
from .plugin import Plugin
from . import telemetry


@telemetry.instrument()
class Repository(Plugin):
    def __init__(self, name: str, config: dict[str, typing.Any] = {}, target_project_name=None):
        super().__init__(name, config, target_project_name)

    async def get_caps(self) -> dict[str, typing.Any]:
        if not self.caps:
            self.caps = await self.query_caps(PluginRequestRepositoryCaps())
        return self.caps
