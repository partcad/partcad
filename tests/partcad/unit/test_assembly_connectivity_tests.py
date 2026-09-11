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
        # The real Assembly exposes 'children'; the per-container walk reads it.
        self.children = self._children

    async def do_instantiate(self):
        return None

    def connected_children(self):
        """Flattened, the way the real one is: a nested 'links:' becomes a
        child assembly whose contents belong to the assembly embedding it."""
        for child in self._children:
            yield child
            if isinstance(child.item, _Assembly):
                yield from child.item.connected_children()


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


def test_a_solid_that_is_the_right_way_out_but_not_valid_is_reported_not_failed(caplog):
    """An LDraw brick is an open mesh - a stud is a cylinder and a top disc
    with no bottom - so it fails IsValid while two copies 100 mm apart
    correctly share nothing. Failing on validity would condemn a whole library
    that works."""
    import logging

    shape = _Shape(solidity={"solids": 1, "volume": 2626.2, "valid": False})
    with caplog.at_level(logging.INFO):
        assert _run(SolidityTest(), shape)
    assert "not a valid one" in caplog.text


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



# --- what the review found --------------------------------------------------


def test_a_solid_of_exactly_no_volume_is_not_a_solid():
    """Negative is inside out; zero encloses nothing. Both are non-solids, and
    zero is the boundary a mesh that collapses lands on."""
    assert not _run(SolidityTest(), _Shape(solidity={"solids": 1, "volume": 0.0, "valid": True}))


def test_one_inverted_solid_is_not_excused_by_the_others():
    """A compound holding an inverted solid and a larger correct one sums to a
    positive number, and the inversion disappears into the total. The least of
    them decides."""
    shape = _Shape(solidity={"solids": 2, "volume": 900.0, "min_solid_volume": -100.0, "valid": True})
    assert not _run(SolidityTest(), shape)


def test_the_settings_that_decide_a_verdict_are_in_its_cache_key():
    """Test.test_cached() keys a remembered verdict on shape.hash plus this
    suffix, and shape.hash carries none of these settings - so a suffix that
    omits them hands back the answer from before they were changed."""
    conn = ConnectivityTest()
    assert conn.cache_key_suffix(None, _Assembly()) != conn.cache_key_suffix(
        None, _Assembly(config={"connectivity": {"allowDuplicates": True}})
    )
    assert conn.cache_key_suffix(None, _Assembly()) != conn.cache_key_suffix(
        None, _Assembly(config={"connectivity": {"requireAnchored": False}})
    )
    assert conn.cache_key_suffix(None, _Assembly()) != conn.cache_key_suffix(
        None, _Assembly(config={"connectivity": {"skip": True}})
    )
    sol = SolidityTest()
    assert sol.cache_key_suffix(None, _Shape()) != sol.cache_key_suffix(
        None, _Shape(config={"solidity": {"skip": True}})
    )


def test_a_verdict_that_turned_on_the_machine_is_not_remembered():
    """A missing runtime is not a fact about the shape. Cached, it would be
    read back under a key that installing the runtime does not change."""
    ctx = {}
    assert _run_ctx(SolidityTest(), _Shape(raises=Exception("no runtime")), ctx)
    assert ctx.get(SolidityTest.NOT_CACHEABLE) is True

    ctx = {}
    assert _run_ctx(ConnectivityTest(), _BrokenAssembly(), ctx)
    assert ctx.get(ConnectivityTest.NOT_CACHEABLE) is True


class _BrokenAssembly(_Assembly):
    async def do_instantiate(self):
        raise Exception("will not instantiate")


def _run_ctx(test, shape, test_ctx):
    return asyncio.run(test.test([], None, shape, test_ctx))


# --- multiConnect, and being able to say "no" --------------------------------


