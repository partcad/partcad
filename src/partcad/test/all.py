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
from .cfd import CfdTest
from .connect import ConnectTest
from .connectivity import ConnectivityTest
from .degenerate import DegenerateTest
from .fea import FeaTest
from .interference import InterferenceTest
from .solidity import SolidityTest

_global_tests: list[Test] = []


def tests(concurrency_cap: int) -> list[Test]:
    """Every check `pc test` runs, built once and shared by every caller.

    `concurrency_cap` is a cap on the tests as a whole rather than on any one of
    them, which is why it is set on the base class here rather than passed down.
    """
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
                ConnectTest(),
                ConnectivityTest(),
                DegenerateTest(),
                # Before interference, deliberately: a part that is inside out
                # makes every boolean against it meaningless, so knowing which
                # parts those are is what makes the interference result mean
                # anything.
                SolidityTest(),
                # Realizes the assembly and intersects the pairs whose boxes
                # meet, so it is the most expensive of the geometry checks and
                # goes after the ones that are nearly free.
                InterferenceTest(),
                # Only ever run for a part that declares the matching section;
                # see 'test/cae.py'. A package with no 'fea:'/'cfd:' in
                # it pays nothing for these two being here.
                FeaTest(),
                CfdTest(),
            ]
        )
    return _global_tests
