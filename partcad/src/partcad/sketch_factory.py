#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .sketch import Sketch
from .shape_factory import ShapeFactory


class SketchFactory(ShapeFactory):
    # TODO(clairbee): Make the next line work for part_factory_file only
    path: typing.Optional[str] = None
    sketch: Sketch
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

    def _create_sketch(self, config: object) -> Sketch:
        sketch = Sketch(self.target_project.name, config)
        # TODO(clairbee): Make the next line work for sketch_factory_file only
        sketch.instantiate = lambda sketch_self: self.instantiate(sketch_self)
        sketch.info = lambda: self.info(sketch)
        sketch.with_ports = self.with_ports
        return sketch

    def _create(self, config: object):
        self.sketch = self._create_sketch(config)
        self.target_project.sketches[self.name] = self.sketch

        self.post_create()

        self.ctx.stats_sketches += 1

    def post_create(self):
        # This is a base class catch-all method
        pass
