#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the telemetry span operations (telemetry.start / telemetry.end)."""

from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.core.session import Session


class FakeSpan:
    def __init__(self, name, attributes):
        self.name = name
        self.attributes = dict(attributes or {})
        self.status = None
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_status(self, status):
        self.status = status

    def end(self):
        self.ended = True


class FakeTracer:
    def __init__(self):
        self.spans = []

    def start_span(self, name, attributes=None):
        span = FakeSpan(name, attributes)
        self.spans.append(span)
        return span


class FakeStatusCode:
    ERROR = "ERROR"
    OK = "OK"


class FakeTrace:
    StatusCode = FakeStatusCode

    @staticmethod
    def Status(code, message=None):
        return (code, message)


class FakeTelemetry:
    def __init__(self):
        self.tracer = FakeTracer()
        self.trace = FakeTrace()
        self.onced = 0

    def once(self):
        self.onced += 1


class FakePartcad:
    def __init__(self):
        self.telemetry = FakeTelemetry()


def _session():
    session = Session()
    session.partcad = FakePartcad()
    return session


def test_telemetry_start_returns_a_span_id_and_starts_a_span():
    session = _session()
    result = operations.telemetry_start(session, {"name": "cli", "attributes": {"command": "info"}})
    assert "span" in result
    tracer = session.partcad.telemetry.tracer
    assert len(tracer.spans) == 1
    assert tracer.spans[0].name == "cli"
    assert tracer.spans[0].attributes["command"] == "info"


def test_telemetry_end_ends_the_started_span():
    session = _session()
    span_id = operations.telemetry_start(session, {"name": "cli"})["span"]
    operations.telemetry_end(session, {"span": span_id})
    assert session.partcad.telemetry.tracer.spans[0].ended is True


def test_telemetry_end_with_error_status_marks_the_span():
    session = _session()
    span_id = operations.telemetry_start(session, {"name": "cli"})["span"]
    operations.telemetry_end(session, {"span": span_id, "status": "error", "message": "boom"})
    span = session.partcad.telemetry.tracer.spans[0]
    assert span.ended is True
    assert span.status == ("ERROR", "boom")


def test_telemetry_end_is_a_noop_for_an_unknown_span():
    session = _session()
    assert operations.telemetry_end(session, {"span": "does-not-exist"}) is None
