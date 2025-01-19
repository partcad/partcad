#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-09-30
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .assembly import Assembly
from .shape_factory import ShapeFactory


class AssemblyFactory(ShapeFactory):
    # TODO(clairbee): Make the next line work for assembly_factory_file only
    path: typing.Optional[str] = None
    assembly: Assembly

    def __init__(self, ctx, source_project, target_project, config, extension=""):
        super().__init__(ctx, source_project, config)
        self.name = config["name"]
        self.orig_name = config["orig_name"]

    def _create(self, config):
        self.assembly = Assembly(self.project.name, config)
        self.assembly.instantiate = lambda assembly_self: self.instantiate(assembly_self)
        self.assembly.info = lambda: self.info(self.assembly)
        self.assembly.with_ports = self.with_ports
        self.project.assemblies[self.name] = self.assembly

        self.post_create()

        self.ctx.stats_assemblies += 1

    def post_create(self):
        # This is a base class catch-all method
        pass
