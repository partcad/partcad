#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the framed stdio JSON-RPC server loop."""

import io
import threading
import time

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


def _render(session, params):
    """A method answering with a file, as 'render.inline' does."""
    session.emitter.emit(events.ITEMS, {"preview": b"tiny"})
    return {"filename": "a.png", "content": b"\x89PNG"}


def _served(*, accept: bool) -> bytes:
    request_stream = io.BytesIO()
    write_message(request_stream, {"jsonrpc": "2.0", "id": 1, "method": "render"}, accept_attachments=accept)
    request_stream.seek(0)
    response_stream = io.BytesIO()
    stdio.serve(request_stream, response_stream, Session(), {"render": _render})
    return response_stream.getvalue()


def test_a_client_that_reads_attachments_is_sent_its_files_as_bytes():
    # The editor on `partcad.serviceChannel: stdio` says so on every request;
    # the answer and the events of the request it said it on carry raw bytes.
    raw = _served(accept=True)
    assert raw.count(b"Attachment-Lengths:") == 2
    event, answer = _drain(io.BytesIO(raw))
    assert event["params"] == {"preview": b"tiny"}
    assert answer["result"] == {"filename": "a.png", "content": b"\x89PNG"}


def test_a_client_from_before_attachments_is_sent_base64_as_it_always_was():
    # An older extension, or the FreeCAD addon, which say nothing about them.
    raw = _served(accept=False)
    assert b"Attachment-Lengths" not in raw
    event, answer = _drain(io.BytesIO(raw))
    assert event["params"] == {"preview": "dGlueQ=="}
    assert answer["result"] == {"filename": "a.png", "content": "iVBORw=="}


# ---- reading while a request runs ----------------------------------------------
#
# Requests are read on the calling thread and served on another, one at a time
# and in order, so that a '$/cancelRequest' reaches the request it is about.


class _Input(io.BytesIO):
    """Stdin, saying when it has been read to the end."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.read_to_the_end = threading.Event()

    def readline(self, *args):
        line = super().readline(*args)
        if not line:
            self.read_to_the_end.set()
        return line


def _requests(*messages) -> bytes:
    stream = io.BytesIO()
    for message in messages:
        write_message(stream, message)
    return stream.getvalue()


def test_a_queued_request_that_is_cancelled_is_answered_and_never_runs():
    ran = []
    stdin = _Input(
        _requests(
            {"jsonrpc": "2.0", "id": 1, "method": "busy"},
            {"jsonrpc": "2.0", "id": 2, "method": "quick"},
            {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 2}},
        )
    )

    def busy(session, params):
        # Running until every message has been read, the cancellation with them.
        assert stdin.read_to_the_end.wait(30)
        return "done"

    stdout = io.BytesIO()
    stdio.serve(stdin, stdout, Session(), {"busy": busy, "quick": lambda s, p: ran.append(p)})

    answers = _drain(stdout)
    assert answers[0] == {"jsonrpc": "2.0", "id": 2, "error": {"code": -32800, "message": "Request cancelled"}}
    assert answers[1] == {"jsonrpc": "2.0", "id": 1, "result": "done"}
    assert ran == []


def test_a_cancellation_sent_as_a_request_is_answered_as_well():
    """The editor sends '$/cancelRequest' as a notification; a client that sends it with an id waits for an answer."""
    stdin = io.BytesIO(
        _requests(
            {"jsonrpc": "2.0", "id": 7, "method": "$/cancelRequest", "params": {"id": 99}},
            {"jsonrpc": "2.0", "id": 1, "method": "n", "params": {"n": 1}},
        )
    )
    stdout = io.BytesIO()
    stdio.serve(stdin, stdout, Session(), {"n": lambda s, p: p["n"]})
    answers = _drain(stdout)
    assert {"jsonrpc": "2.0", "id": 7, "result": None} in answers
    assert {"jsonrpc": "2.0", "id": 1, "result": 1} in answers


def test_an_answer_that_cannot_be_encoded_is_answered_with_an_error():
    """A closed stream and an answer JSON cannot carry both raise ValueError: only the first may go unanswered."""

    def circular(session, params):
        answer = {}
        answer["itself"] = answer
        return answer

    stdin = io.BytesIO(_requests({"jsonrpc": "2.0", "id": 1, "method": "circular"}))
    stdout = io.BytesIO()
    stdio.serve(stdin, stdout, Session(), {"circular": circular})
    (answer,) = _drain(stdout)
    assert answer["id"] == 1 and answer["error"]["code"] == -32603


def test_everything_asked_is_answered_in_order_before_serving_ends():
    # The end of stdin is the client done sending: what it sent is still owed.
    stdin = io.BytesIO(_requests(*({"jsonrpc": "2.0", "id": n, "method": "n", "params": {"n": n}} for n in range(20))))
    stdout = io.BytesIO()
    stdio.serve(stdin, stdout, Session(), {"n": lambda s, p: p["n"]})
    assert [answer["result"] for answer in _drain(stdout)] == list(range(20))


def test_serving_leaves_no_thread_behind():
    before = set(threading.enumerate())
    stdin = io.BytesIO(_requests({"jsonrpc": "2.0", "id": 1, "method": "n", "params": {"n": 1}}))
    stdio.serve(stdin, io.BytesIO(), Session(), {"n": lambda s, p: p["n"]})
    deadline = time.monotonic() + 30
    while [t for t in threading.enumerate() if t not in before] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert [t for t in threading.enumerate() if t not in before] == []
