#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import os

from .sketch_factory import SketchFactory
from . import logging as pc_logging
from . import telemetry


# TODO(clairbee): create ShapeFactoryFile to be reused
#                 by corresponding Sketch, Part and Assembly factories
@telemetry.instrument()
class SketchFactoryFile(SketchFactory):
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
                raise Exception("ERROR: The sketch path (%s) must exist" % self.path)
            if exists and not os.path.isfile(self.path):
                raise Exception("ERROR: The sketch path (%s) must be a file" % self.path)

    def post_create(self) -> None:
        if self.path:
            self.sketch.path = self.path
            self.sketch.cache_dependencies.append(self.path)
        else:
            pc_logging.warning(f"Sketch path is not set: {self.sketch.name}")
        super().post_create()

    async def instantiate(self, sketch):
        if not self.fileFactory is None and not os.path.exists(sketch.path):
            with pc_logging.Action("File", self.target_project.name, sketch.name):
                await self.fileFactory.download(sketch.path)
