#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc

from OCP.TopoDS import TopoDS_Compound
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_compound_part_produces_assembly_compound():
    """A 'compound' part flattens the referenced assembly into a TopoDS_Compound."""
    ctx = pc.init("examples")

    part = ctx.get_part("//produce_assembly_assy:primitive_compound")
    assert part is not None

    shape = asyncio.run(part.get_wrapped(ctx))
    assert shape is not None
    assert isinstance(shape, TopoDS_Compound)

    # Its geometry equals the referenced assembly's compound.
    assembly = ctx._get_assembly("//produce_assembly_assy:primitive")
    assembly_shape = asyncio.run(assembly.get_wrapped(ctx))
    assert abs(_volume(shape) - _volume(assembly_shape)) < 1e-6
