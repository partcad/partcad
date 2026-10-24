#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging
from . import telemetry
from .file_source import SourceFile
from .sketch_factory import SketchFactory


@telemetry.instrument()
class SketchFactoryFile(SourceFile, SketchFactory):
    """A sketch read from one file, handed to its wrapper as it is (see 'partcad.file_source')."""

    SOURCE_NOUN = "sketch"
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
        self.locate_source(source_project, config, extension=extension, can_create=can_create)

    def post_create(self) -> None:
        if self.path:
            self.sketch.path = self.path
            self.sketch.cache_dependencies.append(self.path)
        else:
            pc_logging.warning(f"Sketch path is not set: {self.sketch.name}")
        super().post_create()
