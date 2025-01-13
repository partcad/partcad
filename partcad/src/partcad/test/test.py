#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from abc import ABC, abstractmethod

from .. import logging as pc_logging


class Test(ABC):
    def __init__(self, name):
        self.name = name

    @abstractmethod
    async def test(self, ctx, shape):
        raise NotImplementedError("This method should be overridden")

    async def test_log_wrapper(self, ctx, shape):
        with pc_logging.Action("Test", shape.project_name, shape.name, self.name):
            await self.test(ctx, shape)
