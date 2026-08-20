#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#

from . import factory

from .file_factory import FileFactory
from .port import WithPorts
from . import telemetry


@telemetry.instrument()
class ShapeFactory(factory.Factory):
    fileFactory: FileFactory

    def __init__(self, ctx, project, config) -> None:
        super().__init__()

        self.ctx = ctx
        self.project = project
        self.config = config

        if "manufacturable" not in config:
            config["manufacturable"] = project.is_manufacturable

        if "fileFrom" in config:
            self.fileFactory = factory.instantiate("file", config["fileFrom"], ctx, project, project, config)
        else:
            self.fileFactory = None

        self.with_ports = WithPorts(config["name"], project, config)

    async def prepare_async(self, shape) -> None:
        """Fetch what this shape needs before its cache key can be computed.

        Overridden by the factories that have something to fetch: the file
        factories download whatever 'fileFrom' points at, and the factories
        that reference another object (alias, enrich, compound, assy) resolve
        it, which loads the package holding it. The default is to do nothing -
        a shape defined entirely by its own package has nothing to fetch.
        """
        return None

    def info(self, shape):
        """This is the default implementation of the get_info method for factories."""
        info: dict = shape.shape_info(self.ctx)
        if "url" in self.project.config_obj and self.project.config_obj["url"] is not None:
            info["Url"] = self.project.config_obj["url"]
        if "importUrl" in self.project.config_obj and self.project.config_obj["importUrl"] is not None:
            info["ImportUrl"] = self.project.config_obj["importUrl"]
        info["Path"] = self.project.name
        return info
