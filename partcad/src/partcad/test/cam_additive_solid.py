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
from ..part_config_manufacturing import METHOD_ADDITIVE

from OCP.ShapeAnalysis import ShapeAnalysis_FreeBoundsProperties


class CamAdditiveSolidTest(Test):
    def __init__(self) -> None:
        super().__init__("cam-additive")

    async def test(self, ctx, shape):
        if not isinstance(shape, Part):
            # Not applicable
            return

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_ADDITIVE:
            # Not applicable
            return

        # TODO(clairbee): Utilize the data provided in the config

        # TODO(clairbee): Improve and extend the below
        wrapped = await shape.get_wrapped()
        fbp = ShapeAnalysis_FreeBoundsProperties(wrapped)
        fbp.Perform()
        if fbp.NbFreeBounds() != 0:
            pc_logging.error("The shape is not solid")
            return

        pc_logging.debug(f"Passed test: {self.name}: {shape.project_name}:{shape.name}")
