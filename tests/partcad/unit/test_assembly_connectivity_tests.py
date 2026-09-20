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
    def __init__(self, name, item, location=None, connection=None, located=False):
        self.name = name
        self.item = item
        self.location = location
        self.connection = connection
        # Whether the ASSY file placed it with 'location:', as opposed to it
        # having a location because everything placed has one.
        self.located = located


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
    def __init__(self, children=(), config=None, is_manufacturable=False, **kwargs):
        super().__init__(config=config, **kwargs)
        self.is_manufacturable = is_manufacturable
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


def test_solidity_says_nothing_about_how_well_formed_a_solid_is(caplog):
    """Which way the faces point is this check's question, and the only one.
    Whether the solid is well formed belongs to 'validity', which reports it -
    an LDraw brick is a solid of honest volume that OCCT will not certify, and
    it intersects other parts correctly."""
    import logging

    shape = _Shape(solidity={"solids": 1, "volume": 2626.2, "valid": False})
    with caplog.at_level(logging.INFO):
        assert _run(SolidityTest(), shape)
    assert "not a valid one" not in caplog.text


def test_something_with_no_solid_in_it_is_not_inside_out():
    """A sketch, a shell or a wire has no volume to have a sign."""
    assert _run(SolidityTest(), _Shape(solidity={"solids": 0, "volume": None, "valid": None}))


def test_a_part_cannot_opt_out():
    """An inside-out solid fails whatever the part says about itself.

    There is no setting for this. A part that asked not to be checked used to
    pass; the check now reads the geometry and nothing else, because a solid of
    negative volume is broken however it came to be declared.
    """
    config = {"solidity": {"skip": True}}
    assert not _run(SolidityTest(), _Shape(config=config, solidity={"solids": 1, "volume": -5.0, "valid": False}))


def test_an_assembly_is_checked_through_its_parts():
    assert _run(SolidityTest(), _Assembly(solidity={"solids": 1, "volume": -5.0, "valid": False}))


def test_a_check_that_cannot_run_fails_rather_than_passes():
    """An exception here means this check broke, not that the shape is fine."""
    ctx = {}
    assert not asyncio.run(SolidityTest().test([], None, _Shape(raises=Exception("boom")), ctx))
    assert ctx.get(SolidityTest.NOT_CACHEABLE) is True


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


def test_a_rule_is_turned_off_one_at_a_time_rather_than_all_at_once():
    """There is no blanket opt-out. A package says which rule does not apply to
    it - 'allowDuplicates', 'requireAnchored' - so what it has turned off is
    written down and the rest of the check still runs."""
    brick = _Item("brick")
    config = {"connectivity": {"allowDuplicates": True}}
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
    assert asyncio.run(conn.cache_key_suffix(None, _Assembly())) != asyncio.run(
        conn.cache_key_suffix(None, _Assembly(config={"connectivity": {"allowDuplicates": True}}))
    )
    assert asyncio.run(conn.cache_key_suffix(None, _Assembly())) != asyncio.run(
        conn.cache_key_suffix(None, _Assembly(config={"connectivity": {"requireAnchored": False}}))
    )
    # 'solidity' has nothing in its key: it reads the geometry and takes no
    # settings, so there is nothing a package can change that moves the answer.
    sol = SolidityTest()
    assert asyncio.run(sol.cache_key_suffix(None, _Shape())) == ""
    assert asyncio.run(sol.cache_key_suffix(None, _Shape(config={"solidity": {"anything": True}}))) == ""


def test_a_check_that_cannot_run_is_failed_and_not_remembered():
    """It fails, because an exception means the check broke rather than that
    the shape is sound - and it is not remembered, because the reason was not
    the shape."""
    ctx = {}
    assert not _run_ctx(SolidityTest(), _Shape(raises=Exception("boom")), ctx)
    assert ctx.get(SolidityTest.NOT_CACHEABLE) is True

    ctx = {}
    assert not _run_ctx(ConnectivityTest(), _BrokenAssembly(), ctx)
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
    inner = _Assembly(
        [
            _Child("example-bracket", _Item("bracket"), HERE),
            _connected("example-motor", "example-bracket", "TR-4.5mm"),
            _connected("screw-L", "example-bracket", "L-30mm"),
        ]
    )
    root = _Assembly([_Child("links", inner, HERE)])
    assert _run(ConnectivityTest(), root, ctx=_Ctx())


