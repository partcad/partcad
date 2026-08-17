#!/usr/bin/env python3
#
# OpenVMP, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc
from partcad.assembly_connect import (
    DEFAULT_PUSH_TORQUE_MAX,
    DEFAULT_THREAD_STEP,
    DEFAULT_TURN_DIRECTION,
    DEFAULT_TURN_TORQUE_MAX,
    ConnectHold,
    ConnectHow,
)

# A package whose ASSY file exercises "comment" and "how", and whose parts carry
# the "hold"/"holdInstance" defaults those sections fall back to.
CONNECT_HOW_PACKAGE = "partcad/tests/unit/data/connect_how/partcad.yaml"


class _FakeWithPorts:
    def __init__(self, interfaces):
        self.interfaces = interfaces

    def get_interfaces(self):
        return self.interfaces


class _FakeItem:
    """The bare minimum of a part or an assembly that 'ConnectHow' looks at."""

    def __init__(self, config=None, interfaces=None, project_name="//test"):
        self.config = config or {}
        self.project_name = project_name
        self.with_ports = None if interfaces is None else _FakeWithPorts(interfaces)


def _plate(config=None):
    return _FakeItem(
        config,
        {
            "//test:grip": {"left": {"grip": "left-grip"}, "right": {"grip": "right-grip"}},
            "//test:m3-thru": {"TL": {"m3": "TL-m3"}, "TR": {"m3": "TR-m3"}},
        },
    )


def test_connect_how_defaults():
    """An omitted 'how' section means every documented default"""
    how = ConnectHow(None).resolve()
    assert how.specified is False
    assert how.is_default()
    assert how.push_torque_max == DEFAULT_PUSH_TORQUE_MAX == 5.0
    assert how.turn_direction == DEFAULT_TURN_DIRECTION == "cw"
    assert how.turn_torque_max == DEFAULT_TURN_TORQUE_MAX == 0.0
    assert how.thread_step == DEFAULT_THREAD_STEP == 0.0
    assert how.hold_with == []
    assert how.hold_to == []


def test_connect_how_partial():
    """The fields that are not given keep their defaults"""
    how = ConnectHow({"turnDirection": "CCW", "turnTorqueMax": 1.5}).resolve()
    assert how.specified is True
    assert not how.is_default()
    assert how.turn_direction == "ccw"
    assert how.turn_torque_max == 1.5
    assert how.push_torque_max == DEFAULT_PUSH_TORQUE_MAX
    assert how.thread_step == DEFAULT_THREAD_STEP


def test_connect_how_all_fields():
    how = ConnectHow(
        {
            "pushTorqueMax": 2.5,
            "turnDirection": "ccw",
            "turnTorqueMax": 1.2,
            "threadStep": 0.5,
        }
    ).resolve()
    assert how.push_torque_max == 2.5
    assert how.turn_direction == "ccw"
    assert how.turn_torque_max == 1.2
    assert how.thread_step == 0.5
    assert how.info() == {
        "pushTorqueMax": 2.5,
        "turnDirection": "ccw",
        "turnTorqueMax": 1.2,
        "threadStep": 0.5,
    }


def test_connect_how_invalid_values_fall_back_to_defaults():
    """Invalid values are reported, but they never break the assembly"""
    how = ConnectHow(
        {
            "pushTorqueMax": "a lot",
            "turnDirection": "widdershins",
            "turnTorqueMax": -1.0,
            "threadStep": None,
            "typo": 1,
        }
    ).resolve()
    assert how.push_torque_max == DEFAULT_PUSH_TORQUE_MAX
    assert how.turn_direction == DEFAULT_TURN_DIRECTION
    assert how.turn_torque_max == DEFAULT_TURN_TORQUE_MAX
    assert how.thread_step == DEFAULT_THREAD_STEP


def test_connect_how_hold_explicit():
    """'holdWith'/'holdTo' name the interfaces to hold each end by"""
    how = ConnectHow({"holdWith": "grip", "holdTo": "grip", "holdToInstance": "left"})
    how.resolve(_plate(), _plate())
    assert how.hold_with == [ConnectHold("//test:grip", "left")]
    assert how.hold_to == [ConnectHold("//test:grip", "left")]


def test_connect_how_hold_list():
    """Both ends may be held by more than one interface"""
    how = ConnectHow(
        {
            "holdWith": ["grip", "m3-thru"],
            "holdWithInstance": ["right", "TR"],
        }
    )
    how.resolve(_plate(), None)
    assert how.hold_with == [
        ConnectHold("//test:grip", "right"),
        ConnectHold("//test:m3-thru", "TR"),
    ]


