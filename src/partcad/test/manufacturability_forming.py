#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from ..part import Part
from ..part_config import PartConfiguration
from ..part_config_manufacturing import METHOD_FORMING
from .test import Test


class ManufacturabilityFormingTest(Test):
    WRAPPERS = ("manufacturability.py",)

    def __init__(self) -> None:
        super().__init__("manufacturability-forming")

    def inapplicable(self, shape):
        if not isinstance(shape, Part):
            return "only a part is made by a manufacturing method"
        if PartConfiguration.get_manufacturing_data(shape).method != METHOD_FORMING:
            return "it is not made by the 'forming' method ('manufacturing: method')"
        return None

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)

        # TODO(clairbee): Utilize the data provided in the config
        # TODO(clairbee): Improve and extend the below
        # The manufacturability analysis runs in a sandbox (see manufacturability_analysis), so
        # this module needs no CAD library.
        from .manufacturability_analysis import free_bounds_count

        envelope = await shape.get_wrapped(ctx)
        if envelope is None:
            return self.failed(shape, "Failed to get the shape")
        if await free_bounds_count(ctx, envelope) != 0:
            return self.failed(shape, "The shape is not solid")

        return self.passed(shape)
