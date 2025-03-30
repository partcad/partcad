#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#

from __future__ import annotations
from typing import TYPE_CHECKING

from . import factory

from .file_factory import FileFactory
from .port import WithPorts

if TYPE_CHECKING:
    from partcad.context import Context
    from partcad.project import Project


class ShapeFactory(factory.Factory):
    fileFactory: FileFactory

    def __init__(self, ctx: Context, project: Project, config) -> None:
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

    def info(self, shape):
        """This is the default implementation of the get_info method for factories."""
        info: dict = shape.shape_info(self.ctx)
        if "url" in self.project.config_obj and self.project.config_obj["url"] is not None:
            info["Url"] = self.project.config_obj["url"]
        if "importUrl" in self.project.config_obj and self.project.config_obj["importUrl"] is not None:
            info["ImportUrl"] = self.project.config_obj["importUrl"]
        info["Path"] = self.project.name
        return info
