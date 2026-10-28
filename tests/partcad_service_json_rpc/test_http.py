#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the optional HTTP + SSE transport."""

import asyncio
import base64
import threading

from aiohttp.test_utils import TestClient, TestServer

from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.core.session import Session
from partcad_service_json_rpc.transport import http as http_transport


def _run(coro):
    return asyncio.run(coro)


def test_post_rpc_returns_a_jsonrpc_result():
    app = http_transport.build_app(Session(), {"ping": lambda s, p: "pong"})

    async def run():
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
            assert resp.status == 200
            return await resp.json()

    assert _run(run()) == {"jsonrpc": "2.0", "id": 1, "result": "pong"}


def test_post_notification_returns_empty_object_and_still_runs():
    ran = []
    app = http_transport.build_app(Session(), {"note": lambda s, p: ran.append(p)})

    async def run():
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/rpc", json={"jsonrpc": "2.0", "method": "note", "params": {"x": 1}})
            return resp.status, await resp.json()

    status, body = _run(run())
    assert status == 200
    assert body == {}
    assert ran == [{"x": 1}]


def test_unknown_method_returns_method_not_found():
    app = http_transport.build_app(Session(), {})

    async def run():
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "nope"})
            return await resp.json()

    assert _run(run())["error"]["code"] == -32601


def test_events_stream_delivers_emitted_notifications():
    def go(session, params):
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return "ok"

    app = http_transport.build_app(Session(), {"go": go})

    async def run():
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/events")
            assert resp.status == 200
            await client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "go"})
            line = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), timeout=5)
            return line.decode()

    line = _run(run())
    assert "items" in line
    assert "//" in line


def test_nothing_is_encoded_on_the_event_loop(monkeypatch):
    # The loop is every client's: an answer with a big file in it used to be
    # base64-encoded and dumped there while every other request waited.
    encoded_on = []
    real = http_transport.to_json

    def recording(message):
        encoded_on.append(threading.current_thread())
        return real(message)

    monkeypatch.setattr(http_transport, "to_json", recording)

    def go(session, params):
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return {"content": b"\x89PNG" * 1000}

    app = http_transport.build_app(Session(), {"go": go})

    async def run():
        async with TestClient(TestServer(app)) as client:
            events_stream = await client.get("/events")
            resp = await client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "go"})
            body = await resp.json()
            await asyncio.wait_for(events_stream.content.readuntil(b"\n\n"), timeout=5)
            return threading.current_thread(), body, resp.headers["Content-Type"]

    loop_thread, body, content_type = _run(run())
    assert body["result"]["content"] == base64.b64encode(b"\x89PNG" * 1000).decode("ascii")
    assert content_type == "application/json; charset=utf-8"
    assert len(encoded_on) == 2
    assert loop_thread not in encoded_on


def test_an_event_is_encoded_once_however_many_streams_it_goes_to(monkeypatch):
    calls = []
    real = http_transport.to_json
    monkeypatch.setattr(http_transport, "to_json", lambda message: calls.append(message) or real(message))

    def go(session, params):
        session.emitter.emit(events.ITEMS, {"name": "//"})
        return "ok"

    app = http_transport.build_app(Session(), {"go": go})

    async def run():
        async with TestClient(TestServer(app)) as client:
            streams = [await client.get("/events") for _ in range(3)]
            await client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "go"})
            return [await asyncio.wait_for(s.content.readuntil(b"\n\n"), timeout=5) for s in streams]

    lines = _run(run())
    assert len(set(lines)) == 1 and b"items" in lines[0]
    # One for the event, one for the answer.
    assert len(calls) == 2


def test_an_event_stream_that_lets_too_much_pile_up_is_dropped():
    async def run():
        subscriber = http_transport._Subscriber(max_backlog=10)
        subscriber.put(b"x" * 8)
        first = subscriber.dropped
        # Never too big on its own: only what waits behind another.
        lone = http_transport._Subscriber(max_backlog=10)
        lone.put(b"y" * 100)
        subscriber.put(b"z" * 8)
        return first, lone.dropped, subscriber.dropped, list(subscriber.events)

    first, lone, dropped, left = _run(run())
    assert first is None and lone is None
    assert dropped is not None and "stopped reading" in dropped
    assert left == []
