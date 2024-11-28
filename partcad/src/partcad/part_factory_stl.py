#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import build123d as b3d

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging


class PartFactoryStl(PartFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTL", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".stl",
            )
            # Complement the config object here if necessary
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("STL", part.project_name, part.name):
            try:
                shape = b3d.Mesher().read(self.path)[0].wrapped
            except:
                # First, make sure it's not the known problem in Mesher
                shape = b3d.import_stl(self.path)

            self.ctx.stats_parts_instantiated += 1

            return shape
