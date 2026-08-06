#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the optional HTTP + SSE transport."""

import asyncio

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
