#!/usr/bin/env python3
#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-14
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc
from partcad.test import cam


def test_part_manufacturing_positive_1():
    """Load a manufacturable part and test it"""
    ctx = pc.Context("examples/provider_manufacturer")
    cylinder = ctx._get_part(":cylinder")
    assert cylinder is not None
    assert asyncio.run(cylinder.get_wrapped(ctx)) is not None

    test = pc.test.cam.CamTest()
    assert asyncio.run(test.test([test], ctx, cylinder)) == True


def test_part_manufacturing_negative_1():
    """Load a non-manufacturable part and test it"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    cube = ctx._get_part(":cube")
    assert cube is not None
    assert asyncio.run(cube.get_wrapped(ctx)) is not None

    test = pc.test.cam.CamTest()
    assert asyncio.run(test.test([test], ctx, cube)) == True
