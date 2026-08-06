#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the client-side remote logging backend (partcad_utils).

A thin client (the CLI) receives the structured events the daemon forwards and
replays them locally: as plain lines under --no-ansi, or through
:mod:`partcad_utils.logging_ansi_terminal` (colours + progress footer) when ANSI
is wanted.
"""

import io
import logging
from unittest import mock

import partcad_utils.logging as pc_logging
import partcad_utils.logging_remote_client as remote_client


def teardown_function():
    remote_client.fini()


def test_plain_log_event_written_to_stream():
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)

    remote_client.handle(
        {"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "hello client"}
    )

    assert "hello client" in buf.getvalue()


def test_plain_mode_ignores_process_events():
    buf = io.StringIO()
    remote_client.init(want_ansi=False, stream=buf)

    remote_client.handle({"kind": "process_start", "op": "build", "package": "//pkg", "item": None})

    assert buf.getvalue() == ""


def test_ansi_mode_initializes_and_finalizes_ansi_terminal():
    buf = io.StringIO()
    with mock.patch.object(remote_client.logging_ansi_terminal, "init") as m_init, mock.patch.object(
        remote_client.logging_ansi_terminal, "fini"
    ) as m_fini:
        remote_client.init(want_ansi=True, stream=buf)
        m_init.assert_called_once()

        remote_client.fini()
        m_fini.assert_called_once()


def test_ansi_process_event_replayed_through_ops():
    buf = io.StringIO()
    remote_client.init(want_ansi=True, stream=buf)
    try:
        with mock.patch.object(pc_logging.ops, "process_start") as m:
            remote_client.handle(
                {"kind": "process_start", "op": "build", "package": "//pkg", "item": "x"}
            )
            m.assert_called_once_with("build", "//pkg", "x")
    finally:
        remote_client.fini()
