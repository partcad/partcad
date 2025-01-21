#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import os

from .provider_factory import ProviderFactory
from .file_factory import FileFactory
from . import factory
from . import logging as pc_logging
from .sentry import instrument


@instrument()
class ProviderFactoryFile(ProviderFactory):
    path: str = None
    extension: str
    fileFactory: FileFactory = None

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

        if "fileFrom" in config:
            self.fileFactory = factory.instantiate("file", config["fileFrom"], ctx, self.project, config)

        if "path" in config:
            self.path = config["path"]
        else:
            self.path = self.orig_name + extension

        if not os.path.isdir(source_project.config_dir):
            raise Exception(
                "ERROR: The project config directory must be a directory, found: '%s'" % source_project.config_dir
            )
        self.path = os.path.join(source_project.config_dir, self.path)

        # self.filePath is what file to download if necessary
        if "filePath" in config:
            self.filePath = os.path.join(source_project.config_dir, config["filePath"])
        else:
            self.filePath = self.path

        if self.fileFactory is None or self.filePath != self.path:
            # If the user did not supply a way to download the script,
            # check if the script exists
            exists = os.path.exists(self.path)
            if not can_create and not exists:
                raise Exception("ERROR: The provider path (%s) must exist" % self.path)
            if exists and not os.path.isfile(self.path):
                raise Exception("ERROR: The provider path (%s) must be a file" % self.path)

    async def prepare_script(self, provider) -> bool:
        if not self.fileFactory is None and not os.path.exists(self.filePath):
            with pc_logging.Action("File", self.target_project.name, provider.name):
                await self.fileFactory.download(self.filePath)

        # Check if the data file is present
        if not os.path.exists(self.filePath) or os.path.getsize(self.filePath) == 0:
            pc_logging.error("Provider data file is empty or does not exist: %s" % self.filePath)
            return False

        # Check if the script file is present
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            pc_logging.error("Provider script is empty or does not exist: %s" % self.path)
            return False

        return True
