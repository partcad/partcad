#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the framed stdio JSON-RPC server loop."""

import io

from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport import stdio
from partcad_utils.framing import read_message, write_message


def _drain(stream: io.BytesIO) -> list:
    stream.seek(0)
    out = []
    while True:
        message = read_message(stream)
        if message is None:
            break
        out.append(message)
    return out


def test_serve_dispatches_a_request_and_frames_the_response():
    request_stream = io.BytesIO()
    write_message(request_stream, {"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": {}})
    request_stream.seek(0)
    response_stream = io.BytesIO()

    stdio.serve(request_stream, response_stream, Session(), {"rpc.discover": lambda s, p: {"ok": True}})

    responses = _drain(response_stream)
    assert responses == [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}]


def test_serve_writes_emitted_events_as_notifications_before_the_response():
    request_stream = io.BytesIO()
    write_message(request_stream, {"jsonrpc": "2.0", "id": 9, "method": "go", "params": {}})
    request_stream.seek(0)
    response_stream = io.BytesIO()

    def handler(session, params):
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return "done"

    stdio.serve(request_stream, response_stream, Session(), {"go": handler})

    messages = _drain(response_stream)
    assert messages[0] == {"jsonrpc": "2.0", "method": events.ITEMS, "params": {"name": "//"}}
    assert messages[1] == {"jsonrpc": "2.0", "id": 9, "result": "done"}


def test_serve_stops_at_eof_without_writing_anything():
    response_stream = io.BytesIO()
    stdio.serve(io.BytesIO(b""), response_stream, Session(), {})
    assert response_stream.getvalue() == b""
