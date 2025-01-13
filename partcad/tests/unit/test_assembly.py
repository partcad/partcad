#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import pytest
import sys

import partcad as pc


def test_assembly_primitive():
    ctx = pc.init("examples")
    part1 = ctx.get_part("/produce_part_cadquery_primitive:cube")
    assert part1 is not None
    part2 = ctx.get_part("/produce_part_cadquery_primitive:cylinder")
    assert part2 is not None

    model = pc.Assembly({"name": "example1"})
    model.add(part1, loc=pc.Location((0, 0, 0), (0, 0, 1), 0))
    model.add(part2, loc=pc.Location((0, 0, 1), (0, 0, 1), 0))
    assert asyncio.run(model.get_shape()) is not None
    assert asyncio.run(model.get_build123d()) is not None


def test_assembly_example_assy_primitive():
    ctx = pc.init("examples")
    primitive = ctx._get_assembly("/produce_assembly_assy:primitive")
    assert primitive is not None
    assert asyncio.run(primitive.get_shape()) is not None
    assert asyncio.run(primitive.get_build123d()) is not None


def test_assembly_example_assy_logo():
    ctx = pc.init("examples")
    logo = ctx._get_assembly("/produce_assembly_assy:logo")
    assert logo is not None
    assert asyncio.run(logo.get_shape()) is not None
    assert asyncio.run(logo.get_build123d()) is not None


def test_assembly_example_assy_logo_embedded():
    ctx = pc.init("examples")
    logo = ctx._get_assembly("/produce_assembly_assy:logo_embedded")
    assert logo is not None
    assert asyncio.run(logo.get_shape()) is not None
    assert asyncio.run(logo.get_build123d()) is not None


def test_assembly_example_assy_logo_bom():
    ctx = pc.init("examples")
    logo = ctx._get_assembly("/produce_assembly_assy:logo_embedded")
    assert logo is not None
    bom = asyncio.run(logo.get_bom())
    assert bom is not None
    assert len(bom.keys()) == 3
    assert sum(bom.values()) == 5
