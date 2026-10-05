#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an assembly's joints say about the overlaps inside it, read the way the geometry is named.

The interference check is handed a tree and reports pairs of parts in it by
their path. What excuses a pair has to be named the same way, at whatever
depth the joint that declares it is written, and through whatever 'map:' the
joined port comes from - which is what is checked here, on real 'Assembly'
objects with nothing built.
"""

import asyncio
from types import SimpleNamespace

from partcad.assembly import Assembly
from partcad.test import interference
from partcad.test.interference import InterferenceTest


def _assembly(name, children=(), config=None, container=False):
    asm = Assembly.__new__(Assembly)
    asm.name = name
    asm.project_name = "//pkg"
    asm.config = dict(config or {})
    if container:
        asm.config["child"] = True
    asm.children = list(children)

    async def instantiated():
        return None

    asm.do_instantiate = instantiated
    return asm


def _part(name):
    return SimpleNamespace(name=name)


def _link(name, item, connection=None, how=None):
    return SimpleNamespace(name=name, item=item, connection=connection, how=how)


SNAP = SimpleNamespace(snap_in=True, self_screw=False)


def _joint(target, with_port=None, to_port=None, interferes=()):
    return {
        "target": target,
        "with_port": with_port,
        "to_port": to_port,
        "with_interface": None,
        "to_interface": None,
        "interferes": list(interferes),
    }


def _plan(shape):
    return asyncio.run(interference._plan(None, shape))


def test_a_joint_through_a_mapped_port_names_the_part_that_provides_it():
    # car -> front-end (maps front-frame's port) -> front-frame (maps a pin's end) -> pin
    front_frame = _assembly(
        "front-frame",
        [_link("rail", _part("rail")), _link("pin-nose", _part("2780"))],
        config={"map": {"pin-nose-left": ["pin-nose", "//lego:technic-pin", "left"]}},
    )
    front_end = _assembly(
        "front-end",
        [_link("front-frame", front_frame)],
        config={"map": {"ff-pin-nose-left": ["front-frame", "//lego:technic-pin", "pin-nose-left"]}},
    )
    tub = _assembly("tub", [_link("rail-up", _part("beam"))], config={"map": {"rail-up-h12": ["rail-up", "h12"]}})
    car = _assembly(
        "car",
        [
            _link("tub", tub),
            _link("front-end", front_end, _joint("tub", "ff-pin-nose-left-pin", "rail-up-h12"), SNAP),
        ],
    )
    plan = _plan(car)
    assert plan.expected == {("front-end/front-frame/pin-nose", "tub/rail-up")}
    assert sorted(plan.opaque) == ["front-end", "tub"]


def test_interferes_keeps_the_pair_of_subtrees_it_names():
    battery = _assembly("battery", [_link("box", _part("box"))])
    frame = _assembly("frame", [_link("rail", _part("rail"))])
    tub = _assembly(
        "tub",
        [_link("battery", battery), _link("frame", frame, _joint("battery", interferes=["battery"]))],
    )
    assert _plan(tub).expected == {("frame", "battery")}


def test_interferes_reaches_a_link_inside_a_named_container():
    group = _assembly("group", [_link("bracket", _part("bracket"))], container=True)
    asm = _assembly(
        "asm",
        [
            _link("group", group),
            _link("screw", _part("screw"), _joint("plate", interferes=["group/bracket"])),
            _link("plate", _part("plate")),
        ],
    )
    plan = _plan(asm)
    assert plan.expected == {("screw", "group/bracket")}
    assert plan.opaque == []  # a container is part of the assembly that holds it


def test_interferes_names_a_link_that_has_no_name_of_its_own_by_its_position():
    """A container that named itself nothing is 'link#1', and so is a level of the path.

    It used to be unaddressable, and what was inside it was named as if it were
    not there - which made two brackets in two such containers one name. Every
    link has a name now (see 'Assembly.link_name'), so the container is named
    and the bracket is 'link#1/bracket'.
    """
    unnamed = _assembly("asm:links", [_link("bracket", _part("bracket"))], container=True)
    asm = _assembly(
        "asm",
        [
            _link(None, unnamed),
            _link("screw", _part("screw"), _joint("plate", interferes=["link#1/bracket"])),
            _link("plate", _part("plate")),
        ],
    )
    plan = _plan(asm)
    assert plan.problems == []
    assert plan.expected == {("screw", "link#1/bracket")}

    # The container itself is nameable as a whole, by that same name.
    whole = _assembly(
        "asm",
        [_link(None, unnamed), _link("screw", _part("screw"), _joint("plate", interferes=["link#1"]))],
    )
    assert _plan(whole).expected == {("screw", "link#1")}

    # What is no link of it is still reported, and is no longer reported as a
    # link that merely has no name.
    wrong = _assembly(
        "asm",
        [_link(None, unnamed), _link("screw", _part("screw"), _joint("plate", interferes=["bracket"]))],
    )
    problems = _plan(wrong).problems
    assert problems and "which is not a link" in problems[0]


def test_a_declared_subassembly_answers_for_its_own_inside_once_however_often_it_is_placed(monkeypatch):
    sidepod = _assembly("sidepod", [_link("panel", _part("panel"))])
    car = _assembly("car", [_link("sidepod-l", sidepod), _link("sidepod-r", sidepod)])
    asked = []

    async def verdict(self, tests, ctx, shape, test_ctx={}):
        asked.append(shape.name)
        return False  # the sidepod fails on its own

    monkeypatch.setattr(InterferenceTest, "test_cached", verdict)

    async def nothing(*args, **kwargs):
        return {"overlaps": [], "unchecked": [], "indeterminate": [], "parts": 0}

    car.get_interference_async = nothing
    assert asyncio.run(InterferenceTest().test([], None, car, {})) is False
    assert asked == ["sidepod"]


# --- an assembly's own box -------------------------------------------------


class _Measured:
    """A part as it is once built: it recorded its box, and is never asked to build again."""

    def __init__(self, box):
        self._box = box

    async def get_measurements_async(self, ctx):
        return {"bbox": list(self._box)}

    async def get_bounding_box_async(self, ctx):
        raise AssertionError("a part's box is the one it recorded")


def test_an_assembly_box_is_its_childrens_boxes_where_it_puts_them():
    from partcad.geom import Location

    cube = _Measured((0.0, 0.0, 0.0, 10.0, 10.0, 10.0))
    inner = _assembly(
        "inner",
        [
            SimpleNamespace(name="a", item=cube, location=None),
            # moved 100 along x
            SimpleNamespace(name="b", item=cube, location=Location([[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0])),
        ],
        container=True,
    )
    inner._bounding_box = None
    inner.location = None
    outer = _assembly(
        "outer",
        [
            SimpleNamespace(name="inner", item=inner, location=None),
            # turned a quarter about z: x and y swap, x negated
            SimpleNamespace(name="c", item=cube, location=Location([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 90.0])),
        ],
    )
    outer._bounding_box = None
    outer.location = [[0.0, 0.0, 5.0], [0.0, 0.0, 1.0], 0.0]  # and the whole lifted 5 in z

    box = asyncio.run(outer.get_bounding_box_async(None))
    assert [round(v, 6) + 0.0 for v in box] == [-10.0, 0.0, 5.0, 110.0, 10.0, 15.0]
    assert [round(v, 6) + 0.0 for v in asyncio.run(inner.get_bounding_box_async(None))] == [
        0.0,
        0.0,
        0.0,
        110.0,
        10.0,
        10.0,
    ]
