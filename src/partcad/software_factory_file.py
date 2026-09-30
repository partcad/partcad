#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os

from . import factory
from . import logging as pc_logging
from . import telemetry
from .file_factory import FileFactory
from .software_factory import SoftwareFactory


@telemetry.instrument()
class SoftwareFactoryFile(SoftwareFactory):
    """A software object backed by a file.

    Every software type is, so this is the base of all of them rather than one
    branch among several: what a later type adds is the procedure its file goes
    through (see 'software.DEFAULT_TYPE'), not another way of finding the file.

    Where the file comes from is declared exactly as it is for a file-backed
    part or sketch, and for the same reason - a package author should not have
    to learn a second spelling of the same idea:

      * 'path' names it in the package, defaulting to the object's own name plus
        the type's extension.
      * 'fileFrom' (with 'fileUrl') pulls it from elsewhere, lazily: nothing is
        downloaded until the object is used, and 'path' is then where the
        downloaded copy is kept.

    A 'path' with no 'fileFrom' must exist while the package loads, the same way
    a part's file must: it is content of this repository, and a missing one is a
    broken declaration rather than something to discover later. A file that is
    pulled in is not checked here at all - it is not expected to be on disk yet.
    """

    extension: str
    fileFactory: FileFactory = None

    def __init__(self, ctx, source_project, target_project, config, extension="", can_create=False):
        super().__init__(ctx, source_project, target_project, config)
        self.extension = extension

        if "fileFrom" in config:
            self.fileFactory = factory.instantiate(
                "file", config["fileFrom"], ctx, source_project, target_project, config
            )
        else:
            self.fileFactory = None

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
            exists = os.path.exists(self.path)
            if not can_create and not exists:
                raise Exception("ERROR: The software path (%s) must exist" % self.path)
            if exists and not os.path.isfile(self.path):
                raise Exception("ERROR: The software path (%s) must be a file" % self.path)

    async def prepare_async(self, software) -> None:
        """Fetch what 'fileFrom' points at, unless the file is already there."""
        if self.fileFactory is not None and not os.path.exists(software.path):
            with pc_logging.Action("File", self.target_project.name, software.name):
                await self.fileFactory.download(software.path)
