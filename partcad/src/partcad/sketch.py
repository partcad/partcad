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
from .sync_threads import threadpool_manager


class Sketch(ShapeWithAi):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}) -> None:
        super().__init__(project_name, config)

        self.kind = "sketch"

    async def get_shape(self, ctx):
        return await threadpool_manager.run_async(self.instantiate, self)