def test_a_stray_inside_a_nested_group_is_still_reported(monkeypatch):
    """The exemption is one item per group, not one per assembly."""
    monkeypatch.setattr("partcad.test.connectivity.Assembly", _Assembly)
    inner = _Assembly(
        [
            _Child("base", _Item("base"), HERE),
            _connected("a", "base", "p0"),
            _Child("stray", _Item("stray"), THERE),
        ]
    )
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


# --- validity: the check that reports rather than fails ----------------------


def _validity(shape, ctx=None):
    from partcad.test.validity import ValidityTest

    test_ctx = {}
    verdict = asyncio.run(ValidityTest().test([], ctx, shape, test_ctx))
    return verdict, test_ctx


@pytest.fixture
def _validity_classes(monkeypatch):
    monkeypatch.setattr("partcad.test.validity.Assembly", _Assembly)
    monkeypatch.setattr("partcad.test.validity.Sketch", _Sketch2)


class _Sketch2(_Shape):
    pass


def test_a_well_formed_solid_says_nothing(_validity_classes, caplog):
    import logging

    shape = _Shape(solidity={"solids": 1, "volume": 100.0, "valid": True})
    with caplog.at_level(logging.INFO):
        verdict, _ = _validity(shape)
    assert verdict
    assert "not a well formed one" not in caplog.text


def test_a_defective_solid_is_reported_and_still_passes(_validity_classes, caplog):
    """An LDraw brick is a solid of honest volume that OCCT will not certify -
    224 free boundary edges - and it intersects other parts correctly. Failing
    it would say something untrue, so this reports."""
    import logging

    shape = _Shape(solidity={"solids": 1, "volume": 1706.4, "valid": False})
    with caplog.at_level(logging.INFO):
        verdict, _ = _validity(shape)
    assert verdict, "validity reports; it does not fail"
    assert "not a well formed one" in caplog.text


def test_a_shape_with_no_body_is_left_to_the_shell_check(_validity_classes):
    verdict, _ = _validity(_Shape(solidity={"solids": 0, "volume": None, "valid": None}))
    assert verdict


def test_a_sketch_has_no_answer_to_this_question(_validity_classes):
    verdict, _ = _validity(_Sketch2(solidity={"solids": 1, "volume": 1.0, "valid": False}))
    assert verdict


def test_an_assembly_is_checked_through_its_parts_here_too(_validity_classes):
    verdict, _ = _validity(_Assembly(solidity={"solids": 1, "volume": 1.0, "valid": False}))
    assert verdict


def test_it_cannot_be_silenced_and_does_not_need_to_be(_validity_classes, caplog):
    """'validity' only ever reported - it has never failed anything - so there
    was nothing for a 'skip' to protect a package from, and it takes no
    settings at all now."""
    import logging

    shape = _Shape(config={"validity": {"skip": True}}, solidity={"solids": 1, "volume": 1.0, "valid": False})
    with caplog.at_level(logging.INFO):
        verdict, _ = _validity(shape)
    assert verdict
    assert "not a well formed one" in caplog.text


def test_a_check_that_breaks_says_so_without_failing(_validity_classes, caplog):
    """It does not fail, because this check never fails - but it must not
    pretend the question was answered, and the verdict is not remembered."""
    import logging

    from partcad.test.validity import ValidityTest

    shape = _Shape(raises=Exception("boom"))
    with caplog.at_level(logging.INFO):
        verdict, ctx = _validity(shape)
    assert verdict
    assert "could not be checked" in caplog.text
    assert ctx.get(ValidityTest.NOT_CACHEABLE) is True


