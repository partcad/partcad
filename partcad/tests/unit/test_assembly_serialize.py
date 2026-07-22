#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The assembly cache value preserves the hierarchy (names, labels, nesting)."""

import asyncio
import json
import os
import sys

import partcad as pc

from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _first_leaf(tree):
    for child in tree.get("assembly", []):
        if ocp_serialize.is_shape_object(child):
            return child
        leaf = _first_leaf(child)
        if leaf is not None:
            return leaf
    return None


def test_assembly_cache_value_is_a_nested_tree():
    ctx = pc.init("examples")
    asm = ctx._get_assembly("//produce_assembly_assy:logo_embedded")
    compound = asyncio.run(asm.get_wrapped(ctx))
    tree = asyncio.run(asm.get_cache_value(ctx, compound))

    # It is an assembly object with a name, and it nests sub-assemblies.
    assert ocp_serialize.is_assembly_object(tree)
    assert tree["name"] and tree["name"].endswith(":logo_embedded")

    def has_sub(t):
        return any(
            ocp_serialize.is_assembly_object(c) or has_sub(c)
            for c in t.get("assembly", [])
            if isinstance(c, dict)
        )

    assert has_sub(tree), "logo_embedded must keep its sub-assemblies nested"

    # Leaves carry a name, a label and BREP bytes.
    leaf = _first_leaf(tree)
    assert leaf is not None and leaf["name"] and leaf["label"] and leaf["brep"]


def test_assembly_tree_round_trips_to_the_same_geometry():
    ctx = pc.init("examples")
    asm = ctx._get_assembly("//produce_assembly_assy:logo_embedded")
    compound = asyncio.run(asm.get_wrapped(ctx))
    tree = asyncio.run(asm.get_cache_value(ctx, compound))

    # Through the JSON the cache stores, the tree decodes to the same geometry.
    rebuilt = ocp_serialize.decode_shape(json.loads(json.dumps(tree)))
    assert abs(_volume(rebuilt) - _volume(compound)) < 1e-6
