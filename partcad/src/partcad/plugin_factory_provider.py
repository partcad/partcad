#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_factory_python import PluginFactoryPython
from .plugin_provider import Provider
from . import telemetry


@telemetry.instrument()
class PluginFactoryProvider(PluginFactoryPython):
    plugin: Provider

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config: object,
    ):
        super().__init__(ctx, source_project, target_project, config)

    def _create_provider(self, config: object) -> Provider:
        plugin = Provider(
            f"{self.target_project.name}:{self.name}",
            config,
            target_project_name=self.target_project.name,
        )
        # TODO(clairbee): Make the next line work for provider_factory_file only
        plugin.info = lambda: self.info(plugin)
        return plugin

    def _create(self, config: object):
        self.plugin = self._create_provider(config)
        if hasattr(self, "path"):
            self.plugin.path = self.path

        self.target_project.providers[self.name] = self.plugin
        self.ctx.stats_plugins += 1
        self.ctx.stats_providers += 1
