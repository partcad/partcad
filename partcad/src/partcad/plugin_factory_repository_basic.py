#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_request_repository_list import PluginRequestRepositoryList
from .plugin_request_repository_get import PluginRequestRepositoryGet
from .plugin_request_repository_search import PluginRequestRepositorySearch
from .plugin_factory_repository import PluginFactoryRepository
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
class PluginFactoryRepositoryBasic(PluginFactoryRepository):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitRepBasic", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )
            # Complement the config object here if necessary

            self._create(config)

    def _create(self, config):
        super()._create(config)
        self.plugin.query_list_deps = lambda x: {"result": []}
        self.plugin.query_list = self.query_list
        self.plugin.query_get = self.query_get
        self.plugin.query_search = self.query_search

    async def query_list(self, request: PluginRequestRepositoryList):
        return await self.query_script(self.plugin, "list", request.compose())

    async def query_get(self, request: PluginRequestRepositoryGet):
        return await self.query_script(self.plugin, "get", request.compose())

    async def query_search(self, request: PluginRequestRepositorySearch):
        # TODO(clairbee): Query "list" instead and search through the results
        return await self.query_script(self.plugin, "search", request.compose())
