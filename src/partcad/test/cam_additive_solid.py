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
from ..part_config_manufacturing import METHOD_ADDITIVE


class CamAdditiveSolidTest(Test):
    def __init__(self) -> None:
        super().__init__("cam-additive")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Part):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        manufacturing_data = PartConfiguration.get_manufacturing_data(shape)
        if manufacturing_data.method != METHOD_ADDITIVE:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        # What the part asks the machine for, against what the machine says it
        # can do. The bounding box goes along because "does it fit" is the one
        # question of the lot that the geometry answers rather than the
        # configuration - and it is the question that decides whether this part
        # can be printed on this machine at all.
        box = await shape.get_bounding_box_async(ctx)
        extent = None if box is None else [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
        problems = manufacturing_data.problems(ctx, extent=extent)
        if problems:
            return self.failed(shape, "; ".join(problems))

        # TODO(clairbee): Improve and extend the below
        # The manufacturability analysis runs in a sandbox (see cam_analysis), so
        # this module needs no CAD library.
        from .cam_analysis import free_bounds_count

        envelope = await shape.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape")
        if await free_bounds_count(ctx, envelope) != 0:
            return self.failed(shape, "The shape is not solid")

        return self.passed(shape)
