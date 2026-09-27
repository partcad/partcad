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


def test_part_alias_get_1():
    """Load a STEP part using a short form alias"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx._get_part(":screw")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped(ctx))
    assert wrapped is not None


def test_part_alias_get_2():
    """Load a STEP part using a long form alias"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx._get_part(":fastener")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped(ctx))
    assert wrapped is not None


def test_part_alias_get_3():
    """Load a STEP part using a long form alias"""
    ctx = pc.Context("examples/produce_part_step")
    bolt = ctx._get_part(":hexhead")
    assert bolt is not None

    wrapped = asyncio.run(bolt.get_wrapped(ctx))
    assert wrapped is not None


# Add support for the following one
# def test_part_alias_get_with_params():
#     """Load a CadQuery part using an alias with parameters in its name and see if the parameters changed"""
#     ctx = pc.Context("examples/produce_part_cadquery_primitive")
#     brick = ctx.get_part(":brick2")
#     assert brick is not None
#     assert brick.get_wrapped(ctx) is not None

#     # Check whether the parameter change is in effect
#     assert brick.config["parameters"]["width"]["default"] == 20.0


def test_part_alias_has_the_ports_of_its_source():
    """An alias is its source's geometry, so it connects where its source does"""
    ctx = pc.Context("tests/partcad/unit/data/alias_ports")
    plate = ctx._get_part(":plate")
    elsewhere = ctx._get_part(":plate-elsewhere")
    restated = ctx._get_part(":plate-restated")

    assert set(elsewhere.with_ports.get_ports()) == set(plate.with_ports.get_ports())
    assert set(elsewhere.with_ports.get_interfaces()) == set(plate.with_ports.get_interfaces())
    interface = next(iter(elsewhere.with_ports.get_interfaces()))
    assert set(elsewhere.with_ports.get_interface(interface)) == {"TL", "TR"}

    # ... unless it says where it connects itself
    assert set(restated.with_ports.get_interface(interface)) == {"C"}


def test_part_alias_ports_from_a_resolved_source():
    """Once its source is resolved from a coroutine, an alias does not look it up again

    A synchronous lookup is refused, on a thread running a loop, for a part an
    assembly materializes; so what a coroutine resolved is what is used.
    """
    from partcad.shape_ports import prepare_async

    ctx = pc.Context("tests/partcad/unit/data/alias_ports")
    elsewhere = ctx._get_part(":plate-elsewhere")
    asyncio.run(prepare_async(elsewhere, ctx))

    def refuse(*args, **kwargs):
        raise RuntimeError("looked up synchronously")

    ctx._get_part = refuse
    interface = next(iter(elsewhere.with_ports.get_interfaces()))
    assert set(elsewhere.with_ports.get_interface(interface)) == {"TL", "TR"}