def test_connect_how_hold_defaults_to_the_object_definition():
    """An omitted 'holdWith'/'holdTo' falls back to the object's own 'hold'"""
    how = ConnectHow({})
    how.resolve(
        _plate({"hold": "grip", "holdInstance": "right"}),
        _plate({"hold": ["m3-thru"], "holdInstance": ["TL"]}),
    )
    assert how.hold_with == [ConnectHold("//test:grip", "right")]
    assert how.hold_to == [ConnectHold("//test:m3-thru", "TL")]
    # A default hold is worth reporting even when nothing else was specified.
    assert not how.is_default()


def test_connect_how_hold_instance_defaults_to_the_first_one():
    """Without a 'holdInstance' anywhere, the first instance is used"""
    how = ConnectHow({"holdWith": "grip"})
    how.resolve(_plate(), None)
    assert how.hold_with == [ConnectHold("//test:grip", "left")]


def test_connect_how_hold_instance_from_the_object_definition():
    """'holdInstance' applies even when the ASSY file overrides the interface"""
    how = ConnectHow({"holdWith": "grip"})
    how.resolve(_plate({"hold": "grip", "holdInstance": "right"}), None)
    assert how.hold_with == [ConnectHold("//test:grip", "right")]


def test_connect_how_hold_unknown_interface_is_kept():
    """An interface the object does not implement is reported, not dropped"""
    how = ConnectHow({"holdWith": "nonexistent"})
    how.resolve(_plate(), None)
    assert how.hold_with == [ConnectHold("nonexistent", None)]


def test_connect_how_hold_unknown_instance_falls_back():
    how = ConnectHow({"holdWith": "grip", "holdWithInstance": "nonexistent"})
    how.resolve(_plate(), None)
    assert how.hold_with == [ConnectHold("//test:grip", "left")]


def test_connect_how_hold_without_interface_metadata():
    """An object with no interfaces at all is not a reason to fail"""
    how = ConnectHow({"holdWith": "grip", "holdWithInstance": "left"})
    how.resolve(_FakeItem(), None)
    assert how.hold_with == [ConnectHold("grip", "left")]


def _get_children(assembly):
    """The nodes of the ASSY file's top level 'links:', by name.

    The top level container node of an ASSY file becomes an unnamed child
    assembly of the object it defines, so the parts are one level down.
    """
    asyncio.run(assembly.do_instantiate())
    assert len(assembly.children) == 1
    return {child.name: child for child in assembly.children[0].item.children}


def test_assy_connect_comment_and_how():
    """'comment' and 'how' survive the ASSY file all the way to the children"""
    ctx = pc.init(CONNECT_HOW_PACKAGE)
    assembly = ctx._get_assembly(":connect_how")
    assert assembly is not None

    children = _get_children(assembly)
    assert sorted(children.keys()) == ["plate", "screw-tl", "screw-tr"]

    # A child placed without a "connect*" section carries neither
    plate = children["plate"]
    assert plate.comment is None
    assert plate.how is None
    assert plate.connect_info() is None

    explicit = children["screw-tl"]
    assert explicit.comment.startswith("Start this screw by hand")
    assert explicit.how.push_torque_max == 2.5
    assert explicit.how.turn_direction == "ccw"
    assert explicit.how.turn_torque_max == 1.2
    assert explicit.how.thread_step == 0.5
    assert [hold.interface.split(":")[-1] for hold in explicit.how.hold_with] == ["grip"]
    assert [hold.interface.split(":")[-1] for hold in explicit.how.hold_to] == ["grip"]
    assert [hold.instance for hold in explicit.how.hold_to] == ["left"]

    info = explicit.connect_info()
    assert info["name"] == "screw-tl"
    assert info["comment"] == explicit.comment
    assert info["how"]["threadStep"] == 0.5


def test_assy_connect_how_defaults_from_the_part_definition():
    """The parts' own 'hold'/'holdInstance' are the defaults for 'how'"""
    ctx = pc.init(CONNECT_HOW_PACKAGE)
    assembly = ctx._get_assembly(":connect_how")
    assert assembly is not None

    implicit = _get_children(assembly)["screw-tr"]
    assert implicit.comment is None
    assert implicit.how.thread_step == 0.5
    # Not given in the ASSY file: the screw is held by its own "hold: grip",
    # and the plate by "hold: grip" with "holdInstance: right".
    assert [hold.interface.split(":")[-1] for hold in implicit.how.hold_with] == ["grip"]
    assert [hold.interface.split(":")[-1] for hold in implicit.how.hold_to] == ["grip"]
    assert [hold.instance for hold in implicit.how.hold_to] == ["right"]
