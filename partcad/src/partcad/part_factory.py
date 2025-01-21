#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .part import Part
from .shape_factory import ShapeFactory
from .sentry import instrument


@instrument()
class PartFactory(ShapeFactory):
    # TODO(clairbee): Make the next line work for part_factory_file only
    path: typing.Optional[str] = None
    part: Part
    name: str
    orig_name: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config: object,
    ):
        super().__init__(ctx, source_project, config)
        self.target_project = target_project
        self.name = config["name"]
        self.orig_name = config["orig_name"]

    def _create_part(self, config: object) -> Part:
        part = Part(self.target_project.name, config)
        part.instantiate = lambda part_self: self.instantiate(part_self)
        part.info = lambda: self.info(part)
        part.with_ports = self.with_ports
        return part

    def _create(self, config: object) -> None:
        self.part = self._create_part(config)
        self.target_project.parts[self.name] = self.part

        self.post_create()

        self.ctx.stats_parts += 1

    def post_create(self) -> None:
        # This is a base class catch-all method
        pass
