#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

import typing

from . import telemetry
from .plugin import Plugin
from .plugin_request_repository_caps import PluginRequestRepositoryCaps


@telemetry.instrument()
class Repository(Plugin):
    # Set by the factory to the coroutine that fetches a key from the backing
    # data source (in-process, a subprocess, or a remote endpoint).
    query_data = None
    # 'get_data' takes the key taken apart as well ('query'); see
    # 'ProjectExternalRepository._ask'.
    accepts_query = True

    def __init__(self, name: str, config: dict[str, typing.Any] = {}, target_project_name=None):
        super().__init__(name, config, target_project_name)

    async def get_caps(self) -> dict[str, typing.Any]:
        if not self.caps:
            self.caps = await self.query_caps(PluginRequestRepositoryCaps())
        return self.caps

    async def get_data(self, key: str, query: typing.Optional[dict] = None):
        """Return the value stored under 'key' in this repository.

        Keys address any data the package exposes uniformly - object
        enumerations, single objects, child packages, metadata - so that new
        kinds of data need no new methods here. See ProjectExternalRepository
        for the key conventions. 'query' is the key taken apart
        ('project_external_repository.query_of'), passed on to the plugin.
        """
        if self.query_data is None:
            return None
        response = await (self.query_data(key, query) if query is not None else self.query_data(key))
        if response is None:
            return None
        return response.get("result")
