#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for attaching a serving process to a debugger (``PC_DEBUGPY``)."""

import os
import socket
import sys
import types

from partcad_service_json_rpc import debugger
from partcad_service_json_rpc.rpc import methods


def test_unset_is_a_no_op(monkeypatch):
    monkeypatch.delenv(debugger.ENV, raising=False)
    monkeypatch.setitem(sys.modules, "debugpy", None)  # importing it would raise
    assert debugger.attach_from_env() is False


def test_address_takes_a_bare_port():
    assert debugger._address("5678") == ("localhost", 5678)
    assert debugger._address("127.0.0.1:5679") == ("127.0.0.1", 5679)


def test_no_debugpy_serves_on(monkeypatch, capsys):
    monkeypatch.setenv(debugger.ENV, "localhost:5678")
    monkeypatch.setitem(sys.modules, "debugpy", None)
    assert debugger.attach_from_env() is False
    assert "debugpy is not installed" in capsys.readouterr().err


def test_no_listener_serves_on(monkeypatch, capsys):
    """A debug session that has ended leaves the variable behind in whatever it
    started; a service started from there must still serve."""

    def refuse(_address):
        raise ConnectionRefusedError("nothing is listening")

    fake = types.SimpleNamespace(configure=lambda **_: None, connect=refuse, wait_for_client=lambda: None)
    monkeypatch.setenv(debugger.ENV, "localhost:5678")
    monkeypatch.setitem(sys.modules, "debugpy", fake)
    assert debugger.attach_from_env() is False
    assert "could not attach" in capsys.readouterr().err


def test_attaches_without_following_subprocesses(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(
        configure=lambda **kw: calls.append(("configure", kw)),
        connect=lambda address: calls.append(("connect", address)),
        wait_for_client=lambda: calls.append(("wait", None)),
    )
    monkeypatch.setenv(debugger.ENV, "localhost:5678")
    monkeypatch.setitem(sys.modules, "debugpy", fake)
    assert debugger.attach_from_env() is True
    assert calls == [("configure", {"subProcess": False}), ("connect", ("localhost", 5678)), ("wait", None)]


def test_status_names_this_package(monkeypatch):
    monkeypatch.delitem(sys.modules, "debugpy", raising=False)
    status = debugger.status(None, {})
    assert status["source"] == os.path.dirname(os.path.abspath(debugger.__file__))
    assert status["pid"] == os.getpid()
    assert status["debugger"] is False


def test_status_reports_an_attached_debugger(monkeypatch):
    monkeypatch.setitem(sys.modules, "debugpy", types.SimpleNamespace(is_client_connected=lambda: True))
    assert debugger.status(None, {})["debugger"] is True


def test_registered():
    assert methods.build_registry()["daemon.debug"].__wrapped__ is debugger.status


def test_a_real_refusal(monkeypatch):
    """The real debugpy, against a port nothing listens on."""
    import pytest

    debugpy = pytest.importorskip("debugpy")
    if debugpy.is_client_connected():
        pytest.skip("already under a debugger")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv(debugger.ENV, "127.0.0.1:%d" % port)
    assert debugger.attach_from_env() is False
