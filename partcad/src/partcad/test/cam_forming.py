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
from ..part import Part
from ..part_config import PartConfiguration
from ..part_config_manufacturing import METHOD_FORMING

from OCP.ShapeAnalysis import ShapeAnalysis_FreeBoundsProperties


class CamFormingTest(Test):
    def __init__(self) -> None:
        super().__init__("cam-forming")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Part):
            self.debug(shape, "Not applicable")
            return True

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_FORMING:
            self.debug(shape, "Not applicable")
            return True

        # TODO(clairbee): Utilize the data provided in the config

        # TODO(clairbee): Improve and extend the below
        wrapped = await shape.get_wrapped()
        fbp = ShapeAnalysis_FreeBoundsProperties(wrapped)
        fbp.Perform()
        if fbp.NbFreeBounds() != 0:
            self.failed(shape, "The shape is not solid")
            return False

        self.passed(shape)
        return True
