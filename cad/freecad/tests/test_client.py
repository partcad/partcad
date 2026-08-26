#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The JSON-RPC client, driven over in-memory streams."""

import io
import json

import pytest
from partcad_freecad.client import JsonRpcClient, ServiceError
from partcad_freecad.framing import read_message, write_message


def _stream(*messages):
    stream = io.BytesIO()
    for message in messages:
        write_message(stream, message)
    stream.seek(0)
    return stream


def _requests(stream):
    stream.seek(0)
    out = []
    while True:
        message = read_message(stream)
        if message is None:
            return out
        out.append(message)


def test_call_returns_the_result():
    outgoing = io.BytesIO()
    client = JsonRpcClient(_stream({"jsonrpc": "2.0", "id": 1, "result": {"loaded": True}}), outgoing)

    assert client.call("ensure_loaded", {"path": "/w"}) == {"loaded": True}
    assert _requests(outgoing) == [{"jsonrpc": "2.0", "id": 1, "method": "ensure_loaded", "params": {"path": "/w"}}]


def test_missing_params_are_sent_as_an_empty_object():
    outgoing = io.BytesIO()
    client = JsonRpcClient(_stream({"jsonrpc": "2.0", "id": 1, "result": None}), outgoing)

    client.call("info")

    assert _requests(outgoing)[0]["params"] == {}


def test_notifications_are_forwarded_until_the_response():
    events = []
    client = JsonRpcClient(
        _stream(
            {"jsonrpc": "2.0", "method": "info", "params": "loading"},
            {"jsonrpc": "2.0", "method": "items", "params": {"name": "//"}},
            {"jsonrpc": "2.0", "id": 1, "result": None},
        ),
        io.BytesIO(),
    )

    client.call("list.all", {"name": "//"}, on_event=lambda method, params: events.append((method, params)))

    assert events == [("info", "loading"), ("items", {"name": "//"})]


def test_a_response_to_another_request_is_ignored():
    client = JsonRpcClient(
        _stream(
            {"jsonrpc": "2.0", "id": 99, "result": "stale"},
            {"jsonrpc": "2.0", "id": 1, "result": "mine"},
        ),
        io.BytesIO(),
    )

    assert client.call("info") == "mine"


def test_error_responses_raise_with_the_code():
    client = JsonRpcClient(
        _stream({"jsonrpc": "2.0", "id": 1, "error": {"code": -32002, "message": "Unknown context"}}),
        io.BytesIO(),
    )

    with pytest.raises(ServiceError) as caught:
        client.call("list.all")

    assert caught.value.code == -32002
    assert "Unknown context" in str(caught.value)


def test_a_closed_connection_is_reported():
    client = JsonRpcClient(io.BytesIO(), io.BytesIO())

    with pytest.raises(RuntimeError, match="closed the connection"):
        client.call("info")


def test_request_ids_increment():
    outgoing = io.BytesIO()
    client = JsonRpcClient(
        _stream({"jsonrpc": "2.0", "id": 1, "result": None}, {"jsonrpc": "2.0", "id": 2, "result": None}),
        outgoing,
    )

    client.call("info")
    client.call("info")

    assert [request["id"] for request in _requests(outgoing)] == [1, 2]


def test_close_is_idempotent():
    closed = []
    client = JsonRpcClient(io.BytesIO(), io.BytesIO(), closer=lambda: closed.append(True))

    client.close()
    client.close()

    assert closed == [True]


def test_a_failing_closer_does_not_propagate():
    def closer():
        raise OSError("already gone")

    JsonRpcClient(io.BytesIO(), io.BytesIO(), closer=closer).close()


def test_params_are_serialized_as_json():
    outgoing = io.BytesIO()
    client = JsonRpcClient(_stream({"jsonrpc": "2.0", "id": 1, "result": None}), outgoing)

    client.call("export.part", {"package": "//", "name": "cube", "params": {"width": 2.5}})

    body = _requests(outgoing)[0]
    assert json.loads(json.dumps(body))["params"]["params"] == {"width": 2.5}
