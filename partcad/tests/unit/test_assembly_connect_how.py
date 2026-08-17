#!/usr/bin/env python3
#
# OpenVMP, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import partcad as pc
from partcad import measure
from partcad.assembly_connect import (
    DEFAULT_PUSH_FORCE_MAX,
    DEFAULT_THREAD_STEP,
    DEFAULT_TURN_DIRECTION,
    DEFAULT_TURN_TORQUE_MAX,
    HOW_FIELDS_DEPRECATED,
    PUSH_DISTANCE_FACTOR,
    ConnectHold,
    ConnectHow,
    check_stage_sequence,
)
from partcad.geom import Location

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

    def __init__(self, config=None, interfaces=None, project_name="//test", name="fake", wrapped=None):
        self.config = config or {}
        self.project_name = project_name
        self.name = name
        self.with_ports = None if interfaces is None else _FakeWithPorts(interfaces)
        self._wrapped = wrapped

    async def get_wrapped(self, ctx):
        return self._wrapped


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
    assert how.push_force_max == DEFAULT_PUSH_FORCE_MAX == 5.0
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
    assert how.push_force_max == DEFAULT_PUSH_FORCE_MAX
    assert how.thread_step == DEFAULT_THREAD_STEP


def test_connect_how_all_fields():
    how = ConnectHow(
        {
            "pushForceMax": 2.5,
            "turnDirection": "ccw",
            "turnTorqueMax": 1.2,
            "threadStep": 0.5,
        }
    ).resolve()
    assert how.push_force_max == 2.5
    assert how.turn_direction == "ccw"
    assert how.turn_torque_max == 1.2
    assert how.thread_step == 0.5
    assert how.info() == {
        "pushForceMax": 2.5,
        "pushDistance": None,
        "turnDirection": "ccw",
        "turnTorqueMax": 1.2,
        "threadStep": 0.5,
    }


def test_connect_how_invalid_values_fall_back_to_defaults():
    """Invalid values are reported, but they never break the assembly"""
    how = ConnectHow(
        {
            "pushForceMax": "a lot",
            "turnDirection": "widdershins",
            "turnTorqueMax": -1.0,
            "threadStep": None,
            "typo": 1,
        }
    ).resolve()
    assert how.push_force_max == DEFAULT_PUSH_FORCE_MAX
    assert how.turn_direction == DEFAULT_TURN_DIRECTION
    assert how.turn_torque_max == DEFAULT_TURN_TORQUE_MAX
    assert how.thread_step == DEFAULT_THREAD_STEP


def test_connect_how_deprecated_field_still_works():
    """A push is a force: the old 'pushTorqueMax' spelling still means it"""
    assert HOW_FIELDS_DEPRECATED["pushTorqueMax"] == "pushForceMax"
    how = ConnectHow({"pushTorqueMax": 2.5}).resolve()
    assert how.push_force_max == 2.5
    assert how.info() == {
        "pushForceMax": 2.5,
        "pushDistance": None,
        "turnDirection": DEFAULT_TURN_DIRECTION,
        "turnTorqueMax": DEFAULT_TURN_TORQUE_MAX,
        "threadStep": DEFAULT_THREAD_STEP,
    }


def test_connect_how_new_field_wins_over_the_deprecated_one():
    how = ConnectHow({"pushTorqueMax": 2.5, "pushForceMax": 7.5}).resolve()
    assert how.push_force_max == 7.5


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


def test_connect_how_stage():
    """'stage' is a free-form label naming the steps performed together"""
    assert ConnectHow({"stage": "snug"}).resolve().stage == "snug"
    assert ConnectHow({}).resolve().stage is None
    # A bare number in YAML is a natural way to name a stage.
    assert ConnectHow({"stage": 2}).resolve().stage == "2"
    # Anything that cannot be a label is reported and dropped.
    assert ConnectHow({"stage": ["a", "b"]}).resolve().stage is None
    assert ConnectHow({"stage": "snug"}).resolve().info()["stage"] == "snug"
    assert "stage" not in ConnectHow({}).resolve().info()


def _staged(*stages):
    return [{"part": "p", "connect": {"name": "t", "how": {"stage": stage}}} for stage in stages]


def test_check_stage_sequence_contiguous(caplog):
    """Nodes sharing a stage in one uninterrupted run are what the format means"""
    check_stage_sequence(_staged("snug", "snug", "final", "final"), "test")
    assert "not contiguous" not in caplog.text


def test_check_stage_sequence_interrupted(caplog):
    """A stage that resumes after another one is reported: it is not sequential"""
    check_stage_sequence(_staged("snug", "final", "snug"), "test")
    assert "not contiguous" in caplog.text


def test_check_stage_sequence_ignores_unstaged_nodes():
    """Nodes without a 'connect*' section, or without a stage, are just skipped"""
    check_stage_sequence([{"part": "p", "location": [[0, 0, 0], [0, 0, 1], 0]}], "test")


def test_connect_how_push_distance_explicit():
    """An explicit 'pushDistance' is taken as given, and nothing is measured"""
    how = ConnectHow({"pushDistance": 12.0})
    how.resolve(_FakeItem(wrapped={"brep": "..."}), None, source_frame=Location((0, 0, 5), (0, 0, 1), 0))
    assert how.push_distance == 12.0
    assert how.push_distance_specified
    assert asyncio.run(how.resolve_push_distance(ctx=object())) == 12.0
    assert how.info()["pushDistance"] == 12.0


def _measured(monkeypatch, length):
    """Stand in for the sandboxed measurement, recording what it was asked."""
    from partcad import assembly_connect

    assembly_connect._extent_cache.clear()
    calls = []

    async def fake_extent_z(ctx, shape, frame=None):
        calls.append((shape, frame))
        return length

    monkeypatch.setattr(measure, "extent_z", fake_extent_z)
    return calls


