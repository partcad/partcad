#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from ..part import Part
from ..part_config import PartConfiguration
from ..part_config_manufacturing import METHOD_FORMING


class CamFormingTest(Test):
    def __init__(self) -> None:
        super().__init__("cam-forming")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Part):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_FORMING:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        # TODO(clairbee): Utilize the data provided in the config

        # TODO(clairbee): Improve and extend the below
        # OCP is imported lazily so this module stays off the 'import partcad'
        # OCP path. get_wrapped() returns a BREP envelope; decode it to the live
        # shape this in-process analysis needs.
        import os
        import sys

        sys.path.append(os.path.join(os.path.dirname(__file__), "..", "wrappers"))
        import ocp_serialize
        from OCP.ShapeAnalysis import ShapeAnalysis_FreeBoundsProperties

        envelope = await shape.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape")
        wrapped = ocp_serialize.decode_shape(envelope)
        fbp = ShapeAnalysis_FreeBoundsProperties(wrapped)
        fbp.Perform()
        if fbp.NbFreeBounds() != 0:
            return self.failed(shape, "The shape is not solid")

        return self.passed(shape)
