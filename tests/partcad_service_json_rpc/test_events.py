#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the transport-agnostic event emitter."""

from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.events import EventEmitter


def test_emit_forwards_event_and_payload_to_sink():
    seen = []
    emitter = EventEmitter(lambda event, payload: seen.append((event, payload)))
    emitter.emit("items", {"name": "//"})
    assert seen == [("items", {"name": "//"})]


def test_emit_without_sink_is_a_noop():
    EventEmitter().emit("info", "no sink attached")  # must not raise


def test_set_sink_binds_a_sink_after_construction():
    seen = []
    emitter = EventEmitter()
    emitter.set_sink(lambda event, payload: seen.append((event, payload)))
    emitter.emit("stats", {"packages": 1})
    assert seen == [("stats", {"packages": 1})]


def test_convenience_methods_use_the_documented_event_names():
    seen = []
    emitter = EventEmitter(lambda e, p: seen.append((e, p)))
    emitter.info("hi")
    emitter.warning("careful")
    emitter.error("boom")
    assert seen == [
        (events.INFO, "hi"),
        (events.WARNING, "careful"),
        (events.ERROR, "boom"),
    ]


def test_signal_methods_emit_lifecycle_events_without_payload():
    seen = []
    emitter = EventEmitter(lambda e, p: seen.append((e, p)))
    emitter.signal(events.SHOW_PART_DONE)
    emitter.signal(events.PACKAGE_LOAD_FAILED)
    assert seen == [
        (events.SHOW_PART_DONE, None),
        (events.PACKAGE_LOAD_FAILED, None),
    ]