def test_connect_how_push_distance_derived(monkeypatch):
    """Without one, the distance is 1.5 x the object's length along the port Z"""
    calls = _measured(monkeypatch, 8.0)
    frame = Location((0, 0, 5), (0, 0, 1), 0)
    how = ConnectHow({})
    how.resolve(_FakeItem(wrapped={"brep": "..."}), None, source_frame=frame)

    assert how.push_distance is None
    assert not how.push_distance_specified
    assert asyncio.run(how.resolve_push_distance(ctx=object())) == PUSH_DISTANCE_FACTOR * 8.0 == 12.0
    assert how.push_distance == 12.0
    # Measured in the frame of the interface the object is connected by.
    assert len(calls) == 1
    assert calls[0][1] is frame


def test_connect_how_push_distance_measured_once_per_object_and_frame(monkeypatch):
    """A bolt pattern measures the same screw through the same port only once"""
    calls = _measured(monkeypatch, 8.0)
    frame = Location((0, 0, 5), (0, 0, 1), 0)
    for _ in range(4):
        how = ConnectHow({})
        how.resolve(_FakeItem(wrapped={"brep": "..."}), None, source_frame=frame)
        assert asyncio.run(how.resolve_push_distance(ctx=object())) == 12.0
    assert len(calls) == 1


def test_connect_how_push_distance_without_geometry(monkeypatch):
    """An object whose geometry cannot be built leaves the distance underived"""
    _measured(monkeypatch, 8.0)
    how = ConnectHow({})
    how.resolve(_FakeItem(wrapped=None), None, source_frame=None)
    assert asyncio.run(how.resolve_push_distance(ctx=object())) is None
    assert how.push_distance is None


def test_connect_how_push_distance_measurement_failure_is_not_fatal(monkeypatch):
    """A CAD runtime that is missing or fails does not fail the assembly"""
    from partcad import assembly_connect

    assembly_connect._extent_cache.clear()

    async def boom(ctx, shape, frame=None):
        raise Exception("no CAD runtime here")

    monkeypatch.setattr(measure, "extent_z", boom)
    how = ConnectHow({})
    how.resolve(_FakeItem(wrapped={"brep": "..."}), None, source_frame=None)
    assert asyncio.run(how.resolve_push_distance(ctx=object())) is None


def test_measure_in_frame_moves_the_shape_into_the_frame():
    """Measuring in a frame is measuring the shape moved by that frame's inverse"""
    shape = {"brep": "..."}
    placed = measure.in_frame(shape, Location((0, 0, 5), (0, 0, 1), 0))
    assert shape == {"brep": "..."}  # the caller's envelope is left alone
    translation, _, _ = placed["location"]
    assert translation == [0.0, 0.0, -5.0]
    assert measure.in_frame(shape, None) is shape


def _get_children(assembly):
    """The nodes of the ASSY file's top level 'links:', by name.

    The top level container node of an ASSY file becomes an unnamed child
    assembly of the object it defines, so the parts are one level down.
    """
    asyncio.run(assembly.do_instantiate())
    assert len(assembly.children) == 1
    return {child.name: child for child in assembly.children[0].item.children}


def test_assy_connected_children_sees_through_the_links_container():
    """The connections of an ASSY file belong to the object the file defines"""
    ctx = pc.init(CONNECT_HOW_PACKAGE)
    assembly = ctx._get_assembly(":connect_how")
    asyncio.run(assembly.do_instantiate())

    # The file's top level "links:" is one unnamed child assembly...
    assert [child.name for child in assembly.children] == [None]
    # ...but its connections are reported as the assembly's own.
    named = [child.name for child in assembly.connected_children() if child.name is not None]
    assert sorted(named) == ["plate", "screw-tl", "screw-tr"]
    connected = [child.name for child in assembly.connected_children() if child.connect_info() is not None]
    assert sorted(connected) == ["screw-tl", "screw-tr"]


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
    assert explicit.how.stage == "snug"
    assert explicit.how.push_force_max == 2.5
    assert explicit.how.push_distance == 12.0
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


def _stub_geometry(monkeypatch):
    """Stand in for building a part, which needs a CAD runtime these tests lack."""
    from partcad.shape import Shape

    async def fake_get_wrapped(self, ctx):
        return {"brep": "..."}

    monkeypatch.setattr(Shape, "get_wrapped", fake_get_wrapped)


def test_assy_connect_push_distance_is_derived_from_the_part(monkeypatch):
    """Instantiating leaves 'pushDistance' underived; resolving it measures the part"""
    calls = _measured(monkeypatch, 6.0)
    _stub_geometry(monkeypatch)
    ctx = pc.init(CONNECT_HOW_PACKAGE)
    assembly = ctx._get_assembly(":connect_how")
    assert assembly is not None

    asyncio.run(assembly.do_instantiate())
    children = {child.name: child for child in assembly.connected_children()}

    # Instantiating an assembly builds no geometry, so nothing is measured yet.
    assert calls == []
    assert children["screw-tr"].how.push_distance is None

    # Resolved from the object the ASSY file defines, not from the unnamed
    # assembly its "links:" became.
    asyncio.run(assembly.resolve_connect_metadata(ctx))
    assert children["screw-tr"].how.push_distance == PUSH_DISTANCE_FACTOR * 6.0 == 9.0
    # The screw is measured along its own port frame, not in its own coordinates.
    assert calls[0][1] is not None
    # The explicit distance is left alone, so only the derived one was measured.
    assert children["screw-tl"].how.push_distance == 12.0
    assert len(calls) == 1
