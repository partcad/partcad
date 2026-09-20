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
