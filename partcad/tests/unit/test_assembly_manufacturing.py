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


def test_assembly_manufacturing_positive_1():
    """Load a manufacturable assembly and test it"""
    ctx = pc.Context("examples/provider_manufacturer")
    assembly = ctx._get_assembly(":assembly")
    assert assembly is not None
    assert asyncio.run(assembly.get_wrapped()) is not None

    test = pc.test.cam.CamTest()
    assert asyncio.run(test.test([test], ctx, assembly)) == True


def test_assembly_manufacturing_negative_1():
    """Load a non-manufacturable assembly and test it"""
    ctx = pc.Context("examples/produce_assembly_assy")
    assembly = ctx._get_assembly(":logo")
    assert assembly is not None
    assert asyncio.run(assembly.get_wrapped()) is not None

    test = pc.test.cam.CamTest()
    assert asyncio.run(test.test([test], ctx, assembly)) == True
