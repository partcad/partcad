#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

from . import factory
from .project import Project


class PluginFactory(factory.Factory):
    name: str
    orig_name: str
    # project: Project
    # target_project: Project
    config: object

    def __init__(
        self,
        ctx,
        source_project: Project,
        target_project: Project,
        config: object,
    ):
        super().__init__()

        self.ctx = ctx
        self.project = source_project
        self.config = config

        self.target_project = target_project
        self.name = config["name"]
        self.orig_name = config["orig_name"]
