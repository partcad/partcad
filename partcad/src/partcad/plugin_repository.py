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
    # Set by the factory to the coroutine that fetches a key from the backing
    # data source (in-process, a subprocess, or a remote endpoint).
    query_data = None

    def __init__(self, name: str, config: dict[str, typing.Any] = {}, target_project_name=None):
        super().__init__(name, config, target_project_name)

    async def get_caps(self) -> dict[str, typing.Any]:
        if not self.caps:
            self.caps = await self.query_caps(PluginRequestRepositoryCaps())
        return self.caps

    async def get_data(self, key: str):
        """Return the value stored under 'key' in this repository.

        Keys address any data the package exposes uniformly - object
        enumerations, single objects, child packages, metadata - so that new
        kinds of data need no new methods here. See ProjectExternalRepository
        for the key conventions.
        """
        if self.query_data is None:
            return None
        response = await self.query_data(key)
        if response is None:
            return None
        return response.get("result")
