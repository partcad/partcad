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

import partcad as pc


def test_ctx1():
    ctx = pc.Context("partcad/tests")
    assert ctx is not None


def test_ctx_stats1():
    ctx = pc.Context("examples")
    assert ctx is not None
    ctx.stats_recalc()
    assert ctx.stats_packages > 0
    assert ctx.stats_parts == 0
    ctx.get_project("//produce_part_cadquery_primitive")
    assert ctx.stats_parts > 0
    assert ctx.stats_parts_instantiated == 0
    assert ctx.stats_assemblies == 0
    ctx.get_project("//produce_assembly_assy")
    assert ctx.stats_assemblies > 0
    assert ctx.stats_assemblies_instantiated == 0
    assert ctx.stats_memory > 0


def test_ctx_stats2():
    ctx = pc.Context("examples")
    assert ctx is not None
    ctx.stats_recalc()
    assert ctx.stats_parts_instantiated == 0
    old_memory = ctx.stats_memory

    cube = ctx._get_part("//produce_part_cadquery_primitive:cube")
    assert cube is not None
    assert ctx.stats_parts_instantiated == 0
    ctx.stats_recalc()
    new_memory = ctx.stats_memory
    assert new_memory > old_memory

    old_memory = ctx.stats_memory
    cube.cacheable = False
    obj = asyncio.run(cube.get_wrapped(ctx))
    assert obj is not None
    ctx.stats_recalc()
    assert ctx.stats_parts_instantiated == 1
    new_memory = ctx.stats_memory

    assert new_memory > old_memory


def test_ctx_fini():
    ctx1 = pc.init()
    assert ctx1 is not None
    pc.fini()
    ctx2 = pc.init()
    assert ctx2 is not None
    assert ctx2 != ctx1
    pc.fini()
    ctx3 = pc.init()
    assert ctx3 is not None
