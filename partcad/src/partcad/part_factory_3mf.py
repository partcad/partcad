#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import build123d as b3d

from .sentry import instrument
from .part_factory_file import PartFactoryFile
from . import logging as pc_logging


@instrument()
class PartFactory3mf(PartFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("Init3MF", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".3mf",
            )
            # Complement the config object here if necessary
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("3MF", part.project_name, part.name):
            shape = b3d.Mesher().read(self.path)[0].wrapped

            self.ctx.stats_parts_instantiated += 1

            return shape
