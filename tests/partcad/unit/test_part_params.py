#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-27
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
from unittest.mock import patch

import partcad as pc


def test_part_params_get_1():
    """Load a CadQuery part using parameters"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    brick = ctx._get_part(":cube", {"width": 17.0})
    assert brick is not None
    assert asyncio.run(brick.get_wrapped(ctx)) is not None
    assert brick.config["parameters"]["width"]["default"] == 17.0


def test_part_params_get_2():
    """Load a CadQuery part using parameters and type casting"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    brick = ctx._get_part(":cube", {"width": "17.0"})
    assert brick is not None
    assert asyncio.run(brick.get_wrapped(ctx)) is not None
    assert brick.config["parameters"]["width"]["default"] == 17.0

def test_part_user_config_params_get():
    """Load a CadQuery part using enrichment for parameters and see if the parameters changed from user_config"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    pc.user_config.parameter_config["//pub/examples/partcad/produce_part_cadquery_primitive:cube_enrich"] = {"width": 33.0}
    cube_enrich = ctx._get_part(":cube_enrich")
    assert cube_enrich is not None
    assert asyncio.run(cube_enrich.get_wrapped(ctx)) is not None
    assert cube_enrich.config["parameters"]["width"]["default"] == 33.0
