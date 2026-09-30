#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The telemetry opt-out is a switch that something acts on.

'telemetry.type' is documented three ways ('pc system set telemetry type none',
'telemetry: type: none', PC_TELEMETRY_TYPE) and used to be written, read back by
'pc system telemetry info', and consulted by nothing that collects. These cover
the one function that now decides.
"""

from partcad_utils import telemetry


def test_collecting_by_default(monkeypatch):
    monkeypatch.delenv("PC_TELEMETRY_TYPE", raising=False)
    assert telemetry.collecting() is True


def test_not_collecting_when_opted_out(monkeypatch):
    monkeypatch.setenv("PC_TELEMETRY_TYPE", "none")
    assert telemetry.collecting() is False


def test_collecting_when_a_backend_is_named(monkeypatch):
    monkeypatch.setenv("PC_TELEMETRY_TYPE", "sentry")
    assert telemetry.collecting() is True


def test_method_spans_are_off_by_default(monkeypatch):
    monkeypatch.delenv("PC_TELEMETRY_DETAIL", raising=False)
    telemetry.forget_settings()
    assert telemetry.method_spans() is False


def test_method_spans_when_asked_for(monkeypatch):
    monkeypatch.setenv("PC_TELEMETRY_DETAIL", telemetry.DETAIL_METHODS)
    telemetry.forget_settings()
    try:
        assert telemetry.method_spans() is True
    finally:
        telemetry.forget_settings()


def test_an_instrumented_method_is_called_either_way(monkeypatch):
    """The gate decides whether there is a span, never whether there is a call."""

    class Subject:
        def double(self, value):
            return value * 2

    instrumented = telemetry.instrument()(type("Subject", (Subject,), {"double": Subject.double}))

    for detail, expected in ((telemetry.DETAIL_ACTIONS, False), (telemetry.DETAIL_METHODS, True)):
        monkeypatch.setenv("PC_TELEMETRY_DETAIL", detail)
        telemetry.forget_settings()
        assert telemetry.method_spans() is expected
        assert instrumented().double(21) == 42
    telemetry.forget_settings()


def test_an_instrumented_function_is_called_either_way(monkeypatch):
    calls = []

    @telemetry.instrument_function("subject")
    def subject(value):
        calls.append(value)
        return value + 1

    for detail in (telemetry.DETAIL_ACTIONS, telemetry.DETAIL_METHODS):
        monkeypatch.setenv("PC_TELEMETRY_DETAIL", detail)
        telemetry.forget_settings()
        assert subject(1) == 2
    telemetry.forget_settings()
    assert calls == [1, 1]
