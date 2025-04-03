#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .plugin_factory_enrich import PluginFactoryEnrich
from . import telemetry


@telemetry.instrument()
class PluginFactoryRepositoryEnrich(PluginFactoryEnrich):
    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)

    def init_source_by_config(self, augmented_config):
        self.project.init_repository_by_config(
            augmented_config,
            self.project,
        )

    def get_source_config(self, source_plugin_name: str, source_project=None):
        if source_project is None:
            source_project = self.project
        source_project.get_repository_config(source_plugin_name)
