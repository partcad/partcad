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

import build123d as b3d
from OCP.TopoDS import TopoDS_Iterator

import partcad as pc
from partcad.assembly import Assembly, AssemblyChild


def test_assembly_primitive():
    ctx = pc.init("examples")
    part1 = ctx.get_part("//produce_part_cadquery_primitive:cube")
    assert part1 is not None
    part2 = ctx.get_part("//produce_part_cadquery_primitive:cylinder")
    assert part2 is not None

    model = pc.Assembly({"name": "example1"})
    model.add(part1, loc=pc.Location((0, 0, 0), (0, 0, 1), 0))
    model.add(part2, loc=pc.Location((0, 0, 1), (0, 0, 1), 0))
    assert asyncio.run(model.get_wrapped(ctx)) is not None
    assert asyncio.run(model.convert("build123d", ctx)) is not None


def test_assembly_example_assy_primitive():
    ctx = pc.init("examples")
    primitive = ctx._get_assembly("//produce_assembly_assy:primitive")
    assert primitive is not None
    assert asyncio.run(primitive.get_wrapped(ctx)) is not None
    assert asyncio.run(primitive.convert("build123d", ctx)) is not None


def test_assembly_example_assy_logo():
    ctx = pc.init("examples")
    logo = ctx._get_assembly("//produce_assembly_assy:logo")
    assert logo is not None
    assert asyncio.run(logo.get_wrapped(ctx)) is not None
    assert asyncio.run(logo.convert("build123d", ctx)) is not None


def test_assembly_example_assy_logo_embedded():
    ctx = pc.init("examples")
    logo = ctx._get_assembly("//produce_assembly_assy:logo_embedded")
    assert logo is not None
    assert asyncio.run(logo.get_wrapped(ctx)) is not None
    assert asyncio.run(logo.convert("build123d", ctx)) is not None


def test_assembly_example_assy_logo_bom():
    ctx = pc.init("examples")
    logo = ctx._get_assembly("//produce_assembly_assy:logo_embedded")
    assert logo is not None
    bom = asyncio.run(logo.get_bom())
    assert bom is not None
    assert len(bom.keys()) == 3
    assert sum(bom.values()) == 5


class _SlowChild:
    """A stand-in for a part that takes a known amount of time to build.

    Every instance produces the same unit box, so the only thing that tells the
    children apart in the resulting compound is the location the assembly puts
    them at.
    """

    def __init__(self, name, delay):
        self.project_name = "test"
        self.name = name
        self.delay = delay

    async def convert(self, part_type, ctx=None):
        await asyncio.sleep(self.delay)
        return b3d.Solid.make_box(1.0, 1.0, 1.0)


def _child_offsets(wrapped):
    """The X offset of every immediate child of a compound, in compound order."""
    offsets = []
    it = TopoDS_Iterator(wrapped)
    while it.More():
        offsets.append(it.Value().Location().Transformation().TranslationPart().X())
        it.Next()
    return offsets


def test_assembly_child_order_is_declaration_order():
    """Children are compounded in declaration order, not in the order they finish.

    The children are given decreasing build times, so they always finish in the
    exact reverse of the order they are declared in. Collecting them as they
    complete would produce [40, 30, 20, 10, 0] every time.
    """
    assembly = Assembly("test", {"name": "order_test"})
    expected = [0.0, 10.0, 20.0, 30.0, 40.0]
    for i, x in enumerate(expected):
        assembly.children.append(
            AssemblyChild(
                _SlowChild("child_%d" % i, delay=0.25 - i * 0.05),
                "child_%d" % i,
                b3d.Location((x, 0.0, 0.0)),
            )
        )

    wrapped = asyncio.run(assembly._get_shape_real(None))
    assert _child_offsets(wrapped) == expected
