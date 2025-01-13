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


class ShapeFactory(factory.Factory):
    fileFactory: FileFactory

    def __init__(self, ctx, project, config) -> None:
        super().__init__()

        self.ctx = ctx
        self.project = project
        self.config = config

        if "fileFrom" in config:
            self.fileFactory = factory.instantiate("file", config["fileFrom"], ctx, project, project, config)
        else:
            self.fileFactory = None

        self.with_ports = WithPorts(config["name"], project, config)

    def info(self, shape):
        """This is the default implementation of the get_info method for factories."""
        return shape.shape_info()
