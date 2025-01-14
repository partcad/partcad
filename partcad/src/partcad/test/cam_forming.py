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
    def __init__(self):
        super().__init__("cam-forming")

    async def test(self, ctx, shape):
        if not isinstance(shape, Part):
            # Not applicable
            return

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_FORMING:
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

        pc_logging.debug("Passed test: %s: %s:%s" % (self.name, shape.project_name, shape.name))
