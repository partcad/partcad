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


def test_part_alias_get_1():
    """Load a STEP part using a short form alias"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx._get_part(":screw")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped())
    assert wrapped is not None


def test_part_alias_get_2():
    """Load a STEP part using a long form alias"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx._get_part(":fastener")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped())
    assert wrapped is not None


def test_part_alias_get_3():
    """Load a STEP part using a long form alias"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx._get_part(":hexhead")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped())
    assert wrapped is not None


# Add support for the following one
# def test_part_alias_get_with_params():
#     """Load a CadQuery part using an alias with parameters in its name and see if the parameters changed"""
#     ctx = pc.Context("examples/produce_part_cadquery_primitive")
#     brick = ctx.get_part(":brick2")
#     assert brick is not None
#     assert brick.get_wrapped() is not None

#     # Check whether the parameter change is in effect
#     assert brick.config["parameters"]["width"]["default"] == 20.0
