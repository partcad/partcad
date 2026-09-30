#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import os
import sys

import partcad as pc

# 'partcad' before OCP, and 'isort: split' so it stays there: importing the
# package pins the standard library's expat (see the comment on 'import
# pyexpat' in partcad/__init__.py), and whatever loads first wins for the
# process.
# isort: split

from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS_Compound

# get_wrapped() now returns a BREP envelope, not a live shape; decode it with
# the sandbox codec to inspect the geometry.
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_compound_part_produces_assembly_compound():
    """A 'compound' part flattens the referenced assembly into a TopoDS_Compound."""
    ctx = pc.init("examples")

    part = ctx.get_part("//produce_assembly_assy:primitive_compound")
    assert part is not None

    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None
    shape = ocp_serialize.decode_shape(envelope)
    assert isinstance(shape, TopoDS_Compound)

    # Its geometry equals the referenced assembly's compound.
    assembly = ctx._get_assembly("//produce_assembly_assy:primitive")
    assembly_shape = ocp_serialize.decode_shape(asyncio.run(assembly.get_wrapped(ctx)))
    assert abs(_volume(shape) - _volume(assembly_shape)) < 1e-6
