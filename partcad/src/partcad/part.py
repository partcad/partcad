#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .shape import Shape
from .sync_threads import threadpool_manager
from . import telemetry


@telemetry.instrument(exclude=["ref_inc"])
class Part(Shape):
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}, shape=None):
        super().__init__(project_name, config)

        self.kind = "part"
        self._wrapped = shape

        self.url = None
        if "url" in config:
            self.url = config["url"]

    async def get_shape(self, ctx):
        return await threadpool_manager.run_async(self.instantiate, self)
