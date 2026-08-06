#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the LSP-style Content-Length JSON-RPC framing codec."""

import io

from partcad_service_json_rpc.transport.framing import read_message, write_message


def test_write_message_emits_content_length_header_and_blank_line():
    buf = io.BytesIO()
    write_message(buf, {"jsonrpc": "2.0", "id": 1, "result": None})
    data = buf.getvalue()
    assert data.startswith(b"Content-Length: ")
    header, body = data.split(b"\r\n\r\n", 1)
    assert b"Content-Length: %d" % len(body) in header


def test_read_message_round_trips_a_written_message():
    buf = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 7, "method": "info", "params": {"a": 1}}
    write_message(buf, message)
    buf.seek(0)
    assert read_message(buf) == message


def test_read_message_reads_two_consecutive_messages():
    buf = io.BytesIO()
    first = {"jsonrpc": "2.0", "id": 1, "method": "a"}
    second = {"jsonrpc": "2.0", "id": 2, "method": "b"}
    write_message(buf, first)
    write_message(buf, second)
    buf.seek(0)
    assert read_message(buf) == first
    assert read_message(buf) == second


def test_read_message_returns_none_at_eof():
    assert read_message(io.BytesIO(b"")) is None


def test_read_message_handles_non_ascii_payload_via_content_length_bytes():
    buf = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 3, "result": "café ☕"}
    write_message(buf, message)
    buf.seek(0)
    assert read_message(buf) == message
