#!/usr/bin/env python3
#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc


def test_part_enrich_get_1():
    """Load a CadQuery part using enrichment for parameters and see if the origin is intact"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    cube_enrich = ctx._get_part(":cube_enrich")
    assert cube_enrich is not None
    assert asyncio.run(cube_enrich.get_wrapped(ctx)) is not None

    # Check whether the original part is stil ok or not
    cube_config = ctx.get_project(".").get_part_config("cube")
    assert cube_config["name"] == "cube"
    assert cube_config["parameters"]["width"]["default"] == 10.0


def test_part_enrich_get_2():
    """Load a CadQuery part using enrichment for parameters and see if the parameters changed"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    cube_enrich = ctx._get_part(":cube_enrich")
    assert cube_enrich is not None
    assert asyncio.run(cube_enrich.get_wrapped(ctx)) is not None

    # Check whether the parameter change is in effect
    assert cube_enrich.config["parameters"]["width"]["default"] == 20.0


def test_part_enrich_get_3():
    """An alias to an enrich is the enriched part, parameters and all.

    It used to be the un-enriched one: the enrich worked out what to build from
    the object it was handed, which through an alias is the alias, and an alias
    declares no 'with'. An enrich now decides what it points at from its own
    declaration, so it does not matter who asks.

    Read through 'get_final_config()', which is how an alias answers what it
    resolves to: an alias reports its own configuration, and what it used to
    report here was the enriched one only because the enrich wrote its result
    onto whatever object it was handed.
    """
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    cube_alias_enrich = ctx._get_part(":cube_alias_enrich")
    assert cube_alias_enrich is not None
    assert asyncio.run(cube_alias_enrich.get_wrapped(ctx)) is not None

    # Check whether the parameter change is in effect
    assert cube_alias_enrich.get_final_config()["parameters"]["width"]["default"] == 20.0


def test_part_enrich_get_4():
    """Load a CadQuery part using enrichment for parameters and see if the parameters changed"""
    ctx = pc.Context("examples/produce_part_cadquery_primitive")
    cube_enrich_enrich = ctx._get_part(":cube_enrich_enrich")
    assert cube_enrich_enrich is not None
    assert asyncio.run(cube_enrich_enrich.get_wrapped(ctx)) is not None

    # Check whether the parameter change is in effect
    assert cube_enrich_enrich.config["parameters"]["width"]["default"] == 20.0
    assert cube_enrich_enrich.config["parameters"]["length"]["default"] == 5.0
