#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test


class CadTest(Test):
    def __init__(self) -> None:
        super().__init__("cad")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        wrapped = await shape.get_wrapped(ctx)
        if wrapped is None:
            return self.failed(shape, "Failed to get the shape")

        return self.passed(shape)
