#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-22
#
# Licensed under Apache License, Version 2.0.
#

import os

from .part_factory import PartFactory
from . import logging as pc_logging


class PartFactoryFile(PartFactory):
    extension: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config,
        extension="",
        can_create=False,
    ):
        super().__init__(ctx, source_project, target_project, config)
        self.extension = extension

        if "path" in config:
            self.path = config["path"]
        else:
            self.path = self.orig_name + extension

        if not os.path.isdir(source_project.config_dir):
            raise Exception(
                "ERROR: The project config directory must be a directory, found: '%s'" % source_project.config_dir
            )
        self.path = os.path.join(source_project.config_dir, self.path)

        if self.fileFactory is None:
            # If the user did not supply a way to download the file,
            # check if the file exists
            exists = os.path.exists(self.path)
            if not can_create and not exists:
                raise Exception("ERROR: The part path (%s) must exist" % self.path)
            if exists and not os.path.isfile(self.path):
                raise Exception("ERROR: The part path (%s) must be a file" % self.path)

    def post_create(self):
        if self.path:
            self.part.path = self.path
            self.part.cache_dependencies.append(self.path)
        else:
            pc_logging.warning(f"Part path is not set: {self.part.name}")
        return super().post_create()

    async def instantiate(self, part):
        if not self.fileFactory is None and not os.path.exists(part.path):
            with pc_logging.Action("File", self.target_project.name, part.name):
                await self.fileFactory.download(part.path)
