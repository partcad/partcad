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


def test_assembly_alias_get_1():
    """Load an assembly using an alias"""
    ctx = pc.Context("examples/produce_assembly_assy")
    alias = ctx._get_assembly(":partcad_logo")
    assert alias is not None
    assert asyncio.run(alias.get_wrapped()) is not None


def test_assembly_alias_get_2():
    """Load an assembly using a short form alias"""
    ctx = pc.Context("examples/produce_assembly_assy")
    alias = ctx._get_assembly(":partcad_logo_short")
    assert alias is not None
    assert asyncio.run(alias.get_wrapped()) is not None
