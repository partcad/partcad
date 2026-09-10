#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the 'solidity' and 'connectivity' checks decide, and on what.

Both are about assemblies that build perfectly and render plausibly while being
wrong in a way nothing looks at: a part whose faces are oriented inward, two
items in one place, two items on one port, an item anchored to nothing.
"""

import asyncio

import pytest

from partcad.geom import Location
from partcad.test.connectivity import ConnectivityTest, _packed
from partcad.test.solidity import SolidityTest


class _Item:
    def __init__(self, name, project="pkg"):
        self.name = name
        self.project_name = project


class _Child:
    def __init__(self, name, item, location=None, connection=None):
        self.name = name
        self.item = item
        self.location = location
        self.connection = connection


class _Shape:
    def __init__(self, config=None, solidity=None, raises=None):
        self.config = config or {}
        self.project_name = "pkg"
        self.name = "thing"
        self._solidity = solidity
        self._raises = raises

    async def get_solidity_async(self, ctx):
        if self._raises:
            raise self._raises
        return self._solidity


class _Assembly(_Shape):
    def __init__(self, children=(), config=None, **kwargs):
        super().__init__(config=config, **kwargs)
        self._children = list(children)

    async def do_instantiate(self):
        return None

    def connected_children(self):
        return iter(self._children)


@pytest.fixture(autouse=True)
def _assembly_is_an_assembly(monkeypatch):
    monkeypatch.setattr("partcad.test.connectivity.Assembly", _Assembly)
    monkeypatch.setattr("partcad.test.solidity.Assembly", _Assembly)


def _run(test, shape, ctx=None):
    return asyncio.run(test.test([], ctx, shape))


# --- solidity ---------------------------------------------------------------


def test_a_solid_the_right_way_out_passes():
    assert _run(SolidityTest(), _Shape(solidity={"solids": 1, "volume": 1939.6, "valid": True}))


def test_a_solid_that_is_inside_out_fails():
    """The regression: LDraw parts meshed from triangles came out inverted, so
    Brick 2 x 4 measured -1939.6 mm^3 and two copies 100 mm apart intersected
    to 2282 mm^3. It rendered correctly the whole time."""
    assert not _run(SolidityTest(), _Shape(solidity={"solids": 1, "volume": -1939.6, "valid": False}))


def test_a_solid_that_is_the_right_way_out_but_still_invalid_fails():
    assert not _run(SolidityTest(), _Shape(solidity={"solids": 1, "volume": 12.0, "valid": False}))


def test_something_with_no_solid_in_it_is_not_inside_out():
    """A sketch, a shell or a wire has no volume to have a sign."""
    assert _run(SolidityTest(), _Shape(solidity={"solids": 0, "volume": None, "valid": None}))


def test_a_part_can_opt_out():
    config = {"solidity": {"skip": True}}
    assert _run(SolidityTest(), _Shape(config=config, solidity={"solids": 1, "volume": -5.0, "valid": False}))


def test_an_assembly_is_checked_through_its_parts():
    assert _run(SolidityTest(), _Assembly(solidity={"solids": 1, "volume": -5.0, "valid": False}))


def test_a_shape_that_cannot_be_measured_is_left_to_the_cad_test():
    assert _run(SolidityTest(), _Shape(raises=Exception("no runtime")))


# --- connectivity: two items in one place -----------------------------------


HERE = Location((0, 0, 0), (0, 0, 1), 0)
THERE = Location((8, 0, 0), (0, 0, 1), 0)


def test_parts_in_different_places_pass():
    brick = _Item("brick")
    children = [_Child("a", brick, HERE), _Child("b", brick, THERE)]
    assert _run(ConnectivityTest(), _Assembly(children))


def test_the_same_part_twice_in_the_same_place_fails():
    brick = _Item("brick")
    children = [_Child("a", brick, HERE), _Child("b", brick, Location((0, 0, 0), (0, 0, 1), 0))]
    assert not _run(ConnectivityTest(), _Assembly(children))


def test_two_different_parts_in_one_place_are_interference_not_duplication():
    """Overlapping is the interference test's question; this one is about an
    item placed twice over."""
    children = [_Child("a", _Item("brick"), HERE), _Child("b", _Item("plate"), HERE)]
    assert _run(ConnectivityTest(), _Assembly(children))


def test_duplicates_can_be_allowed():
    brick = _Item("brick")
    config = {"connectivity": {"allowDuplicates": True}}
    children = [_Child("a", brick, HERE), _Child("b", brick, HERE)]
    assert _run(ConnectivityTest(), _Assembly(children, config=config))


# --- connectivity: two items on one port ------------------------------------


def _connected(name, target, port, interface="//pub:stud"):
    return _Child(name, _Item(name), None, {"target": target, "to_port": port, "to_interface": interface})


class _Ctx:
    def __init__(self, multi=()):
        self._multi = set(multi)

    def get_interface(self, spec):
        return _Iface(spec in self._multi)


class _Iface:
    def __init__(self, multi):
        self._multi = multi

    def get_multi_connect(self):
        return self._multi


def test_one_item_per_port_passes():
    children = [_Child("base", _Item("base"), HERE), _connected("a", "base", "c0r0"), _connected("b", "base", "c1r0")]
    assert _run(ConnectivityTest(), _Assembly(children), ctx=_Ctx())


def test_two_items_on_one_port_fails():
    children = [_Child("base", _Item("base"), HERE), _connected("a", "base", "c0r0"), _connected("b", "base", "c0r0")]
    assert not _run(ConnectivityTest(), _Assembly(children), ctx=_Ctx())


def test_an_interface_that_takes_many_says_so():
    """A shaft carries several parts along its length; a stud takes one brick."""
    children = [
        _Child("shaft", _Item("shaft"), HERE),
        _connected("gear1", "shaft", "along", "//pub:shaft"),
        _connected("gear2", "shaft", "along", "//pub:shaft"),
    ]
    assert _run(ConnectivityTest(), _Assembly(children), ctx=_Ctx(multi={"//pub:shaft"}))


def test_the_same_port_name_on_two_different_targets_is_two_ports():
    # 'requireAnchored' off so that this says something about ports alone:
    # 'r' is placed by coordinates, which is that other check's business.
    config = {"connectivity": {"requireAnchored": False}}
    children = [
        _Child("l", _Item("l"), HERE),
        _Child("r", _Item("r"), THERE),
        _connected("a", "l", "c0r0"),
        _connected("b", "r", "c0r0"),
    ]
    assert _run(ConnectivityTest(), _Assembly(children, config=config), ctx=_Ctx())


# --- connectivity: an item anchored to nothing ------------------------------


def test_an_assembly_placed_entirely_by_coordinates_is_a_legitimate_assembly():
    """Which is why this only applies once something in it does connect."""
    children = [_Child("a", _Item("a"), HERE), _Child("b", _Item("b"), THERE)]
    assert _run(ConnectivityTest(), _Assembly(children), ctx=_Ctx())


def test_an_item_left_on_coordinates_among_connected_ones_fails():
    children = [
        _Child("base", _Item("base"), HERE),
        _connected("a", "base", "c0r0"),
        _Child("stray", _Item("stray"), THERE),
    ]
    assert not _run(ConnectivityTest(), _Assembly(children), ctx=_Ctx())


def test_the_first_item_is_what_everything_else_hangs_from():
    """It has nothing to connect to, so it is not reported."""
    children = [_Child("base", _Item("base"), HERE), _connected("a", "base", "c0r0")]
    assert _run(ConnectivityTest(), _Assembly(children), ctx=_Ctx())


def test_requiring_an_anchor_can_be_turned_off():
    config = {"connectivity": {"requireAnchored": False}}
    children = [
        _Child("base", _Item("base"), HERE),
        _connected("a", "base", "c0r0"),
        _Child("stray", _Item("stray"), THERE),
    ]
    assert _run(ConnectivityTest(), _Assembly(children, config=config), ctx=_Ctx())


def test_a_whole_assembly_can_opt_out():
    brick = _Item("brick")
    config = {"connectivity": {"skip": True}}
    assert _run(ConnectivityTest(), _Assembly([_Child("a", brick, HERE), _Child("b", brick, HERE)], config=config))


def test_two_placements_that_differ_only_by_arithmetic_noise_are_one_place():
    a = _packed(Location((1.0, 2.0, 3.0), (0, 0, 1), 90))
    b = _packed(Location((1.0 + 1e-12, 2.0, 3.0), (0, 0, 1), 90))
    assert a == b
