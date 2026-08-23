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
from partcad import shape_envelope

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _bbox(shape):
    """The assembled bounding box, as the two corners in world coordinates."""
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    lo, hi = box.CornerMin(), box.CornerMax()
    return (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())


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


def _brep_payloads(tree):
    """Every "brep" field in the tree, the root's own first."""
    if isinstance(tree, list):
        for item in tree:
            yield from _brep_payloads(item)
        return
    if not isinstance(tree, dict):
        return
    if "brep" in tree:
        yield tree["brep"]
    for child in tree.get("assembly", []):
        yield from _brep_payloads(child)


def test_assembly_tree_round_trips_to_the_same_geometry():
    ctx = pc.init("examples")
    asm = ctx._get_assembly("//produce_assembly_assy:logo_embedded")
    compound = asyncio.run(asm.get_wrapped(ctx))
    tree = asyncio.run(asm.get_cache_value(ctx, compound))

    # In memory a BREP payload is the compressed bytes themselves; base64 is
    # applied only where the value has to become JSON text. That boundary is
    # shape_envelope.dumps()/loads(), which is what the shape cache serializes
    # through - so the round trip goes through it, not through bare json, which
    # has no byte type to carry the payload in the first place.
    text = shape_envelope.dumps(tree)

    # What it produced really is JSON, and every payload in it really is text:
    # nothing bytes-shaped is left for the cache - or a wrapper - to choke on.
    raw = json.loads(text)
    payloads = list(_brep_payloads(raw))
    assert payloads, "the encoded tree carries no BREP payload at all"
    assert all(isinstance(payload, str) for payload in payloads), "a BREP payload survived as non-text"

    # And it comes back as the same geometry. get_wrapped() returns a BREP
    # envelope too, so decode that as well before measuring.
    rebuilt = ocp_serialize.decode_shape(shape_envelope.loads(text))
    original = ocp_serialize.decode_shape(compound)
    assert abs(_volume(rebuilt) - _volume(original)) < 1e-6

    # Volume alone is placement-blind: a child that came back at the origin, or
    # anywhere else, displaces exactly as much as one in its right place, so the
    # assertion above would not notice. The bounding box does - it is the cheap
    # invariant that moves when a child does. Both sides are measured the same
    # way, so Bnd_Box's own gap cancels out.
    rebuilt_bbox = _bbox(rebuilt)
    original_bbox = _bbox(original)
    assert all(abs(a - b) < 1e-6 for a, b in zip(rebuilt_bbox, original_bbox, strict=True)), (
        "the assembly does not occupy the same space: %r vs %r" % (rebuilt_bbox, original_bbox)
    )
