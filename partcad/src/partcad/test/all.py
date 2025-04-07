#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#
import os

from .test import Test
from .cad import CadTest
from .cam import CamTest
from .cam_additive_solid import CamAdditiveSolidTest
from .cam_subtractive import CamSubtractiveTest
from .cam_forming import CamFormingTest

_global_tests: list[Test] = []


def tests(concurrency_cap: int) -> list[Test]:
    if concurrency_cap is None:
        concurrency_cap = max(os.cpu_count(), 8)
    Test.MAX_CONCURRENT_TESTS = concurrency_cap
    if len(_global_tests) == 0:
        _global_tests.extend(
            [
                CadTest(),
                CamTest(),
                CamAdditiveSolidTest(),
                CamSubtractiveTest(),
                CamFormingTest(),
            ]
        )
    return _global_tests