def test_nothing_a_package_writes_moves_its_cache_key():
    """It reads the geometry and takes no settings, so there is nothing a
    package can write that changes the answer - and nothing for the key to
    carry."""
    from partcad.test.validity import ValidityTest

    t = ValidityTest()
    assert asyncio.run(t.cache_key_suffix(None, _Shape())) == ""
    assert asyncio.run(t.cache_key_suffix(None, _Shape(config={"validity": {"anything": True}}))) == ""


# --- an assembly somebody has to actually make ------------------------------


def _thing():
    return _Shape()


def test_an_assembly_to_be_made_may_not_place_anything_by_coordinates():
    """A coordinate says where a part ends up, not what holds it there, and
    somebody standing at a bench cannot act on the first of those. The rule for
    an assembly nobody is making is looser - see the test below it."""
    asm = _Assembly(
        children=[
            _Child("base", _thing()),
            _Child("arm", _thing(), located=True),
        ],
        is_manufacturable=True,
    )
    assert not _run(ConnectivityTest(), asm)


def test_the_item_everything_hangs_from_is_placed_by_being_first():
    """It has nothing to connect to, so it says nothing at all: no 'location:',
    which is what the rule is about."""
    asm = _Assembly(
        children=[
            _Child("base", _thing()),
            _Child("arm", _thing(), connection={"target": "base"}),
        ],
        is_manufacturable=True,
    )
    assert _run(ConnectivityTest(), asm)


def test_an_assembly_nobody_is_making_may_still_place_everything_by_coordinates():
    """Unchanged: only meaningful once something in the group does connect."""
    asm = _Assembly(
        children=[
            _Child("base", _thing(), located=True),
            _Child("arm", _thing(), located=True),
        ],
    )
    assert _run(ConnectivityTest(), asm)


def test_the_manufacturable_rule_is_still_turned_off_by_configuration():
    asm = _Assembly(
        children=[
            _Child("base", _thing()),
            _Child("arm", _thing(), located=True),
        ],
        config={"connectivity": {"requireAnchored": False}},
        is_manufacturable=True,
    )
    assert _run(ConnectivityTest(), asm)


def test_whether_it_is_to_be_made_is_part_of_the_connectivity_cache_key():
    """The verdict turns on it, so a cached pass must not be read back for an
    assembly that has since said it is to be made."""
    test = ConnectivityTest()
    made = asyncio.run(test.cache_key_suffix(None, _Assembly(is_manufacturable=True)))
    not_made = asyncio.run(test.cache_key_suffix(None, _Assembly(is_manufacturable=False)))
    assert made != not_made


def test_every_check_agrees_on_how_its_cache_key_is_asked_for():
    """'Test.cache_key_suffix' is awaited, so a check that defines it without
    'async' fails the whole run with "object str can't be used in 'await'
    expression" - and fails it at the point a *different* check is being
    cached, which says nothing about where the mistake is.

    Cheap to assert and awkward to find otherwise: the unit tests call it
    directly and so are happy either way, and an example only breaks once the
    object it belongs to is built.
    """
    import inspect

    from partcad.test.all import tests as registered_tests

    checks = registered_tests(concurrency_cap=8)
    assert checks, "no checks are registered"
    for test in checks:
        suffix = getattr(type(test), "cache_key_suffix", None)
        if suffix is None:
            continue
        assert inspect.iscoroutinefunction(suffix), "%s.cache_key_suffix is not async" % type(test).__name__


def test_an_item_that_says_nothing_at_all_is_reported_too():
    """No 'location:' and no 'connect:' either. The factory gives it an identity
    placement, which is a coordinate like any other and the only one nobody
    chose - so the manufacturable rule has to catch it as well as an explicit
    one."""
    asm = _Assembly(
        children=[
            _Child("base", _thing()),
            _Child("arm", _thing()),
        ],
        is_manufacturable=True,
    )
    assert not _run(ConnectivityTest(), asm)
