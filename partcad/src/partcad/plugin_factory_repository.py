#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_factory_python import PluginFactoryPython
from .plugin_repository import Repository
from . import telemetry


@telemetry.instrument()
class PluginFactoryRepository(PluginFactoryPython):
    plugin: Repository

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config: object,
    ):
        super().__init__(ctx, source_project, target_project, config)

    def _create_repository(self, config: object) -> Repository:
        plugin = Repository(
            f"{self.target_project.name}:{self.name}",
            config,
            target_project_name=self.target_project.name,
        )
        # TODO(clairbee): Make the next line work for plugin_factory_file only
        plugin.info = lambda: self.info(plugin)
        return plugin

    def _create(self, config: object):
        self.plugin = self._create_repository(config)
        if hasattr(self, "path"):
            self.plugin.path = self.path

        self.target_project.repositories[self.name] = self.plugin
        self.ctx.stats_plugins += 1
        self.ctx.stats_repositories += 1
