#!/usr/bin/env python3
#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-12
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc


def test_sketch_get_dxf():
    """Load a DXF sketch from a project by the part name"""
    ctx = pc.Context("examples/produce_sketch_dxf")
    repo1 = ctx.get_project(".")
    assert repo1 is not None
    sketch = repo1.get_sketch("dxf_01")
    assert sketch is not None
    wrapped = asyncio.run(sketch.get_wrapped())
    assert wrapped is not None


def test_sketch_get_svg():
    """Load a SVG sketch from a project by the part name"""
    ctx = pc.Context("examples/produce_sketch_svg")
    repo1 = ctx.get_project(".")
    assert repo1 is not None
    sketch = repo1.get_sketch("svg_01")
    assert sketch is not None
    wrapped = asyncio.run(sketch.get_wrapped())
    assert wrapped is not None
