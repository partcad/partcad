#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .shape_ai import ShapeWithAi
from . import sync_threads as pc_thread


class Sketch(ShapeWithAi):
    path: typing.Optional[str] = None

    def __init__(self, config: object = {}):
        super().__init__(config)

        self.kind = "sketches"

    async def get_shape(self):
        async with self.locked():
            if self.shape is None:
                self.shape = await pc_thread.run_async(self.instantiate, self)
            return self.shape

    def ref_inc(self):
        # Not applicable to sketches
        # TODO(clairbee): move reference counter from Shape to another class
        #                 that would be used by both Part and Assembly
        pass

    def clone(self):
        # Not applicable to sketches
        # TODO(clairbee): move clone() from Shape to another class
        #                 that would be used by both Part and Assembly
        pass