class _Iface2:
    """The little of Interface these need: the stored value and the parents."""

    def __init__(self, config, parent=None, name="i"):
        from partcad.interface import Interface

        self.get_multi_connect = Interface.get_multi_connect.__get__(self)
        self._inherited = Interface._inherited.__get__(self)
        self.multi_connect = bool(config["multiConnect"]) if "multiConnect" in config else None
        self.full_name = name
        self._parent = parent

    def get_parents(self):
        if self._parent is None:
            return {}
        return {"p": type("_Inherit", (), {"interface": self._parent})()}


def test_an_interface_that_says_nothing_takes_one_item():
    assert _Iface2({}).get_multi_connect() is False


def test_multi_connect_is_inherited():
    shaft = _Iface2({"multiConnect": True}, name="shaft")
    assert _Iface2({}, parent=shaft, name="splined").get_multi_connect() is True


def test_a_child_can_say_no_to_a_parent_that_says_yes():
    """A stored False that means "not set" cannot be told from one that means
    "no", so an explicit false used to be skipped and the parent's true won."""
    shaft = _Iface2({"multiConnect": True}, name="shaft")
    keyed = _Iface2({"multiConnect": False}, parent=shaft, name="keyed")
    assert keyed.get_multi_connect() is False


def test_the_item_the_others_hang_from_is_exempt_wherever_it_sits(monkeypatch):
    """The regression CI found in examples/feature_interface.

    An ASSY file's top-level 'links:' becomes a child assembly, so flattening
    the tree and exempting the first item exempts that wrapper and then reports
    'example-bracket' - the one item that is allowed to be placed by
    coordinates, because everything else connects to it.
    """
    monkeypatch.setattr("partcad.test.connectivity.Assembly", _Assembly)
    inner = _Assembly([
        _Child("example-bracket", _Item("bracket"), HERE),
        _connected("example-motor", "example-bracket", "TR-4.5mm"),
        _connected("screw-L", "example-bracket", "L-30mm"),
    ])
    root = _Assembly([_Child("links", inner, HERE)])
    assert _run(ConnectivityTest(), root, ctx=_Ctx())


def test_a_stray_inside_a_nested_group_is_still_reported(monkeypatch):
    """The exemption is one item per group, not one per assembly."""
    monkeypatch.setattr("partcad.test.connectivity.Assembly", _Assembly)
    inner = _Assembly([
        _Child("base", _Item("base"), HERE),
        _connected("a", "base", "p0"),
        _Child("stray", _Item("stray"), THERE),
    ])
    root = _Assembly([_Child("links", inner, HERE)])
    assert not _run(ConnectivityTest(), root, ctx=_Ctx())


def test_a_verdict_that_consulted_an_interface_is_not_remembered(monkeypatch):
    """'multiConnect' lives in the interface's configuration, which is neither
    in shape.hash nor among this shape's cache dependencies. A remembered
    verdict would survive that setting being changed."""
    monkeypatch.setattr("partcad.test.connectivity.Assembly", _Assembly)
    children = [
        _Child("shaft", _Item("shaft"), HERE),
        _connected("gear1", "shaft", "along", "//pub:shaft"),
        _connected("gear2", "shaft", "along", "//pub:shaft"),
    ]
    ctx_out = {}
    assert _run_ctx2(ConnectivityTest(), _Assembly(children), _Ctx(multi={"//pub:shaft"}), ctx_out)
    assert ctx_out.get(ConnectivityTest.NOT_CACHEABLE) is True


def test_a_verdict_that_consulted_nothing_is_remembered(monkeypatch):
    """Most assemblies never reach an interface: one item per port, no lookup,
    and the verdict depends only on what shape.hash already covers."""
    monkeypatch.setattr("partcad.test.connectivity.Assembly", _Assembly)
    children = [_Child("a", _Item("a"), HERE), _Child("b", _Item("b"), THERE)]
    ctx_out = {}
    assert _run_ctx2(ConnectivityTest(), _Assembly(children), _Ctx(), ctx_out)
    assert ConnectivityTest.NOT_CACHEABLE not in ctx_out


def _run_ctx2(test, shape, ctx, test_ctx):
    return asyncio.run(test.test([], ctx, shape, test_ctx))
