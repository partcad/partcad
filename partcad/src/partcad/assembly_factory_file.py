#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#


import os

from . import telemetry
from .assembly_factory import AssemblyFactory
from . import logging as pc_logging


@telemetry.instrument()
class AssemblyFactoryFile(AssemblyFactory):
    def __init__(self, ctx, source_project, target_project, config, extension=""):
        super().__init__(ctx, source_project, target_project, config)

        if "path" in config:
            self.path = config["path"]
        else:
            self.path = self.orig_name + extension

        if not os.path.isdir(source_project.config_dir):
            raise Exception(
                "ERROR: The project config directory must be a directory, found: '%s'" % source_project.config_dir
            )
        self.path = os.path.join(source_project.config_dir, self.path)
        if not os.path.exists(self.path):
            raise Exception("ERROR: The assembly path must exist")

    def post_create(self) -> None:
        if self.path:
            self.assembly.path = self.path
            self.assembly.cache_dependencies.append(self.path)
        else:
            pc_logging.warning(f"Assembly path is not set: {self.assembly.name}")
        super().post_create()

    async def download_file_async(self, assembly) -> None:
        """Fetch what 'fileFrom' points at, unless the file is already there."""
        if not self.fileFactory is None and not os.path.exists(assembly.path):
            with pc_logging.Action("File", self.target_project.name, assembly.name):
                await self.fileFactory.download(assembly.path)

    async def prepare_async(self, assembly) -> None:
        """Download the source file without building the assembly.

        The cache key hashes the file's content, so it only means anything once
        the file is on disk. 'pc install' calls this for every object, which is
        why the first build after an install is a cache hit and not a miss.
        """
        await self.download_file_async(assembly)

    async def instantiate(self, assembly):
        await self.download_file_async(assembly)
