#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from .cad import CadTest
from .cam import CamTest
from .cam_additive_solid import CamAdditiveSolidTest

_global_tests = []


def tests() -> list[Test]:
    if len(_global_tests) == 0:
        _global_tests.extend(
            [
                CadTest(),
                CamTest(),
                CamAdditiveSolidTest(),
            ]
        )
    return _global_tests
