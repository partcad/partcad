#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc


def test_part_enrich_get_1():
    """Load a CadQuery part using enrichment for parameters and see if the origin is intact"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    brick = ctx._get_part(":brick")
    assert brick is not None
    assert asyncio.run(brick.get_wrapped()) is not None

    # Check whether the original part is stil ok or not
    cube_config = ctx.get_project(".").get_part_config("cube")
    assert cube_config["name"] == "cube"
    assert cube_config["parameters"]["width"]["default"] == 10.0


def test_part_enrich_get_2():
    """Load a CadQuery part using enrichment for parameters and see if the parameters changed"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    brick = ctx._get_part(":brick")
    assert brick is not None
    assert asyncio.run(brick.get_wrapped()) is not None

    # Check whether the parameter change is in effect
    assert brick.config["parameters"]["width"]["default"] == 20.0


# TODO(clairbee): add support for the following one
# def test_part_enrich_get_3():
#     """Load a CadQuery part using enrichment for parameters and see if the parameters changed"""
#     ctx = pc.Context("examples/produce_part_cadquery_primitive")
#     brick = ctx._get_part(":brick2")
#     assert brick is not None
#     assert asyncio.run(brick.get_wrapped()) is not None

#     # Check whether the parameter change is in effect
#     assert brick.config["parameters"]["width"]["default"] == 20.0
