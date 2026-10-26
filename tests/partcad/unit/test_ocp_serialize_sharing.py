#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Nodes carrying the same BREP decode into one shared 'TShape', each placed where its node says.

An assembly is mostly repeats of a few parts, and decoding every node into a
copy of its own made a drawing of the LEGO castle (731 placements of 9 bricks)
mesh and project 731 bricks: 3.4 GB where sharing them takes 1.4 GB. These hold
what sharing must not change -- where each placement is, what type each shape
is, that every placement is still there -- and what it must not do: confuse two
different shapes, or let one node's handle move another's.
"""

import os
import sys

import pytest

import partcad as pc

# 'partcad' before OCP, and 'isort: split' so it stays there: importing the
# package pins the standard library's expat (see the comment on 'import
# pyexpat' in partcad/__init__.py), and whatever loads first wins for the
# process.
# isort: split

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Trsf, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Solid

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402


def _leaf(shape, label, location=None):
    leaf = ocp_serialize.encode_shape(shape, name="//pkg:part", label=label)
    if location is not None:
        leaf[ocp_serialize.KEY_LOCATION] = location
    return leaf


def _brick():
    return BRepPrimAPI_MakeBox(8.0, 8.0, 9.6).Solid()


def _assembly(*children, location=None):
    tree = {"name": "//pkg:assembly", "label": "assembly", ocp_serialize.KEY_ASSEMBLY: list(children)}
    if location is not None:
        tree[ocp_serialize.KEY_LOCATION] = location
    return tree


def _row(count):
    """'count' bricks side by side, every one of them the same payload."""
    leaf = _leaf(_brick(), "brick")
    return _assembly(*[dict(leaf, label="b%d" % i, location=[[8.0 * i, 0, 0], [0, 0, 1], 0]) for i in range(count)])


def _box_of(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return [round(value, 6) for value in box.Get()]


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_one_payload_placed_many_times_is_one_tshape():
    _whole, tree = ocp_serialize.decode_tree(_row(5))
    shapes = [node[ocp_serialize.KEY_SHAPE] for node in tree[ocp_serialize.KEY_ASSEMBLY]]

    assert all(shape.TShape() == shapes[0].TShape() for shape in shapes)


def test_every_node_still_has_a_handle_of_its_own():
    """Setting a location on one node's shape must not move another's."""
    _whole, tree = ocp_serialize.decode_tree(_row(2))
    first, second = (node[ocp_serialize.KEY_SHAPE] for node in tree[ocp_serialize.KEY_ASSEMBLY])

    assert first is not second
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(0, 0, 100))
    first.Location(TopLoc_Location(trsf))
    assert _box_of(second) == _box_of(_brick())


def test_the_shape_keeps_its_type():
    _whole, tree = ocp_serialize.decode_tree(_row(2))

    assert all(isinstance(node[ocp_serialize.KEY_SHAPE], TopoDS_Solid) for node in tree[ocp_serialize.KEY_ASSEMBLY])


def test_every_placement_is_still_there_and_where_it_was():
    whole = ocp_serialize.decode_shape(_row(5))

    assert _volume(whole) == pytest.approx(5 * 8.0 * 8.0 * 9.6)
    assert _box_of(whole) == [0.0, 0.0, 0.0, 40.0, 8.0, 9.6]


def test_placements_compose_through_sub_assemblies():
    """A shared shape is placed by its own location and by every one above it."""
    inner = _row(2)
    tree = _assembly(inner, dict(inner, location=[[0, 0, 100], [0, 0, 1], 90]))

    whole = ocp_serialize.decode_shape(tree)

    assert _volume(whole) == pytest.approx(4 * 8.0 * 8.0 * 9.6)
    # The second row is turned a quarter about Z and lifted 100.
    assert _box_of(whole) == [-8.0, 0.0, 0.0, 16.0, 16.0, 109.6]


def test_two_different_shapes_are_never_confused():
    brick = _leaf(_brick(), "brick")
    round_brick = _leaf(BRepPrimAPI_MakeCylinder(4.0, 9.6).Solid(), "round")

    _whole, tree = ocp_serialize.decode_tree(_assembly(brick, round_brick, dict(brick, label="again")))
    first, second, third = (node[ocp_serialize.KEY_SHAPE] for node in tree[ocp_serialize.KEY_ASSEMBLY])

    assert first.TShape() == third.TShape()
    assert first.TShape() != second.TShape()
    assert _volume(second) == pytest.approx(3.141592653589793 * 16.0 * 9.6, rel=1e-6)


def test_shapes_anywhere_in_a_request_are_shared():
    """'decode' of a whole request: the same payload under two keys is one shape too."""
    leaf = _leaf(_brick(), "brick")

    decoded = ocp_serialize.decode({"wrapped": _assembly(leaf), "other": [dict(leaf, label="other")]})

    assert decoded["other"][0].TShape() == next(iter(_children(decoded["wrapped"]))).TShape()


def _children(compound):
    from OCP.TopoDS import TopoDS_Iterator

    iterator = TopoDS_Iterator(compound)
    while iterator.More():
        yield iterator.Value()
        iterator.Next()


def test_decoding_twice_shares_nothing_between_the_two():
    """What is shared is one decoding's; nothing lives on in the module between calls."""
    first = ocp_serialize.decode_shape(_leaf(_brick(), "brick"))
    second = ocp_serialize.decode_shape(_leaf(_brick(), "brick"))

    assert first.TShape() != second.TShape()
