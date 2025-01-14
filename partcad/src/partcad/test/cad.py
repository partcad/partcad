#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from .. import logging as pc_logging


class CadTest(Test):
    def __init__(self) -> None:
        super().__init__("cad")

    async def test(self, ctx, shape):
        wrapped = await shape.get_wrapped()
        if wrapped is None:
            pc_logging.error("Failed to get the shape of %s:%s" % (shape.package, shape.name))
            return

        pc_logging.debug(f"Passed test: {self.name}: {shape.project_name}:{shape.name}")
